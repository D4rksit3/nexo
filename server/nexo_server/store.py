"""Persistencia de Nexo Server: SQLite + cifrado de credenciales + contraseñas + 2FA (TOTP)."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import struct
import threading
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL COLLATE NOCASE,
    full_name TEXT NOT NULL DEFAULT '',
    pw_hash TEXT NOT NULL,
    totp_secret TEXT,
    totp_enabled INTEGER NOT NULL DEFAULT 0,
    totp_last_step INTEGER NOT NULL DEFAULT 0,
    role TEXT NOT NULL DEFAULT 'user',
    disabled INTEGER NOT NULL DEFAULT 0,
    must_change_pw INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL,
    last_login REAL
);
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL COLLATE NOCASE
);
CREATE TABLE IF NOT EXISTS team_members (
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (team_id, user_id)
);
CREATE TABLE IF NOT EXISTS hosts (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL COLLATE NOCASE,
    grp TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 22,
    username TEXT NOT NULL,
    auth TEXT NOT NULL DEFAULT 'key',
    secret BLOB,
    host_key TEXT,
    icon TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    record INTEGER NOT NULL DEFAULT 1,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS grants (
    id INTEGER PRIMARY KEY,
    subject TEXT NOT NULL CHECK (subject IN ('user', 'team')),
    subject_id INTEGER NOT NULL,
    host_id INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
    shell INTEGER NOT NULL DEFAULT 1,
    sftp INTEGER NOT NULL DEFAULT 1,
    tunnel INTEGER NOT NULL DEFAULT 0,
    UNIQUE (subject, subject_id, host_id)
);
CREATE TABLE IF NOT EXISTS tokens (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    created REAL NOT NULL,
    expires REAL NOT NULL,
    csrf TEXT,
    client TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER,
    username TEXT NOT NULL,
    host_id INTEGER,
    host_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    client_ip TEXT NOT NULL DEFAULT '',
    started REAL NOT NULL,
    ended REAL,
    recording TEXT,
    bytes_in INTEGER NOT NULL DEFAULT 0,
    bytes_out INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);
"""


# --- contraseñas (scrypt, stdlib) ------------------------------------------
def hash_password(pw):
    salt = secrets.token_bytes(16)
    n, r, p = 2 ** 15, 8, 1
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=n, r=r, p=p, maxmem=64 * 1024 * 1024, dklen=32)
    return f"scrypt${n}${r}${p}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(pw, stored):
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                              maxmem=64 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


# Hash fijo para comparar cuando el usuario no existe (evita distinguir usuarios por tiempo).
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def password_policy(pw):
    if len(pw) < 10:
        return "La contraseña debe tener al menos 10 caracteres"
    if pw.lower() == pw or pw.upper() == pw or not any(c.isdigit() for c in pw):
        return "Usa mayúsculas, minúsculas y al menos un número"
    return None


# --- 2FA: TOTP (RFC 6238) --------------------------------------------------
def new_totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret, counter):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    code = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def totp_match(secret, code, last_step=0, now=None, window=1):
    """Devuelve el paso (step) válido o None. No acepta reutilizar un código ya usado."""
    code = (code or "").strip().replace(" ", "")
    if not secret or len(code) != 6 or not code.isdigit():
        return None
    step = int((now or time.time()) // 30)
    for s in range(step - window, step + window + 1):
        if s > last_step and hmac.compare_digest(_hotp(secret, s), code):
            return s
    return None


def totp_uri(secret, username, issuer):
    from urllib.parse import quote
    return (f"otpauth://totp/{quote(issuer)}:{quote(username)}?secret={secret}"
            f"&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30")


# --- base de datos -----------------------------------------------------------
class Store:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        os.makedirs(data_dir, mode=0o700, exist_ok=True)
        os.chmod(data_dir, 0o700)
        os.makedirs(os.path.join(data_dir, "recordings"), mode=0o700, exist_ok=True)
        self.key = self._master_key()
        self.lock = threading.RLock()
        self.db = sqlite3.connect(os.path.join(data_dir, "nexo.db"), check_same_thread=False,
                                  isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)

    def _master_key(self):
        env = os.environ.get("NEXO_MASTER_KEY")
        if env:
            key = base64.b64decode(env)
            if len(key) != 32:
                raise SystemExit("NEXO_MASTER_KEY debe ser 32 bytes en base64")
            return key
        path = os.path.join(self.data_dir, "master.key")
        if not os.path.exists(path):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(secrets.token_bytes(32))
        with open(path, "rb") as f:
            return f.read()

    # cifrado de credenciales de hosts (AES-256-GCM; el id del host va como dato asociado)
    def seal(self, host_id, plaintext):
        nonce = secrets.token_bytes(12)
        return nonce + AESGCM(self.key).encrypt(nonce, plaintext.encode(), f"host:{host_id}".encode())

    def unseal(self, host_id, blob):
        if not blob:
            return ""
        return AESGCM(self.key).decrypt(blob[:12], blob[12:], f"host:{host_id}".encode()).decode()

    def q(self, sql, *args):
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def one(self, sql, *args):
        with self.lock:
            return self.db.execute(sql, args).fetchone()

    def run(self, sql, *args):
        with self.lock:
            cur = self.db.execute(sql, args)
            return cur.lastrowid

    def audit(self, actor, action, detail="", ip=""):
        self.run("INSERT INTO audit (ts, actor, action, detail, ip) VALUES (?,?,?,?,?)",
                 time.time(), actor, action, detail if isinstance(detail, str) else json.dumps(detail), ip)

    # --- usuarios --------------------------------------------------------
    def user_by_name(self, username):
        return self.one("SELECT * FROM users WHERE username = ?", username)

    def user(self, uid):
        return self.one("SELECT * FROM users WHERE id = ?", uid)

    def create_user(self, username, password, role="user", full_name="", must_change=True):
        return self.run(
            "INSERT INTO users (username, full_name, pw_hash, role, must_change_pw, created) VALUES (?,?,?,?,?,?)",
            username.strip(), full_name.strip(), hash_password(password), role, 1 if must_change else 0, time.time())

    def check_login(self, username, password, totp_code=None, require_totp=True):
        """(usuario, error). Con require_totp, el 2FA es obligatorio si está activado."""
        u = self.user_by_name(username or "")
        if u is None:
            verify_password(password or "", _DUMMY_HASH)
            return None, "Usuario o contraseña incorrectos"
        if not verify_password(password or "", u["pw_hash"]):
            return None, "Usuario o contraseña incorrectos"
        if u["disabled"]:
            return None, "Cuenta bloqueada. Contacta al administrador."
        if require_totp and u["totp_enabled"]:
            step = totp_match(u["totp_secret"], totp_code, u["totp_last_step"])
            if step is None:
                return None, "Código 2FA incorrecto"
            self.run("UPDATE users SET totp_last_step = ? WHERE id = ?", step, u["id"])
        return u, None

    # --- tokens (sesión web y app) ---------------------------------------
    def issue_token(self, user_id, kind, hours, client=""):
        raw = ("nxt_" if kind == "app" else "nxw_") + secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        self.run("INSERT INTO tokens (token_hash, user_id, kind, created, expires, csrf, client) VALUES (?,?,?,?,?,?,?)",
                 hashlib.sha256(raw.encode()).hexdigest(), user_id, kind, time.time(),
                 time.time() + hours * 3600, csrf, client)
        return raw, csrf

    def token_user(self, raw, kind):
        if not raw:
            return None, None
        row = self.one("SELECT * FROM tokens WHERE token_hash = ? AND kind = ?",
                       hashlib.sha256(raw.encode()).hexdigest(), kind)
        if row is None or row["expires"] < time.time():
            return None, None
        u = self.user(row["user_id"])
        if u is None or u["disabled"]:
            return None, None
        return u, row

    def revoke_token(self, raw):
        self.run("DELETE FROM tokens WHERE token_hash = ?", hashlib.sha256(raw.encode()).hexdigest())

    def revoke_user_tokens(self, user_id):
        self.run("DELETE FROM tokens WHERE user_id = ?", user_id)

    # --- permisos --------------------------------------------------------
    def perms(self, user_id, host_id):
        """Permisos efectivos (unión de los del usuario y sus equipos)."""
        rows = self.q("""
            SELECT g.shell, g.sftp, g.tunnel FROM grants g
            WHERE g.host_id = ? AND (
                (g.subject = 'user' AND g.subject_id = ?) OR
                (g.subject = 'team' AND g.subject_id IN (SELECT team_id FROM team_members WHERE user_id = ?)))
        """, host_id, user_id, user_id)
        p = {"shell": False, "sftp": False, "tunnel": False}
        for r in rows:
            for k in p:
                p[k] = p[k] or bool(r[k])
        return p

    def allowed_hosts(self, user_id):
        out = []
        for h in self.q("SELECT id, name, grp, icon, notes FROM hosts ORDER BY grp, name"):
            p = self.perms(user_id, h["id"])
            if any(p.values()):
                out.append({"id": h["id"], "name": h["name"], "group": h["grp"], "icon": h["icon"],
                            "notes": h["notes"], "perms": p})
        return out

    def host_by_ref(self, ref):
        if ref.isdigit():
            h = self.one("SELECT * FROM hosts WHERE id = ?", int(ref))
            if h:
                return h
        return self.one("SELECT * FROM hosts WHERE name = ?", ref)
