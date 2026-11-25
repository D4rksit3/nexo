"""Paleta de comandos (Ctrl+K): buscar y conectar hosts o ejecutar acciones con el teclado."""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import conn  # noqa: E402
from . import icons as I  # noqa: E402


class CommandPalette(Gtk.Window):
    MAX_ROWS = 9

    def __init__(self, app):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.app = app
        self.set_transient_for(app.win)
        self.set_modal(True)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_default_size(600, -1)
        self.get_style_context().add_class("nx-palette")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(box)
        row = Gtk.Box(spacing=10)
        row.get_style_context().add_class("nx-palette-input")
        row.pack_start(I.ui_image("search", 16), False, False, 0)
        self.entry = Gtk.Entry(placeholder_text="Conectar a un host o ejecutar una acción…")
        self.entry.set_has_frame(False)
        self.entry.connect("changed", lambda *_: self.refresh())
        self.entry.connect("activate", lambda *_: self.activate_selected())
        self.entry.connect("key-press-event", self._on_key)
        row.pack_start(self.entry, True, True, 0)
        esc = Gtk.Label(label="Esc")
        esc.get_style_context().add_class("nx-kbd")
        row.pack_start(esc, False, False, 0)
        box.pack_start(row, False, False, 0)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.BROWSE)
        self.list.get_style_context().add_class("nx-palette-list")
        self.list.connect("row-activated", lambda lb, r: self.run(r))
        box.pack_start(self.list, False, False, 0)
        self.hint = Gtk.Label(xalign=0)
        self.hint.get_style_context().add_class("nx-palette-hint")
        self.hint.set_markup("↑↓ moverse  ·  Enter abrir  ·  Ctrl+Enter abrir SFTP")
        box.pack_start(self.hint, False, False, 0)

        self.connect("focus-out-event", lambda *_: GLib.timeout_add(80, self._maybe_close))
        self.connect("key-press-event", self._on_key)
        self.refresh()
        self.show_all()
        self._place()
        self.entry.grab_focus()

    def _place(self):
        win = self.app.win
        x, y = win.get_position()
        w, _h = win.get_size()
        self.move(x + (w - 600) // 2, y + 70)

    def _maybe_close(self):
        if not self.is_active():
            self.destroy()
        return False

    def _actions(self):
        a = self.app
        return [
            ("terminal", "Terminal local", "Ctrl+Shift+T", a.open_local),
            ("plus", "Nuevo host", "Ctrl+N", a.new_host),
            ("folder-plus", "Nuevo grupo", "", a.new_group),
            ("shield", "Conectar a una organización (Nexo Server)", "", a.add_org),
            ("import", "Importar hosts de ~/.ssh/config", "", a.import_config),
            ("keys", "Generar llave SSH", "", a.generate_key),
            ("sidebar", "Mostrar / ocultar panel", "F9",
             lambda: a.win.b_side.set_active(not a.win.b_side.get_active())),
            ("palette", "Cambiar tema", "", lambda: a.win.b_theme.set_active(True)),
            ("lock", "Bloquear bóveda", "Ctrl+L", a.lock),
        ]

    def refresh(self):
        for c in self.list.get_children():
            c.destroy()
        q = self.entry.get_text().strip().lower()
        words = q.split()

        def ok(text):
            return all(w in text.lower() for w in words)

        items = []
        hosts = self.app.vault.all_hosts() if self.app.vault.unlocked else []
        ordered = sorted(hosts, key=lambda h: (-(h.get("last_used") or 0), h["name"].lower()))
        for h in ordered:
            hay = " ".join(str(h.get(k) or "") for k in ("name", "host", "user", "group"))
            if ok(hay):
                items.append(("host", h))
        for act in self._actions():
            if ok(act[1]):
                items.append(("action", act))
        for kind, data in items[: self.MAX_ROWS]:
            self.list.add(self._row(kind, data))
        if not items:
            r = Gtk.ListBoxRow(activatable=False, selectable=False)
            lbl = Gtk.Label(label="Sin resultados", xalign=0)
            lbl.get_style_context().add_class("nx-muted")
            r.add(lbl)
            self.list.add(r)
        self.list.show_all()
        first = self.list.get_row_at_index(0)
        if first is not None and getattr(first, "kind", None):
            self.list.select_row(first)

    def _row(self, kind, data):
        r = Gtk.ListBoxRow()
        r.kind, r.data = kind, data
        box = Gtk.Box(spacing=12)
        if kind == "host":
            h = data
            box.pack_start(I.image(I.host_icon(h), 18), False, False, 0)
            n = Gtk.Label(label=h["name"], xalign=0, ellipsize=Pango.EllipsizeMode.END)
            n.get_style_context().add_class("enlace-host-name")
            box.pack_start(n, False, True, 0)
            sub = Gtk.Label(label=conn.label(h), xalign=0, ellipsize=Pango.EllipsizeMode.END)
            sub.get_style_context().add_class("nx-mono-sub")
            box.pack_start(sub, True, True, 0)
            tag = Gtk.Label(label=h.get("org_name") or h.get("group") or h["protocol"].upper())
            tag.get_style_context().add_class("nx-caption")
            box.pack_start(tag, False, False, 0)
        else:
            icon, text, accel, _cb = data
            box.pack_start(I.ui_image(icon, 16), False, False, 0)
            box.pack_start(Gtk.Label(label=text, xalign=0), True, True, 0)
            if accel:
                k = Gtk.Label(label=accel)
                k.get_style_context().add_class("nx-kbd")
                box.pack_start(k, False, False, 0)
        r.add(box)
        return r

    def _on_key(self, w, ev):
        key = ev.keyval
        if key == Gdk.KEY_Escape:
            self.destroy()
            return True
        if key in (Gdk.KEY_Down, Gdk.KEY_Up):
            rows = [r for r in self.list.get_children() if getattr(r, "kind", None)]
            if rows:
                cur = self.list.get_selected_row()
                i = rows.index(cur) if cur in rows else -1
                i = (i + (1 if key == Gdk.KEY_Down else -1)) % len(rows)
                self.list.select_row(rows[i])
            return True
        if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and ev.state & Gdk.ModifierType.CONTROL_MASK:
            r = self.list.get_selected_row()
            if r is not None and getattr(r, "kind", None) == "host" and r.data["protocol"] == "ssh":
                self.destroy()
                self.app.open_sftp(r.data)
            return True
        return False

    def activate_selected(self):
        r = self.list.get_selected_row()
        if r is not None:
            self.run(r)

    def run(self, r):
        kind = getattr(r, "kind", None)
        if not kind:
            return
        self.destroy()
        if kind == "host":
            GLib.idle_add(lambda: (self.app.connect_host(r.data), False)[1])
        else:
            GLib.idle_add(lambda: (r.data[3](), False)[1])
