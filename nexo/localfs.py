"""Acceso a los archivos de «Este equipo» para el SFTP de dos paneles.

Fuera del snap se usa el disco directamente (OsFS). Dentro del snap (confinamiento estricto)
el proceso solo ve parte del disco: nada de /etc, /var, /srv, /media, ni el /tmp real, ni los
archivos ocultos de la carpeta personal, ni la papelera. Por eso ahí el panel local entra por
SFTP a 127.0.0.1 (SshFS), igual que la terminal local: la sesión la abre el sshd del sistema,
fuera del sandbox, con los permisos normales del usuario. Usa la misma llave propia de Nexo
(local_ed25519) que la terminal, autorizada una sola vez y válida solo desde localhost.
"""
import os
import posixpath
import shlex
import shutil
import stat
import subprocess

from gi.repository import Gio, GLib


def via_ssh():
    """¿El panel local debe ir por SSH a 127.0.0.1? (snap, o forzado para pruebas)."""
    return bool(os.environ.get("SNAP") or os.environ.get("NEXO_LOCAL_VIA_SSH"))


def base_dir():
    return os.environ.get("SNAP_USER_COMMON") or os.environ.get("SNAP_USER_DATA") or os.path.expanduser("~")


def port():
    return int(os.environ.get("NEXO_LOCAL_SSH_PORT") or 22)


def key_path():
    return os.path.join(base_dir(), "local_ed25519")


def known_hosts_path():
    return os.path.join(base_dir(), "known_hosts_local")


class NeedPassword(Exception):
    """La llave local todavía no está autorizada en ~/.ssh/authorized_keys."""


class NoSshd(Exception):
    """No hay servidor SSH escuchando en 127.0.0.1."""


# --- disco directo ------------------------------------------------------------

class OsFS:
    remote = False

    def scandir(self, path):
        out = []
        for e in os.scandir(path):
            try:
                st = e.stat(follow_symlinks=True)
                is_dir = e.is_dir(follow_symlinks=True)
            except OSError:  # enlace roto
                st, is_dir = e.stat(follow_symlinks=False), False
            out.append((e.name, st.st_mode, st.st_size, st.st_mtime, is_dir, e.is_symlink()))
        return out

    def exists(self, p):
        return os.path.exists(p)

    def isdir(self, p):
        return os.path.isdir(p)

    def isfile(self, p):
        return os.path.isfile(p)

    def listdir(self, p):
        return os.listdir(p)

    def size(self, p):
        return os.path.getsize(p)

    def mkdir(self, p):
        os.mkdir(p)

    def makedirs(self, p):
        os.makedirs(p, exist_ok=True)

    def rename(self, a, b):
        os.rename(a, b)

    def replace(self, a, b):
        os.replace(a, b)

    def remove(self, p):
        os.unlink(p)

    def open(self, p, mode="rb"):
        return open(p, mode)

    def trash(self, paths):
        failed = []
        for p in paths:
            try:
                Gio.File.new_for_path(p).trash(None)
            except GLib.Error as e:
                failed.append(f"{os.path.basename(p)}: {e.message}")
        return failed

    def open_default(self, p):
        Gio.AppInfo.launch_default_for_uri(GLib.filename_to_uri(p), None)

    def close(self):
        pass


# --- por SSH a 127.0.0.1 ------------------------------------------------------

class SshFS:
    """Mismo contrato que OsFS, sobre un canal SFTP de una conexión a 127.0.0.1.

    Un SFTPClient de paramiko no se debe usar desde dos hilos a la vez: el panel (hilo de
    GTK) y las transferencias (hilo de trabajo) usan cada uno su propio canal (ver LocalLink).
    """
    remote = True

    def __init__(self, link, sftp):
        self.link = link
        self.sftp = sftp

    def scandir(self, path):
        out = []
        for a in self.sftp.listdir_attr(path):
            mode = a.st_mode or 0
            is_link = stat.S_ISLNK(mode)
            if is_link:
                try:
                    a2 = self.sftp.stat(posixpath.join(path, a.filename))
                    mode, size, mtime = a2.st_mode or 0, a2.st_size or 0, a2.st_mtime or 0
                except OSError:  # enlace roto
                    size, mtime = a.st_size or 0, a.st_mtime or 0
            else:
                size, mtime = a.st_size or 0, a.st_mtime or 0
            out.append((a.filename, mode, size, mtime, stat.S_ISDIR(mode), is_link))
        return out

    def _stat(self, p):
        try:
            return self.sftp.stat(p)
        except OSError:
            return None

    def exists(self, p):
        return self._stat(p) is not None

    def isdir(self, p):
        st = self._stat(p)
        return bool(st and stat.S_ISDIR(st.st_mode or 0))

    def isfile(self, p):
        st = self._stat(p)
        return bool(st and stat.S_ISREG(st.st_mode or 0))

    def listdir(self, p):
        return self.sftp.listdir(p)

    def size(self, p):
        return self.sftp.stat(p).st_size or 0

    def mkdir(self, p):
        self.sftp.mkdir(p)

    def makedirs(self, p):
        if self.isdir(p):
            return
        parent = posixpath.dirname(p.rstrip("/"))
        if parent and parent != p:
            self.makedirs(parent)
        try:
            self.sftp.mkdir(p)
        except OSError:
            if not self.isdir(p):
                raise

    def rename(self, a, b):
        self.sftp.rename(a, b)

    def replace(self, a, b):
        try:
            self.sftp.posix_rename(a, b)  # reemplaza en un paso (OpenSSH)
        except OSError:
            try:
                self.sftp.remove(b)
            except OSError:
                pass
            self.sftp.rename(a, b)

    def remove(self, p):
        self.sftp.remove(p)

    def open(self, p, mode="rb"):
        f = self.sftp.open(p, mode)
        if "w" in mode or "a" in mode:
            f.set_pipelined(True)
        else:
            try:
                f.prefetch(f.stat().st_size)
            except Exception:  # noqa: BLE001
                pass
        return f

    def trash(self, paths):
        # gio trash corre en la sesión real del usuario: usa su papelera de verdad.
        rc, err = self.link.run("gio trash -- " + " ".join(shlex.quote(p) for p in paths))
        return [err.strip() or "gio trash falló"] if rc else []

    def open_default(self, p):
        if os.path.exists(p):  # visible también dentro del sandbox: abre por el portal
            try:
                Gio.AppInfo.launch_default_for_uri(GLib.filename_to_uri(p), None)
                return
            except GLib.Error:
                pass
        # Fuera del sandbox: «gio open» en la sesión del usuario, con su pantalla y su D-Bus.
        env = ['XDG_RUNTIME_DIR="/run/user/$(id -u)"',
               'DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"']
        for var in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_CURRENT_DESKTOP"):
            if os.environ.get(var):
                env.append(f"{var}={shlex.quote(os.path.basename(os.environ[var]) if var == 'WAYLAND_DISPLAY' else os.environ[var])}")
        rc, err = self.link.run(f"env {' '.join(env)} setsid -f gio open {shlex.quote(p)} </dev/null >/dev/null 2>&1")
        if rc:
            raise OSError(err.strip() or "no se pudo abrir")

    def close(self):
        try:
            self.sftp.close()
        except Exception:  # noqa: BLE001
            pass


class LocalLink:
    """Conexión SSH a 127.0.0.1 con la llave local de Nexo, con dos canales SFTP."""

    def __init__(self, client):
        self.client = client
        self.ui = SshFS(self, client.open_sftp())
        self.xfer = SshFS(self, client.open_sftp())

    def run(self, command, timeout=30):
        _in, out, err = self.client.exec_command(command, timeout=timeout)
        rc = out.channel.recv_exit_status()
        return rc, err.read().decode(errors="replace")

    @property
    def alive(self):
        t = self.client.get_transport()
        return bool(t and t.is_active())

    def close(self):
        self.ui.close()
        self.xfer.close()
        try:
            self.client.close()
        except Exception:  # noqa: BLE001
            pass


def _ensure_key():
    key = key_path()
    if os.path.exists(key):
        return key
    keygen = shutil.which("ssh-keygen")
    if not keygen:
        raise OSError("falta ssh-keygen")
    os.makedirs(os.path.dirname(key), exist_ok=True)
    subprocess.run([keygen, "-q", "-t", "ed25519", "-N", "", "-C", f"nexo-local@{os.uname().nodename}", "-f", key],
                   check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return key


def _client():
    import paramiko

    c = paramiko.SSHClient()
    kh = known_hosts_path()
    if os.path.exists(kh):
        try:
            c.load_host_keys(kh)
        except Exception:  # noqa: BLE001
            pass
    # Igual que StrictHostKeyChecking=accept-new de la terminal local: la primera se guarda,
    # una distinta se rechaza (BadHostKeyException).
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    return c


def _user():
    import pwd

    return pwd.getpwuid(os.getuid()).pw_name


def _save_host_key(c):
    try:
        c.save_host_keys(known_hosts_path())
    except Exception:  # noqa: BLE001
        pass


def _probe():
    import socket

    try:
        socket.create_connection(("127.0.0.1", port()), timeout=3).close()
    except OSError:
        raise NoSshd(f"No hay servidor SSH en 127.0.0.1:{port()}")


def connect():
    """Abre la conexión con la llave local. NeedPassword si aún no está autorizada."""
    import paramiko

    _probe()
    key = _ensure_key()
    c = _client()
    try:
        c.connect("127.0.0.1", port=port(), username=_user(), key_filename=key, allow_agent=False,
                  look_for_keys=False, timeout=8, banner_timeout=8, auth_timeout=10)
    except paramiko.AuthenticationException:
        c.close()
        raise NeedPassword()
    except paramiko.BadHostKeyException:
        c.close()
        raise OSError("La llave SSH de este equipo no coincide con la guardada por Nexo "
                      f"({known_hosts_path()}).")
    _save_host_key(c)
    return LocalLink(c)


def authorize(password):
    """Entra una vez con la contraseña de Linux y agrega la llave local de Nexo a
    ~/.ssh/authorized_keys, limitada a 127.0.0.1 (lo mismo que hace la terminal local)."""
    import paramiko

    _probe()
    key = _ensure_key()
    with open(key + ".pub", encoding="utf-8") as f:
        pub = f.read().strip()
    line = f'from="127.0.0.1,::1",no-agent-forwarding,no-X11-forwarding {pub}'
    body = pub.rsplit(" ", 1)[0] if pub.count(" ") >= 2 else pub
    cmd = ("umask 077; mkdir -p ~/.ssh; "
           f"grep -qF {shlex.quote(body)} ~/.ssh/authorized_keys 2>/dev/null || "
           f"echo {shlex.quote(line)} >> ~/.ssh/authorized_keys")
    c = _client()
    try:
        c.connect("127.0.0.1", port=port(), username=_user(), password=password, allow_agent=False,
                  look_for_keys=False, timeout=8, banner_timeout=8, auth_timeout=15)
    except paramiko.AuthenticationException:
        c.close()
        raise OSError("Contraseña incorrecta")
    try:
        _save_host_key(c)
        _in, out, err = c.exec_command(cmd, timeout=15)
        if out.channel.recv_exit_status():
            raise OSError(err.read().decode(errors="replace").strip() or "no se pudo autorizar la llave")
    finally:
        c.close()
