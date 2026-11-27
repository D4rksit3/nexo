"""Pestaña de base de datos para Nexo en Windows: usa nexo/dbclient.py (el mismo de Linux).

Si el host tiene «Saltar por», abre antes un túnel local con paramiko (forward.local_forward).
Todas las llamadas a la conexión pasan por un candado: los controladores no son seguros
entre hilos y pywebview atiende cada llamada de la página en un hilo distinto.
"""
import csv
import secrets
import threading

from nexo import dbclient as DB


class DbSession:
    kind = "db"

    def __init__(self, vault, host, password=None):
        self.id = secrets.token_urlsafe(12)
        self.vault = vault
        self.host = dict(host)
        if password:
            self.host["password"] = password
        self.title = host.get("name") or host.get("host")
        self.engine = host["protocol"]
        opts = host.get("db") or {}
        self.readonly = bool(opts.get("readonly"))
        self.db = None
        self.tunnel = None
        self.result = None
        self._lock = threading.Lock()

    def connect(self):
        h = self.host
        target_host, target_port = h["host"], int(h.get("port") or DB.default_port(self.engine))
        if h.get("jump"):
            from .forward import local_forward

            jump = self.vault.host(h["jump"])
            if not jump:
                raise DB.DBError("El host para el túnel ya no existe")
            self.tunnel, lport = local_forward(self.vault, jump, target_host, target_port)
            target_host, target_port = "127.0.0.1", lport
        opts = h.get("db") or {}
        with self._lock:
            self.db = DB.connect(self.engine, target_host, target_port, h.get("user", ""), h.get("password", ""),
                                 opts.get("database", ""), self.readonly, bool(opts.get("tls")),
                                 opts.get("auth_db") or None)
            try:
                dbs = self.db.databases()
            except DB.DBError:
                dbs = []
            tree = self.db.tree()
        return self._state(dbs, tree)

    def _state(self, dbs, tree):
        cur = self.db.database
        if cur and cur not in dbs:
            dbs = list(dbs) + [cur]
        return {"engine": self.engine, "engine_name": DB.ENGINES[self.engine][0], "database": cur,
                "databases": list(dbs), "tree": _tree(tree), "readonly": self.readonly}

    def use(self, name):
        with self._lock:
            self.db.use(name)
            tree = self.db.tree()
        return {"database": self.db.database, "tree": _tree(tree)}

    def tree(self):
        with self._lock:
            return {"database": self.db.database, "tree": _tree(self.db.tree())}

    def default_query(self, group, obj):
        return self.db.default_query(group, obj)

    def run(self, text, limit=500):
        with self._lock:
            res = self.db.run(text, int(limit))
        self.result = res
        return {"columns": [str(c) for c in res.columns], "rows": [[str(v) for v in r] for r in res.rows],
                "info": res.info, "database": self.db.database}

    def export_csv(self, path):
        if not self.result or not self.result.columns:
            raise DB.DBError("No hay resultados para exportar")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:  # con BOM: Excel lo abre bien
            w = csv.writer(f)
            w.writerow(self.result.columns)
            w.writerows(self.result.rows)
        return len(self.result.rows)

    def close(self):
        db, self.db = self.db, None
        if db is not None:
            threading.Thread(target=db.close, daemon=True).start()
        if self.tunnel is not None:
            self.tunnel.stop()


def _tree(tree):
    return [{"group": g, "items": [{"name": o, "kind": k} for o, k in objs]} for g, objs in tree]
