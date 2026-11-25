"""Llaves SSH: carga, generación, huella y un ssh-agent propio de la app.

Las llaves privadas viven cifradas en la bóveda. Para conectar se cargan en un
ssh-agent privado (socket en $XDG_RUNTIME_DIR, permisos 0700): la llave privada
descifrada nunca toca el disco. Al disco solo va la llave PÚBLICA, que ssh usa
con -i + IdentitiesOnly para elegir cuál ofrecer.
"""
import base64
import hashlib
import os
import shutil
import subprocess
import tempfile
import time

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa


class KeyError_(Exception):
    pass


class NeedsPassphrase(Exception):
    pass


def load_private(text, passphrase=None):
    data = text.strip().encode() + b"\n"
    pw = passphrase.encode() if passphrase else None
    errors = []
    for loader in (serialization.load_ssh_private_key, serialization.load_pem_private_key):
        try:
            return loader(data, pw)
        except TypeError as e:
            msg = str(e)
            if "not provided" in msg or "not given" in msg or "encrypted" in msg and pw is None:
                raise NeedsPassphrase()
            if "not encrypted" in msg:
                # se dio frase pero la llave no la tiene: reintentar sin frase
                return loader(data, None)
            errors.append(msg)
        except (ValueError, UnsupportedAlgorithm) as e:
            errors.append(str(e))
    if pw is not None:
        raise KeyError_("Frase de paso incorrecta o llave no válida")
    raise KeyError_("No es una llave privada reconocible: " + "; ".join(errors))


def key_kind(pk):
    if isinstance(pk, ed25519.Ed25519PrivateKey):
        return "ED25519"
    if isinstance(pk, rsa.RSAPrivateKey):
        return f"RSA {pk.key_size}"
    if isinstance(pk, ec.EllipticCurvePrivateKey):
        return f"ECDSA {pk.curve.key_size}"
    return type(pk).__name__


def to_openssh(pk):
    """Privada en formato OpenSSH SIN frase (solo se guarda dentro de la bóveda)."""
    return pk.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ).decode()


def public_line(pk, comment=""):
    pub = pk.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    ).decode()
    return f"{pub} {comment}".strip()


def fingerprint(pub_line):
    blob = base64.b64decode(pub_line.split()[1])
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


def make_key_record(name, pk):
    pub = public_line(pk, name)
    return {
        "id": None,
        "name": name,
        "kind": key_kind(pk),
        "private": to_openssh(pk),
        "public": pub,
        "fingerprint": fingerprint(pub),
    }


def generate(name, kind="ed25519"):
    if kind == "ed25519":
        pk = ed25519.Ed25519PrivateKey.generate()
    elif kind == "rsa":
        pk = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    elif kind == "ecdsa":
        pk = ec.generate_private_key(ec.SECP256R1())
    else:
        raise KeyError_(f"Tipo no soportado: {kind}")
    return make_key_record(name, pk)


def paramiko_pkey(private_text):
    import io

    import paramiko

    last = None
    for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            return cls.from_private_key(io.StringIO(private_text))
        except Exception as e:  # noqa: BLE001 - probamos el siguiente tipo
            last = e
    raise KeyError_(f"paramiko no pudo leer la llave: {last}")


class Agent:
    """ssh-agent privado de la app."""

    def __init__(self):
        base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
        self.dir = tempfile.mkdtemp(prefix="nexo-", dir=base)
        os.chmod(self.dir, 0o700)
        self.sock = os.path.join(self.dir, "agent.sock")
        self.proc = subprocess.Popen(
            ["ssh-agent", "-D", "-a", self.sock],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        for _ in range(100):
            if os.path.exists(self.sock):
                break
            time.sleep(0.02)
        self.loaded = {}  # key_id -> fingerprint

    def env(self):
        return {"SSH_AUTH_SOCK": self.sock}

    def ensure(self, key):
        """Carga la llave en el agente (si no estaba) y devuelve la ruta de su .pub."""
        pub_path = os.path.join(self.dir, f"key-{key['id']}.pub")
        if self.loaded.get(key["id"]) != key["fingerprint"]:
            r = subprocess.run(
                ["ssh-add", "-q", "-"],
                input=key["private"].encode(),
                env={**os.environ, **self.env()},
                capture_output=True,
                timeout=15,
            )
            if r.returncode != 0:
                raise KeyError_("ssh-add falló: " + r.stderr.decode(errors="replace").strip())
            self.loaded[key["id"]] = key["fingerprint"]
        with open(pub_path, "w") as f:
            f.write(key["public"] + "\n")
        os.chmod(pub_path, 0o600)
        return pub_path

    def clear(self):
        subprocess.run(
            ["ssh-add", "-D"],
            env={**os.environ, **self.env()},
            capture_output=True,
            timeout=10,
        )
        self.loaded.clear()

    def tmpfile(self, name):
        return os.path.join(self.dir, name)

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(self.dir, ignore_errors=True)
