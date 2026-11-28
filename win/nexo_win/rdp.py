"""Escritorio remoto: `mstsc` en Windows (FreeRDP en Linux, para desarrollar).

- Con salto, abre antes un túnel local por paramiko y conecta a 127.0.0.1:<puerto>.
- La contraseña nunca va en la línea de comandos ni en el .rdp: se guarda en el
  Administrador de credenciales de Windows como TERMSRV/<destino> con persistencia de
  SESIÓN (desaparece al cerrar sesión) y Nexo la borra en cuanto mstsc se cierra.
- El .rdp temporal se borra a los pocos segundos, cuando mstsc ya lo leyó.
"""
import hashlib
import json
import os
import shutil
import socket
import ssl
import struct
import subprocess
import tempfile
import threading
import time

from . import IS_WINDOWS

RESOLUTIONS = [("auto", "Ajustar a la ventana"), ("1280x720", "1280 × 720"), ("1366x768", "1366 × 768"),
               ("1600x900", "1600 × 900"), ("1920x1080", "1920 × 1080"), ("2560x1440", "2560 × 1440")]


# --- Administrador de credenciales (Win32 CredWrite/CredDelete) ---------------------

def _cred_api():
    import ctypes
    from ctypes import wintypes

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    adv.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
    adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    return ctypes, CREDENTIALW, adv


CRED_TYPE_DOMAIN_PASSWORD = 2
CRED_PERSIST_SESSION = 1


def cred_write(target, user, password):
    ctypes, CREDENTIALW, adv = _cred_api()
    blob = password.encode("utf-16-le")
    buf = ctypes.create_string_buffer(blob, len(blob))
    c = CREDENTIALW()
    c.Type = CRED_TYPE_DOMAIN_PASSWORD
    c.TargetName = target
    c.CredentialBlobSize = len(blob)
    c.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
    c.Persist = CRED_PERSIST_SESSION
    c.UserName = user
    if not adv.CredWriteW(ctypes.byref(c), 0):
        raise OSError(f"No se pudo guardar la credencial temporal (error {ctypes.get_last_error()})")


def cred_delete(target):
    try:
        _, _, adv = _cred_api()
        adv.CredDeleteW(target, CRED_TYPE_DOMAIN_PASSWORD, 0)
    except Exception:  # noqa: BLE001
        pass


# --- confianza en el certificado del servidor (como known_hosts de SSH) -------------------------
#
# Los servidores RDP usan casi siempre un certificado autofirmado, y por eso Windows muestra
# «No se puede comprobar la identidad del equipo remoto». Nexo hace lo mismo que con SSH:
# la primera vez recuerda la huella SHA-256 del certificado y conecta sin preguntar; las
# siguientes compara, y solo si CAMBIÓ pide confirmación (dentro de Nexo, no con un aviso de Windows).

def known_path():
    base = os.path.dirname(os.environ.get("NEXO_KNOWN_HOSTS", "")) or os.path.join(
        os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "nexo")
    return os.path.join(base, "rdp_known.json")


def _load_known():
    try:
        with open(known_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def remember(key, fp):
    data = _load_known()
    data[key] = fp
    path = known_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def server_cert(host, port, timeout=8):
    """Huella SHA-256 (hex con «:») del certificado TLS del servidor RDP, o None si el
    servidor solo habla la seguridad RDP antigua (sin TLS)."""
    neg = struct.pack("<BBHI", 0x01, 0x00, 8, 0x00000003)            # pide TLS o NLA
    x224 = bytes([0xE0, 0, 0, 0, 0, 0]) + neg
    pkt = bytes([3, 0]) + struct.pack(">H", 4 + 1 + len(x224)) + bytes([len(x224)]) + x224
    with socket.create_connection((host, int(port)), timeout=timeout) as sock:
        sock.sendall(pkt)
        head = _recv(sock, 4)
        if head[0] != 3:
            raise ConnectionError("Ese puerto no responde como un servidor RDP")
        body = _recv(sock, struct.unpack(">H", head[2:4])[0] - 4)
        if len(body) < 2 or body[1] & 0xF0 != 0xD0:
            raise ConnectionError("Ese puerto no responde como un servidor RDP")
        if len(body) < 15:                  # servidor muy viejo, sin negociación: no hay TLS
            return None
        ntype, sel = body[7], struct.unpack("<I", body[11:15])[0]
        if ntype == 0x03 or sel == 0:       # fallo de negociación o RDP clásico: no hay TLS
            return None
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.minimum_version = ssl.TLSVersion.TLSv1
            ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
        except (ValueError, ssl.SSLError):
            pass
        with ctx.wrap_socket(sock, server_hostname=None) as tls:
            der = tls.getpeercert(binary_form=True)
    d = hashlib.sha256(der).hexdigest().upper()
    return ":".join(d[i:i + 2] for i in range(0, len(d), 2))


def _recv(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("El servidor RDP cerró la conexión")
        buf += chunk
    return buf


def trust_check(key, host, port, accept=None):
    """Compara el certificado con el recordado para «key» (host:puerto real).
    Devuelve (ok, huella, anterior). ok=False solo si cambió y no se aceptó esa huella."""
    fp = server_cert(host, port)
    if fp is None:
        return True, None, None
    old = _load_known().get(key)
    if old == fp:
        return True, fp, old
    if old is None or accept == fp:
        remember(key, fp)
        return True, fp, old
    return False, fp, old


# --- archivo .rdp ---------------------------------------------------------------------

def rdp_file_text(address, user, opts):
    o = opts or {}
    lines = [f"full address:s:{address}", "prompt for credentials:i:0", "authentication level:i:2",
             "autoreconnection enabled:i:1", "use multimon:i:0", "audiomode:i:0"]
    if user:
        domain = (o.get("domain") or "").strip()
        lines.append(f"username:s:{domain + chr(92) + user if domain and chr(92) not in user else user}")
    lines.append(f"screen mode id:i:{2 if o.get('fullscreen') else 1}")
    res = o.get("resolution") or "auto"
    if res == "auto":
        lines += ["dynamic resolution:i:1", "smart sizing:i:1"]
    else:
        w, h = res.split("x")
        lines += [f"desktopwidth:i:{w}", f"desktopheight:i:{h}"]
    lines.append(f"redirectclipboard:i:{1 if o.get('clipboard', True) else 0}")
    if o.get("share_home"):
        lines.append("drivestoredirect:s:*")
    return "\r\n".join(lines) + "\r\n"


class RdpSession:
    """Una ventana de escritorio remoto. on_exit(session, error_o_vacío) al cerrarse."""

    def __init__(self, vault, host, password=None, on_exit=None):
        self.vault = vault
        self.host = dict(host)
        if password:
            self.host["password"] = password
        self.on_exit = on_exit or (lambda *a: None)
        self.tunnel = None
        self.proc = None
        self.state = "conectando"

    def start(self):
        threading.Thread(target=self._run, name="rdp", daemon=True).start()

    def _run(self):
        h = self.host
        target_host, target_port = h["host"], int(h.get("port") or 3389)
        cred_target = None
        err = ""
        try:
            if h.get("jump"):
                from .forward import local_forward

                jump = self.vault.host(h["jump"])
                if not jump:
                    raise RuntimeError("El host de salto ya no existe")
                self.tunnel, lport = local_forward(self.vault, jump, target_host, target_port)
                target_host, target_port = "127.0.0.1", lport
            address = target_host if target_port == 3389 else f"{target_host}:{target_port}"
            if IS_WINDOWS:
                cred_target = f"TERMSRV/{target_host}"
                err = self._run_mstsc(address, cred_target)
            else:
                err = self._run_freerdp(target_host, target_port)
        except Exception as e:  # noqa: BLE001
            err = str(e) or type(e).__name__
        finally:
            if cred_target:
                cred_delete(cred_target)
            if self.tunnel:
                self.tunnel.stop()
        self.state = "cerrado"
        self.on_exit(self, err)

    def _run_mstsc(self, address, cred_target):
        h = self.host
        o = h.get("rdp") or {}
        user = h.get("user") or ""
        if user and o.get("domain") and "\\" not in user:
            user = f"{o['domain']}\\{user}"
        if h.get("password") and user:
            cred_write(cred_target, user, h["password"])
        fd, path = tempfile.mkstemp(prefix="nexo-", suffix=".rdp")
        with os.fdopen(fd, "w", encoding="utf-16") as f:  # mstsc lee .rdp en UTF-16
            f.write(rdp_file_text(address, h.get("user") or "", o))
        mstsc = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "mstsc.exe")
        started = time.time()
        self.proc = subprocess.Popen([mstsc, path])
        self.state = "abierto"
        threading.Timer(15, lambda: _unlink(path)).start()
        code = self.proc.wait()
        _unlink(path)
        if code not in (0, None) and time.time() - started < 10:
            return f"mstsc terminó con código {code}"
        return ""

    def _run_freerdp(self, host, port):
        from nexo import conn

        binary = conn.rdp_binary()
        if not binary:
            raise RuntimeError("No hay cliente FreeRDP. Instala: sudo apt install freerdp3-x11")
        h, o = self.host, self.host.get("rdp") or {}
        args = [f"/v:{host}:{port}", "/cert:tofu", f"/title:{h.get('name')} — Nexo"]
        if h.get("user"):
            args.append(f"/u:{h['user']}")
        if o.get("domain"):
            args.append(f"/d:{o['domain']}")
        if h.get("password"):
            args.append(f"/p:{h['password']}")
        if o.get("fullscreen"):
            args.append("/f")
        res = o.get("resolution") or "auto"
        args += ["+dynamic-resolution", "/size:90%"] if res == "auto" else [f"/size:{res}"]
        if o.get("clipboard", True):
            args.append("+clipboard")
        started = time.time()
        self.proc = subprocess.Popen([binary, "/args-from:stdin"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.proc.stdin.write(("\n".join(args) + "\n").encode())
        self.proc.stdin.close()
        self.state = "abierto"
        out = self.proc.stdout.read().decode(errors="replace")
        code = self.proc.wait()
        if code != 0 and time.time() - started < 20:
            lines = [ln for ln in out.splitlines() if "error" in ln.lower()]
            return "\n".join((lines or out.splitlines())[-3:]) or f"FreeRDP terminó con código {code}"
        return ""

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


def _unlink(path):
    try:
        os.remove(path)
    except OSError:
        pass


def available():
    if IS_WINDOWS:
        return True
    from nexo import conn

    return bool(conn.rdp_binary()) or bool(shutil.which("xfreerdp3"))
