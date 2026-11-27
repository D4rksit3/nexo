"""Túneles SSH con paramiko (sin el ejecutable `ssh`): local (L), remoto (R) y SOCKS5 (D).

Un `Tunnel` abre UNA conexión SSH al host (con su salto, si tiene) y levanta todos sus
reenvíos sobre ella. También lo usan las bases de datos y RDP que van «por salto»:
`local_forward(vault, jump, destino, puerto)` devuelve un túnel con un puerto local libre.
"""
import ipaddress
import select
import socket
import struct
import threading
import time

BUF = 65536


def _pipe(chan, sock):
    """Copia en ambos sentidos entre un canal SSH y un socket hasta que uno cierre."""
    try:
        while True:
            r, _, _ = select.select([sock, chan], [], [], 60)
            if sock in r:
                data = sock.recv(BUF)
                if not data:
                    break
                chan.sendall(data)
            if chan in r:
                data = chan.recv(BUF)
                if not data:
                    break
                sock.sendall(data)
    except Exception:  # noqa: BLE001 — cualquiera de los dos se cayó
        pass
    finally:
        for c in (chan, sock):
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("el cliente SOCKS cerró")
        buf += chunk
    return buf


def socks5_handshake(sock):
    """Negocia SOCKS5 (sin autenticación, solo CONNECT). Devuelve (host, puerto) o lanza."""
    ver, n = _recv_exact(sock, 2)
    if ver != 5:
        raise ConnectionError("no es SOCKS5")
    methods = _recv_exact(sock, n)
    if 0 not in methods:
        sock.sendall(b"\x05\xff")
        raise ConnectionError("el cliente SOCKS exige autenticación")
    sock.sendall(b"\x05\x00")
    ver, cmd, _, atyp = _recv_exact(sock, 4)
    if atyp == 1:
        host = socket.inet_ntoa(_recv_exact(sock, 4))
    elif atyp == 3:
        host = _recv_exact(sock, _recv_exact(sock, 1)[0]).decode("idna")
    elif atyp == 4:
        host = str(ipaddress.IPv6Address(_recv_exact(sock, 16)))
    else:
        raise ConnectionError("tipo de dirección SOCKS desconocido")
    port = struct.unpack("!H", _recv_exact(sock, 2))[0]
    if cmd != 1:
        sock.sendall(b"\x05\x07\x00\x01" + b"\0" * 6)  # comando no soportado
        raise ConnectionError("solo se admite CONNECT")
    return host, port


def socks5_reply(sock, ok):
    sock.sendall((b"\x05\x00" if ok else b"\x05\x05") + b"\x00\x01" + b"\0" * 6)


class Tunnel:
    """Conexión SSH + sus reenvíos. Estados: detenido, conectando, activo, error."""

    def __init__(self, vault, host, forwards, on_change=None, password=None):
        self.vault = vault
        self.host = dict(host)
        if password:
            self.host["password"] = password
        self.forwards = [dict(f) for f in forwards]
        self.on_change = on_change
        self.state = "detenido"
        self.error = ""
        self.client = None
        self._servers = []
        self._stop = threading.Event()
        self.ready = threading.Event()

    # --- ciclo de vida -------------------------------------------------------
    def start(self):
        self._stop.clear()
        self.ready.clear()
        self._set("conectando")
        threading.Thread(target=self._run, name=f"tunnel-{self.host.get('name')}", daemon=True).start()

    def _run(self):
        from nexo import conn

        try:
            self.client = conn.paramiko_client(self.vault, self.host)
            transport = self.client.get_transport()
            transport.set_keepalive(30)
            for fw in self.forwards:
                if fw["type"] == "R":
                    self._start_remote(transport, fw)
                else:
                    self._start_local(transport, fw)
        except Exception as e:  # noqa: BLE001
            self.error = _reason(e)
            self._close_all()
            self._set("error")
            self.ready.set()
            return
        self._set("activo")
        self.ready.set()
        # vigilar la conexión: si se cae, se informa
        while not self._stop.wait(2):
            if not transport.is_active():
                self.error = "se perdió la conexión SSH"
                self._close_all()
                self._set("error")
                return

    def _start_local(self, transport, fw):
        bind = fw.get("bind") or "127.0.0.1"
        srv = socket.socket(socket.AF_INET6 if ":" in bind else socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: que nadie más tome el puerto
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind((bind, int(fw["port"])))
        except OSError as e:
            srv.close()
            raise OSError(f"el puerto local {bind}:{fw['port']} está ocupado ({e.strerror or e})")
        srv.listen(64)
        srv.settimeout(1)
        self._servers.append(srv)
        threading.Thread(target=self._accept_loop, args=(transport, srv, fw), daemon=True).start()

    def _accept_loop(self, transport, srv, fw):
        while not self._stop.is_set():
            try:
                sock, peer = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=self._serve_one, args=(transport, sock, peer, fw), daemon=True).start()

    def _serve_one(self, transport, sock, peer, fw):
        sock.settimeout(None)
        socks = fw["type"] == "D"
        try:
            if socks:
                dest = socks5_handshake(sock)
            else:
                dest = (fw["dest_host"], int(fw["dest_port"]))
            chan = transport.open_channel("direct-tcpip", dest, peer[:2], timeout=15)
        except Exception:  # noqa: BLE001 — destino inalcanzable o cliente SOCKS roto
            if socks:
                try:
                    socks5_reply(sock, False)
                except OSError:
                    pass
            sock.close()
            return
        if socks:
            socks5_reply(sock, True)
        _pipe(chan, sock)

    def _start_remote(self, transport, fw):
        dest = (fw["dest_host"], int(fw["dest_port"]))

        def handler(chan, origin, server):
            def run():
                try:
                    sock = socket.create_connection(dest, timeout=15)
                except OSError:
                    chan.close()
                    return
                _pipe(chan, sock)

            threading.Thread(target=run, daemon=True).start()

        bind = fw.get("bind") or "127.0.0.1"
        transport.request_port_forward(bind if bind not in ("127.0.0.1", "localhost") else "localhost",
                                       int(fw["port"]), handler)

    def _close_all(self):
        for s in self._servers:
            try:
                s.shutdown(socket.SHUT_RDWR)  # despierta el accept() pendiente
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass
        self._servers = []
        c, self.client = self.client, None
        for x in (c, getattr(c, "_nexo_jump", None)):
            try:
                if x is not None:
                    x.close()
            except Exception:  # noqa: BLE001
                pass

    def stop(self):
        self._stop.set()
        self._close_all()
        if self.state != "error":
            self._set("detenido")

    @property
    def running(self):
        return self.state in ("conectando", "activo")

    def _set(self, state):
        self.state = state
        if self.on_change:
            try:
                self.on_change(self)
            except Exception:  # noqa: BLE001
                pass


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def local_forward(vault, jump, dest_host, dest_port, timeout=25):
    """Túnel L a un puerto local libre hacia dest por `jump`. Devuelve (túnel, puerto)."""
    port = free_port()
    t = Tunnel(vault, jump, [{"type": "L", "bind": "127.0.0.1", "port": port,
                               "dest_host": dest_host, "dest_port": int(dest_port)}])
    t.start()
    if not t.ready.wait(timeout) or t.state != "activo":
        t.stop()
        raise ConnectionError(f"No se pudo abrir el túnel por {jump.get('name')}: {t.error or 'sin respuesta'}")
    return t, port


def wait_closed(t, timeout=3):
    end = time.time() + timeout
    while t.running and time.time() < end:
        time.sleep(0.05)


def _reason(e):
    from .sessions import _reason as r

    return r(e)
