"""Barra lateral: secciones de grupo plegables con sus hosts."""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import icons as I  # noqa: E402
from .terminal import DRAG_HOST  # noqa: E402

UNGROUPED = ""


class GroupSection(Gtk.Box):
    """Encabezado (clic = plegar/desplegar, soltar un host = moverlo aquí) + lista de hosts."""

    def __init__(self, win, group, hosts):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.app = win.app
        self.group = group
        self.name = group["name"]
        self.org_id = group.get("org")
        self.hosts = hosts

        # --- encabezado
        self.header = Gtk.EventBox()
        self.header.get_style_context().add_class("enlace-group-header")
        hb = Gtk.Box(spacing=6)
        hb.set_border_width(4)
        self.arrow = Gtk.Image()
        hb.pack_start(self.arrow, False, False, 2)
        hb.pack_start(I.image(group.get("icon") if self.name else "box", 14, fallback="folder"), False, False, 0)
        title = Gtk.Label(label=(self.name or "Sin grupo").upper(), xalign=0, ellipsize=Pango.EllipsizeMode.END)
        title.get_style_context().add_class("enlace-group-title")
        hb.pack_start(title, True, True, 0)
        self.count = Gtk.Label(label=str(len(hosts)))
        self.count.get_style_context().add_class("enlace-count")
        hb.pack_start(self.count, False, False, 0)
        acts = Gtk.Box()
        acts.get_style_context().add_class("nx-row-actions")
        hb.pack_start(acts, False, False, 0)

        def small(icon, tip, cb):
            b = Gtk.Button()
            b.add(I.ui_image(icon, 13))
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.set_tooltip_text(tip)
            b.set_focus_on_click(False)
            b.connect("clicked", lambda *_: cb())
            acts.pack_start(b, False, False, 0)
            return b

        if self.org_id:
            small("refresh", "Actualizar hosts de la organización", lambda: self.app.refresh_orgs(quiet=False))
        else:
            small("plus", "Nuevo host en este grupo", lambda: self.app.new_host(group=self.name or None))
        more = small("more", "Opciones del grupo", lambda: None)
        more.connect("clicked", lambda b: self._menu_at(b))
        self.header.add(hb)
        self.header.set_tooltip_text("Clic: plegar / desplegar · Arrastra un host aquí para moverlo a este grupo")
        self.header.connect("button-release-event", self._on_header_click)
        if self.org_id:
            org = self.app.vault.org(self.org_id) or {}
            self.header.set_tooltip_text(f"Organización · {org.get('url', '')} · como {org.get('username', '')}\n"
                                         "Clic: plegar / desplegar · clic derecho: opciones")
            if org.get("expired"):
                self.count.set_text("sesión expirada")
        self.header.drag_dest_set(Gtk.DestDefaults.ALL, [DRAG_HOST], Gdk.DragAction.COPY)
        self.header.connect("drag-motion", lambda *_: self._hl(True) or False)
        self.header.connect("drag-leave", lambda *_: self._hl(False))
        self.header.connect("drag-data-received", self._on_drop)
        self.pack_start(self.header, False, False, 0)

        # --- hosts
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.listbox.set_activate_on_single_click(False)
        self.listbox.set_filter_func(lambda row: self.win._filter(row))
        self.listbox.set_sort_func(lambda a, b: (a.host["name"].lower() > b.host["name"].lower()) -
                                   (a.host["name"].lower() < b.host["name"].lower()))
        self.listbox.connect("row-activated", lambda lb, row: self.app.connect_host(row.host))
        for h in hosts:
            self.listbox.add(win._host_row(h))
        if not hosts:
            text = "Vacío — arrastra hosts aquí"
            if self.org_id:
                org = self.app.vault.org(self.org_id) or {}
                text = ("Sesión expirada — clic derecho → Volver a ingresar" if org.get("expired")
                        else "Sin hosts asignados por tu organización")
            empty = Gtk.Label(label=text, xalign=0)
            empty.get_style_context().add_class("enlace-sub")
            empty.set_margin_start(40)
            empty.set_margin_bottom(6)
            self.listbox.set_placeholder(empty)
            empty.show()
        # también se puede soltar sobre la lista del grupo
        self.listbox.drag_dest_set(Gtk.DestDefaults.ALL, [DRAG_HOST], Gdk.DragAction.COPY)
        self.listbox.connect("drag-data-received", self._on_drop)
        self.revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
                                     transition_duration=150)
        self.revealer.add(self.listbox)
        self.pack_start(self.revealer, False, False, 0)
        self.collapsed = bool(group.get("collapsed"))
        self._apply_collapsed(animate=False)
        self.show_all()

    # --- plegar ------------------------------------------------------------
    def _apply_collapsed(self, animate=True, force_open=False):
        open_ = force_open or not self.collapsed
        self.arrow.set_from_icon_name(I.ui_name("chevron-down" if open_ else "chevron-right"), Gtk.IconSize.MENU)
        self.arrow.set_pixel_size(11)
        if not animate:
            dur = self.revealer.get_transition_duration()
            self.revealer.set_transition_duration(0)
            self.revealer.set_reveal_child(open_)
            self.revealer.set_transition_duration(dur)
        else:
            self.revealer.set_reveal_child(open_)

    def toggle(self):
        self.collapsed = not self.collapsed
        self._apply_collapsed()
        if self.org_id:
            self.app.ui.setdefault("org_collapsed", {})[self.org_id] = self.collapsed
            self.app.save_ui()
        elif self.name:
            self.app.vault.set_collapsed(self.name, self.collapsed)
        else:
            self.app.ui["ungrouped_collapsed"] = self.collapsed
            self.app.save_ui()

    def _on_header_click(self, w, ev):
        if ev.button == 1:
            self.toggle()
            return True
        if ev.button == 3:
            self._menu_at(None, ev)
            return True
        return False

    # --- búsqueda ----------------------------------------------------------
    def apply_search(self, query):
        self.listbox.invalidate_filter()
        if not query:
            self.set_visible(True)
            self._apply_collapsed(animate=False)
            return
        visible = sum(1 for r in self.listbox.get_children() if self.win._filter(r))
        self.set_visible(visible > 0)
        self._apply_collapsed(animate=False, force_open=True)

    def visible_rows(self):
        return [r for r in self.listbox.get_children() if self.win._filter(r)]

    # --- soltar hosts ------------------------------------------------------
    def _hl(self, on):
        ctx = self.header.get_style_context()
        (ctx.add_class if on else ctx.remove_class)("drop-target")

    def _on_drop(self, w, ctx, x, y, data, info, time_):
        self._hl(False)
        if self.org_id:
            return
        raw = data.get_data()
        if raw:
            host_id = bytes(raw).decode()
            GLib.idle_add(lambda: (self.app.move_host_to_group(host_id, self.name), False)[1])

    # --- menú ----------------------------------------------------------------
    def _menu_at(self, widget, ev=None):
        menu = Gtk.Menu()

        def item(text, cb, sensitive=True):
            mi = Gtk.MenuItem(label=text)
            mi.set_sensitive(sensitive)
            mi.connect("activate", lambda *_: cb())
            menu.append(mi)

        if self.org_id:
            oid = self.org_id
            item("Actualizar hosts", lambda: self.app.refresh_orgs(quiet=False))
            item("Volver a ingresar…", lambda: self.app.add_org(self.app.vault.org(oid)))
            menu.append(Gtk.SeparatorMenuItem())
            item("Cerrar sesión", lambda: self.app.org_logout(oid))
            item("Quitar organización…", lambda: self.app.org_logout(oid, remove=True))
            menu.show_all()
            self._menu = menu
            if ev is not None:
                menu.popup_at_pointer(ev)
            else:
                menu.popup_at_widget(widget, Gdk.Gravity.SOUTH_EAST, Gdk.Gravity.NORTH_EAST, None)
            return
        item("Nuevo host en este grupo…", lambda: self.app.new_host(group=self.name or None))
        item("Abrir todos sus hosts juntos", lambda: self.app.connect_group(self.name),
             any(h["protocol"] == "ssh" for h in self.hosts))
        if self.name:
            menu.append(Gtk.SeparatorMenuItem())
            item("Editar nombre e icono…", lambda: self.app.edit_group(self.name))
            item("Subir", lambda: self.app.move_group(self.name, -1))
            item("Bajar", lambda: self.app.move_group(self.name, 1))
            menu.append(Gtk.SeparatorMenuItem())
            item("Eliminar grupo…", lambda: self.app.delete_group(self.name))
        menu.append(Gtk.SeparatorMenuItem())
        item("Nuevo grupo…", self.app.new_group)
        menu.show_all()
        self._menu = menu
        if ev is not None:
            menu.popup_at_pointer(ev)
        else:
            menu.popup_at_widget(widget, Gdk.Gravity.SOUTH_EAST, Gdk.Gravity.NORTH_EAST, None)
