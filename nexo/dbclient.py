"""Clientes de bases de datos: PostgreSQL, MySQL/MariaDB, SQL Server, MongoDB y Redis.

Interfaz común (sin GTK):
    c = connect(engine, host, port, user, password, database, readonly, tls)
    c.databases()            -> [nombre]
    c.tree()                 -> [(grupo, [objeto, ...])]   p. ej. esquemas y tablas
    c.default_query(obj)     -> texto de consulta para abrir un objeto
    c.run(texto, limite)     -> Result(columns, rows, info)
    c.use(db) / c.close()
"""
import json
import re
import shlex
import time

ENGINES = {
    "postgres": ("PostgreSQL", 5432, "psycopg2", "python3-psycopg2"),
    "mysql": ("MySQL / MariaDB", 3306, "pymysql", "python3-pymysql"),
    "mssql": ("SQL Server", 1433, "pymssql", "python3-pymssql"),
    "mongodb": ("MongoDB", 27017, "pymongo", "python3-pymongo"),
    "redis": ("Redis", 6379, "redis", "python3-redis"),
}
SHORT = {"postgres": "PG", "mysql": "MySQL", "mssql": "MSSQL", "mongodb": "Mongo", "redis": "Redis"}


class DBError(Exception):
    pass


class Result:
    def __init__(self, columns=None, rows=None, info=""):
        self.columns = columns or []
        self.rows = rows or []
        self.info = info


def is_db(protocol):
    return protocol in ENGINES


def default_port(protocol):
    return ENGINES[protocol][1] if protocol in ENGINES else None


def _cell(v):
    if v is None:
        return "NULL"
    if isinstance(v, (bytes, bytearray, memoryview)):
        b = bytes(v)
        try:
            return b.decode()
        except UnicodeDecodeError:
            return "0x" + b[:64].hex() + ("…" if len(b) > 64 else "")
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    return str(v)


def clean_error(e):
    """Mensaje legible a partir de las excepciones de cada controlador."""
    args = getattr(e, "args", ())
    if len(args) == 1 and isinstance(args[0], tuple):  # pymssql: ((código, mensaje),)
        args = args[0]
    if len(args) >= 2 and isinstance(args[0], int):  # pymysql / pymssql: (código, mensaje)
        msg = args[1].decode(errors="replace") if isinstance(args[1], bytes) else str(args[1])
        return f"{msg.split('DB-Lib')[0].strip()} (código {args[0]})"
    msg = str(e).strip()
    if "FATAL:" in msg:  # psycopg2
        msg = msg.split("FATAL:")[-1].strip()
    msg = msg.split(", full error")[0]  # pymongo
    return msg.splitlines()[0][:300] if msg else type(e).__name__


def _require(engine):
    mod, pkg = ENGINES[engine][2], ENGINES[engine][3]
    try:
        return __import__(mod)
    except ImportError:
        raise DBError(f"Falta el controlador de {ENGINES[engine][0]}. Instálalo con: sudo apt install {pkg}")


def split_statements(text):
    """Separa sentencias SQL por ';' respetando comillas y comentarios simples."""
    out, cur, q = [], [], None
    i = 0
    while i < len(text):
        ch = text[i]
        if q:
            cur.append(ch)
            if ch == q:
                q = None
        elif ch in ("'", '"', "`"):
            q = ch
            cur.append(ch)
        elif ch == "-" and text[i:i + 2] == "--":
            j = text.find("\n", i)
            j = len(text) if j < 0 else j
            cur.append(text[i:j])
            i = j
            continue
        elif ch == ";":
            s = "".join(cur).strip()
            if s:
                out.append(s)
            cur = []
        else:
            cur.append(ch)
        i += 1
    s = "".join(cur).strip()
    if s and not all(line.strip().startswith("--") for line in s.splitlines() if line.strip()):
        out.append(s)
    return out


# --- SQL genérico (DB-API) ---------------------------------------------------
class _SQL:
    engine = ""

    def __init__(self, conn, database, readonly):
        self.conn = conn
        self.database = database
        self.readonly = readonly

    def _fetch(self, sql, args=None):
        cur = self.conn.cursor()
        try:
            cur.execute(sql, args or ())
            return cur.fetchall()
        finally:
            cur.close()

    def run(self, text, limit=500):
        stmts = split_statements(text)
        if not stmts:
            raise DBError("Escribe una consulta")
        last = Result()
        t0 = time.time()
        affected = 0
        for st in stmts:
            cur = self.conn.cursor()
            try:
                cur.execute(st)
                if cur.description:
                    cols = [d[0] for d in cur.description]
                    rows = cur.fetchmany(limit + 1)
                    more = len(rows) > limit
                    rows = [[_cell(v) for v in r] for r in rows[:limit]]
                    last = Result(cols, rows, f"{len(rows)} fila(s)" + (f" (se muestran las primeras {limit})" if more else ""))
                else:
                    affected += max(cur.rowcount, 0)
                    last = Result(info=f"OK · {affected} fila(s) afectada(s)")
            except Exception as e:  # noqa: BLE001
                self._rollback()
                raise DBError(clean_error(e))
            finally:
                cur.close()
        last.info += f" · {len(stmts)} sentencia(s) · {(time.time() - t0) * 1000:.0f} ms"
        return last

    def _rollback(self):
        try:
            self.conn.rollback()
        except Exception:  # noqa: BLE001
            pass

    def close(self):
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001
            pass


class Postgres(_SQL):
    engine = "postgres"

    @classmethod
    def open(cls, host, port, user, password, database, readonly, tls):
        pg = _require("postgres")
        try:
            conn = pg.connect(host=host, port=port, user=user or None, password=password or None,
                              dbname=database or "postgres", connect_timeout=10,
                              sslmode="require" if tls else "prefer", application_name="Nexo")
        except Exception as e:  # noqa: BLE001
            raise DBError(clean_error(e))
        conn.autocommit = True
        if readonly:
            cur = conn.cursor()
            cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
            cur.close()
        c = cls(conn, database or "postgres", readonly)
        c._args = (host, port, user, password, tls)
        return c

    def databases(self):
        return [r[0] for r in self._fetch("SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY 1")]

    def use(self, db):
        host, port, user, password, tls = self._args
        new = Postgres.open(host, port, user, password, db, self.readonly, tls)
        self.close()
        self.conn, self.database = new.conn, db

    def tree(self):
        rows = self._fetch("""
            SELECT table_schema, table_name, table_type FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema') ORDER BY 1, 2""")
        out = {}
        for schema, name, ttype in rows:
            out.setdefault(schema, []).append((name, "vista" if "VIEW" in ttype else "tabla"))
        return sorted(out.items(), key=lambda kv: (kv[0] != "public", kv[0]))

    def default_query(self, group, obj):
        return f'SELECT * FROM "{group}"."{obj}" LIMIT 100;'


class MySQL(_SQL):
    engine = "mysql"

    @classmethod
    def open(cls, host, port, user, password, database, readonly, tls):
        pm = _require("mysql")
        try:
            conn = pm.connect(host=host, port=port, user=user or "root", password=password or "",
                              database=database or None, connect_timeout=10, autocommit=True, charset="utf8mb4",
                              ssl={"ssl": {}} if tls else None)
        except Exception as e:  # noqa: BLE001
            raise DBError(clean_error(e))
        if readonly:
            cur = conn.cursor()
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            cur.close()
        return cls(conn, database or "", readonly)

    def databases(self):
        return [r[0] for r in self._fetch("SHOW DATABASES")]

    def use(self, db):
        self.conn.select_db(db)
        self.database = db

    def tree(self):
        if not self.database:
            return [("bases de datos", [(d, "base") for d in self.databases()])]
        rows = self._fetch("SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = %s ORDER BY 1",
                           (self.database,))
        return [(self.database, [(n, "vista" if "VIEW" in t else "tabla") for n, t in rows])]

    def default_query(self, group, obj):
        if group == "bases de datos":
            return f"USE `{obj}`;"
        return f"SELECT * FROM `{group}`.`{obj}` LIMIT 100;"


class MSSQL(_SQL):
    engine = "mssql"

    @classmethod
    def open(cls, host, port, user, password, database, readonly, tls):
        ms = _require("mssql")
        try:
            conn = ms.connect(server=host, port=str(port), user=user or "sa", password=password or "",
                              database=database or "master", login_timeout=10, timeout=60, autocommit=True,
                              appname="Nexo", charset="UTF-8")
        except Exception as e:  # noqa: BLE001
            raise DBError(clean_error(e))
        return cls(conn, database or "master", readonly)

    def run(self, text, limit=500):
        if self.readonly:
            for st in split_statements(text):
                first = st.lstrip().split(None, 1)[0].lower() if st.strip() else ""
                if first not in ("select", "with", "exec", "sp_help", "sp_columns", "use", "set", "declare"):
                    raise DBError("Conexión en modo solo lectura: solo se permiten consultas SELECT")
                if first == "exec" and not re.match(r"(?is)\s*exec\s+sp_(help|columns|tables|who)", st):
                    raise DBError("Conexión en modo solo lectura: ese procedimiento no está permitido")
        return super().run(text, limit)

    def databases(self):
        return [r[0] for r in self._fetch("SELECT name FROM sys.databases ORDER BY name")]

    def use(self, db):
        cur = self.conn.cursor()
        cur.execute(f"USE [{db.replace(']', ']]')}]")
        cur.close()
        self.database = db

    def tree(self):
        rows = self._fetch("SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES ORDER BY 1, 2")
        out = {}
        for schema, name, ttype in rows:
            out.setdefault(schema, []).append((name, "vista" if "VIEW" in ttype else "tabla"))
        return sorted(out.items(), key=lambda kv: (kv[0] != "dbo", kv[0]))

    def default_query(self, group, obj):
        return f"SELECT TOP 100 * FROM [{group}].[{obj}];"


# --- MongoDB -------------------------------------------------------------------
class Mongo:
    engine = "mongodb"
    HELP = ("Escribe un filtro JSON para la colección elegida, por ejemplo {\"estado\": \"activo\"},\n"
            "o una de estas formas:  coleccion.find({...})  ·  coleccion.count({...})  ·  coleccion.aggregate([...])")

    def __init__(self, client, database, readonly):
        self.client = client
        self.database = database
        self.readonly = readonly
        self.current = None  # colección elegida en el árbol

    @classmethod
    def open(cls, host, port, user, password, database, readonly, tls, auth_db=None):
        pm = _require("mongodb")
        kw = dict(host=host, port=port, serverSelectionTimeoutMS=8000, connectTimeoutMS=8000, appname="Nexo",
                  directConnection=True, tls=bool(tls))
        if user:
            kw.update(username=user, password=password, authSource=auth_db or "admin")
        try:
            client = pm.MongoClient(**kw)
            client.admin.command("ping")
        except Exception as e:  # noqa: BLE001
            raise DBError(clean_error(e))
        return cls(client, database or "test", readonly)

    def databases(self):
        try:
            return sorted(self.client.list_database_names())
        except Exception as e:  # noqa: BLE001
            raise DBError(str(e)[:300])

    def use(self, db):
        self.database = db
        self.current = None

    def tree(self):
        db = self.client[self.database]
        try:
            names = sorted(db.list_collection_names())
        except Exception as e:  # noqa: BLE001
            raise DBError(str(e)[:300])
        return [(self.database, [(n, "colección") for n in names])]

    def default_query(self, group, obj):
        self.current = obj
        return f"{obj}.find({{}})"

    def run(self, text, limit=500):
        from bson import json_util
        text = text.strip().rstrip(";")
        if not text:
            raise DBError("Escribe un filtro JSON o una consulta como coleccion.find({...})")
        m = re.match(r"^(?:db\.)?([\w.$-]+)\.(find|count|countDocuments|aggregate|distinct)\((.*)\)$", text, re.S)
        if m:
            coll, op, arg = m.group(1), m.group(2), m.group(3).strip()
        else:
            if not self.current:
                raise DBError("Elige una colección en el árbol o escribe coleccion.find({...})\n" + self.HELP)
            coll, op, arg = self.current, "find", text
        self.current = coll
        try:
            if op == "distinct":
                parts = arg.split(",", 1)
                field = json.loads(parts[0])
                flt = json_util.loads(parts[1]) if len(parts) > 1 and parts[1].strip() else {}
            else:
                parsed = json_util.loads(arg) if arg else ({} if op != "aggregate" else [])
        except Exception as e:  # noqa: BLE001
            raise DBError(f"JSON inválido: {e}. Las claves y textos van entre comillas dobles.")
        col = self.client[self.database][coll]
        t0 = time.time()
        try:
            if op in ("count", "countDocuments"):
                n = col.count_documents(parsed or {})
                return Result(["total"], [[str(n)]], f"{coll}: {n} documento(s) · {(time.time() - t0) * 1000:.0f} ms")
            if op == "distinct":
                vals = col.distinct(field, flt)
                return Result([field], [[_cell(v)] for v in vals[:limit]], f"{len(vals)} valor(es)")
            if op == "aggregate":
                if not isinstance(parsed, list):
                    raise DBError("aggregate espera una lista de etapas: [ {...}, {...} ]")
                if self.readonly and any(("$out" in st or "$merge" in st) for st in parsed if isinstance(st, dict)):
                    raise DBError("Conexión en modo solo lectura: $out y $merge no están permitidos")
                docs = list(col.aggregate(parsed + [{"$limit": limit + 1}]))
            else:
                docs = list(col.find(parsed if isinstance(parsed, dict) else {}).limit(limit + 1))
        except DBError:
            raise
        except Exception as e:  # noqa: BLE001
            raise DBError(str(e)[:300])
        more = len(docs) > limit
        docs = docs[:limit]
        cols = []
        for d in docs:
            for k in d:
                if k not in cols:
                    cols.append(k)
        rows = [[(json_util.dumps(d[k], ensure_ascii=False) if isinstance(d.get(k), (dict, list)) else
                  _cell(d[k]) if k in d else "") for k in cols] for d in docs]
        return Result(cols, rows, f"{coll}: {len(docs)} documento(s)" + (" (hay más)" if more else "")
                      + f" · {(time.time() - t0) * 1000:.0f} ms")

    def close(self):
        self.client.close()


# --- Redis ---------------------------------------------------------------------------
READ_CMDS = {
    "get", "mget", "strlen", "getrange", "exists", "type", "ttl", "pttl", "keys", "scan", "dbsize", "info",
    "hget", "hgetall", "hkeys", "hvals", "hlen", "hmget", "hexists", "hscan", "lrange", "llen", "lindex",
    "smembers", "scard", "sismember", "srandmember", "sscan", "zrange", "zrangebyscore", "zrevrange", "zcard",
    "zscore", "zrank", "zscan", "xrange", "xrevrange", "xlen", "xinfo", "ping", "time", "memory", "object",
    "client", "config", "slowlog", "select", "echo", "lastsave", "role",
}


class Redis:
    engine = "redis"

    def __init__(self, r, database, readonly, args):
        self.r = r
        self.database = database
        self.readonly = readonly
        self._args = args

    @classmethod
    def open(cls, host, port, user, password, database, readonly, tls):
        rd = _require("redis")
        db = int(database) if str(database or "").isdigit() else 0
        try:
            r = rd.Redis(host=host, port=port, username=user or None, password=password or None, db=db,
                         socket_connect_timeout=8, socket_timeout=30, ssl=bool(tls), decode_responses=False)
            r.ping()
        except Exception as e:  # noqa: BLE001
            raise DBError(str(e))
        return cls(r, str(db), readonly, (host, port, user, password, tls))

    def databases(self):
        try:
            cfg = self.r.config_get("databases")
            n = int(cfg.get("databases") or cfg.get(b"databases") or 16)
        except Exception:  # noqa: BLE001
            n = 16
        return [str(i) for i in range(n)]

    def use(self, db):
        host, port, user, password, tls = self._args
        new = Redis.open(host, port, user, password, db, self.readonly, tls)
        self.close()
        self.r, self.database = new.r, str(db)

    def tree(self, pattern="*", limit=500):
        keys = []
        for k in self.r.scan_iter(match=pattern, count=200):
            keys.append(_cell(k))
            if len(keys) >= limit:
                break
        groups = {}
        for k in sorted(keys):
            prefix = k.split(":", 1)[0] if ":" in k else "(sin prefijo)"
            groups.setdefault(prefix, []).append((k, "clave"))
        return sorted(groups.items())

    def default_query(self, group, obj):
        t = _cell(self.r.type(obj))
        cmd = {"string": "GET", "hash": "HGETALL", "list": "LRANGE", "set": "SMEMBERS", "zset": "ZRANGE",
               "stream": "XRANGE"}.get(t, "TYPE")
        q = f"{cmd} {shlex.quote(obj)}"
        if cmd in ("LRANGE", "ZRANGE"):
            q += " 0 199" + (" WITHSCORES" if cmd == "ZRANGE" else "")
        if cmd == "XRANGE":
            q += " - + COUNT 100"
        return q

    def run(self, text, limit=500):
        lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
        if not lines:
            raise DBError("Escribe un comando, por ejemplo: GET clave · HGETALL clave · KEYS usuario:*")
        res = Result()
        t0 = time.time()
        for line in lines:
            try:
                parts = shlex.split(line)
            except ValueError as e:
                raise DBError(f"Comando mal formado: {e}")
            cmd = parts[0].lower()
            if self.readonly and cmd not in READ_CMDS:
                raise DBError(f"Conexión en modo solo lectura: {parts[0].upper()} no está permitido")
            if cmd == "select":
                self.use(parts[1] if len(parts) > 1 else "0")
                res = Result(info=f"OK · base {self.database}")
                continue
            try:
                out = self.r.execute_command(*parts)
            except Exception as e:  # noqa: BLE001
                raise DBError(str(e))
            res = self._render(out, cmd, limit)
        res.info += f" · {(time.time() - t0) * 1000:.0f} ms"
        return res

    @staticmethod
    def _render(out, cmd, limit):
        if isinstance(out, dict):
            items = list(out.items())[:limit]
            return Result(["campo", "valor"], [[_cell(k), _cell(v)] for k, v in items], f"{len(out)} campo(s)")
        if isinstance(out, (list, tuple)):
            if cmd == "hgetall" and len(out) % 2 == 0:
                pairs = list(zip(out[0::2], out[1::2]))[:limit]
                return Result(["campo", "valor"], [[_cell(k), _cell(v)] for k, v in pairs], f"{len(out) // 2} campo(s)")
            if cmd == "scan" and len(out) == 2 and isinstance(out[1], (list, tuple)):
                return Result(["clave"], [[_cell(k)] for k in out[1][:limit]], f"cursor siguiente: {_cell(out[0])}")
            return Result(["#", "valor"], [[str(i + 1), _cell(v)] for i, v in enumerate(out[:limit])],
                          f"{len(out)} elemento(s)")
        if isinstance(out, bytes) and b"\r\n" in out and cmd == "info":
            rows = [l.split(":", 1) for l in out.decode(errors="replace").splitlines() if ":" in l]
            return Result(["clave", "valor"], rows, f"{len(rows)} línea(s)")
        return Result(["resultado"], [[_cell(out)]], "OK")

    def close(self):
        try:
            self.r.close()
        except Exception:  # noqa: BLE001
            pass


CLASSES = {"postgres": Postgres, "mysql": MySQL, "mssql": MSSQL, "mongodb": Mongo, "redis": Redis}


def connect(engine, host, port, user, password, database, readonly=False, tls=False, auth_db=None):
    if engine not in CLASSES:
        raise DBError(f"Motor no soportado: {engine}")
    if engine == "mongodb":
        return Mongo.open(host, int(port), user, password, database, readonly, tls, auth_db)
    return CLASSES[engine].open(host, int(port), user, password, database, readonly, tls)
