"""API que la página llama con window.pywebview.api.<método>(...).

Nunca devuelve secretos a la página: ni contraseñas guardadas, ni llaves privadas, ni tokens.
(Sí recibe de la página lo que el usuario escribe: contraseñas nuevas, llaves pegadas.)
Los atributos internos empiezan con «_» para que pywebview no los exponga.

Todas las respuestas son {"ok": True, ...} o {"ok": False, "error": "..."}.
Python avisa a la página por eventos: window.nexoEvent({type, ...}).
"""
import copy
import json
import os
import threading
import time

from nexo import __version__
from nexo import keys as K
from nexo import themes as T
from nexo.vault import VAULT_PATH, Vault, VaultError, blank_host, new_id

from . import IS_WINDOWS
from .sessions import LocalSession, SshSession, _reason, local_shell

MIN_PASSWORD = 8
PROTOCOLS = ("ssh", "rdp", "postgres", "mysql", "mssql", "mongodb", "redis")
AUTOLOCK_DEFAULT_MIN = 15


def _fail(e):
    msg = e if isinstance(e, str) else (_reason(e) if not isinstance(e, (VaultError, ValueError)) else str(e))
    return {"ok": False, "error": msg or "Error desconocido"}


def guarded(fn):
    """Convierte cualquier excepción en {"ok": False, "error": ...} para la página."""
    import functools

    @functools.wraps(fn)
    def wrap(self, *a, **kw):
        try:
            return fn(self, *a, **kw)
        except Exception as e:  # noqa: BLE001
            return _fail(e)
    return wrap


def needs_vault(fn):
    import functools

    @functools.wraps(fn)
    def wrap(self, *a, **kw):
        if not self._vault.unlocked:
            return {"ok": False, "error": "La bóveda está bloqueada", "locked": True}
        return fn(self, *a, **kw)
    return guarded(wrap)


class Api:
    def __init__(self):
        self._vault = Vault()
        self._sessions = {}       # terminales (las usa el puente WebSocket)
        self._files = {}          # pestañas SFTP
        self._dbs = {}            # pestañas de base de datos
        self._rdps = {}
        self._tunnels = {}        # host_id -> forward.Tunnel
        self._bridge = None       # lo asigna main una vez creado
        self._window = None
        self._ui = T.load_ui()
        self._lock = threading.Lock()
        self._pending_key = None  # llave leída que espera su frase de paso

    # --- eventos hacia la página --------------------------------------------------
    def _emit(self, kind, payload=None):
        w = self._window
        if w is None:
            return
        data = json.dumps({"type": kind, **(payload or {})}, ensure_ascii=False)
        try:
            w.evaluate_js(f"window.nexoEvent && window.nexoEvent({data})")
        except Exception:  # noqa: BLE001 — ventana cerrándose
            pass

    # --- estado general --------------------------------------------------------------
    def info(self):
        from . import rdp

        return {
            "version": __version__,
            "platform": "windows" if IS_WINDOWS else "linux",
            "store": bool(os.environ.get("NEXO_STORE")) or _is_packaged(),
            "vault_exists": self._vault.exists(),
            "unlocked": self._vault.unlocked,
            "local_shell": local_shell()[1],
            "sep": os.sep,
            "home": os.path.expanduser("~"),
            "rdp": rdp.available(),
            "ui": {"sidebar": bool(self._ui.get("sidebar", True))},
            "theme": self.theme(),
            "settings": self._settings() if self._vault.unlocked else None,
        }

    def theme(self):
        t = T.get(self._ui.get("theme", T.DEFAULT), self._ui.get("accent"))
        return {"id": t["id"], "name": t["name"], "bg": t["bg"], "fg": t["fg"], "accent": t["accent"],
                "accent_id": t["accent_id"], "palette": t["palette"],
                # la interfaz es siempre la neutra de Nexo; el tema solo pinta las terminales
                "ui": T.colors(T.ui_theme(t)), "term_sel": T.colors(t)["sel"]}

    def themes(self):
        out = []
        for tid, (name, bg, fg, acc, pal) in T.THEMES.items():
            out.append({"id": tid, "name": name, "bg": bg, "fg": fg, "accent": acc, "palette": pal})
        accents = [{"id": aid, "name": n, "color": c} for aid, (n, c) in T.ACCENTS.items()]
        return {"ok": True, "themes": out, "accents": accents, "current": self.theme()}

    @guarded
    def set_theme(self, theme_id=None, accent=None):
        if theme_id is not None:
            if theme_id not in T.THEMES:
                return _fail("Tema desconocido")
            self._ui["theme"] = theme_id
        if accent is not None:
            if accent not in T.ACCENTS:
                return _fail("Color desconocido")
            self._ui["accent"] = accent
        T.save_ui(self._ui)
        return {"ok": True, "theme": self.theme()}

    def _settings(self):
        s = self._vault.data.get("settings", {})
        return {"autolock_min": int(s.get("autolock_min", AUTOLOCK_DEFAULT_MIN)),
                "lock_on_screen": bool(s.get("lock_on_screen", True))}

    @needs_vault
    def set_settings(self, autolock_min=None, lock_on_screen=None):
        s = self._vault.data["settings"]
        if autolock_min is not None:
            m = int(autolock_min)
            if m < 0 or m > 24 * 60:
                return _fail("Entre 0 (nunca) y 1440 minutos")
            s["autolock_min"] = m
        if lock_on_screen is not None:
            s["lock_on_screen"] = bool(lock_on_screen)
        self._vault.save()
        return {"ok": True, "settings": self._settings()}

    # --- bóveda ------------------------------------------------------------------------
    @guarded
    def create_vault(self, password, repeat):
        if self._vault.exists():
            return _fail("Ya existe una bóveda en este equipo")
        if len(password or "") < MIN_PASSWORD:
            return _fail(f"Usa al menos {MIN_PASSWORD} caracteres")
        if password != repeat:
            return _fail("Las contraseñas no coinciden")
        self._vault.create(password)
        return {"ok": True}

    def unlock(self, password):
        try:
            self._vault.unlock(password or "")
        except VaultError as e:
            return _fail(str(e))
        except Exception as e:  # noqa: BLE001 — archivo dañado, etc.
            return _fail(f"No se pudo abrir la bóveda: {e}")
        return {"ok": True}

    def lock(self):
        self._close_everything()
        self._vault.lock()
        return {"ok": True}

    @needs_vault
    def change_password(self, current, new, repeat):
        probe = Vault(self._vault.path)
        try:
            probe.unlock(current or "")
        except VaultError:
            return _fail("La contraseña actual no es correcta")
        finally:
            probe.lock()
        if len(new or "") < MIN_PASSWORD:
            return _fail(f"Usa al menos {MIN_PASSWORD} caracteres")
        if new != repeat:
            return _fail("Las contraseñas nuevas no coinciden")
        self._vault.change_password(new)
        return {"ok": True}

    @needs_vault
    def export_vault(self):
        """Copia el archivo cifrado (vault.enc) donde elija el usuario. Sirve de respaldo y para
        llevar los hosts a otro equipo: se abre con la misma contraseña maestra."""
        import shutil

        import webview

        name = f"nexo-boveda-{time.strftime('%Y%m%d')}.enc"
        r = self._window.create_file_dialog(webview.FileDialog.SAVE, directory=os.path.expanduser("~"),
                                            save_filename=name)
        path = _first(r)
        if not path:
            return {"ok": False, "cancelled": True}
        self._vault.save()
        shutil.copyfile(self._vault.path, path)
        return {"ok": True, "path": path}

    @guarded
    def import_vault(self):
        """Desde la pantalla de bloqueo: reemplaza la bóveda de este equipo por un archivo
        exportado (o el vault.enc de Nexo para Linux). La actual queda como respaldo."""
        import shutil

        import webview

        if self._vault.unlocked:
            return _fail("Bloquea Nexo antes de importar una bóveda")
        r = self._window.create_file_dialog(webview.FileDialog.OPEN, directory=os.path.expanduser("~"),
                                            file_types=("Bóveda de Nexo (*.enc)", "Todos los archivos (*.*)"))
        path = _first(r)
        if not path:
            return {"ok": False, "cancelled": True}
        try:
            with open(path, encoding="utf-8") as f:
                blob = json.load(f)
            assert blob.get("format") == "enlace-vault" and blob.get("ct")
        except Exception:  # noqa: BLE001
            return _fail("Ese archivo no es una bóveda de Nexo")
        os.makedirs(os.path.dirname(VAULT_PATH), exist_ok=True)
        if os.path.exists(self._vault.path):
            shutil.copyfile(self._vault.path, self._vault.path + f".antes-de-importar-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copyfile(path, self._vault.path)
        return {"ok": True}

    # --- hosts ---------------------------------------------------------------------------
    def _host_view(self, h):
        jump = self._vault.host(h["jump"]) if h.get("jump") else None
        proto = h.get("protocol", "ssh")
        return {
            "id": h["id"], "name": h.get("name") or h.get("host"), "group": h.get("group") or "",
            "protocol": proto, "host": h.get("host", ""), "port": int(h.get("port") or 22),
            "user": h.get("user", ""), "auth": h.get("auth", "key"),
            "needs_password": proto == "ssh" and h.get("auth") == "password" and not h.get("password"),
            "jump": jump["name"] if jump else None, "icon": h.get("icon"),
            "last_used": h.get("last_used") or 0, "forwards": len(h.get("forwards") or []),
            "org": h.get("org"), "org_name": h.get("org_name"), "perms": h.get("perms") or {},
            "notes": bool((h.get("notes") or "").strip()),
            "tunnel": self._tunnels[h["id"]].state if h["id"] in self._tunnels else None,
        }

    @needs_vault
    def hosts(self):
        out = [self._host_view(h) for h in self._vault.hosts]
        for o in self._vault.orgs:
            out += [self._host_view(h) for h in self._vault.org_hosts(o)]
        groups = [{"name": g["name"], "icon": g.get("icon") or "folder", "collapsed": bool(g.get("collapsed"))}
                  for g in self._vault.group_list()]
        orgs = [{"id": o["id"], "name": o["name"], "url": o["url"], "username": o["username"],
                 "expired": bool(o.get("expired")) or (o.get("expires") or 0) < time.time(),
                 "hosts": len(o.get("hosts") or [])} for o in self._vault.orgs]
        return {"ok": True, "hosts": out, "groups": groups, "orgs": orgs}

    @needs_vault
    def host_get(self, host_id):
        """Datos para el formulario de edición. La contraseña no viaja: solo si hay una guardada."""
        h = self._vault.host(host_id) if host_id else None
        if host_id and not h:
            return _fail("Ese host ya no existe")
        h = copy.deepcopy(h) if h else blank_host()
        h.setdefault("rdp", blank_host()["rdp"])
        h.setdefault("db", blank_host()["db"])
        h["has_password"] = bool(h.pop("password", ""))
        jumps = [{"id": x["id"], "name": x["name"], "host": x["host"]}
                 for x in sorted(self._vault.hosts, key=lambda x: x["name"].lower())
                 if x.get("protocol", "ssh") == "ssh" and x["id"] != h.get("id")]
        for o in self._vault.orgs:
            for oh in self._vault.org_hosts(o):
                if oh.get("perms", {}).get("tunnel"):
                    jumps.append({"id": oh["id"], "name": oh["name"], "host": f"vía {o['name']}"})
        keys = [{"id": k["id"], "name": k["name"], "kind": k["kind"]} for k in self._vault.keys]
        return {"ok": True, "host": h, "groups": self._vault.groups(), "jumps": jumps, "keys": keys}

    @needs_vault
    def save_host(self, data):
        """Crea o actualiza un host con lo que manda el formulario."""
        hid = data.get("id")
        old = self._vault.host(hid) if hid else None
        if hid and (not old or old.get("org")):
            return _fail("Ese host no se puede editar")
        h = copy.deepcopy(old) if old else blank_host()
        proto = data.get("protocol") or "ssh"
        if proto not in PROTOCOLS:
            return _fail("Protocolo no soportado")
        host = (data.get("host") or "").strip()
        if not host:
            return _fail("Falta el host (IP o nombre)")
        try:
            port = int(data.get("port") or 0)
        except (TypeError, ValueError):
            port = 0
        if not 1 <= port <= 65535:
            return _fail("Puerto inválido")
        h.update(name=(data.get("name") or "").strip() or host, group=(data.get("group") or "").strip(),
                 protocol=proto, host=host, port=port, user=(data.get("user") or "").strip(),
                 icon=data.get("icon") or h.get("icon"), notes=data.get("notes") or "")
        h["auth"] = (data.get("auth") or "key") if proto == "ssh" else "password"
        if h["auth"] == "key":
            h["key"] = data.get("key") or None
            if not h["key"] or not self._vault.key(h["key"]):
                return _fail("Elige una llave (o créala en «Llaves»)")
            h["password"] = ""
        else:
            h["key"] = None
            if data.get("password_clear"):
                h["password"] = ""
            elif data.get("password"):
                h["password"] = data["password"]
            # si no viene nada, se conserva la guardada
        jump = data.get("jump") or None
        if jump and (jump == h.get("id") or not self._vault.host(jump)):
            return _fail("El salto elegido no es válido")
        h["jump"] = jump
        fws = []
        if proto == "ssh":
            for fw in data.get("forwards") or []:
                typ = fw.get("type")
                if typ not in ("L", "R", "D"):
                    continue
                p = str(fw.get("port") if fw.get("port") is not None else "").strip()
                if not p:
                    continue
                if not p.isdigit() or not 1 <= int(p) <= 65535:
                    return _fail(f"Puerto inválido en un túnel: {p}")
                rec = {"type": typ, "bind": (fw.get("bind") or "127.0.0.1").strip(), "port": int(p)}
                if typ != "D":
                    dh, dp = (fw.get("dest_host") or "").strip(), str(fw.get("dest_port") or "").strip()
                    if not dh or not dp.isdigit():
                        return _fail("Cada túnel local o remoto necesita destino y puerto de destino")
                    rec.update(dest_host=dh, dest_port=int(dp))
                fws.append(rec)
        h["forwards"] = fws
        r = data.get("rdp") or {}
        h["rdp"] = {"domain": (r.get("domain") or "").strip(), "resolution": r.get("resolution") or "auto",
                    "fullscreen": bool(r.get("fullscreen")), "clipboard": bool(r.get("clipboard", True)),
                    "share_home": bool(r.get("share_home"))}
        d = data.get("db") or {}
        h["db"] = {"database": (d.get("database") or "").strip(), "auth_db": (d.get("auth_db") or "").strip(),
                   "readonly": bool(d.get("readonly")), "tls": bool(d.get("tls"))}
        if not old:
            h["id"] = None
        self._vault.upsert_host(h)
        if h["group"]:
            self._vault.group_list()
            self._vault.save()
        return {"ok": True, "id": h["id"]}

    @needs_vault
    def delete_host(self, host_id):
        t = self._tunnels.pop(host_id, None)
        if t:
            t.stop()
        self._vault.delete_host(host_id)
        return {"ok": True}

    @needs_vault
    def duplicate_host(self, host_id):
        h = self._vault.host(host_id)
        if not h or h.get("org"):
            return _fail("Ese host no se puede duplicar")
        c = copy.deepcopy(h)
        c["id"], c["name"], c["last_used"] = None, f"{h['name']} (copia)", 0
        self._vault.upsert_host(c)
        return {"ok": True, "id": c["id"]}

    @needs_vault
    def move_host(self, host_id, group):
        self._vault.set_host_group(host_id, group or "")
        return {"ok": True}

    @needs_vault
    def host_notes(self, host_id):
        h = self._vault.host(host_id)
        return {"ok": True, "notes": (h or {}).get("notes") or ""}

    # --- grupos ------------------------------------------------------------------------
    @needs_vault
    def add_group(self, name, icon="folder"):
        name = (name or "").strip()
        if not name:
            return _fail("Escribe un nombre")
        self._vault.add_group(name, icon or "folder")
        return {"ok": True}

    @needs_vault
    def update_group(self, old, name, icon="folder"):
        name = (name or "").strip()
        if not name:
            return _fail("Escribe un nombre")
        self._vault.update_group(old, name, icon or "folder")
        return {"ok": True}

    @needs_vault
    def delete_group(self, name):
        self._vault.delete_group(name)
        return {"ok": True}

    @needs_vault
    def move_group(self, name, delta):
        self._vault.move_group(name, int(delta))
        return {"ok": True}

    @needs_vault
    def set_collapsed(self, name, collapsed):
        self._vault.set_collapsed(name, bool(collapsed))
        return {"ok": True}

    @needs_vault
    def import_ssh_config(self):
        """Importa los hosts de ~/.ssh/config (y sus llaves, si se pueden leer sin frase)."""
        import webview

        from nexo import conn

        path = os.path.join(os.path.expanduser("~"), ".ssh", "config")
        if not os.path.exists(path):
            r = self._window.create_file_dialog(webview.FileDialog.OPEN, directory=os.path.expanduser("~"))
            path = _first(r)
            if not path:
                return {"ok": False, "cancelled": True}
        entries = conn.parse_ssh_config(path)
        existing = {(h["host"], int(h.get("port") or 22), h.get("user") or "") for h in self._vault.hosts}
        by_alias = {h["name"]: h for h in self._vault.hosts}
        added, skipped, locked_keys = [], 0, []
        for e in entries:
            hostname = e.get("hostname", e["alias"])
            port = int(e.get("port", 22)) if str(e.get("port", 22)).isdigit() else 22
            user = e.get("user", "")
            if (hostname, port, user) in existing:
                skipped += 1
                continue
            h = blank_host()
            h.update(name=e["alias"], group="~/.ssh/config", host=hostname, port=port, user=user)
            if e.get("identityfile"):
                kp = os.path.expanduser(e["identityfile"].strip('"'))
                try:
                    with open(kp, encoding="utf-8", errors="replace") as f:
                        rec = K.make_key_record(os.path.basename(kp), K.load_private(f.read()))
                    h["key"] = self._add_key(rec)["id"]
                except K.NeedsPassphrase:
                    locked_keys.append(os.path.basename(kp))
                except Exception:  # noqa: BLE001 — llave ilegible: queda con contraseña
                    pass
            h["auth"] = "key" if h["key"] else "password"
            h["_proxyjump"] = e.get("proxyjump")
            h["id"] = new_id()
            self._vault.hosts.append(h)
            by_alias[h["name"]] = h
            existing.add((hostname, port, user))
            added.append(h)
        for h in added:
            pj = h.pop("_proxyjump", None)
            if pj:
                alias = pj.split(",")[0].split("@")[-1].split(":")[0]
                if alias in by_alias:
                    h["jump"] = by_alias[alias]["id"]
        self._vault.group_list()
        self._vault.save()
        return {"ok": True, "added": len(added), "skipped": skipped, "locked_keys": locked_keys}

    # --- llaves ---------------------------------------------------------------------------
    @needs_vault
    def keys(self):
        out = []
        for k in self._vault.keys:
            used = [h["name"] for h in self._vault.hosts_using_key(k["id"])]
            out.append({"id": k["id"], "name": k["name"], "kind": k["kind"], "public": k["public"],
                        "fingerprint": k["fingerprint"], "used_by": used})
        return {"ok": True, "keys": out}

    def _add_key(self, rec):
        for k in self._vault.keys:
            if k["fingerprint"] == rec["fingerprint"]:
                return k
        return self._vault.upsert_key(rec)

    @needs_vault
    def generate_key(self, name, kind="ed25519"):
        name = (name or "").strip() or f"nexo-{kind}"
        rec = K.generate(name, kind)
        self._vault.upsert_key(rec)
        return {"ok": True, "id": rec["id"], "public": rec["public"]}

    @needs_vault
    def import_key_text(self, text, name, passphrase=None):
        name = (name or "").strip() or "llave"
        try:
            pk = K.load_private(text or "", passphrase or None)
        except K.NeedsPassphrase:
            return {"ok": False, "need_passphrase": True, "error": "La llave está protegida con frase de paso"}
        except K.KeyError_ as e:
            if passphrase:
                return {"ok": False, "need_passphrase": True, "error": "Frase de paso incorrecta"}
            return _fail(str(e))
        rec = self._add_key(K.make_key_record(name, pk))
        return {"ok": True, "id": rec["id"], "name": rec["name"]}

    @needs_vault
    def pick_key_file(self):
        """Elige un archivo de llave privada; devuelve su texto SOLO al backend (no a la página)."""
        import webview

        start = os.path.join(os.path.expanduser("~"), ".ssh")
        r = self._window.create_file_dialog(webview.FileDialog.OPEN,
                                            directory=start if os.path.isdir(start) else os.path.expanduser("~"))
        path = _first(r)
        if not path:
            return {"ok": False, "cancelled": True}
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        name = os.path.basename(path)
        for suf in (".pem", ".key", ".ppk"):
            if name.endswith(suf):
                name = name[: -len(suf)]
        if "PuTTY-User-Key-File" in text:
            return _fail("Es una llave de PuTTY (.ppk). Conviértela con PuTTYgen → Conversions → Export OpenSSH key.")
        self._pending_key = (text, name)
        return self.import_pending_key(None)

    @needs_vault
    def import_pending_key(self, passphrase=None):
        if not self._pending_key:
            return _fail("No hay llave pendiente")
        text, name = self._pending_key
        r = self.import_key_text(text, name, passphrase)
        if r.get("ok") or not r.get("need_passphrase"):
            self._pending_key = None
        r["name"] = r.get("name") or name
        return r

    @needs_vault
    def rename_key(self, key_id, name):
        k = self._vault.key(key_id)
        if not k:
            return _fail("La llave no existe")
        k["name"] = (name or "").strip() or k["name"]
        self._vault.save()
        return {"ok": True}

    @needs_vault
    def delete_key(self, key_id):
        self._vault.delete_key(key_id)
        return {"ok": True}

    @needs_vault
    def save_public_key(self, key_id):
        import webview

        k = self._vault.key(key_id)
        if not k:
            return _fail("La llave no existe")
        r = self._window.create_file_dialog(webview.FileDialog.SAVE, directory=os.path.expanduser("~"),
                                            save_filename=f"{k['name']}.pub")
        path = _first(r)
        if not path:
            return {"ok": False, "cancelled": True}
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(k["public"] + "\n")
        return {"ok": True, "path": path}

    # --- terminales ---------------------------------------------------------------------
    def _register(self, session):
        with self._lock:
            self._sessions[session.id] = session
        session.start()
        return {"ok": True, "sid": session.id, "title": session.title, "kind": session.kind,
                "ws": self._bridge.url(session.id)}

    def _host_for(self, host_id, password, protocols):
        host = self._vault.host(host_id)
        if not host:
            raise ValueError("Ese host ya no existe")
        if host.get("protocol", "ssh") not in protocols:
            raise ValueError("Este host no es de ese tipo")
        needs = host.get("auth") == "password" and not (host.get("password") or password)
        if needs and host.get("protocol", "ssh") == "ssh":
            return host, "need_password"
        return host, None

    @needs_vault
    def open_ssh(self, host_id, password=None, cols=120, rows=32):
        host, need = self._host_for(host_id, password, ("ssh",))
        if need:
            return _fail(need)
        self._touch(host)
        return self._register(SshSession(self._vault, host, password, int(cols), int(rows)))

    @needs_vault
    def open_quick(self, target, password=None, cols=120, rows=32):
        """Conexión rápida «usuario@host:puerto» sin guardar nada en la bóveda."""
        target = (target or "").strip()
        if not target or " " in target:
            return _fail("Escribe usuario@host o usuario@host:puerto")
        user, _, rest = target.rpartition("@")
        host, port = rest, 22
        if rest.count(":") == 1:
            host, p = rest.split(":")
            if not p.isdigit() or not 1 <= int(p) <= 65535:
                return _fail("Puerto inválido")
            port = int(p)
        if not host:
            return _fail("Falta el host")
        if not password:
            return _fail("need_password")
        h = dict(blank_host(), id=f"quick:{new_id()}", name=target, host=host, port=port,
                 user=user or os.environ.get("USERNAME") or os.environ.get("USER") or "", auth="password")
        return self._register(SshSession(self._vault, h, password, int(cols), int(rows)))

    @needs_vault
    def open_local(self, cols=120, rows=32):
        return self._register(LocalSession(int(cols), int(rows)))

    @needs_vault
    def reopen(self, sid, cols=120, rows=32):
        """Enter tras una desconexión: misma pestaña, sesión nueva."""
        old = self._sessions.pop(sid, None)
        if old is None:
            return _fail("Sesión desconocida")
        old.close()
        if isinstance(old, SshSession):
            host = self._vault.host(old.host["id"]) or old.host
            pw = old.host.get("password") if old.host.get("auth") == "password" else None
            return self._register(SshSession(self._vault, host, pw, int(cols), int(rows)))
        return self._register(LocalSession(int(cols), int(rows)))

    def close_session(self, sid):
        for store in (self._sessions, self._files, self._dbs):
            s = store.pop(sid, None)
            if s:
                s.close()
        return {"ok": True}

    def _touch(self, host):
        if host.get("org"):
            return
        h = self._vault.host(host["id"])
        if h is None:
            return
        h["last_used"] = int(time.time())
        try:
            self._vault.save()
        except Exception:  # noqa: BLE001 — no es grave si no se guarda
            pass

    # --- SFTP -----------------------------------------------------------------------------
    @needs_vault
    def open_sftp(self, host_id, password=None):
        from .files import FileSession

        host, need = self._host_for(host_id, password, ("ssh",))
        if need:
            return _fail(need)
        if host.get("org") and not (host.get("perms") or {}).get("sftp", True):
            return _fail("Tu organización no te permite SFTP en este host")
        fs = FileSession(self._vault, host, password, emit=self._emit)
        home = fs.connect()
        self._files[fs.id] = fs
        self._touch(host)
        return {"ok": True, "sid": fs.id, "title": fs.title, "home": home}

    def _fs(self, sid):
        fs = self._files.get(sid)
        if fs is None:
            raise ValueError("La pestaña SFTP ya no está conectada")
        return fs

    @guarded
    def sftp_list(self, sid, path):
        return {"ok": True, **self._fs(sid).list(path)}

    @guarded
    def sftp_mkdir(self, sid, path):
        self._fs(sid).mkdir(path)
        return {"ok": True}

    @guarded
    def sftp_rename(self, sid, path, new_name):
        self._fs(sid).rename(path, new_name)
        return {"ok": True}

    @guarded
    def sftp_delete(self, sid, paths):
        self._fs(sid).delete(paths)
        return {"ok": True}

    @guarded
    def sftp_clash(self, sid, direction, names, dest):
        """Nombres que ya existen en el destino (para preguntar reemplazar/omitir)."""
        if direction == "up":
            return {"ok": True, "clash": self._fs(sid).exists_remote(dest, names)}
        there = set(os.listdir(dest)) if os.path.isdir(dest) else set()
        return {"ok": True, "clash": sorted(set(names) & there)}

    @guarded
    def sftp_transfer(self, sid, direction, names, src, dest, skip=None):
        job = self._fs(sid).start_transfer(direction, names, src, dest, skip or [])
        return {"ok": True, "job": dict(job)}

    @guarded
    def sftp_progress(self, sid):
        return {"ok": True, "job": self._fs(sid).progress()}

    @guarded
    def sftp_cancel(self, sid):
        self._fs(sid).cancel_transfer()
        return {"ok": True}

    @guarded
    def sftp_edit(self, sid, path):
        rec = self._fs(sid).edit(path)
        return {"ok": True, "local": rec["local"]}

    @guarded
    def sftp_force_upload(self, sid, local):
        self._fs(sid).force_upload(local)
        return {"ok": True}

    @guarded
    def sftp_pick_upload(self, sid, folder=False):
        import webview

        kind = webview.FileDialog.FOLDER if folder else webview.FileDialog.OPEN
        r = self._window.create_file_dialog(kind, directory=os.path.expanduser("~"), allow_multiple=not folder)
        paths = list(r or [])
        return {"ok": True, "paths": paths}

    # --- este equipo -------------------------------------------------------------------------
    @guarded
    def local_list(self, path):
        from . import files

        return {"ok": True, **files.local_list(path), "parent": files.local_parent(path) if path else None}

    @guarded
    def local_mkdir(self, path):
        from . import files

        files.local_mkdir(path)
        return {"ok": True}

    @guarded
    def local_rename(self, path, new_name):
        from . import files

        files.local_rename(path, new_name)
        return {"ok": True}

    @guarded
    def local_trash(self, paths):
        from . import files

        files.local_trash(paths)
        return {"ok": True}

    @guarded
    def local_open(self, path, reveal=False):
        from . import files

        (files.reveal if reveal else files.open_default)(path)
        return {"ok": True}

    # --- túneles --------------------------------------------------------------------------
    @needs_vault
    def tunnels(self):
        from nexo import conn

        out = []
        for h in self._vault.hosts:
            if h.get("protocol", "ssh") != "ssh" or not h.get("forwards"):
                continue
            t = self._tunnels.get(h["id"])
            out.append({"id": h["id"], "name": h["name"], "target": conn.label(h),
                        "forwards": [conn.forward_text(f) for f in h["forwards"]],
                        "state": t.state if t else "detenido", "error": t.error if t else "",
                        "needs_password": h.get("auth") == "password" and not h.get("password")})
        return {"ok": True, "tunnels": out}

    @needs_vault
    def tunnel_start(self, host_id, password=None):
        from .forward import Tunnel

        h = self._vault.host(host_id)
        if not h or not h.get("forwards"):
            return _fail("Ese host no tiene túneles")
        if h.get("auth") == "password" and not (h.get("password") or password):
            return _fail("need_password")
        old = self._tunnels.get(host_id)
        if old and old.running:
            return {"ok": True}

        def changed(t):
            self._emit("tunnel", {"id": host_id, "state": t.state, "error": t.error})

        t = Tunnel(self._vault, h, h["forwards"], on_change=changed, password=password)
        self._tunnels[host_id] = t
        t.start()
        return {"ok": True}

    @guarded
    def tunnel_stop(self, host_id):
        t = self._tunnels.pop(host_id, None)
        if t:
            t.stop()
            self._emit("tunnel", {"id": host_id, "state": "detenido", "error": ""})
        return {"ok": True}

    # --- bases de datos ---------------------------------------------------------------------
    @needs_vault
    def open_db(self, host_id, password=None):
        from .database import DbSession

        host, _ = self._host_for(host_id, password, ("postgres", "mysql", "mssql", "mongodb", "redis"))
        s = DbSession(self._vault, host, password)
        state = s.connect()
        self._dbs[s.id] = s
        self._touch(host)
        return {"ok": True, "sid": s.id, "title": s.title, **state}

    def _db(self, sid):
        s = self._dbs.get(sid)
        if s is None or s.db is None:
            raise ValueError("La pestaña ya no está conectada")
        return s

    @guarded
    def db_use(self, sid, name):
        return {"ok": True, **self._db(sid).use(name)}

    @guarded
    def db_tree(self, sid):
        return {"ok": True, **self._db(sid).tree()}

    @guarded
    def db_default_query(self, sid, group, obj):
        return {"ok": True, "query": self._db(sid).default_query(group, obj)}

    @guarded
    def db_run(self, sid, text, limit=500):
        return {"ok": True, **self._db(sid).run(text, limit)}

    @guarded
    def db_export(self, sid):
        import webview

        s = self._db(sid)
        name = f"{s.title}-{time.strftime('%Y%m%d-%H%M')}.csv"
        r = self._window.create_file_dialog(webview.FileDialog.SAVE, directory=os.path.expanduser("~"),
                                            save_filename=name)
        path = _first(r)
        if not path:
            return {"ok": False, "cancelled": True}
        n = s.export_csv(path)
        return {"ok": True, "rows": n, "path": path}

    # --- RDP ---------------------------------------------------------------------------------
    @needs_vault
    def open_rdp(self, host_id, password=None, accept_cert=None):
        """Escritorio remoto. En Windows va DENTRO de Nexo (control RDP incrustado): devuelve
        {"embedded": True, "sid"} y la página llama a rdp_place con el área de la pestaña.
        Sin el control (Linux o si falla) se abre aparte, como antes."""
        from . import rdp, rdp_embed

        host, _ = self._host_for(host_id, password, ("rdp",))
        if not rdp.available():
            return _fail("No hay cliente de escritorio remoto en este equipo")
        if host.get("auth") == "password" and not (host.get("password") or password):
            return _fail("need_password")
        if self._window is not None and rdp_embed.available():
            return self._open_rdp_embedded(host, password, accept_cert)

        def done(sess, err):
            self._rdps.pop(host_id, None)
            self._emit("rdp_closed", {"id": host_id, "name": host["name"], "error": err})

        s = rdp.RdpSession(self._vault, host, password, on_exit=done)
        self._rdps[host_id] = s
        s.start()
        self._touch(host)
        return {"ok": True, "embedded": False}

    def _open_rdp_embedded(self, host, password, accept_cert):
        from . import rdp, rdp_embed
        from .forward import local_forward

        real_host, real_port = host["host"], int(host.get("port") or 3389)
        target_host, target_port, tunnel = real_host, real_port, None
        if host.get("jump"):
            jump = self._vault.host(host["jump"])
            if not jump:
                return _fail("El host de salto ya no existe")
            tunnel, lport = local_forward(self._vault, jump, real_host, real_port)
            target_host, target_port = "127.0.0.1", lport
        try:
            ok, fp, old = rdp.trust_check(f"{real_host}:{real_port}", target_host, target_port, accept_cert)
        except Exception as e:  # noqa: BLE001
            if tunnel:
                tunnel.stop()
            return _fail(f"No se pudo llegar a {real_host}:{real_port} ({_reason(e) or e})")
        if not ok:
            if tunnel:
                tunnel.stop()
            return {"ok": False, "cert_changed": True, "fingerprint": fp, "previous": old,
                    "error": "El certificado del servidor cambió"}
        sid = "rdp-" + new_id()
        hid, name = host["id"], host["name"]

        def on_event(sess, state, msg):
            if state == "closed":
                self._rdps.pop(sid, None)
            self._emit("rdp_state", {"sid": sid, "id": hid, "name": name, "state": state, "error": msg})

        s = rdp_embed.EmbeddedRdp(self._window.native, host, target_host, target_port,
                                  password or host.get("password"), on_event, tunnel=tunnel)
        self._rdps[sid] = s
        self._touch(host)
        return {"ok": True, "embedded": True, "sid": sid, "title": name, "fingerprint": fp, "new_cert": old is None}

    @guarded
    def rdp_place(self, sid, x, y, w, h, visible=True):
        """La página informa dónde está el área de la pestaña (píxeles CSS). La primera vez
        crea el control y conecta."""
        s = self._rdps.get(sid)
        if s is None or not hasattr(s, "place"):
            return _fail("Esa sesión ya no existe")
        if not s.started:
            if not visible:
                return {"ok": True}
            try:
                s.attach(float(x), float(y), float(w), float(h), True)
            except Exception as e:  # noqa: BLE001
                self._rdps.pop(sid, None)
                s.close()
                return _fail(f"No se pudo iniciar el escritorio remoto: {e}")
            return {"ok": True}
        s.place(float(x), float(y), float(w), float(h), bool(visible))
        return {"ok": True}

    @guarded
    def rdp_focus(self, sid):
        s = self._rdps.get(sid)
        if s is not None and hasattr(s, "focus"):
            s.focus()
        return {"ok": True}

    @guarded
    def rdp_fullscreen(self, sid, on=True):
        s = self._rdps.get(sid)
        if s is None or not hasattr(s, "set_fullscreen"):
            return _fail("Esa sesión ya no existe")
        s.set_fullscreen(bool(on))
        return {"ok": True}

    @guarded
    def rdp_close(self, sid):
        s = self._rdps.pop(sid, None)
        if s is not None:
            (s.close if hasattr(s, "close") else s.stop)()
        return {"ok": True}

    # --- ventana -----------------------------------------------------------------------------
    @guarded
    def set_ui_pref(self, key, value):
        """Preferencias de la interfaz que no son secretas (ui.json, compartido con Linux)."""
        if key not in ("sidebar",):
            return _fail("Preferencia desconocida")
        self._ui[key] = bool(value)
        T.save_ui(self._ui)
        return {"ok": True}

    @guarded
    def window_fullscreen(self):
        if self._window is not None:
            self._window.toggle_fullscreen()
        return {"ok": True}

    # --- organizaciones (Nexo Server) ------------------------------------------------------------
    @needs_vault
    def org_login(self, url, username, password, totp):
        from nexo import orgclient

        if not (url and username and password and totp):
            return _fail("Completa servidor, usuario, contraseña y código 2FA")
        try:
            info = orgclient.login(url, username, password, totp)
            info["hosts"] = orgclient.hosts(info)
        except orgclient.OrgError as e:
            return _fail(str(e))
        existing = next((o for o in self._vault.orgs if o["url"] == info["url"]
                         and o["username"].lower() == info["username"].lower()), None)
        if existing:
            info["id"] = existing["id"]
        info["updated"] = time.time()
        info["expired"] = False
        self._vault.upsert_org(info)
        return {"ok": True, "name": info["name"], "hosts": len(info["hosts"])}

    @needs_vault
    def org_refresh(self):
        from nexo import orgclient

        msgs = []
        for o in self._vault.orgs:
            if not o.get("token"):
                continue
            try:
                o["hosts"], o["updated"], o["expired"] = orgclient.hosts(o), time.time(), False
            except orgclient.OrgExpired:
                o["expired"], o["hosts"] = True, []
                msgs.append(f"Tu sesión en {o['name']} expiró o fue revocada")
            except orgclient.OrgError as e:
                msgs.append(f"{o['name']}: {e}")
        self._vault.save()
        return {"ok": True, "messages": msgs}

    @needs_vault
    def org_logout(self, org_id, remove=False):
        from nexo import orgclient

        o = self._vault.org(org_id)
        if not o:
            return _fail("La organización no existe")
        threading.Thread(target=orgclient.logout, args=(dict(o),), daemon=True).start()
        if remove:
            self._vault.delete_org(org_id)
        else:
            o["token"], o["hosts"], o["expired"] = "", [], True
            self._vault.save()
        return {"ok": True}

    @needs_vault
    def org_info(self, org_id):
        o = self._vault.org(org_id)
        if not o:
            return _fail("La organización no existe")
        return {"ok": True, "url": o["url"], "username": o["username"], "name": o["name"]}

    # --- portapapeles (respaldo si el de la página no está permitido) ------------------------------
    def clipboard_set(self, text):
        from . import clipboard

        return {"ok": clipboard.set_text(text or "")}

    def clipboard_get(self):
        from . import clipboard

        text = clipboard.get_text()
        return {"ok": text is not None, "text": text or ""}

    @guarded
    def open_url(self, url):
        import webbrowser

        if not str(url).startswith(("https://", "http://")):
            return _fail("Dirección no válida")
        webbrowser.open(url)
        return {"ok": True}

    # --- archivos soltados desde el Explorador ------------------------------------------------------
    def _on_drop(self, event):
        files = (event.get("dataTransfer") or {}).get("files") or []
        paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        if paths:
            self._emit("files_dropped", {"paths": paths})

    # --- cierre ---------------------------------------------------------------------------------------
    def _close_everything(self):
        for store in (self._sessions, self._files, self._dbs):
            for s in list(store.values()):
                try:
                    s.close()
                except Exception:  # noqa: BLE001
                    pass
            store.clear()
        for t in list(self._tunnels.values()):
            t.stop()
        self._tunnels.clear()
        for r in list(self._rdps.values()):
            try:
                (r.close if hasattr(r, "close") else r.stop)()
            except Exception:  # noqa: BLE001
                pass
        self._rdps.clear()
        self._pending_key = None

    def _shutdown(self):
        self._close_everything()
        if self._vault.unlocked:
            self._vault.lock()


def _first(r):
    if not r:
        return None
    return r if isinstance(r, str) else r[0]


def _is_packaged():
    """¿Corre dentro de un paquete MSIX (Microsoft Store)?"""
    if not IS_WINDOWS:
        return False
    try:
        import ctypes

        n = ctypes.c_uint32(0)
        # APPMODEL_ERROR_NO_PACKAGE = 15700: proceso sin identidad de paquete
        return ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(n), None) != 15700
    except Exception:  # noqa: BLE001
        return False
