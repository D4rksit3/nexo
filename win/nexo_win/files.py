"""SFTP de dos paneles para Nexo en Windows: «Este equipo» y el servidor.

- Cada pestaña SFTP abre una conexión SSH con dos canales SFTP: `ui` (listar, renombrar,
  borrar…) y `xfer` (transferencias), porque un SFTPClient no se comparte entre hilos.
- Las transferencias corren en segundo plano; la página consulta el avance con `progress()`.
  Escriben a «<nombre>.nexo-parcial» y renombran al final: nunca queda un archivo a medias
  con el nombre definitivo.
- Editar: baja el archivo a una carpeta temporal, lo abre con el programa de Windows y, cada
  vez que se guarda, lo sube (avisa si en el servidor cambió mientras tanto).
"""
import os
import posixpath
import secrets
import shutil
import stat
import string
import subprocess
import tempfile
import threading
import time

from . import IS_WINDOWS

PART = ".nexo-parcial"


class Cancelled(Exception):
    pass


def _err(e, where=""):
    if isinstance(e, Cancelled):
        return "Transferencia cancelada"
    if isinstance(e, PermissionError) or getattr(e, "errno", None) == 13:
        return f"Permiso denegado{(' ' + where) if where else ''}"
    if isinstance(e, FileNotFoundError) or getattr(e, "errno", None) == 2:
        return f"No existe{(' ' + where) if where else ''}"
    msg = (e.strerror if isinstance(e, OSError) and e.strerror else str(e)) or type(e).__name__
    return f"{msg}{(' · ' + where) if where else ''}"


def _entry(name, is_dir, size, mtime, link=False):
    return {"name": name, "dir": bool(is_dir), "size": int(size or 0), "mtime": int(mtime or 0), "link": link}


# --- este equipo ------------------------------------------------------------------

def home_dir():
    return os.path.expanduser("~")


def drives():
    if not IS_WINDOWS:
        return []
    return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]


def local_list(path):
    """Lista una carpeta local. En Windows, la ruta vacía es la lista de unidades."""
    if IS_WINDOWS and not path:
        return {"path": "", "entries": [_entry(d, True, 0, 0) for d in drives()]}
    path = os.path.abspath(path or home_dir())
    out = []
    with os.scandir(path) as it:
        for e in it:
            if e.name.endswith(PART):
                continue
            try:
                st = e.stat()
                is_dir = e.is_dir()
            except OSError:
                continue
            if IS_WINDOWS and _hidden_system(st):
                continue
            out.append(_entry(e.name, is_dir, 0 if is_dir else st.st_size, st.st_mtime, e.is_symlink()))
    return {"path": path, "entries": out}


def _hidden_system(st):
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & 0x2 and attrs & 0x4)  # oculto + sistema (desktop.ini, $Recycle.Bin…)


def local_parent(path):
    if not path:
        return ""
    parent = os.path.dirname(os.path.abspath(path).rstrip("\\/")) or path
    if IS_WINDOWS and os.path.abspath(path).rstrip("\\") == os.path.splitdrive(os.path.abspath(path))[0]:
        return ""  # de «C:\» se sube a la lista de unidades
    return parent if parent != path else ("" if IS_WINDOWS else "/")


def local_mkdir(path):
    os.mkdir(path)


def local_rename(path, new_name):
    if not new_name or "/" in new_name or "\\" in new_name:
        raise ValueError("Nombre no válido")
    os.rename(path, os.path.join(os.path.dirname(path), new_name))


def local_trash(paths):
    """A la papelera (Windows: SHFileOperation con deshacer; Linux: gio trash)."""
    if IS_WINDOWS:
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                        ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                        ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

        FO_DELETE, FOF_ALLOWUNDO, FOF_NOCONFIRMATION, FOF_SILENT, FOF_NOERRORUI = 3, 0x40, 0x10, 0x4, 0x400
        op = SHFILEOPSTRUCTW(None, FO_DELETE, "\0".join(paths) + "\0\0", None,
                             FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI, False, None, None)
        r = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if r != 0:
            raise OSError(f"Windows no pudo mover a la papelera (código {r})")
        return
    if shutil.which("gio"):
        r = subprocess.run(["gio", "trash", "--", *paths], capture_output=True, timeout=30)
        if r.returncode == 0:
            return
    for p in paths:
        shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.remove(p)


def open_default(path):
    """Abre con el programa predeterminado del sistema."""
    if IS_WINDOWS:
        os.startfile(path)  # noqa: S606 — archivo elegido por el usuario
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def reveal(path):
    """Muestra el archivo en el Explorador."""
    if IS_WINDOWS:
        subprocess.Popen(["explorer.exe", "/select,", path])
    else:
        open_default(os.path.dirname(path))


# --- sesión SFTP --------------------------------------------------------------------

class FileSession:
    kind = "sftp"

    def __init__(self, vault, host, password=None, emit=None):
        self.id = secrets.token_urlsafe(12)
        self.vault = vault
        self.host = dict(host)
        if password:
            self.host["password"] = password
        self.title = host.get("name") or host.get("host")
        self.emit = emit or (lambda *a: None)
        self.client = None
        self.ui = None
        self.xfer = None
        self.home = "/"
        self._ui_lock = threading.Lock()
        self._xfer_lock = threading.Lock()
        self.cancel = threading.Event()
        self.job = None          # transferencia en curso: dict de avance
        self.edits = {}          # ruta local -> registro de edición
        self.closed = False

    # --- conexión -------------------------------------------------------------
    def connect(self):
        from nexo import conn

        self.client = conn.paramiko_client(self.vault, self.host)
        self.client.get_transport().set_keepalive(30)
        self.ui = self.client.open_sftp()
        self.xfer = self.client.open_sftp()
        try:
            self.home = self.ui.normalize(".")
        except OSError:
            self.home = "/"
        return self.home

    def alive(self):
        t = self.client.get_transport() if self.client else None
        return bool(t and t.is_active())

    def close(self):
        self.closed = True
        self.cancel.set()
        for c in (self.ui, self.xfer, self.client, getattr(self.client, "_nexo_jump", None)):
            try:
                if c is not None:
                    c.close()
            except Exception:  # noqa: BLE001
                pass
        for rec in list(self.edits.values()):
            shutil.rmtree(rec["dir"], ignore_errors=True)
        self.edits.clear()

    # --- servidor: navegar y operar ---------------------------------------------
    def list(self, path):
        with self._ui_lock:
            path = self.ui.normalize(path or self.home)
            out = []
            for a in self.ui.listdir_attr(path):
                if a.filename.endswith(PART):
                    continue
                mode = a.st_mode or 0
                is_dir = stat.S_ISDIR(mode)
                link = stat.S_ISLNK(mode)
                if link:
                    try:
                        is_dir = stat.S_ISDIR(self.ui.stat(posixpath.join(path, a.filename)).st_mode or 0)
                    except OSError:
                        pass
                out.append(_entry(a.filename, is_dir, 0 if is_dir else a.st_size, a.st_mtime, link))
            return {"path": path, "entries": out}

    def mkdir(self, path):
        with self._ui_lock:
            self.ui.mkdir(path)

    def rename(self, path, new_name):
        if not new_name or "/" in new_name:
            raise ValueError("Nombre no válido")
        with self._ui_lock:
            self.ui.rename(path, posixpath.join(posixpath.dirname(path), new_name))

    def delete(self, paths):
        with self._ui_lock:
            for p in paths:
                self._rm_tree(p)

    def _rm_tree(self, p):
        st = self.ui.lstat(p)
        if stat.S_ISDIR(st.st_mode or 0):
            for a in self.ui.listdir_attr(p):
                self._rm_tree(posixpath.join(p, a.filename))
            self.ui.rmdir(p)
        else:
            self.ui.remove(p)

    def exists_remote(self, folder, names):
        names = {os.path.basename(n.rstrip("\\/")) if os.path.isabs(n) else n for n in names}
        with self._ui_lock:
            there = set(self.ui.listdir(folder))
        return sorted(names & there)

    # --- transferencias ------------------------------------------------------------
    def start_transfer(self, direction, items, src, dest, skip=()):
        """direction: "up" (este equipo → servidor) o "down". items: nombres dentro de src."""
        if self.job and self.job.get("running"):
            raise RuntimeError("Ya hay una transferencia en curso")
        self.cancel.clear()
        skip = set(skip)
        todo = [n for n in items if (os.path.basename(n.rstrip("\\/")) if os.path.isabs(n) else n) not in skip]
        self.job = {"running": True, "direction": direction, "file": "", "done": 0, "total": 0,
                    "files": 0, "error": None, "dest": dest, "n": len(todo), "i": 0}
        threading.Thread(target=self._transfer, args=(direction, todo, src, dest), daemon=True).start()
        return self.job

    def progress(self):
        return dict(self.job) if self.job else {"running": False}

    def _cb(self, name):
        job = self.job

        def cb(done, total):
            if self.cancel.is_set():
                raise Cancelled()
            job["file"], job["done"], job["total"] = name, done, total
        return cb

    def _transfer(self, direction, items, src, dest):
        job = self.job
        try:
            with self._xfer_lock:
                for i, name in enumerate(items, 1):
                    job["i"] = i
                    if direction == "up":
                        # nombres relativos a src, o rutas completas (soltadas desde el Explorador)
                        local = name if os.path.isabs(name) else os.path.join(src, name)
                        self._put_tree(local, posixpath.join(dest, os.path.basename(local.rstrip("\\/"))))
                    else:
                        self._get_tree(posixpath.join(src, name), os.path.join(dest, name))
        except Exception as e:  # noqa: BLE001
            job["error"] = _err(e)
            job["cancelled"] = isinstance(e, Cancelled)
        job["running"] = False
        self.emit("sftp_done", {"sid": self.id, "job": dict(job)})

    def _put_tree(self, local, remote):
        if self.cancel.is_set():
            raise Cancelled()
        if os.path.isdir(local):
            try:
                self.xfer.mkdir(remote)
            except OSError:
                pass
            for name in sorted(os.listdir(local)):
                self._put_tree(os.path.join(local, name), posixpath.join(remote, name))
            return
        part = remote + PART
        try:
            with open(local, "rb") as f:
                self.xfer.putfo(f, part, file_size=os.path.getsize(local), callback=self._cb(os.path.basename(local)))
            self._replace_remote(part, remote)
        except BaseException:
            try:
                self.xfer.remove(part)
            except OSError:
                pass
            raise
        self.job["files"] += 1

    def _replace_remote(self, src, dst):
        try:
            self.xfer.posix_rename(src, dst)
        except OSError:
            try:
                self.xfer.remove(dst)
            except OSError:
                pass
            self.xfer.rename(src, dst)

    def _get_tree(self, remote, local):
        if self.cancel.is_set():
            raise Cancelled()
        st = self.xfer.stat(remote)
        if stat.S_ISDIR(st.st_mode or 0):
            os.makedirs(local, exist_ok=True)
            for a in self.xfer.listdir_attr(remote):
                self._get_tree(posixpath.join(remote, a.filename), os.path.join(local, a.filename))
            return
        part = local + PART
        try:
            with open(part, "wb") as f:
                self.xfer.getfo(remote, f, callback=self._cb(posixpath.basename(remote)))
            os.replace(part, local)
        finally:
            if os.path.exists(part):
                try:
                    os.remove(part)
                except OSError:
                    pass
        self.job["files"] += 1

    def cancel_transfer(self):
        self.cancel.set()

    # --- editar en el equipo --------------------------------------------------------
    def edit(self, remote):
        with self._ui_lock:
            st = self.ui.stat(remote)
        if stat.S_ISDIR(st.st_mode or 0):
            raise ValueError("Es una carpeta")
        if (st.st_size or 0) > 50 * 1024 * 1024:
            raise ValueError("Archivo demasiado grande para editar (más de 50 MB)")
        d = tempfile.mkdtemp(prefix="nexo-editar-")
        local = os.path.join(d, posixpath.basename(remote))
        with self._xfer_lock:
            self.xfer.get(remote, local)
        rec = {"remote": remote, "local": local, "dir": d, "mtime": os.path.getmtime(local),
               "remote_mtime": st.st_mtime, "uploads": 0}
        self.edits[local] = rec
        open_default(local)
        if len(self.edits) == 1:
            threading.Thread(target=self._watch_edits, daemon=True).start()
        return rec

    def _watch_edits(self):
        while not self.closed and self.edits:
            time.sleep(1)
            for rec in list(self.edits.values()):
                try:
                    m = os.path.getmtime(rec["local"])
                except OSError:
                    continue
                if m == rec["mtime"]:
                    continue
                time.sleep(0.4)  # dejar que el editor termine de escribir
                rec["mtime"] = os.path.getmtime(rec["local"])
                self._upload_edit(rec, force=False)

    def _upload_edit(self, rec, force):
        name = posixpath.basename(rec["remote"])
        try:
            with self._xfer_lock:
                cur = self.xfer.stat(rec["remote"]).st_mtime
                if not force and rec["remote_mtime"] and cur != rec["remote_mtime"]:
                    self.emit("edit_conflict", {"sid": self.id, "local": rec["local"], "name": name})
                    return
                part = rec["remote"] + PART
                self.xfer.put(rec["local"], part)
                self._replace_remote(part, rec["remote"])
                rec["remote_mtime"] = self.xfer.stat(rec["remote"]).st_mtime
            rec["uploads"] += 1
            self.emit("edit_saved", {"sid": self.id, "name": name, "remote": rec["remote"]})
        except Exception as e:  # noqa: BLE001
            self.emit("edit_error", {"sid": self.id, "name": name, "error": _err(e)})

    def force_upload(self, local):
        rec = self.edits.get(local)
        if rec:
            self._upload_edit(rec, force=True)
