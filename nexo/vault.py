"""Bóveda cifrada: hosts, llaves y ajustes en un solo archivo.

Formato: JSON con la sal y los parámetros de scrypt, y el contenido cifrado
con AES-256-GCM. La contraseña maestra nunca se guarda.
"""
import base64
import json
import os
import secrets
import shutil
import tempfile
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

_DATA_BASE = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
DATA_DIR = os.path.join(_DATA_BASE, "nexo")
VAULT_PATH = os.path.join(DATA_DIR, "vault.enc")
LEGACY_VAULT = os.path.join(_DATA_BASE, "enlace", "vault.enc")  # nombre anterior de la app


def migrate_legacy():
    """Si existe la bóveda de «Enlace» y aún no la de Nexo, se COPIA (la original queda intacta)."""
    if os.path.exists(VAULT_PATH) or not os.path.exists(LEGACY_VAULT):
        return False
    os.makedirs(DATA_DIR, mode=0o700, exist_ok=True)
    tmp = VAULT_PATH + ".migrando"
    shutil.copy2(LEGACY_VAULT, tmp)
    os.chmod(tmp, 0o600)
    os.replace(tmp, VAULT_PATH)
    return True
AAD = b"enlace-vault-v1"
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1


class VaultError(Exception):
    pass


def _derive(password, salt, n, r, p):
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(password.encode("utf-8"))


def new_id():
    return uuid.uuid4().hex[:12]


class Vault:
    def __init__(self, path=VAULT_PATH):
        if path == VAULT_PATH:
            migrate_legacy()
        self.path = path
        self._key = None
        self._salt = None
        self.data = None

    # --- ciclo de vida -------------------------------------------------
    def exists(self):
        return os.path.exists(self.path)

    @property
    def unlocked(self):
        return self.data is not None

    def create(self, password):
        self._salt = secrets.token_bytes(16)
        self._key = _derive(password, self._salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
        self.data = {}
        self._defaults()
        self.save()

    def unlock(self, password):
        with open(self.path, "r", encoding="utf-8") as f:
            blob = json.load(f)
        salt = base64.b64decode(blob["salt"])
        key = _derive(password, salt, blob["n"], blob["r"], blob["p"])
        try:
            raw = AESGCM(key).decrypt(
                base64.b64decode(blob["nonce"]), base64.b64decode(blob["ct"]), AAD
            )
        except InvalidTag:
            raise VaultError("Contraseña maestra incorrecta")
        self._salt, self._key = salt, key
        self.data = json.loads(raw)
        self._defaults()

    def lock(self):
        self._key = None
        self.data = None

    def change_password(self, new_password):
        self._salt = secrets.token_bytes(16)
        self._key = _derive(new_password, self._salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
        self.save()

    def _defaults(self):
        self.data.setdefault("version", 1)
        self.data.setdefault("hosts", [])
        self.data.setdefault("keys", [])
        self.data.setdefault("settings", {})
        self.data.setdefault("groups", [])
        self.data.setdefault("orgs", [])

    def save(self):
        if self._key is None:
            raise VaultError("La bóveda está bloqueada")
        os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
        nonce = secrets.token_bytes(12)
        ct = AESGCM(self._key).encrypt(
            nonce, json.dumps(self.data, ensure_ascii=False).encode("utf-8"), AAD
        )
        blob = {
            "format": "enlace-vault",
            "kdf": "scrypt",
            "n": SCRYPT_N,
            "r": SCRYPT_R,
            "p": SCRYPT_P,
            "salt": base64.b64encode(self._salt).decode(),
            "nonce": base64.b64encode(nonce).decode(),
            "ct": base64.b64encode(ct).decode(),
        }
        # copia de la versión anterior por si algo sale mal al escribir
        if os.path.exists(self.path):
            shutil.copy2(self.path, self.path + ".bak")
            os.chmod(self.path + ".bak", 0o600)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), prefix=".vault-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(blob, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # --- hosts -----------------------------------------------------------
    @property
    def hosts(self):
        return self.data["hosts"]

    @property
    def keys(self):
        return self.data["keys"]

    def host(self, host_id):
        if isinstance(host_id, str) and host_id.startswith("org:"):
            return self.org_host(host_id)
        return next((h for h in self.hosts if h["id"] == host_id), None)

    # --- organizaciones (Nexo Server) ---------------------------------------
    # Los hosts de una organización no tienen credenciales aquí: se entra por su puerta SSH
    # con un token temporal. Solo se guarda la lista que entrega el servidor.
    @property
    def orgs(self):
        return self.data["orgs"]

    def org(self, org_id):
        return next((o for o in self.orgs if o["id"] == org_id), None)

    def upsert_org(self, org):
        if not org.get("id"):
            org["id"] = new_id()
        for i, o in enumerate(self.orgs):
            if o["id"] == org["id"]:
                self.orgs[i] = org
                break
        else:
            self.orgs.append(org)
        self.save()
        return org

    def delete_org(self, org_id):
        self.data["orgs"] = [o for o in self.orgs if o["id"] != org_id]
        self.save()

    @staticmethod
    def _org_host(org, h):
        return {
            "id": f"org:{org['id']}:{h['id']}", "org": org["id"], "org_name": org["name"],
            "name": h["name"], "group": h.get("group") or "", "protocol": "ssh",
            "host": org["ssh_host"], "port": int(org["ssh_port"]), "user": f"{org['username']}:{h['name']}",
            "auth": "org", "password": "", "key": None, "jump": None, "forwards": [], "rdp": {},
            "icon": h.get("icon") or "server", "notes": h.get("notes") or "", "perms": h.get("perms") or {},
        }

    def org_hosts(self, org):
        return [self._org_host(org, h) for h in org.get("hosts", [])]

    def org_host(self, host_id):
        try:
            _, oid, rid = host_id.split(":", 2)
        except ValueError:
            return None
        org = self.org(oid)
        if not org:
            return None
        h = next((x for x in org.get("hosts", []) if str(x["id"]) == rid), None)
        return self._org_host(org, h) if h else None

    def all_hosts(self):
        out = list(self.hosts)
        for o in self.orgs:
            out += self.org_hosts(o)
        return out

    def key(self, key_id):
        return next((k for k in self.keys if k["id"] == key_id), None)

    def upsert_host(self, host):
        if not host.get("id"):
            host["id"] = new_id()
        for i, h in enumerate(self.hosts):
            if h["id"] == host["id"]:
                self.hosts[i] = host
                break
        else:
            self.hosts.append(host)
        self.save()
        return host

    def delete_host(self, host_id):
        self.data["hosts"] = [h for h in self.hosts if h["id"] != host_id]
        for h in self.hosts:
            if h.get("jump") == host_id:
                h["jump"] = None
        self.save()

    def upsert_key(self, key):
        if not key.get("id"):
            key["id"] = new_id()
        for i, k in enumerate(self.keys):
            if k["id"] == key["id"]:
                self.keys[i] = key
                break
        else:
            self.keys.append(key)
        self.save()
        return key

    def delete_key(self, key_id):
        self.data["keys"] = [k for k in self.keys if k["id"] != key_id]
        for h in self.hosts:
            if h.get("key") == key_id:
                h["key"] = None
        self.save()

    def hosts_using_key(self, key_id):
        return [h for h in self.hosts if h.get("key") == key_id]

    # --- grupos -----------------------------------------------------------
    def group_list(self):
        """Grupos en el orden del usuario; agrega los que existan solo en algún host."""
        groups = self.data["groups"]
        names = {g["name"] for g in groups}
        for h in self.hosts:
            n = h.get("group") or ""
            if n and n not in names:
                groups.append({"name": n, "icon": "folder", "collapsed": False})
                names.add(n)
        return groups

    def groups(self):
        return [g["name"] for g in self.group_list()]

    def group(self, name):
        return next((g for g in self.group_list() if g["name"] == name), None)

    def add_group(self, name, icon="folder"):
        if self.group(name):
            raise VaultError(f"Ya existe el grupo «{name}»")
        self.data["groups"].append({"name": name, "icon": icon, "collapsed": False})
        self.save()

    def update_group(self, old_name, name, icon):
        g = self.group(old_name)
        if g is None:
            raise VaultError("El grupo no existe")
        if name != old_name and self.group(name):
            raise VaultError(f"Ya existe el grupo «{name}»")
        g["name"], g["icon"] = name, icon
        for h in self.hosts:
            if (h.get("group") or "") == old_name:
                h["group"] = name
        self.save()

    def delete_group(self, name):
        self.data["groups"] = [g for g in self.group_list() if g["name"] != name]
        for h in self.hosts:
            if (h.get("group") or "") == name:
                h["group"] = ""
        self.save()

    def move_group(self, name, delta):
        gl = self.group_list()
        i = next((k for k, g in enumerate(gl) if g["name"] == name), None)
        j = None if i is None else i + delta
        if i is not None and 0 <= j < len(gl):
            gl[i], gl[j] = gl[j], gl[i]
            self.save()

    def set_collapsed(self, name, collapsed):
        g = self.group(name)
        if g is not None and g.get("collapsed") != collapsed:
            g["collapsed"] = collapsed
            self.save()

    def set_host_group(self, host_id, name):
        h = self.host(host_id)
        if h is not None and (h.get("group") or "") != name:
            h["group"] = name
            if name:
                self.group_list()
            self.save()
            return True
        return False


def blank_host():
    return {
        "id": None,
        "name": "",
        "group": "",
        "protocol": "ssh",
        "host": "",
        "port": 22,
        "user": "",
        "auth": "key",
        "password": "",
        "key": None,
        "jump": None,
        "forwards": [],
        "rdp": {
            "domain": "",
            "fullscreen": False,
            "resolution": "auto",
            "clipboard": True,
            "share_home": False,
        },
        "icon": None,
        "db": {"database": "", "readonly": False, "tls": False},
        "notes": "",
    }
