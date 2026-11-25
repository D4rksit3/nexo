"""Cliente de la API de Nexo Server (inicio de sesión con 2FA y lista de hosts permitidos)."""
import json
import ssl
import urllib.error
import urllib.request


class OrgError(Exception):
    pass


class OrgExpired(OrgError):
    pass


def _norm(url):
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _call(url, path, payload=None, token=None, timeout=15):
    req = urllib.request.Request(_norm(url) + path, method="POST" if payload is not None else "GET")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "Nexo")
    if payload is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(payload).encode()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode()).get("error") or e.reason
        except Exception:  # noqa: BLE001
            msg = e.reason
        if e.code == 401 and token:
            raise OrgExpired(msg)
        raise OrgError(msg)
    except urllib.error.URLError as e:
        raise OrgError(f"No se pudo conectar con {url}: {e.reason}")
    except (TimeoutError, OSError) as e:
        raise OrgError(f"No se pudo conectar con {url}: {e}")


def login(url, username, password, totp):
    r = _call(url, "/api/v1/login", {"username": username, "password": password, "totp": totp, "client": "Nexo"})
    return {"url": _norm(url), "name": r["name"], "username": r["username"], "token": r["token"],
            "expires": r["expires"], "ssh_host": r["ssh_host"], "ssh_port": r["ssh_port"],
            "fingerprint": r.get("fingerprint", "")}


def hosts(org):
    return _call(org["url"], "/api/v1/hosts", token=org["token"])["hosts"]


def logout(org):
    try:
        _call(org["url"], "/api/v1/logout", {}, token=org["token"], timeout=5)
    except OrgError:
        pass
