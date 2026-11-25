"""Puerta SSH de Nexo Server.

El usuario se conecta como  <usuario>:<host>@servidor  (puerto 2222 por defecto).
  - App Nexo: contraseña = token emitido por la API (nxt_...).
  - Cliente ssh normal: keyboard-interactive -> contraseña + código 2FA.
La puerta abre la conexión con el host real usando las credenciales guardadas (cifradas)
y retransmite terminal, exec, SFTP y túneles (-L / -D). Las credenciales nunca salen del servidor.
Las sesiones de terminal se graban en formato asciicast v2.
"""
import asyncio
import codecs
import inspect
import json
import logging
import os
import secrets
import time
import weakref

import asyncssh
from asyncssh.constants import EXTENDED_DATA_STDERR
from asyncssh.stream import SSHReader, SSHWriter

log = logging.getLogger("nexo.gateway")


class RelayProcess(asyncssh.SSHServerProcess):
    """Sesión que deja pasar el subsistema «sftp» a nuestro manejador (para retransmitirlo
    al host real) en vez de usar el servidor SFTP interno de asyncssh."""

    def subsystem_requested(self, subsystem):
        return subsystem == "sftp"

    def session_started(self):
        stdin = SSHReader(self, self._chan)
        stdout = SSHWriter(self, self._chan)
        stderr = SSHWriter(self, self._chan, EXTENDED_DATA_STDERR)
        handler = self._session_factory(stdin, stdout, stderr)
        if inspect.isawaitable(handler):
            self._conn.create_task(handler, stdin.logger)

# conexiones vivas por usuario (para cortarlas al bloquear)
LIVE = {}  # user_id -> set(conn)
CONN_STATE = weakref.WeakKeyDictionary()  # conn -> GatewayServer
FAILS = {}  # (ip) -> [timestamps]
MAX_FAILS, FAIL_WINDOW = 8, 300


def kill_user(user_id, reason="bloqueado por el administrador"):
    n = 0
    for conn in list(LIVE.get(user_id, ())):
        try:
            conn.disconnect(asyncssh.DISC_BY_APPLICATION, f"Nexo: acceso {reason}")
            n += 1
        except Exception:  # noqa: BLE001
            pass
    return n


def kill_session(session_id):
    for conn, state in list(CONN_STATE.items()):
        if session_id in state.session_ids:
            conn.disconnect(asyncssh.DISC_BY_APPLICATION, "Nexo: sesión cerrada por el administrador")
            return True
    return False


def live_sessions():
    out = []
    for state in list(CONN_STATE.values()):
        out.extend(state.session_ids)
    return set(out)


def _too_many_fails(ip):
    now = time.time()
    lst = [t for t in FAILS.get(ip, []) if now - t < FAIL_WINDOW]
    FAILS[ip] = lst
    return len(lst) >= MAX_FAILS


def _fail(ip):
    FAILS.setdefault(ip, []).append(time.time())


class Recorder:
    """Grabación asciicast v2 (solo la salida: lo que el usuario vio en pantalla)."""

    def __init__(self, path, width, height, title, term):
        self.f = open(path, "w", encoding="utf-8")
        os.chmod(path, 0o600)
        self.t0 = time.time()
        self.dec = codecs.getincrementaldecoder("utf-8")("replace")
        self.f.write(json.dumps({"version": 2, "width": width or 80, "height": height or 24,
                                 "timestamp": int(self.t0), "title": title,
                                 "env": {"TERM": term or "xterm-256color"}}) + "\n")

    def output(self, data):
        text = self.dec.decode(data)
        if text:
            self.f.write(json.dumps([round(time.time() - self.t0, 4), "o", text]) + "\n")

    def resize(self, w, h):
        self.f.write(json.dumps([round(time.time() - self.t0, 4), "r", f"{w}x{h}"]) + "\n")

    def close(self):
        try:
            self.f.close()
        except Exception:  # noqa: BLE001
            pass


class GatewayServer(asyncssh.SSHServer):
    def __init__(self, store, cfg):
        self.store = store
        self.cfg = cfg
        self.conn = None
        self.ip = ""
        self.user = None
        self.host = None
        self.perms = None
        self.target = None
        self.target_lock = asyncio.Lock()
        self.session_ids = set()
        self.login_name = ""

    # --- conexión -----------------------------------------------------------
    def connection_made(self, conn):
        self.conn = conn
        peer = conn.get_extra_info("peername") or ("", 0)
        self.ip = peer[0]
        CONN_STATE[conn] = self

    def connection_lost(self, exc):
        if self.user is not None:
            LIVE.get(self.user["id"], set()).discard(self.conn)
        if self.target is not None:
            self.target.close()

    def begin_auth(self, username):
        self.login_name = username
        return True

    def _parse(self, username):
        if ":" not in username:
            return None, None
        user, host = username.split(":", 1)
        return user, host

    def _authorize(self, user):
        _, host_ref = self._parse(self.login_name)
        host = self.store.host_by_ref(host_ref or "")
        if host is None:
            return False
        perms = self.store.perms(user["id"], host["id"])
        if not any(perms.values()):
            self.store.audit(user["username"], "ssh.denegado", f"sin permiso para {host['name']}", self.ip)
            return False
        self.user, self.host, self.perms = user, host, perms
        LIVE.setdefault(user["id"], set()).add(self.conn)
        self.store.run("UPDATE users SET last_login = ? WHERE id = ?", time.time(), user["id"])
        return True

    # contraseña: solo tokens de la app (nxt_...)
    def password_auth_supported(self):
        return True

    def validate_password(self, username, password):
        if _too_many_fails(self.ip):
            return False
        uname, _ = self._parse(username)
        if not uname or not (password or "").startswith("nxt_"):
            _fail(self.ip)
            return False
        u, _row = self.store.token_user(password, "app")
        if u is None or u["username"].lower() != uname.lower():
            _fail(self.ip)
            return False
        ok = self._authorize(u)
        if not ok:
            _fail(self.ip)
        return ok

    # keyboard-interactive: contraseña + 2FA (cliente ssh normal)
    def kbdint_auth_supported(self):
        return True

    def get_kbdint_challenge(self, username, lang, submethods):
        _, host = self._parse(username)
        return ("Nexo", f"Acceso a {host or '?'} a través de Nexo", "",
                [("Contraseña: ", False), ("Código 2FA: ", True)])

    def validate_kbdint_response(self, username, responses):
        if _too_many_fails(self.ip) or len(responses) != 2:
            return False
        uname, _ = self._parse(username)
        if not uname:
            _fail(self.ip)
            return False
        u, err = self.store.check_login(uname, responses[0], responses[1], require_totp=True)
        if u is None or not u["totp_enabled"]:
            _fail(self.ip)
            self.store.audit(uname, "ssh.login_fallido", err or "2FA no configurado", self.ip)
            return False
        ok = self._authorize(u)
        if not ok:
            _fail(self.ip)
        return ok

    # --- conexión al host real ------------------------------------------
    async def target_conn(self):
        async with self.target_lock:
            if self.target is not None:
                return self.target
            h = self.host
            secret = self.store.unseal(h["id"], h["secret"])
            kw = dict(host=h["address"], port=h["port"], username=h["username"], known_hosts=None,
                      connect_timeout=15, keepalive_interval=30)
            if h["auth"] == "key":
                kw["client_keys"] = [asyncssh.import_private_key(secret)]
                kw["password"] = None
            else:
                kw["password"] = secret
                kw["client_keys"] = None
            kw["agent_path"] = None
            conn = await asyncssh.connect(**kw)
            fp = conn.get_server_host_key().get_fingerprint()
            if h["host_key"] and h["host_key"] != fp:
                conn.close()
                self.store.audit("sistema", "ssh.llave_distinta",
                                 f"{h['name']}: esperada {h['host_key']}, recibida {fp}", self.ip)
                raise asyncssh.DisconnectError(asyncssh.DISC_HOST_KEY_NOT_VERIFIABLE,
                                               "La llave del servidor destino cambió; el administrador debe revisarla")
            if not h["host_key"]:
                self.store.run("UPDATE hosts SET host_key = ? WHERE id = ?", fp, h["id"])
            self.target = conn
            return conn

    def _new_session(self, kind, detail="", record=False, size=(80, 24), term=None):
        sid = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
        rec_path, recorder = None, None
        if record and self.cfg.record and self.host["record"]:
            rec_path = os.path.join(self.store.data_dir, "recordings", f"{sid}.cast")
            recorder = Recorder(rec_path, size[0], size[1],
                                f"{self.user['username']} @ {self.host['name']}", term)
        self.store.run(
            "INSERT INTO sessions (id, user_id, username, host_id, host_name, kind, client_ip, started, recording, detail)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            sid, self.user["id"], self.user["username"], self.host["id"], self.host["name"], kind, self.ip,
            time.time(), os.path.basename(rec_path) if rec_path else None, detail)
        self.session_ids.add(sid)
        return sid, recorder

    def _end_session(self, sid, bytes_in, bytes_out, recorder=None):
        if recorder:
            recorder.close()
        self.store.run("UPDATE sessions SET ended = ?, bytes_in = ?, bytes_out = ? WHERE id = ?",
                       time.time(), bytes_in, bytes_out, sid)
        self.session_ids.discard(sid)

    # --- túneles (-L / -D) ------------------------------------------------
    def connection_requested(self, dest_host, dest_port, orig_host, orig_port):
        if not self.perms or not self.perms.get("tunnel"):
            self.store.audit(self.user["username"] if self.user else "?", "tunel.denegado",
                             f"{self.host['name'] if self.host else '?'} -> {dest_host}:{dest_port}", self.ip)
            return False
        return TunnelSession(self, dest_host, dest_port)

    def server_requested(self, listen_host, listen_port):
        return False  # -R no se permite

    def session_requested(self):
        return RelayProcess(self.handle_process, None, 3, False)

    async def handle_process(self, process):
        """Terminal, comandos y SFTP."""
        sub = process.subsystem
        if sub:
            if sub != "sftp" or not self.perms.get("sftp"):
                process.stderr.write(b"Nexo: no tienes permiso de SFTP en este host\r\n")
                process.exit(1)
                return
            await self._relay(process, kind="sftp", subsystem="sftp")
            return
        if not self.perms.get("shell"):
            process.stderr.write(b"Nexo: no tienes permiso de terminal en este host (solo SFTP/tuneles)\r\n")
            process.exit(1)
            return
        if process.command:
            await self._relay(process, kind="exec", command=process.command)
        else:
            await self._relay(process, kind="shell")

    async def _relay(self, process, kind, command=None, subsystem=None):
        try:
            tconn = await self.target_conn()
        except Exception as e:  # noqa: BLE001
            msg = getattr(e, "reason", None) or str(e)
            process.stderr.write(f"\r\nNexo: no se pudo conectar a {self.host['name']}: {msg}\r\n".encode())
            process.exit(255)
            return
        term = process.get_terminal_type()
        size = process.get_terminal_size()
        w, h = (size[0], size[1]) if size else (80, 24)
        kw = {"encoding": None}
        if subsystem:
            kw["subsystem"] = subsystem
        elif command:
            kw["command"] = command
        if term:
            kw["term_type"] = term
            kw["term_size"] = (w, h)
        record = kind in ("shell", "exec")
        sid, rec = self._new_session(kind, command or subsystem or "", record=record, size=(w, h), term=term)
        self.store.audit(self.user["username"], f"ssh.{kind}", f"{self.host['name']} {command or ''}".strip(), self.ip)
        counters = {"in": 0, "out": 0}
        tproc = await tconn.create_process(**kw)

        async def up():
            while True:
                try:
                    data = await process.stdin.read(32768)
                except asyncssh.TerminalSizeChanged as ch:
                    tproc.change_terminal_size(ch.width, ch.height)
                    if rec:
                        rec.resize(ch.width, ch.height)
                    continue
                except (asyncssh.BreakReceived, asyncssh.SignalReceived):
                    continue
                if not data:
                    tproc.stdin.write_eof()
                    break
                counters["in"] += len(data)
                tproc.stdin.write(data)

        async def down(src, dst, record_it):
            while True:
                data = await src.read(32768)
                if not data:
                    break
                counters["out"] += len(data)
                if record_it and rec:
                    rec.output(data)
                dst.write(data)

        t_up = asyncio.ensure_future(up())
        try:
            await asyncio.gather(down(tproc.stdout, process.stdout, True),
                                 down(tproc.stderr, process.stderr, True))
            await tproc.wait_closed()
        except (asyncssh.Error, ConnectionError, BrokenPipeError):
            pass
        finally:
            t_up.cancel()
            self._end_session(sid, counters["in"], counters["out"], rec)
        status = tproc.exit_status if tproc.exit_status is not None else 0
        try:
            process.exit(status)
        except Exception:  # noqa: BLE001
            pass


class TunnelSession(asyncssh.SSHTCPSession):
    """Un -L / -D: se abre desde el host destino, no desde la puerta."""

    def __init__(self, gw, dest_host, dest_port):
        self.gw = gw
        self.dest = (dest_host, dest_port)
        self.chan = None
        self.writer = None
        self.pending = []
        self.sid = None
        self.count = {"in": 0, "out": 0}

    def connection_made(self, chan):
        self.chan = chan
        self.sid, _ = self.gw._new_session("tunel", f"{self.dest[0]}:{self.dest[1]}")
        self.gw.store.audit(self.gw.user["username"], "ssh.tunel",
                            f"{self.gw.host['name']} -> {self.dest[0]}:{self.dest[1]}", self.gw.ip)
        asyncio.ensure_future(self._open())

    async def _open(self):
        try:
            tconn = await self.gw.target_conn()
            reader, self.writer = await tconn.open_connection(*self.dest)
        except Exception:  # noqa: BLE001
            self.chan.close()
            return
        for d in self.pending:
            self.writer.write(d)
        self.pending = []
        try:
            while True:
                data = await reader.read(32768)
                if not data:
                    break
                self.count["out"] += len(data)
                self.chan.write(data)
        except Exception:  # noqa: BLE001
            pass
        self.chan.close()

    def data_received(self, data, datatype):
        self.count["in"] += len(data)
        if self.writer is None:
            self.pending.append(data)
        else:
            self.writer.write(data)

    def eof_received(self):
        if self.writer is not None:
            self.writer.write_eof()

    def connection_lost(self, exc):
        if self.writer is not None:
            self.writer.close()
        if self.sid:
            self.gw._end_session(self.sid, self.count["in"], self.count["out"])


async def start(store, cfg):
    key_path = os.path.join(store.data_dir, "ssh_host_ed25519_key")
    if not os.path.exists(key_path):
        k = asyncssh.generate_private_key("ssh-ed25519")
        k.write_private_key(key_path)
        os.chmod(key_path, 0o600)

    def factory():
        return GatewayServer(store, cfg)

    server = await asyncssh.create_server(
        factory, cfg.ssh_bind, cfg.ssh_port, server_host_keys=[key_path],
        encoding=None, allow_scp=False, agent_forwarding=False, x11_forwarding=False,
        login_timeout=60, keepalive_interval=30, server_version="Nexo")
    fp = asyncssh.read_private_key(key_path).get_fingerprint()
    log.info("Puerta SSH escuchando en %s:%s (huella %s)", cfg.ssh_bind, cfg.ssh_port, fp)
    return server
