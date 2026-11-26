"""Piezas comunes de los paneles de archivos y el panel «Este equipo» del SFTP de dos paneles."""
import json
import os
import stat
import time
from urllib.parse import unquote, urlparse

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango  # noqa: E402

COL_ICON, COL_NAME, COL_SIZE, COL_MTIME, COL_PERM, COL_ISDIR, COL_BYTES, COL_SORT = range(8)

# Arrastre interno entre los dos paneles (solo dentro de la misma ventana de Nexo).
TARGET_REMOTE = "application/x-nexo-remote-files"
TARGET_URIS = "text/uri-list"
INFO_REMOTE, INFO_URIS = 71, 72


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def new_store():
    store = Gtk.ListStore(str, str, str, str, str, bool, GObject.TYPE_INT64, str)
    store.set_sort_column_id(COL_SORT, Gtk.SortType.ASCENDING)
    return store


# --- iconos por tipo de archivo -------------------------------------------------
# tipo -> (icono de Bootstrap Icons, color). Los colores son fijos para que cada tipo se
# reconozca igual en cualquier tema.
KINDS = {
    "folder": ("folder-fill", "#e8b75a"),
    "link": ("link-45deg", "#5fd4d4"),
    "archive": ("file-earmark-zip", "#c8955c"),
    "pdf": ("file-earmark-pdf", "#ff6b6b"),
    "image": ("file-earmark-image", "#5fd49a"),
    "video": ("file-earmark-play", "#ff7fc8"),
    "audio": ("file-earmark-music", "#b18cff"),
    "code": ("file-earmark-code", "#6cb6ff"),
    "script": ("terminal-fill", "#8fd18a"),
    "text": ("file-earmark-text", "#c8ced9"),
    "sheet": ("file-earmark-spreadsheet", "#3ddc84"),
    "doc": ("file-earmark-word", "#5b9bff"),
    "slides": ("file-earmark-slides", "#ff8a2a"),
    "key": ("file-earmark-lock", "#f2c66d"),
    "db": ("database-fill", "#4fd8e0"),
    "disk": ("disc", "#9aa7bd"),
    "binary": ("file-earmark-binary", "#a3e635"),
    "font": ("file-earmark-font", "#d7b4f8"),
    "config": ("gear-fill", "#9fb3c8"),
    "file": ("file-earmark", "#8a93a3"),
}
_EXT = {}
for _kind, _exts in {
    "archive": "zip tar gz tgz bz2 tbz xz txz zst 7z rar lz lzma deb rpm apk jar war ear snap flatpak cab",
    "pdf": "pdf",
    "image": "png jpg jpeg gif svg webp bmp ico tif tiff heic avif psd xcf",
    "video": "mp4 mkv avi mov webm wmv flv m4v mpg mpeg",
    "audio": "mp3 wav flac ogg oga m4a aac opus wma",
    "code": "py pyc js mjs cjs ts tsx jsx go rs c h cc cpp hpp cs java kt php rb pl lua swift dart scala r "
            "html htm css scss sass less vue svelte json jsonc xml yaml yml toml sql graphql proto tf hcl",
    "script": "sh bash zsh fish ps1 psm1 bat cmd",
    "text": "txt md rst log nfo readme",
    "sheet": "xls xlsx xlsm ods csv tsv",
    "doc": "doc docx odt rtf",
    "slides": "ppt pptx odp",
    "key": "pem key crt cer csr der pub p12 pfx jks kdbx gpg asc sig",
    "db": "db sqlite sqlite3 mdb accdb dump bak frm ibd",
    "disk": "iso img qcow2 vmdk vdi vhd vhdx dmg",
    "binary": "exe dll so bin elf o a msi appimage",
    "font": "ttf otf woff woff2",
    "config": "conf cfg ini env properties service socket timer rules",
}.items():
    for _e in _exts.split():
        _EXT[_e] = _kind
_NAMES = {  # archivos conocidos sin extensión (o con una engañosa)
    "dockerfile": "code", "makefile": "code", "jenkinsfile": "code", "vagrantfile": "code",
    "authorized_keys": "key", "known_hosts": "key", "id_rsa": "key", "id_ed25519": "key", "id_ecdsa": "key",
    ".env": "config", ".bashrc": "script", ".zshrc": "script", ".profile": "script", "crontab": "config",
    "readme": "text", "license": "text", "changelog": "text",
}


def kind_of(name, is_dir=False, is_link=False, mode=0):
    """Tipo de un archivo para elegir su icono y color."""
    if is_dir:
        return "folder"
    low = name.lower()
    if low in _NAMES:
        return _NAMES[low]
    if low.endswith((".tar.gz", ".tar.xz", ".tar.bz2", ".tar.zst")):
        return "archive"
    ext = low.rsplit(".", 1)[-1] if "." in low.lstrip(".") else ""
    if ext in _EXT:
        return _EXT[ext]
    if low.startswith("id_") and not ext:
        return "key"
    if is_link:
        return "link"
    if mode and stat.S_ISREG(mode) and mode & 0o111:
        return "binary"   # ejecutable sin extensión conocida
    return "file"


_PIXBUFS = {}


def kind_pixbuf(kind, size, scale=1):
    """Icono del tipo pintado en su color (se guarda en caché)."""
    key = (kind, size, scale)
    pb = _PIXBUFS.get(key)
    if pb is None:
        icon, color = KINDS.get(kind, KINDS["file"])
        rgba = Gdk.RGBA()
        rgba.parse(color)
        info = Gtk.IconTheme.get_default().lookup_icon_for_scale(
            f"bi-{icon}-symbolic", size, scale, Gtk.IconLookupFlags.FORCE_SIZE)
        if info is None:
            return None
        pb, _ = info.load_symbolic(rgba, None, None, None)
        _PIXBUFS[key] = pb
    return pb


def _paint_icon(col, cell, model, it, view):
    scale = view.get_scale_factor()
    pb = kind_pixbuf(model[it][COL_ICON], 16, scale)
    if pb is not None and scale > 1:
        cell.set_property("surface", Gdk.cairo_surface_create_from_pixbuf(pb, scale, view.get_window()))
    else:
        cell.set_property("pixbuf", pb)


def row_values(name, mode, size, mtime, is_dir=None, is_link=False):
    is_dir = stat.S_ISDIR(mode or 0) if is_dir is None else is_dir
    icon = kind_of(name, is_dir, is_link, mode)
    return [icon, name, "" if is_dir else human(size or 0),
            time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime or 0)),
            stat.filemode(mode or 0), is_dir, size or 0, ("0" if is_dir else "1") + name.lower()]


def build_view(store, perms=True):
    view = Gtk.TreeView(model=store)
    view.set_enable_search(True)
    view.set_search_column(COL_NAME)
    view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
    view.set_rubber_banding(True)
    col = Gtk.TreeViewColumn("Nombre")
    r_icon = Gtk.CellRendererPixbuf()
    r_name = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
    r_icon.set_padding(2, 0)
    col.pack_start(r_icon, False)
    col.pack_start(r_name, True)
    col.set_cell_data_func(r_icon, _paint_icon, view)
    col.add_attribute(r_name, "text", COL_NAME)
    col.set_expand(True)
    col.set_sort_column_id(COL_SORT)
    col.set_resizable(True)
    view.append_column(col)
    cols = [("Tamaño", COL_SIZE, COL_BYTES), ("Modificado", COL_MTIME, COL_MTIME)]
    if perms:
        cols.append(("Permisos", COL_PERM, COL_PERM))
    for title, idx, sort in cols:
        r = Gtk.CellRendererText()
        if idx == COL_SIZE:
            r.set_property("xalign", 1.0)
        c = Gtk.TreeViewColumn(title, r, text=idx)
        c.set_sort_column_id(sort)
        c.set_resizable(True)
        view.append_column(c)
    return view


def selected_rows(view):
    model, paths = view.get_selection().get_selected_rows()
    return [(model[p][COL_NAME], model[p][COL_ISDIR], model[p][COL_BYTES]) for p in paths]


def folder_under(view, x, y):
    """Nombre de la carpeta bajo el puntero al soltar (o None = la carpeta abierta)."""
    res = view.get_dest_row_at_pos(x, y)
    if not res:
        return None
    path, pos = res
    row = view.get_model()[path]
    if row[COL_ISDIR] and pos in (Gtk.TreeViewDropPosition.INTO_OR_BEFORE, Gtk.TreeViewDropPosition.INTO_OR_AFTER):
        return row[COL_NAME]
    return None


def uris_to_paths(uris):
    out = []
    for uri in uris or []:
        u = urlparse(uri)
        if u.scheme == "file":
            out.append(unquote(u.path))
    return out


def head_label(icon_widget, text, sub=None):
    box = Gtk.Box(spacing=8)
    box.get_style_context().add_class("nx-files-head")
    box.pack_start(icon_widget, False, False, 0)
    t = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
    t.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>" +
                 (f"  <span alpha='60%'>{GLib.markup_escape_text(sub)}</span>" if sub else ""))
    box.pack_start(t, True, True, 0)
    return box, t


class LocalPane(Gtk.Box):
    """Panel izquierdo: archivos de este equipo.

    on_send(paths, dest_name|None): subir esos archivos al servidor (dest_name = carpeta remota
    bajo el puntero, o None para la carpeta abierta del servidor).
    on_receive(items, src_dir, dest_dir): bajar ítems del servidor a una carpeta local.
    """

    def __init__(self, app, start_dir, on_send, on_receive, send_label="Subir"):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        from . import icons as I

        self.app = app
        self.on_send = on_send
        self.on_receive = on_receive
        self.cwd = None
        self.show_hidden = False

        head, _ = head_label(I.ui_image("home", 14), "Este equipo")
        self.pack_start(head, False, False, 0)

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

        btn("up", "Subir un nivel (Retroceso)", self.go_up)
        btn("home", "Carpeta personal", lambda: self.navigate(start_dir))
        btn("refresh", "Actualizar (F5)", self.refresh)
        self.path_entry = Gtk.Entry()
        self.path_entry.connect("activate", lambda e: self.navigate(os.path.expanduser(e.get_text().strip())))
        bar.pack_start(self.path_entry, True, True, 4)
        send = Gtk.Button()
        sb = Gtk.Box(spacing=6)
        sb.pack_start(Gtk.Label(label=send_label), False, False, 0)
        sb.pack_start(I.ui_image("chevron-right", 12), False, False, 0)
        send.add(sb)
        send.get_style_context().add_class("suggested-action")
        send.set_tooltip_text("Subir la selección a la carpeta abierta del servidor (Ctrl+Flecha derecha)")
        send.connect("clicked", lambda *_: self.send_selected())
        bar.pack_end(send, False, False, 2)
        btn("trash", "Mover a la papelera (Supr)", self.trash_dialog, end=True)
        btn("edit", "Renombrar (F2)", self.rename_dialog, end=True)
        btn("new-folder", "Nueva carpeta", self.mkdir_dialog, end=True)
        self.b_hidden = Gtk.ToggleButton()
        self.b_hidden.add(I.ui_image("view", 15))
        self.b_hidden.set_relief(Gtk.ReliefStyle.NONE)
        self.b_hidden.set_tooltip_text("Mostrar archivos ocultos (Ctrl+H)")
        self.b_hidden.connect("toggled", lambda b: (setattr(self, "show_hidden", b.get_active()), self.refresh()))
        bar.pack_end(self.b_hidden, False, False, 0)
        self.pack_start(bar, False, False, 0)

        self.store = new_store()
        self.view = build_view(self.store, perms=False)
        self.view.connect("row-activated", self._on_activate)
        self.view.connect("key-press-event", self._on_key)
        self.view.connect("button-press-event", self._on_button)
        # arrastrar desde aquí: hacia el panel del servidor (o a otra app como archivos)
        self.view.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK,
                                           [Gtk.TargetEntry.new(TARGET_URIS, 0, INFO_URIS)], Gdk.DragAction.COPY)
        self.view.connect("drag-data-get", self._drag_get)
        # soltar aquí: lo que viene del panel del servidor = descargar
        self.view.enable_model_drag_dest([Gtk.TargetEntry.new(TARGET_REMOTE, Gtk.TargetFlags.SAME_APP, INFO_REMOTE)],
                                         Gdk.DragAction.COPY)
        self.view.connect("drag-data-received", self._drop)
        sw = Gtk.ScrolledWindow()
        sw.add(self.view)
        self.pack_start(sw, True, True, 0)
        self.navigate(start_dir)

    # --- navegación ------------------------------------------------------
    def navigate(self, path):
        path = os.path.abspath(path or "/")
        try:
            entries = list(os.scandir(path))
        except OSError as e:
            self.app.toast(f"No se puede abrir {path}: {e.strerror or e}", error=True)
            return
        self.cwd = path
        self.path_entry.set_text(path)
        self.path_entry.set_position(-1)  # que se vea la carpeta actual, no el inicio de la ruta
        self.store.clear()
        for e in entries:
            if not self.show_hidden and e.name.startswith("."):
                continue
            try:
                st = e.stat(follow_symlinks=True)
                is_dir = e.is_dir(follow_symlinks=True)
            except OSError:  # enlace roto
                st, is_dir = e.stat(follow_symlinks=False), False
            self.store.append(row_values(e.name, st.st_mode, st.st_size, st.st_mtime, is_dir, e.is_symlink()))

    def refresh(self):
        if self.cwd:
            self.navigate(self.cwd)

    def go_up(self):
        if self.cwd and self.cwd != "/":
            self.navigate(os.path.dirname(self.cwd.rstrip("/")) or "/")

    def path_of(self, name):
        return os.path.join(self.cwd, name)

    def selected(self):
        return selected_rows(self.view)

    def _on_activate(self, view, path, col):
        row = self.store[path]
        target = self.path_of(row[COL_NAME])
        if row[COL_ISDIR]:
            self.navigate(target)
        else:
            try:
                Gio.AppInfo.launch_default_for_uri(GLib.filename_to_uri(target), None)
            except GLib.Error as e:
                self.app.toast(f"No se pudo abrir: {e.message}", error=True)

    def send_selected(self):
        sel = self.selected()
        if not sel:
            self.app.toast("Selecciona archivos o carpetas de este equipo para subir")
            return
        self.on_send([self.path_of(n) for n, *_ in sel], None)

    # --- arrastrar y soltar -------------------------------------------------
    def _drag_get(self, view, ctx, data, info, time_):
        data.set_uris([GLib.filename_to_uri(self.path_of(n)) for n, *_ in self.selected()])

    def _drop(self, view, ctx, x, y, data, info, time_):
        ok = False
        if info == INFO_REMOTE:
            try:
                payload = json.loads(data.get_data().decode())
                sub = folder_under(view, x, y)
                dest = self.path_of(sub) if sub else self.cwd
                self.on_receive(payload["items"], payload["dir"], dest)
                ok = True
            except (ValueError, KeyError):
                pass
        Gtk.drag_finish(ctx, ok, False, time_)

    # --- operaciones -----------------------------------------------------
    def _on_key(self, view, ev):
        k, ctrl = ev.keyval, bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        if k == Gdk.KEY_BackSpace:
            self.go_up()
        elif k == Gdk.KEY_F5:
            self.refresh()
        elif k == Gdk.KEY_Delete:
            self.trash_dialog()
        elif k == Gdk.KEY_F2:
            self.rename_dialog()
        elif ctrl and k in (Gdk.KEY_h, Gdk.KEY_H):
            self.b_hidden.set_active(not self.b_hidden.get_active())
        elif ctrl and k == Gdk.KEY_Right:
            self.send_selected()
        else:
            return False
        return True

    def _on_button(self, view, ev):
        if ev.button != 3:
            return False
        res = view.get_path_at_pos(int(ev.x), int(ev.y))
        sel = view.get_selection()
        if res and not sel.path_is_selected(res[0]):
            sel.unselect_all()
            sel.select_path(res[0])
        n = len(self.selected())
        menu = Gtk.Menu()
        for text, cb, needs in (
            ("Subir al servidor  →", self.send_selected, 1),
            ("Abrir", lambda: self._on_activate(view, view.get_selection().get_selected_rows()[1][0], None), 1),
            ("Renombrar…", self.rename_dialog, 1),
            ("Mover a la papelera…", self.trash_dialog, 1),
            ("Copiar ruta", self.copy_path, 0),
            (None, None, 0),
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
        sel = self.selected()
        path = self.path_of(sel[0][0]) if sel else self.cwd
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(path, -1)
        self.app.toast("Ruta copiada")

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
        name = self._ask("Nueva carpeta en este equipo", ok="Crear")
        if name:
            try:
                os.mkdir(self.path_of(name))
            except OSError as e:
                self.app.toast(f"No se pudo crear: {e.strerror or e}", error=True)
            self.refresh()

    def rename_dialog(self):
        sel = self.selected()
        if len(sel) != 1:
            return
        old = sel[0][0]
        new = self._ask("Renombrar", old, ok="Renombrar")
        if new and new != old:
            if os.path.exists(self.path_of(new)):
                self.app.toast(f"Ya existe «{new}»", error=True)
                return
            try:
                os.rename(self.path_of(old), self.path_of(new))
            except OSError as e:
                self.app.toast(f"No se pudo renombrar: {e.strerror or e}", error=True)
            self.refresh()

    def trash_dialog(self):
        sel = self.selected()
        if not sel:
            return
        from .dialogs import confirm

        names = ", ".join(n for n, *_ in sel[:5]) + ("…" if len(sel) > 5 else "")
        if not confirm(self.app.win, f"¿Mover {len(sel)} elemento(s) a la papelera?", names,
                       ok="Mover a la papelera", destructive=True):
            return
        failed = []
        for name, *_ in sel:
            try:
                Gio.File.new_for_path(self.path_of(name)).trash(None)
            except GLib.Error as e:
                failed.append(f"{name}: {e.message}")
        if failed:
            self.app.toast("No se pudo mover a la papelera: " + "; ".join(failed[:2]), error=True)
        self.refresh()
