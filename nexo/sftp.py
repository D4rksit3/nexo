"""Pestaña SFTP: navegador de archivos remoto con paramiko en un hilo aparte."""
import hashlib
import json
import os
import tempfile
import posixpath
import queue
import stat
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from . import conn  # noqa: E402
from .filepane import (COL_BYTES, COL_ISDIR, COL_NAME, COL_PERM, INFO_REMOTE, INFO_URIS,  # noqa: E402
                       TARGET_REMOTE, TARGET_URIS, LocalPane, build_view, folder_under, head_label, human,
                       new_store, row_values, selected_rows, uris_to_paths)


class Cancelled(Exception):
    pass


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class SftpTab(Gtk.Box):
    def __init__(self, app, host):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.host = host
        self.title = host["name"]
        self.client = None
        self.sftp = None
        self.cwd = None
        self.jobs = queue.Queue()
        self.closed = False
        self.alive = False
        self.editing = {}  # ruta remota -> registro de edición

        self.cancel = threading.Event()
        self.busy = 0

        from . import icons as I

        # --- panel derecho: el servidor
        remote = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        head, _ = head_label(I.image(I.host_icon(host), 14), host["name"], conn.label(host))
        remote.pack_start(head, False, False, 0)
        bar = Gtk.Box(spacing=4)
        bar.get_style_context().add_class("enlace-toolbar")
        bar.set_border_width(6)

        def btn(icon, tip, cb, end=False):
            b = Gtk.Button()
            b.add(I.ui_image(icon, 15))
            b.set_tooltip_text(tip)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.connect("clicked", lambda *_: cb())
            (bar.pack_end if end else bar.pack_start)(b, False, False, 0)
            return b

        down = Gtk.Button()
        db = Gtk.Box(spacing=6)
        db.pack_start(I.ui_image("chevron-left", 12), False, False, 0)
        db.pack_start(Gtk.Label(label="Bajar"), False, False, 0)
        down.add(db)
        down.get_style_context().add_class("suggested-action")
        down.set_tooltip_text("Bajar la selección a la carpeta abierta de este equipo (Ctrl+Flecha izquierda)")
        down.connect("clicked", lambda *_: self.download_selected())
        bar.pack_start(down, False, False, 2)
        btn("up", "Subir un nivel (Retroceso)", self.go_up)
        btn("home", "Carpeta personal", lambda: self.navigate("."))
        btn("refresh", "Actualizar (F5)", self.refresh)
        self.path_entry = Gtk.Entry()
        self.path_entry.set_placeholder_text("/ruta/remota")
        self.path_entry.connect("activate", lambda e: self.navigate(e.get_text().strip() or "/"))
        bar.pack_start(self.path_entry, True, True, 4)
        btn("terminal", "Abrir terminal SSH aquí", self.open_terminal_here, end=True)
        btn("trash", "Eliminar (Supr)", self.delete_dialog, end=True)
        btn("edit", "Renombrar (F2)", self.rename_dialog, end=True)
        btn("new-folder", "Nueva carpeta", self.mkdir_dialog, end=True)
        remote.pack_start(bar, False, False, 0)

        self.store = new_store()
        self.view = build_view(self.store)
        self.view.connect("row-activated", self._on_activate)
        self.view.connect("key-press-event", self._on_key)
        self.view.connect("button-press-event", self._on_button)
        # arrastrar desde aquí hacia «Este equipo» = bajar
        self.view.enable_model_drag_source(
            Gdk.ModifierType.BUTTON1_MASK,
            [Gtk.TargetEntry.new(TARGET_REMOTE, Gtk.TargetFlags.SAME_APP, INFO_REMOTE)], Gdk.DragAction.COPY)
        self.view.connect("drag-data-get", self._drag_get)
        # soltar aquí archivos de «Este equipo» o del gestor de archivos = subir
        self.view.enable_model_drag_dest([Gtk.TargetEntry.new(TARGET_URIS, 0, INFO_URIS)], Gdk.DragAction.COPY)
        self.view.connect("drag-data-received", self._on_drop)
        sw = Gtk.ScrolledWindow()
        sw.add(self.view)
        remote.pack_start(sw, True, True, 0)

        # --- panel izquierdo: este equipo
        self.local = LocalPane(app, conn.REAL_HOME, on_send=self._send_from_local,
                               on_receive=self._receive_to_local)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.get_style_context().add_class("nx-files-split")
        paned.pack1(self.local, True, False)
        paned.pack2(remote, True, False)
        paned.connect("size-allocate", self._half_once)
        self._split_done = False
        self.pack_start(paned, True, True, 0)

        # --- estado y transferencias
        st = Gtk.Box(spacing=8)
        st.get_style_context().add_class("enlace-statusbar")
        st.set_border_width(6)
        self.status = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.status.get_style_context().add_class("dim-label")
        self.progress = Gtk.ProgressBar()
        self.progress.set_size_request(220, -1)
        self.progress.set_valign(Gtk.Align.CENTER)
        self.progress.set_no_show_all(True)
        self.b_cancel = Gtk.Button(label="Cancelar")
        self.b_cancel.set_tooltip_text("Detener la transferencia en curso")
        self.b_cancel.set_no_show_all(True)
        self.b_cancel.connect("clicked", lambda *_: self.cancel.set())
        st.pack_start(self.status, True, True, 0)
        st.pack_end(self.b_cancel, False, False, 0)
        st.pack_end(self.progress, False, False, 0)
        self.pack_start(st, False, False, 0)

        self.show_all()
        self.set_status(f"Conectando a {conn.label(host)}…")
        threading.Thread(target=self._worker, daemon=True).start()
        self.submit(self._connect, self._connected)

    def _half_once(self, paned, alloc):
        if not self._split_done and alloc.width > 100:
            self._split_done = True
            paned.set_position(alloc.width // 2)

    # --- hilo de trabajo -------------------------------------------------
    def _worker(self):
        while not self.closed:
            try:
                fn, done = self.jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                res, err = fn(), None
            except Exception as e:  # noqa: BLE001
                res, err = None, e
            GLib.idle_add(self._finish, done, res, err)

    def _finish(self, done, res, err):
        if self.closed:
            return False
        if err is not None:
            self._transfer_end()
            if isinstance(err, Cancelled):
                self._note = "✖ Transferencia cancelada"
                self.set_status(self._note)
                self.app.toast("Transferencia cancelada")
                self.refresh()
                self.local.refresh()
                return False
            msg = str(err) or type(err).__name__
            self.set_status(f"✖ {msg}")
            self.app.toast(f"SFTP {self.host['name']}: {msg}", error=True)
        elif done:
            done(res)
        return False

    def submit(self, fn, done=None):
        self.jobs.put((fn, done))

    def _connect(self):
        self.client = conn.paramiko_client(self.app.vault, self.host)
        self.sftp = self.client.open_sftp()
        return self.sftp.normalize(".")

    def _connected(self, home):
        self.alive = True
        self.home = home
        self.app.tab_state_changed(self)
        self.navigate(home)
        self.view.grab_focus()

    # --- navegación ------------------------------------------------------
    def set_status(self, text):
        self.status.set_text(text)

    def _list(self, path):
        path = self.sftp.normalize(path)
        entries = self.sftp.listdir_attr(path)
        return path, entries

    def navigate(self, path):
        if not self.sftp:
            return
        if path == ".":
            path = self.home
        self.submit(lambda: self._list(path), self._show)

    def refresh(self):
        if self.cwd:
            self.navigate(self.cwd)

    def go_up(self):
        if self.cwd and self.cwd != "/":
            self.navigate(posixpath.dirname(self.cwd.rstrip("/")) or "/")

    def _show(self, res):
        path, entries = res
        self.cwd = path
        self.path_entry.set_text(path)
        self.path_entry.set_position(-1)  # que se vea la carpeta actual, no el inicio de la ruta
        self.store.clear()
        ndirs = nfiles = 0
        for a in entries:
            vals = row_values(a.filename, a.st_mode, a.st_size, a.st_mtime,
                              is_link=stat.S_ISLNK(a.st_mode or 0))
            ndirs, nfiles = (ndirs + 1, nfiles) if vals[COL_ISDIR] else (ndirs, nfiles + 1)
            self.store.append(vals)
        listing = f"{path} — {ndirs} carpetas, {nfiles} archivos"
        note, self._note = getattr(self, "_note", None), None
        self.set_status(f"{note}   ·   {listing}" if note else listing)

    def _selected(self):
        return selected_rows(self.view)

    def _remote(self, name):
        return posixpath.join(self.cwd, name)

    def _on_activate(self, view, path, col):
        row = self.store[path]
        name, is_dir, size = row[COL_NAME], row[COL_ISDIR], row[COL_BYTES]
        target = self._remote(name)
        if is_dir or row[COL_PERM].startswith("l"):
            # los enlaces simbólicos pueden ser carpetas: se intenta entrar
            if is_dir:
                self.navigate(target)
                return

            def check():
                return stat.S_ISDIR(self.sftp.stat(target).st_mode)

            self.submit(check, lambda d: self.navigate(target) if d else self.edit_file(name, size))
        else:
            self.edit_file(name, size)

    # --- edición remota: abrir en el editor local y subir al guardar ------
    BIG_FILE = 20 * 1024 * 1024

    def edit_file(self, name, size=0):
        remote = self._remote(name)
        if remote in self.editing:
            rec = self.editing[remote]
            self._launch_editor(rec["local"])
            self.set_status(f"{name} ya está abierto para editar")
            return
        if size > self.BIG_FILE:
            from .dialogs import confirm
            if not confirm(self.app.win, f"{name} pesa {human(size)}",
                           "Se descargará completo para editarlo. ¿Continuar?", ok="Abrir", destructive=False):
                return
        workdir = tempfile.mkdtemp(prefix="edit-", dir=self.app.agent.dir)
        local = os.path.join(workdir, name)

        def job():
            self.sftp.get(remote, local, callback=self._progress_cb(f"Abriendo {name}"))
            return self.sftp.stat(remote)

        def done(st):
            self._transfer_end()
            os.chmod(local, 0o600)
            rec = {"name": name, "remote": remote, "local": local, "dir": workdir,
                   "mtime": st.st_mtime, "size": st.st_size, "hash": _sha(local),
                   "timer": None, "busy": False}
            mon = Gio.File.new_for_path(workdir).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
            mon.connect("changed", self._on_local_change, rec)
            rec["monitor"] = mon
            self.editing[remote] = rec
            self._launch_editor(local)
            self._update_editing_status()
            self.app.toast(f"Editando {name}: cada vez que guardes se sube a {self.host['name']}")

        self.submit(job, done)

    def _launch_editor(self, local):
        with open(local, "rb") as f:
            head = f.read(4096)
        ctype, _ = Gio.content_type_guess(local, head)
        is_text = Gio.content_type_is_a(ctype, "text/plain") or (head and b"\0" not in head)
        app_info = Gio.AppInfo.get_default_for_type("text/plain" if is_text else ctype, False)
        if app_info is None:
            app_info = Gio.AppInfo.get_default_for_type("text/plain", False)
        try:
            if app_info:
                app_info.launch([Gio.File.new_for_path(local)], None)
            else:
                Gio.AppInfo.launch_default_for_uri(GLib.filename_to_uri(local), None)
        except GLib.Error as e:
            self.app.toast(f"No se pudo abrir un editor: {e.message}", error=True)

    def _on_local_change(self, monitor, f, other, event, rec):
        names = {x.get_basename() for x in (f, other) if x is not None}
        if rec["name"] not in names:
            return
        if event not in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CHANGED,
                         Gio.FileMonitorEvent.CREATED, Gio.FileMonitorEvent.MOVED_IN,
                         Gio.FileMonitorEvent.RENAMED):
            return
        # los editores guardan en varios pasos: se espera a que termine
        if rec["timer"]:
            GLib.source_remove(rec["timer"])
        rec["timer"] = GLib.timeout_add(700, self._upload_edit, rec, False)

    def _upload_edit(self, rec, force):
        rec["timer"] = None
        if self.closed or not os.path.exists(rec["local"]):
            return False
        if rec["busy"]:
            rec["timer"] = GLib.timeout_add(700, self._upload_edit, rec, force)
            return False
        h = _sha(rec["local"])
        if h == rec["hash"] and not force:
            return False
        rec["busy"] = True
        name, remote, local = rec["name"], rec["remote"], rec["local"]

        def job():
            if not force:
                st = self.sftp.stat(remote)
                if int(st.st_mtime) != int(rec["mtime"]) or st.st_size != rec["size"]:
                    return "conflict"
            self.sftp.put(local, remote, callback=self._progress_cb(f"Subiendo {name}"))
            return self.sftp.stat(remote)

        def done(res):
            rec["busy"] = False
            self._transfer_end()
            if res == "conflict":
                self._edit_conflict(rec)
                return
            rec["mtime"], rec["size"], rec["hash"] = res.st_mtime, res.st_size, h
            stamp = time.strftime("%H:%M:%S")
            self.set_status(f"↑ {name} subido a {self.host['name']} ({stamp})")
            self.app.toast(f"↑ {name} guardado en {self.host['name']}")
            if self.cwd and posixpath.dirname(remote) == self.cwd:
                self.refresh()

        def fail_wrap():
            try:
                return job()
            finally:
                rec["busy"] = False

        self.submit(fail_wrap, done)
        return False

    def _edit_conflict(self, rec):
        d = Gtk.MessageDialog(
            transient_for=self.app.win, modal=True, message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=f"{rec['name']} cambió en {self.host['name']} desde que lo abriste",
        )
        d.format_secondary_text("Alguien (u otro proceso) lo modificó en el servidor. "
                                "Si subes tu versión, esos cambios se pierden.")
        d.add_buttons("No subir", Gtk.ResponseType.CANCEL, "Subir y sobrescribir", Gtk.ResponseType.OK)
        r = d.run()
        d.destroy()
        if r == Gtk.ResponseType.OK:
            self._upload_edit(rec, True)
        else:
            self.set_status(f"{rec['name']}: no se subió (conflicto). Vuelve a guardar para reintentar.")

    def _update_editing_status(self):
        n = len(self.editing)
        if n:
            self.set_status(f"Editando {n} archivo(s) — se suben al guardar: " +
                            ", ".join(r["name"] for r in list(self.editing.values())[:4]))

    def open_file(self, name):
        """Descarga a una carpeta temporal y abre con la aplicación por defecto (solo lectura)."""
        local = self.app.agent.tmpfile(f"sftp-{int(time.time())}-{name}")
        remote = self._remote(name)

        def job():
            self.sftp.get(remote, local, callback=self._progress_cb(f"Abriendo {name}"))
            os.chmod(local, 0o400)
            return local

        def done(path):
            self._transfer_end()
            self.set_status(f"Abierto {name} (copia local de solo lectura)")
            Gio.AppInfo.launch_default_for_uri(GLib.filename_to_uri(path), None)

        self.submit(job, done)

    def _on_key(self, view, ev):
        k = ev.keyval
        if k == Gdk.KEY_BackSpace:
            self.go_up()
            return True
        if k == Gdk.KEY_F5:
            self.refresh()
            return True
        if k == Gdk.KEY_Delete:
            self.delete_dialog()
            return True
        if k == Gdk.KEY_F2:
            self.rename_dialog()
            return True
        if k == Gdk.KEY_Left and ev.state & Gdk.ModifierType.CONTROL_MASK:
            self.download_selected()
            return True
        return False

    def _on_button(self, view, ev):
        if ev.button != 3:
            return False
        res = view.get_path_at_pos(int(ev.x), int(ev.y))
        sel = view.get_selection()
        if res and not sel.path_is_selected(res[0]):
            sel.unselect_all()
            sel.select_path(res[0])
        menu = Gtk.Menu()
        n = len(self._selected())
        for text, cb, needs in (
            ("Editar (se sube al guardar)", self._edit_selected, 1),
            ("Abrir copia de solo lectura", lambda: self.open_file(self._selected()[0][0]), 1),
            ("←  Bajar a este equipo", self.download_selected, 1),
            ("Descargar en otra carpeta…", self.download_dialog, 1),
            ("Renombrar…", self.rename_dialog, 1),
            ("Eliminar…", self.delete_dialog, 1),
            ("Copiar ruta", self.copy_path, 0),
            (None, None, 0),
            ("Subir archivos aquí…", self.upload_dialog, 0),
            ("Subir carpeta aquí…", self.upload_folder_dialog, 0),
            ("Nueva carpeta…", self.mkdir_dialog, 0),
            ("Actualizar", self.refresh, 0),
        ):
            if text is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            mi = Gtk.MenuItem(label=text)
            mi.set_sensitive(n >= needs)
            mi.connect("activate", lambda _m, f=cb: f())
            menu.append(mi)
        menu.show_all()
        self._menu = menu
        menu.popup_at_pointer(ev)
        return True

    def copy_path(self):
        sel = self._selected()
        path = self._remote(sel[0][0]) if sel else self.cwd
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(path, -1)
        self.app.toast("Ruta copiada")

    # --- transferencias --------------------------------------------------
    def _progress_cb(self, label):
        last = [0.0]
        t0 = time.time()

        def cb(done, total):
            if self.cancel.is_set():
                raise Cancelled()
            now = time.time()
            if now - last[0] < 0.12 and done < total:
                return
            last[0] = now
            frac = done / total if total else 1
            speed = done / max(now - t0, 0.001)
            rate = f" · {human(speed)}/s" if now - t0 > 0.5 else ""
            GLib.idle_add(self._set_progress, frac, f"{label}: {human(done)} / {human(total)}{rate}")

        return cb

    def _set_progress(self, frac, text):
        self.progress.show()
        self.b_cancel.show()
        self.progress.set_fraction(frac)
        self.set_status(text)
        return False

    def _transfer_start(self):
        self.cancel.clear()
        self.busy += 1
        self.b_cancel.show()

    def _transfer_end(self):
        self.busy = max(0, self.busy - 1)
        if not self.busy:
            self.progress.hide()
            self.b_cancel.hide()

    def _ask_overwrite(self, names, where):
        """None = cancelar, True = reemplazar, False = omitir los existentes."""
        if not names:
            return True
        shown = ", ".join(sorted(names)[:5]) + ("…" if len(names) > 5 else "")
        d = Gtk.MessageDialog(transient_for=self.app.win, modal=True, message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.NONE,
                              text=f"{len(names)} elemento(s) ya existen en {where}")
        d.format_secondary_text(f"{shown}\n\nLas carpetas se combinan; los archivos con el mismo nombre se reemplazan.")
        d.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Omitir existentes", 1, "Reemplazar", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        r = d.run()
        d.destroy()
        return {Gtk.ResponseType.OK: True, 1: False}.get(r)

    # subir: este equipo -> servidor
    def _send_from_local(self, paths, sub=None):
        if not self.sftp or not self.cwd:
            self.app.toast("Todavía no hay conexión con el servidor")
            return
        self._upload_paths(paths, posixpath.join(self.cwd, sub) if sub else self.cwd)

    def _upload_paths(self, paths, dest=None):
        if not self.cwd:
            return
        dest = dest or self.cwd
        paths = [p for p in paths if os.path.exists(p)]
        if not paths:
            return

        def existing():
            return set(self.sftp.listdir(dest))

        def decide(names_there):
            clash = {os.path.basename(p.rstrip("/")) for p in paths} & names_there
            choice = self._ask_overwrite(clash, f"{self.host['name']}:{dest}")
            if choice is None:
                return
            todo = [p for p in paths if choice or os.path.basename(p.rstrip("/")) not in clash]
            if todo:
                self._do_upload(todo, dest)

        self.submit(existing, decide)

    def _do_upload(self, paths, dest):
        n = len(paths)
        count = [0]

        def put_tree(local, remote, i):
            if self.cancel.is_set():
                raise Cancelled()
            if os.path.isdir(local):
                try:
                    self.sftp.mkdir(remote)
                except OSError:
                    pass
                for name in sorted(os.listdir(local)):
                    put_tree(os.path.join(local, name), posixpath.join(remote, name), i)
            elif os.path.isfile(local):
                tag = f"↑ {os.path.basename(local)}" + (f" ({i}/{n})" if n > 1 else "")
                part = remote + ".nexo-parcial"
                try:
                    self.sftp.put(local, part, callback=self._progress_cb(tag))
                    self._replace_remote(part, remote)  # nunca deja un archivo a medias con el nombre final
                except BaseException:
                    try:
                        self.sftp.remove(part)
                    except OSError:
                        pass
                    raise
                count[0] += 1

        def job():
            for i, p in enumerate(paths, 1):
                put_tree(p, posixpath.join(dest, os.path.basename(p.rstrip("/"))), i)
            return count[0]

        def done(files):
            self._transfer_end()
            msg = f"↑ {files} archivo(s) subidos a {self.host['name']}:{dest}"
            self._note = msg
            self.set_status(msg)
            self.app.toast(msg)
            self.refresh()

        self._transfer_start()
        self.submit(job, done)

    def _replace_remote(self, src, dst):
        try:
            self.sftp.posix_rename(src, dst)          # reemplaza en un paso (OpenSSH)
        except OSError:
            try:
                self.sftp.remove(dst)
            except OSError:
                pass
            self.sftp.rename(src, dst)

    # bajar: servidor -> este equipo
    def download_selected(self):
        sel = self._selected()
        if not sel:
            self.app.toast("Selecciona archivos o carpetas del servidor para bajar")
            return
        self._receive_to_local(sel, self.cwd, self.local.cwd)

    def _receive_to_local(self, items, src, dest):
        if not self.sftp:
            return
        items = [tuple(x) for x in items]
        clash = {name for name, *_ in items if os.path.exists(os.path.join(dest, name))}
        choice = self._ask_overwrite(clash, dest)
        if choice is None:
            return
        todo = [x for x in items if choice or x[0] not in clash]
        if todo:
            self._do_download(todo, src, dest)

    def _do_download(self, items, src, dest):
        n = len(items)
        count = [0]

        def get_tree(remote, local, is_dir, i):
            if self.cancel.is_set():
                raise Cancelled()
            if is_dir:
                os.makedirs(local, exist_ok=True)
                for a in self.sftp.listdir_attr(remote):
                    get_tree(posixpath.join(remote, a.filename), os.path.join(local, a.filename),
                             stat.S_ISDIR(a.st_mode or 0), i)
            else:
                tag = f"↓ {posixpath.basename(remote)}" + (f" ({i}/{n})" if n > 1 else "")
                part = local + ".nexo-parcial"
                try:
                    self.sftp.get(remote, part, callback=self._progress_cb(tag))
                    os.replace(part, local)  # nunca deja un archivo a medias con el nombre final
                finally:
                    if os.path.exists(part):
                        os.unlink(part)
                count[0] += 1

        def job():
            for i, (name, is_dir, _size) in enumerate(items, 1):
                get_tree(posixpath.join(src, name), os.path.join(dest, name), is_dir, i)
            return count[0]

        def done(files):
            self._transfer_end()
            msg = f"↓ {files} archivo(s) bajados a {dest}"
            self._note = msg
            self.set_status(msg)
            self.app.toast(msg)
            if self.local.cwd == dest or os.path.dirname(dest) == self.local.cwd:
                self.local.refresh()

        self._transfer_start()
        self.submit(job, done)

    def _drag_get(self, view, ctx, data, info, time_):
        payload = {"dir": self.cwd, "items": self._selected()}
        data.set(Gdk.Atom.intern(TARGET_REMOTE, False), 8, json.dumps(payload).encode())

    def _on_drop(self, widget, ctx, x, y, data, info, time_):
        paths = uris_to_paths(data.get_uris())
        if paths:
            sub = folder_under(self.view, x, y)
            self._upload_paths(paths, posixpath.join(self.cwd, sub) if sub and self.cwd else None)
        Gtk.drag_finish(ctx, bool(paths), False, time_)

    def _chooser(self, title, action, multiple=False):
        d = Gtk.FileChooserNative.new(title, self.app.win, action, None, None)
        d.set_select_multiple(multiple)
        start = os.path.join(conn.REAL_HOME, "Descargas")
        d.set_current_folder(start if os.path.isdir(start) else conn.REAL_HOME)
        if d.run() == Gtk.ResponseType.ACCEPT:
            files = d.get_filenames()
            d.destroy()
            return files
        d.destroy()
        return []

    def upload_dialog(self):
        files = self._chooser("Subir archivos", Gtk.FileChooserAction.OPEN, multiple=True)
        if files:
            self._upload_paths(files)

    def upload_folder_dialog(self):
        files = self._chooser("Subir carpeta", Gtk.FileChooserAction.SELECT_FOLDER)
        if files:
            self._upload_paths(files)

    def download_dialog(self):
        sel = self._selected()
        if not sel:
            self.app.toast("Selecciona archivos o carpetas para descargar")
            return
        dirs = self._chooser("Descargar en…", Gtk.FileChooserAction.SELECT_FOLDER)
        if dirs:
            self._receive_to_local(sel, self.cwd, dirs[0])

    # --- operaciones -----------------------------------------------------
    def _ask(self, title, text="", ok="Aceptar"):
        d = Gtk.Dialog(title=title, transient_for=self.app.win, modal=True)
        d.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, ok, Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        e = Gtk.Entry(text=text, activates_default=True)
        e.set_width_chars(40)
        box = d.get_content_area()
        box.set_border_width(12)
        box.add(e)
        d.show_all()
        r = d.run()
        val = e.get_text().strip()
        d.destroy()
        return val if r == Gtk.ResponseType.OK and val else None

    def mkdir_dialog(self):
        name = self._ask("Nueva carpeta", ok="Crear")
        if name:
            path = self._remote(name)
            self.submit(lambda: self.sftp.mkdir(path), lambda _: self.refresh())

    def rename_dialog(self):
        sel = self._selected()
        if len(sel) != 1:
            return
        old = sel[0][0]
        new = self._ask("Renombrar", old, ok="Renombrar")
        if new and new != old:
            a, b = self._remote(old), self._remote(new)
            self.submit(lambda: self.sftp.posix_rename(a, b), lambda _: self.refresh())

    def delete_dialog(self):
        sel = self._selected()
        if not sel:
            return
        names = ", ".join(n for n, *_ in sel[:5]) + ("…" if len(sel) > 5 else "")
        d = Gtk.MessageDialog(
            transient_for=self.app.win, modal=True, message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE, text=f"¿Eliminar {len(sel)} elemento(s) en {self.host['name']}?",
        )
        d.format_secondary_text(f"{names}\n\nLas carpetas se eliminan con todo su contenido. No se puede deshacer.")
        d.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Eliminar", Gtk.ResponseType.OK)
        d.get_widget_for_response(Gtk.ResponseType.OK).get_style_context().add_class("destructive-action")
        r = d.run()
        d.destroy()
        if r != Gtk.ResponseType.OK:
            return
        base = self.cwd

        def rm_tree(path, is_dir):
            if is_dir:
                for a in self.sftp.listdir_attr(path):
                    rm_tree(posixpath.join(path, a.filename), stat.S_ISDIR(a.st_mode or 0))
                self.sftp.rmdir(path)
            else:
                self.sftp.remove(path)

        def job():
            for name, is_dir, _ in sel:
                rm_tree(posixpath.join(base, name), is_dir)

        self.submit(job, lambda _: self.refresh())

    def open_terminal_here(self):
        self.app.open_ssh(self.host, cwd=self.cwd)

    def _edit_selected(self):
        for name, is_dir, size in self._selected():
            if not is_dir:
                self.edit_file(name, size)

    def close(self):
        self.closed = True
        self.cancel.set()
        for rec in self.editing.values():
            rec["monitor"].cancel()
            if rec["timer"]:
                GLib.source_remove(rec["timer"])
        self.editing.clear()
        try:
            if self.client:
                jump = getattr(self.client, "_nexo_jump", None)
                self.client.close()
                if jump:
                    jump.close()
        except Exception:  # noqa: BLE001
            pass

    def focus(self):
        self.view.grab_focus()
