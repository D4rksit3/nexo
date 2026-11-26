"""API que la página llama con window.pywebview.api.<método>(...).

Nunca devuelve secretos a la página: ni contraseñas, ni llaves privadas, ni tokens.
Los atributos internos empiezan con «_» para que pywebview no los exponga.
"""
import threading

from nexo import __version__
from nexo import themes as T
from nexo.vault import Vault, VaultError

from . import IS_WINDOWS
from .sessions import LocalSession, SshSession, local_shell

MIN_PASSWORD = 8


class Api:
    def __init__(self):
        self._vault = Vault()
        self._sessions = {}
        self._bridge = None       # lo asigna main una vez creado
        self._window = None
        self._ui = T.load_ui()
        self._lock = threading.Lock()

    # --- estado general --------------------------------------------------
    def info(self):
        return {
            "version": __version__,
            "platform": "windows" if IS_WINDOWS else "linux",
            "vault_exists": self._vault.exists(),
            "unlocked": self._vault.unlocked,
            "local_shell": local_shell()[1],
            "theme": self.theme(),
        }

    def theme(self):
        t = T.get(self._ui.get("theme", T.DEFAULT), self._ui.get("accent"))
        return {"id": t["id"], "name": t["name"], "bg": t["bg"], "fg": t["fg"], "accent": t["accent"],
                "palette": t["palette"], "ui": T.colors(t)}

    # --- bóveda ------------------------------------------------------------
    def create_vault(self, password, repeat):
        if self._vault.exists():
            return {"ok": False, "error": "Ya existe una bóveda en este equipo"}
        if len(password or "") < MIN_PASSWORD:
            return {"ok": False, "error": f"Usa al menos {MIN_PASSWORD} caracteres"}
        if password != repeat:
            return {"ok": False, "error": "Las contraseñas no coinciden"}
        self._vault.create(password)
        return {"ok": True}

    def unlock(self, password):
        try:
            self._vault.unlock(password or "")
        except VaultError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001 — archivo dañado, etc.
            return {"ok": False, "error": f"No se pudo abrir la bóveda: {e}"}
        return {"ok": True}

    def lock(self):
        for s in list(self._sessions.values()):
            s.close()
        self._sessions.clear()
        self._vault.lock()
        return {"ok": True}

    # --- hosts -------------------------------------------------------------
    def hosts(self):
        if not self._vault.unlocked:
            return {"ok": False, "error": "La bóveda está bloqueada"}
        out = []
        for h in self._vault.hosts:
            jump = self._vault.host(h["jump"]) if h.get("jump") else None
            out.append({
                "id": h["id"],
                "name": h.get("name") or h.get("host"),
                "group": h.get("group") or "",
                "protocol": h.get("protocol", "ssh"),
                "host": h.get("host", ""),
                "port": int(h.get("port") or 22),
                "user": h.get("user", ""),
                "auth": h.get("auth", "key"),
                "needs_password": h.get("auth") == "password" and not h.get("password"),
                "jump": jump["name"] if jump else None,
                "icon": h.get("icon"),
                "last_used": h.get("last_used") or 0,
            })
        groups = [{"name": g["name"], "collapsed": bool(g.get("collapsed"))} for g in self._vault.group_list()]
        return {"ok": True, "hosts": out, "groups": groups}

    # --- sesiones ------------------------------------------------------------
    def _register(self, session):
        with self._lock:
            self._sessions[session.id] = session
        session.start()
        return {"ok": True, "sid": session.id, "title": session.title, "kind": session.kind,
                "ws": self._bridge.url(session.id)}

    def open_ssh(self, host_id, password=None, cols=120, rows=32):
        if not self._vault.unlocked:
            return {"ok": False, "error": "La bóveda está bloqueada"}
        host = self._vault.host(host_id)
        if not host:
            return {"ok": False, "error": "Ese host ya no existe"}
        if host.get("protocol", "ssh") != "ssh":
            return {"ok": False, "error": "Esta versión de prueba solo abre hosts SSH"}
        if host.get("auth") == "password" and not (host.get("password") or password):
            return {"ok": False, "error": "need_password"}
        self._touch(host)
        return self._register(SshSession(self._vault, host, password, int(cols), int(rows)))

    def open_local(self, cols=120, rows=32):
        if not self._vault.unlocked:
            return {"ok": False, "error": "La bóveda está bloqueada"}
        return self._register(LocalSession(int(cols), int(rows)))

    def reopen(self, sid, cols=120, rows=32):
        """Enter tras una desconexión: misma pestaña, sesión nueva."""
        old = self._sessions.pop(sid, None)
        if old is None:
            return {"ok": False, "error": "Sesión desconocida"}
        old.close()
        if isinstance(old, SshSession):
            pw = old.host.get("password") if old.host.get("auth") == "password" else None
            return self._register(SshSession(self._vault, self._vault.host(old.host["id"]) or old.host,
                                             pw, int(cols), int(rows)))
        return self._register(LocalSession(int(cols), int(rows)))

    def close_session(self, sid):
        s = self._sessions.pop(sid, None)
        if s:
            s.close()
        return {"ok": True}

    def _touch(self, host):
        import time

        host["last_used"] = int(time.time())
        try:
            self._vault.save()
        except Exception:  # noqa: BLE001 — no es grave si no se guarda
            pass

    # --- portapapeles (respaldo si el de la página no está permitido) ------------
    def clipboard_set(self, text):
        from . import clipboard

        return {"ok": clipboard.set_text(text or "")}

    def clipboard_get(self):
        from . import clipboard

        text = clipboard.get_text()
        return {"ok": text is not None, "text": text or ""}

    # --- cierre ----------------------------------------------------------------
    def _shutdown(self):
        for s in list(self._sessions.values()):
            s.close()
        self._sessions.clear()
        if self._vault.unlocked:
            self._vault.lock()
