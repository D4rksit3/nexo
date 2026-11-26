"""Sesiones de terminal: SSH (paramiko) y shell local (ConPTY en Windows, pty en Linux).

Cada sesión produce bytes hacia un «sumidero» (la conexión WebSocket de su pestaña).
Lo que sale antes de que la pestaña se conecte se guarda y se entrega al conectar.
"""
import json
import os
import secrets
import shutil
import threading

from . import IS_WINDOWS

READ_CHUNK = 32768
EARLY_BUFFER_MAX = 256 * 1024


class Session:
    kind = "base"

    def __init__(self, title, cols=120, rows=32):
        self.id = secrets.token_urlsafe(12)
        self.title = title
        self.cols, self.rows = cols, rows
        self.alive = False
        self._sink = None
        self._early = []
        self._early_size = 0
        self._lock = threading.Lock()

    # --- salida hacia la pestaña ---------------------------------------
    def attach(self, sink):
        """sink(bytes | str): bytes = salida de la terminal, str = mensaje de control JSON."""
        with self._lock:
            self._sink = sink
            pending, self._early, self._early_size = self._early, [], 0
        for item in pending:
            sink(item)

    def detach(self):
        with self._lock:
            self._sink = None

    def _emit(self, item):
        with self._lock:
            sink = self._sink
            if sink is None:
                if self._early_size < EARLY_BUFFER_MAX:
                    self._early.append(item)
                    self._early_size += len(item)
                return
        try:
            sink(item)
        except Exception:  # noqa: BLE001 — la pestaña se cerró: se descarta
            pass

    def output(self, data: bytes):
        self._emit(data)

    def notice(self, text, color="2"):
        """Mensaje propio de Nexo dentro de la terminal (atenuado o en color ANSI)."""
        self.output(f"\r\n\x1b[{color}m{text}\x1b[0m\r\n".encode())

    def status(self, state, message=""):
        self._emit(json.dumps({"t": "status", "state": state, "msg": message}))

    # --- a implementar ---------------------------------------------------
    def start(self):
        raise NotImplementedError

    def write(self, data: bytes):
        raise NotImplementedError

    def resize(self, cols, rows):
        self.cols, self.rows = cols, rows

    def close(self):
        self.alive = False


# --- SSH ---------------------------------------------------------------------

class SshSession(Session):
    kind = "ssh"

    def __init__(self, vault, host, password=None, cols=120, rows=32):
        super().__init__(host.get("name") or host.get("host"), cols, rows)
        self.vault = vault
        self.host = dict(host)
        if password:
            self.host["password"] = password
        self.client = None
        self.chan = None

    def start(self):
        threading.Thread(target=self._run, name=f"ssh-{self.id}", daemon=True).start()

    def _run(self):
        from nexo import conn

        h = self.host
        target = f"{h.get('user') + '@' if h.get('user') else ''}{h['host']}"
        port = int(h.get("port") or 22)
        via = ""
        if h.get("jump"):
            j = self.vault.host(h["jump"])
            via = f" vía {j['name']}" if j else ""
        self.status("connecting")
        self.notice(f"Conectando a {target}{'' if port == 22 else ':' + str(port)}{via}…")
        try:
            self.client = conn.paramiko_client(self.vault, h)
            self.chan = self.client.invoke_shell(term="xterm-256color", width=self.cols, height=self.rows)
            self.chan.settimeout(None)
        except Exception as e:  # noqa: BLE001 — se muestra tal cual en la pestaña
            self.notice(f"No se pudo conectar: {_reason(e)}", "31")
            self.status("closed", _reason(e))
            self._cleanup()
            return
        self.alive = True
        self.status("connected")
        try:
            while True:
                data = self.chan.recv(READ_CHUNK)
                if not data:
                    break
                self.output(data)
        except Exception:  # noqa: BLE001
            pass
        code = self.chan.recv_exit_status() if self.chan.exit_status_ready() else None
        self.alive = False
        self.notice("Conexión cerrada" + (f" (código {code})" if code not in (None, 0) else "")
                    + ". Enter para reconectar.")
        self.status("closed")
        self._cleanup()

    def write(self, data):
        if self.chan is not None and self.alive:
            self.chan.sendall(data)

    def resize(self, cols, rows):
        super().resize(cols, rows)
        if self.chan is not None and self.alive:
            try:
                self.chan.resize_pty(width=cols, height=rows)
            except Exception:  # noqa: BLE001
                pass

    def _cleanup(self):
        for c in (self.chan, self.client, getattr(self.client, "_nexo_jump", None)):
            try:
                if c is not None:
                    c.close()
            except Exception:  # noqa: BLE001
                pass

    def close(self):
        self.alive = False
        self.detach()
        self._cleanup()


def _reason(e):
    import socket

    import paramiko

    if isinstance(e, paramiko.AuthenticationException):
        return "usuario, contraseña o llave rechazados"
    if isinstance(e, socket.timeout):
        return "el servidor no responde (tiempo agotado)"
    if isinstance(e, ConnectionRefusedError):
        return "conexión rechazada (¿puerto correcto?)"
    if isinstance(e, socket.gaierror):
        return "no se encontró el host (revisa el nombre)"
    return str(e) or type(e).__name__


# --- shell local -----------------------------------------------------------------

def local_shell():
    """(argv, nombre) del shell local por defecto."""
    if IS_WINDOWS:
        for exe, name in (("pwsh.exe", "PowerShell"), ("powershell.exe", "Windows PowerShell")):
            path = shutil.which(exe)
            if path:
                return [path, "-NoLogo"], name
        return [os.environ.get("COMSPEC", "cmd.exe")], "Símbolo del sistema"
    shell = os.environ.get("SHELL") or shutil.which("bash") or "/bin/sh"
    return [shell, "-l"], os.path.basename(shell)


class LocalSession(Session):
    kind = "local"

    def __init__(self, cols=120, rows=32):
        self.argv, name = local_shell()
        super().__init__(f"Local · {name}", cols, rows)
        self._proc = None   # Windows: winpty.PtyProcess
        self._pid = None    # Linux
        self._fd = None

    def start(self):
        home = os.path.expanduser("~")
        try:
            if IS_WINDOWS:
                from winpty import PtyProcess

                self._proc = PtyProcess.spawn(self.argv, cwd=home, dimensions=(self.rows, self.cols))
            else:
                self._spawn_posix(home)
        except Exception as e:  # noqa: BLE001
            self.notice(f"No se pudo abrir el shell local: {e}", "31")
            self.status("closed", str(e))
            return
        self.alive = True
        self.status("connected")
        threading.Thread(target=self._pump, name=f"local-{self.id}", daemon=True).start()

    def _spawn_posix(self, home):
        import pty

        env = dict(os.environ, TERM="xterm-256color", COLORTERM="truecolor")
        pid, fd = pty.fork()
        if pid == 0:  # hijo
            try:
                os.chdir(home)
                os.execvpe(self.argv[0], self.argv, env)
            finally:
                os._exit(127)
        self._pid, self._fd = pid, fd
        self.resize(self.cols, self.rows)

    def _pump(self):
        fd = self._fd  # copia propia: close() puede soltar self._fd mientras se lee
        try:
            while True:
                if IS_WINDOWS:
                    text = self._proc.read(READ_CHUNK)
                    if not text:
                        if not self._proc.isalive():
                            break
                        continue
                    self.output(text.encode("utf-8", "replace"))
                else:
                    data = os.read(fd, READ_CHUNK)
                    if not data:
                        break
                    self.output(data)
        except (OSError, EOFError):
            pass
        self.alive = False
        self.notice("El shell terminó. Enter para abrir otro.")
        self.status("closed")
        self._reap()

    def write(self, data):
        if not self.alive:
            return
        if IS_WINDOWS:
            self._proc.write(data.decode("utf-8", "replace"))
        else:
            os.write(self._fd, data)

    def resize(self, cols, rows):
        super().resize(cols, rows)
        try:
            if IS_WINDOWS and self._proc is not None:
                self._proc.setwinsize(rows, cols)
            elif self._fd is not None:
                import fcntl
                import struct
                import termios

                fcntl.ioctl(self._fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except Exception:  # noqa: BLE001
            pass

    def _reap(self):
        if IS_WINDOWS:
            return
        fd, self._fd = self._fd, None  # cerrar una sola vez, venga de donde venga
        try:
            if fd is not None:
                os.close(fd)
        except OSError:
            pass
        try:
            if self._pid:
                os.waitpid(self._pid, os.WNOHANG)
        except OSError:
            pass

    def close(self):
        self.detach()
        if not self.alive:
            return
        self.alive = False
        try:
            if IS_WINDOWS:
                self._proc.terminate(force=True)
            elif self._pid:
                import signal

                os.kill(self._pid, signal.SIGHUP)
        except Exception:  # noqa: BLE001
            pass
        self._reap()
