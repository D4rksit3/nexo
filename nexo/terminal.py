"""Terminales (VTE) y pestañas divisibles en paneles.

Una pestaña de sesión (SplitTab) contiene un árbol de Gtk.Paned cuyas hojas son
paneles de terminal (TerminalPane). Cada panel puede ser de un host distinto.

Arrastrar y soltar:
  - un host de la barra lateral sobre un borde de un panel => abre ese host ahí al lado
  - la barra de título de un panel sobre un borde de otro => lo mueve ahí
  - la barra de un panel sobre el centro de otro => intercambian lugar
  - archivos del gestor de archivos sobre la terminal => pega sus rutas
"""
import math
import os
import shlex
import signal
from urllib.parse import unquote, urlparse

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Vte", "2.91")
from gi.repository import Gdk, GLib, Gtk, Pango, Vte  # noqa: E402

T_HOST, T_PANE, T_URI, T_TAB = 1, 2, 3, 4
DRAG_HOST = Gtk.TargetEntry.new("application/x-enlace-host", Gtk.TargetFlags.SAME_APP, T_HOST)
DRAG_PANE = Gtk.TargetEntry.new("application/x-enlace-pane", Gtk.TargetFlags.SAME_APP, T_PANE)
DRAG_URI = Gtk.TargetEntry.new("text/uri-list", 0, T_URI)
DRAG_TAB = Gtk.TargetEntry.new("application/x-enlace-tab", Gtk.TargetFlags.SAME_APP, T_TAB)

H, V = Gtk.Orientation.HORIZONTAL, Gtk.Orientation.VERTICAL
ZONES = {"left": (H, True), "right": (H, False), "top": (V, True), "bottom": (V, False)}
ZONE_LABELS = {"left": "← aquí", "right": "aquí →", "top": "↑ arriba", "bottom": "↓ abajo",
               "center": "⇄ intercambiar"}


def rgba(hex_):
    c = Gdk.RGBA()
    c.parse(hex_)
    return c


class TerminalPane(Gtk.Overlay):
    """Un panel: barra de título (visible si hay varios) + terminal VTE + indicador de soltar."""

    def __init__(self, app, title, argv_factory, host=None):
        super().__init__()
        self.app = app
        self.title = title
        self.host = host
        self.argv_factory = argv_factory  # () -> (argv, env_extra)
        self.owner = None
        self.pid = None
        self.alive = False
        self._respawn = False
        self._zone = None
        self._drop_zone = None
        self.uid = f"p{id(self):x}"
        app.pane_registry[self.uid] = self
        self.font_size = app.settings.get("font_size", 11)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(body)

        # barra del panel (se arrastra para mover el panel)
        self.header_ev = Gtk.EventBox()
        self.header = Gtk.Box(spacing=4)
        self.header.get_style_context().add_class("enlace-pane-header")
        self.header_ev.add(self.header)
        self.header_ev.set_tooltip_text("Arrastra esta barra a un borde de otro panel para moverlo, "
                                        "o al centro para intercambiarlos")
        from . import icons as I
        self.h_icon = I.image(I.host_icon(host), 14) if host else Gtk.Image.new_from_icon_name(
            "utilities-terminal-symbolic", Gtk.IconSize.MENU)
        from . import icons as _Ig
        grip = _Ig.ui_image("grip", 12)
        self.h_label = Gtk.Label(label=title, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.h_bcast = Gtk.Label(label="⚡ difusión")
        self.h_bcast.get_style_context().add_class("enlace-bcast")
        self.h_bcast.set_no_show_all(True)
        self.header.pack_start(grip, False, False, 2)
        self.header.pack_start(self.h_icon, False, False, 2)
        self.header.pack_start(self.h_label, True, True, 0)
        self.header.pack_start(self.h_bcast, False, False, 4)

        from . import icons as _I

        def hbtn(icon, tip, cb):
            b = Gtk.Button()
            b.add(_I.ui_image(icon, 12))
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.set_focus_on_click(False)
            b.set_tooltip_text(tip)
            b.connect("clicked", lambda *_: cb())
            self.header.pack_end(b, False, False, 0)
            return b

        hbtn("close", "Cerrar panel (Ctrl+Shift+W)", lambda: self.owner and self.owner.close_pane(self))
        hbtn("popout", "Sacar este panel a su propia pestaña", lambda: self.app.pane_to_new_tab(self))
        hbtn("split-down", "Dividir abajo (Ctrl+Shift+O)", lambda: self.owner and self.owner.split(self, V))
        hbtn("split-right", "Dividir a la derecha (Ctrl+Shift+E)",
             lambda: self.owner and self.owner.split(self, H))
        sw_host = hbtn("hosts", "Cambiar el host de este panel", lambda: None)
        sw_host.connect("clicked", self._pop_host_menu)
        self.header_ev.set_no_show_all(True)
        self.header.show_all()
        self.h_bcast.hide()
        body.pack_start(self.header_ev, False, False, 0)

        self.header_ev.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [DRAG_PANE], Gdk.DragAction.MOVE)
        self.header_ev.connect("drag-begin", lambda w, ctx: Gtk.drag_set_icon_name(ctx, "view-grid-symbolic", 0, 0))
        self.header_ev.connect("drag-data-get",
                               lambda w, ctx, data, info, t: data.set(data.get_target(), 8, self.uid.encode()))

        self.term = Vte.Terminal()
        self.term.set_scrollback_lines(20000)
        self.term.set_mouse_autohide(True)
        self.term.set_audible_bell(False)
        self.term.set_size_request(120, 60)
        self.term.drag_dest_unset()  # el panel maneja los drops (incluye archivos)
        self.apply_theme(app.theme)
        self._apply_font()
        self.term.connect("child-exited", self._on_exit)
        self.term.connect("key-press-event", self._on_key)
        self.term.connect("button-press-event", self._on_button)
        self.term.connect("focus-in-event", lambda *_: self.owner and self.owner.set_active(self))
        self.term.connect("commit", lambda t, text, size: self.owner and self.owner.broadcast_from(self, text))

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(self.term)
        body.pack_start(sw, True, True, 0)

        # indicador de dónde caerá lo que se arrastra
        self.indicator = Gtk.DrawingArea()
        self.indicator.connect("draw", self._draw_indicator)
        self.indicator.set_no_show_all(True)
        self.add_overlay(self.indicator)
        self.set_overlay_pass_through(self.indicator, True)

        self.drag_dest_set(0, [DRAG_HOST, DRAG_PANE, DRAG_TAB, DRAG_URI], Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        self.connect("drag-motion", self._drag_motion)
        self.connect("drag-leave", lambda *_: self._show_zone(None))
        self.connect("drag-drop", self._drag_drop)
        self.connect("drag-data-received", self._drag_received)

        body.show_all()
        self.show()
        self.spawn()

    # --- apariencia ------------------------------------------------------
    def _apply_font(self):
        family = self.app.settings.get("font", "JetBrains Mono")
        self.term.set_font(Pango.FontDescription(f"{family} {self.font_size}"))

    def apply_theme(self, t):
        self.term.set_colors(rgba(t["fg"]), rgba(t["bg"]), [rgba(c) for c in t["palette"]])
        self.term.set_color_cursor(rgba(t["accent"]))
        self.term.set_color_cursor_foreground(rgba(t["bg"]))
        self.term.set_color_highlight(rgba(t["accent"]))
        self.term.set_color_highlight_foreground(rgba(t["bg"]))

    def show_header(self, show):
        self.header_ev.set_visible(show)

    def set_active_style(self, active):
        ctx = self.header.get_style_context()
        (ctx.add_class if active else ctx.remove_class)("active")

    # --- arrastrar y soltar ----------------------------------------------
    def _target_kind(self, ctx):
        target = self.drag_dest_find_target(ctx, None)
        if target is None:
            return None, None
        name = target.name()
        if name == "application/x-enlace-host":
            return target, "host"
        if name == "application/x-enlace-pane":
            return target, "pane"
        if name == "application/x-enlace-tab":
            return target, "tab"
        return target, "uri"

    def _zone_at(self, x, y, allow_center):
        w, h = max(1, self.get_allocated_width()), max(1, self.get_allocated_height())
        fx, fy = x / w, y / h
        edges = {"left": fx, "right": 1 - fx, "top": fy, "bottom": 1 - fy}
        zone = min(edges, key=edges.get)
        if allow_center and edges[zone] > 0.28:
            return "center"
        return zone

    def _drag_motion(self, w, ctx, x, y, time):
        target, kind = self._target_kind(ctx)
        if kind is None:
            return False
        if kind == "uri":
            self._show_zone("center")
            Gdk.drag_status(ctx, Gdk.DragAction.COPY, time)
            return True
        self._show_zone(self._zone_at(x, y, allow_center=(kind == "pane")))
        Gdk.drag_status(ctx, Gdk.DragAction.COPY if kind == "host" else Gdk.DragAction.MOVE, time)
        return True

    def _drag_drop(self, w, ctx, x, y, time):
        target, kind = self._target_kind(ctx)
        if target is None:
            return False
        self._drop_zone = self._zone_at(x, y, allow_center=(kind == "pane")) if kind != "uri" else "center"
        self.drag_get_data(ctx, target, time)
        return True

    def _drag_received(self, w, ctx, x, y, data, info, time):
        zone = self._drop_zone or self._zone_at(x, y, info == T_PANE)
        self._drop_zone = None
        self._show_zone(None)
        ok = True
        if info == T_URI:
            paths = [unquote(urlparse(u).path) for u in (data.get_uris() or []) if u.startswith("file:")]
            if paths and self.alive:
                self.term.feed_child((" ".join(shlex.quote(p) for p in paths) + " ").encode())
        else:
            raw = data.get_data()
            payload = bytes(raw).decode(errors="replace") if raw else ""
            if info == T_HOST:
                GLib.idle_add(self._drop_host, payload, zone)
            elif info == T_PANE:
                GLib.idle_add(self._drop_pane, payload, zone)
            elif info == T_TAB:
                GLib.idle_add(self._drop_tab, payload, zone)
            else:
                ok = False
        Gtk.drag_finish(ctx, ok, False, time)

    def _drop_host(self, host_id, zone):
        host = self.app.vault.host(host_id) if self.app.vault.unlocked else None
        if host and self.owner:
            if host["protocol"] != "ssh":
                self.app.connect_host(host)
            else:
                orient, before = ZONES.get(zone, (H, False))
                self.owner.split(self, orient, target=host, before=before)
        return False

    def _drop_pane(self, uid, zone):
        src = self.app.pane_registry.get(uid)
        if src is None or src is self or src.owner is None or self.owner is None:
            return False
        if zone == "center":
            SplitTab.swap(src, self)
        else:
            orient, before = ZONES[zone]
            src.owner.detach(src)
            self.owner.insert(src, self, orient, before)
        return False

    def _drop_tab(self, uid, zone):
        if self.owner is None:
            return False
        self.app.merge_tab_into(uid, self, zone if zone in ZONES else "right")
        return False

    def _show_zone(self, zone):
        self._zone = zone
        if zone:
            self.indicator.show()
        else:
            self.indicator.hide()
        self.indicator.queue_draw()

    def _draw_indicator(self, w, cr):
        if not self._zone:
            return False
        W, Hh = w.get_allocated_width(), w.get_allocated_height()
        rects = {"left": (0, 0, W / 2, Hh), "right": (W / 2, 0, W / 2, Hh),
                 "top": (0, 0, W, Hh / 2), "bottom": (0, Hh / 2, W, Hh / 2),
                 "center": (W * .2, Hh * .2, W * .6, Hh * .6)}
        x, y, rw, rh = rects[self._zone]
        acc = rgba(self.app.theme["accent"])
        cr.set_source_rgba(acc.red, acc.green, acc.blue, 0.22)
        cr.rectangle(x + 4, y + 4, rw - 8, rh - 8)
        cr.fill_preserve()
        cr.set_source_rgba(acc.red, acc.green, acc.blue, 0.9)
        cr.set_line_width(2)
        cr.set_dash([6, 4])
        cr.stroke()
        cr.set_dash([])
        cr.select_font_face("Sans")
        cr.set_font_size(16)
        text = ZONE_LABELS[self._zone]
        ext = cr.text_extents(text)
        cr.move_to(x + rw / 2 - ext.width / 2, y + rh / 2 + ext.height / 2)
        cr.show_text(text)
        return False

    # --- proceso ---------------------------------------------------------
    def spawn(self):
        try:
            argv, env_extra = self.argv_factory()
        except Exception as e:  # noqa: BLE001
            self.term.feed(f"\r\n\x1b[31m✖ {e}\x1b[0m\r\n".encode())
            self.term.feed(b"\x1b[2m  Enter para reintentar\x1b[0m\r\n")
            return
        env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor", **env_extra}
        envv = [f"{k}={v}" for k, v in env.items()]
        if self.host:
            self.term.feed(f"\x1b[2mConectando a {self.title}…\x1b[0m\r\n".encode())
        self.term.spawn_async(
            Vte.PtyFlags.DEFAULT, os.path.expanduser("~"), argv, envv,
            GLib.SpawnFlags.DEFAULT, None, None, -1, None, self._spawned,
        )

    def _spawned(self, term, pid, error, *data):
        if error:
            self.term.feed(f"\r\n\x1b[31m✖ No se pudo iniciar: {error.message}\x1b[0m\r\n".encode())
            return
        self.pid = pid
        self.alive = True
        self.app.tab_state_changed(self)
        if self.owner and self.owner.active is self:
            self.term.grab_focus()

    def _on_exit(self, term, status):
        self.alive = False
        self.pid = None
        if self._respawn:
            self._respawn = False
            self.term.reset(True, False)
            self.spawn()
            return
        code = os.waitstatus_to_exitcode(status) if status >= 0 else status
        msg = "sesión cerrada" if code == 0 else f"conexión terminada (código {code})"
        self.term.feed(
            f"\r\n\x1b[33m■ {msg}.\x1b[0m \x1b[2mEnter para reconectar · Ctrl+Shift+W para cerrar\x1b[0m\r\n".encode()
        )
        self.app.tab_state_changed(self)

    def reconnect(self):
        if self.alive:
            self._respawn = True
            self.kill()
        else:
            self.term.reset(True, False)
            self.spawn()

    def retarget(self, host):
        """Cambia el host de este panel (None = terminal local) y reconecta."""
        factory, title = self.app.pane_target(host)
        self.argv_factory, self.title, self.host = factory, title, host
        self.h_label.set_text(title)
        from . import icons as I
        ctx = self.h_icon.get_style_context()
        for c in list(ctx.list_classes()):
            if c.startswith("bi-"):
                ctx.remove_class(c)
        if host:
            k = I.host_icon(host)
            self.h_icon.set_from_icon_name(I.icon_name(k), Gtk.IconSize.MENU)
            self.h_icon.set_pixel_size(14)
            ctx.add_class(f"bi-{k}")
        else:
            self.h_icon.set_from_icon_name("utilities-terminal-symbolic", Gtk.IconSize.MENU)
        self.reconnect()
        if self.owner:
            self.owner.update_title()

    def kill(self):
        if self.pid:
            try:
                os.kill(self.pid, signal.SIGHUP)
            except ProcessLookupError:
                pass

    def close(self):
        self.kill()
        self.app.pane_registry.pop(self.uid, None)

    def focus(self):
        self.term.grab_focus()

    # --- teclado y ratón -------------------------------------------------
    def _on_key(self, widget, ev):
        mods = ev.state & Gtk.accelerator_get_default_mod_mask()
        ctrl_shift = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        key = Gdk.keyval_to_lower(ev.keyval)
        if not self.alive and ev.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not self._respawn:
            self.term.reset(True, False)
            self.spawn()
            return True
        if mods == ctrl_shift:
            if key == Gdk.KEY_c:
                self.term.copy_clipboard_format(Vte.Format.TEXT)
                return True
            if key == Gdk.KEY_v:
                self.term.paste_clipboard()
                return True
            if self.owner:
                if key == Gdk.KEY_e:
                    self.owner.split(self, H)
                    return True
                if key == Gdk.KEY_o:
                    self.owner.split(self, V)
                    return True
                if key == Gdk.KEY_b:
                    self.owner.toggle_broadcast()
                    return True
        if mods == Gdk.ModifierType.MOD1_MASK and self.owner:
            if ev.keyval in (Gdk.KEY_Right, Gdk.KEY_Down):
                self.owner.focus_next(1)
                return True
            if ev.keyval in (Gdk.KEY_Left, Gdk.KEY_Up):
                self.owner.focus_next(-1)
                return True
        if mods == Gdk.ModifierType.CONTROL_MASK:
            if key in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
                self.zoom(1)
                return True
            if key in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
                self.zoom(-1)
                return True
            if key == Gdk.KEY_0:
                self.zoom(0)
                return True
        return False

    def zoom(self, delta):
        self.font_size = 11 if delta == 0 else max(6, min(32, self.font_size + delta))
        self._apply_font()

    def _pop_host_menu(self, button):
        self._menu = self._host_menu(self.retarget)
        self._menu.popup_at_widget(button, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)

    def _host_menu(self, on_pick):
        menu = Gtk.Menu()
        mi = Gtk.MenuItem(label="Terminal local")
        mi.connect("activate", lambda *_: on_pick(None))
        menu.append(mi)
        menu.append(Gtk.SeparatorMenuItem())
        for h in sorted(self.app.vault.hosts if self.app.vault.unlocked else [], key=lambda x: x["name"].lower()):
            if h["protocol"] != "ssh":
                continue
            mi = Gtk.MenuItem(label=f"{h['name']}  —  {h['host']}")
            mi.connect("activate", lambda _m, host=h: on_pick(host))
            menu.append(mi)
        menu.show_all()
        return menu

    def _on_button(self, widget, ev):
        if ev.button != 3:
            return False
        menu = Gtk.Menu()

        def item(text, cb, sensitive=True, accel=None):
            mi = Gtk.MenuItem(label=text + (f"   ({accel})" if accel else ""))
            mi.set_sensitive(sensitive)
            mi.connect("activate", lambda *_: cb())
            menu.append(mi)

        def sub(text, submenu):
            mi = Gtk.MenuItem(label=text)
            mi.set_submenu(submenu)
            menu.append(mi)

        item("Copiar", lambda: self.term.copy_clipboard_format(Vte.Format.TEXT), self.term.get_has_selection(),
             "Ctrl+Shift+C")
        item("Pegar", self.term.paste_clipboard, accel="Ctrl+Shift+V")
        menu.append(Gtk.SeparatorMenuItem())
        if self.owner:
            o = self.owner
            item("Dividir a la derecha", lambda: o.split(self, H), accel="Ctrl+Shift+E")
            item("Dividir abajo", lambda: o.split(self, V), accel="Ctrl+Shift+O")
            sub("Dividir a la derecha con…", self._host_menu(lambda h: o.split(self, H, target=h)))
            item("Sacar a pestaña propia", lambda: self.app.pane_to_new_tab(self), len(o.panes) > 1)
            sub("Cambiar host de este panel", self._host_menu(self.retarget))
            mi = Gtk.CheckMenuItem(label="Escribir en todos los paneles   (Ctrl+Shift+B)")
            mi.set_active(o.broadcast)
            mi.set_sensitive(len(o.panes) > 1)
            mi.connect("toggled", lambda *_: o.toggle_broadcast())
            menu.append(mi)
            if len(o.panes) > 1:
                item("Cerrar este panel", lambda: o.close_pane(self), accel="Ctrl+Shift+W")
            menu.append(Gtk.SeparatorMenuItem())
        if self.host:
            item("Abrir SFTP de este host", lambda: self.app.open_sftp(self.host))
        item("Reconectar", self.reconnect)
        item("Limpiar", lambda: self.term.reset(True, True))
        menu.show_all()
        self._menu = menu  # mantener referencia mientras está abierto
        menu.popup_at_pointer(ev)
        return True


class SplitTab(Gtk.Box):
    """Pestaña con uno o más paneles de terminal en un árbol de Gtk.Paned."""

    MAX_PANES = 36

    def __init__(self, app, first):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.panes = []
        self.active = None
        self.broadcast = False
        self._feeding = False
        self.tab_label = None
        self._adopt(first)
        self.pack_start(first, True, True, 0)
        self.set_active(first)
        self.show()

    # --- propiedades usadas por la app -----------------------------------
    @property
    def alive(self):
        return any(p.alive for p in self.panes)

    @property
    def host(self):
        return self.panes[0].host if self.panes else None

    @property
    def title(self):
        return self.panes[0].title if self.panes else ""

    def has_remote(self):
        return any(p.alive and p.host for p in self.panes)

    def _adopt(self, pane):
        pane.owner = self
        if pane not in self.panes:
            self.panes.append(pane)

    def update_title(self):
        n = len(self.panes)
        for p in self.panes:
            p.show_header(n > 1)
            p.h_bcast.set_visible(self.broadcast)
        if self.tab_label is not None and self.panes:
            names = list(dict.fromkeys(p.title for p in self._ordered() or self.panes))
            text = names[0] if len(names) == 1 else f"{names[0]} +{len(names) - 1}"
            if getattr(self, "custom_title", None):
                text = self.custom_title
            if n > 1:
                text += f"  ▦{n}"
            self.tab_label.lbl.set_text(text)
            self.tab_label.lbl.set_width_chars(min(len(text), 24))
            self.tab_label.set_tooltip_text("\n".join(p.title for p in self.panes))

    def set_active(self, pane):
        self.active = pane
        for p in self.panes:
            p.set_active_style(p is pane)

    def focus(self):
        if self.active:
            self.active.focus()

    def focus_next(self, step):
        if len(self.panes) < 2:
            return
        order = self._ordered()
        i = order.index(self.active) if self.active in order else 0
        p = order[(i + step) % len(order)]
        self.set_active(p)
        p.focus()

    def _ordered(self):
        """Paneles en orden visual (izquierda→derecha, arriba→abajo)."""
        out = []

        def walk(node):
            if isinstance(node, TerminalPane):
                out.append(node)
            elif isinstance(node, Gtk.Paned):
                walk(node.get_child1())
                walk(node.get_child2())

        for c in self.get_children():
            walk(c)
        return out

    def apply_theme(self, t):
        for p in self.panes:
            p.apply_theme(t)

    # --- árbol de paneles ------------------------------------------------
    def _new_pane(self, target="same"):
        host = (self.active.host if self.active else None) if target == "same" else target
        return self.app.make_pane(host)

    def _replace(self, old, new):
        """Pone `new` en el lugar de `old` dentro del árbol."""
        parent = old.get_parent()
        if parent is self:
            self.remove(old)
            self.pack_start(new, True, True, 0)
        else:
            first = parent.get_child1() is old
            parent.remove(old)
            if first:
                parent.pack1(new, True, False)
            else:
                parent.pack2(new, True, False)

    @staticmethod
    def _paned(orientation, a, b, fraction):
        p = Gtk.Paned(orientation=orientation, wide_handle=True)
        p.pack1(a, True, False)
        p.pack2(b, True, False)
        done = {"v": False}

        def on_alloc(widget, alloc):
            if done["v"]:
                return
            size = alloc.width if orientation == H else alloc.height
            if size > 1:
                done["v"] = True
                widget.set_position(int(size * fraction))

        p.connect("size-allocate", on_alloc)
        p.show()
        return p

    def split(self, pane, orientation, target="same", new=None, before=False):
        if new is None and len(self.panes) >= self.MAX_PANES:
            self.app.toast(f"Máximo {self.MAX_PANES} paneles por pestaña", error=True)
            return
        new = new or self._new_pane(target)
        self._adopt(new)
        holder = Gtk.Box()
        self._replace(pane, holder)
        a, b = (new, pane) if before else (pane, new)
        self._replace(holder, self._paned(orientation, a, b, 0.5))
        holder.destroy()
        self.update_title()
        self.set_active(new)
        GLib.idle_add(lambda: (new.focus(), False)[1])

    def absorb(self, other, target, orientation, before):
        """Pega toda la pestaña `other` (con su distribución) al lado de `target`."""
        roots = other.get_children()
        if not roots or other is self:
            return
        root = roots[0]
        other.remove(root)
        holder = Gtk.Box()
        self._replace(target, holder)
        a, b = (root, target) if before else (target, root)
        self._replace(holder, self._paned(orientation, a, b, 0.5))
        holder.destroy()
        moved = list(other.panes)
        for p in moved:
            p.owner = self
            if p not in self.panes:
                self.panes.append(p)
        other.panes = []
        self.app.discard_tab(other)
        self.update_title()
        self.set_active(moved[0])
        GLib.idle_add(lambda: (moved[0].focus(), False)[1])

    def insert(self, pane, target, orientation, before):
        """Inserta un panel existente (movido desde otro lugar) junto a `target`."""
        self.split(target, orientation, new=pane, before=before)

    def detach(self, pane):
        """Saca el panel del árbol sin cerrar su sesión. Si era el último, la pestaña desaparece."""
        if pane not in self.panes:
            return
        parent = pane.get_parent()
        self.panes.remove(pane)
        pane.owner = None
        if parent is self:
            self.remove(pane)
        else:
            sibling = parent.get_child2() if parent.get_child1() is pane else parent.get_child1()
            parent.remove(pane)
            parent.remove(sibling)
            self._replace(parent, sibling)
            parent.destroy()
        if not self.panes:
            self.app.discard_tab(self)
            return
        if len(self.panes) == 1:
            self.broadcast = False
        if self.active is pane:
            self.set_active(self._ordered()[0])
        self.update_title()

    @staticmethod
    def swap(a, b):
        """Intercambia la posición de dos paneles (pueden estar en pestañas distintas)."""
        oa, ob = a.owner, b.owner
        ha, hb = Gtk.Box(), Gtk.Box()
        oa._replace(a, ha)
        ob._replace(b, hb)
        oa._replace(ha, b)
        ob._replace(hb, a)
        ha.destroy()
        hb.destroy()
        if oa is not ob:
            oa.panes[oa.panes.index(a)] = b
            ob.panes[ob.panes.index(b)] = a
            a.owner, b.owner = ob, oa
            for o in (oa, ob):
                o.set_active(o.panes[0])
        for o in {oa, ob}:
            o.update_title()
        a.focus()

    def grid(self, rows, cols, fill=True):
        rows, cols = max(1, int(rows)), max(1, int(cols))
        order = self._ordered()
        order += [p for p in self.panes if p not in order]  # adoptados aún sin lugar en el árbol
        n = min(rows * cols, self.MAX_PANES) if fill else min(len(order), self.MAX_PANES)
        extra = len(order) - n
        if extra > 0:
            # sobran paneles: se cierran los últimos (el activo se conserva)
            victims = [p for p in reversed(order) if p is not self.active][:extra]
            live = [p for p in victims if p.alive and p.host]
            if live:
                from .dialogs import confirm
                names = ", ".join(p.title for p in live[:4])
                if not confirm(self.app.win, f"¿Cerrar {extra} panel(es) para dejar {rows}×{cols}?",
                               f"Se cerrarán sesiones abiertas: {names}", ok="Cerrar", destructive=False):
                    return
            for p in victims:
                p.close()
                self.panes.remove(p)
                order.remove(p)
        while len(order) < n:
            p = self._new_pane()
            self._adopt(p)
            order.append(p)
        for p in order:
            par = p.get_parent()
            if par is not None:
                par.remove(p)
        for c in self.get_children():
            self.remove(c)
            c.destroy()
        rows = math.ceil(n / cols)
        row_widgets = [self._chain(order[r * cols:(r + 1) * cols], H) for r in range(rows)]
        self.pack_start(self._chain(row_widgets, V), True, True, 0)
        self.panes = order
        self.set_active(self.active if self.active in order else order[0])
        if len(order) == 1:
            self.broadcast = False
        self.update_title()
        GLib.idle_add(lambda: (self.active.focus(), False)[1])

    def _chain(self, items, orientation):
        if len(items) == 1:
            return items[0]
        return self._paned(orientation, items[0], self._chain(items[1:], orientation), 1 / len(items))

    def close_pane(self, pane):
        if pane not in self.panes:
            return
        if len(self.panes) == 1:
            self.app.close_tab(self)
            return
        self.detach(pane)
        pane.close()
        pane.destroy()
        if self.active:
            self.active.focus()

    # --- difusión (escribir en todos) ------------------------------------
    def toggle_broadcast(self):
        if len(self.panes) < 2:
            self.app.toast("La difusión necesita al menos 2 paneles")
            return
        self.broadcast = not self.broadcast
        self.update_title()
        self.app.toast("Escribiendo en TODOS los paneles" if self.broadcast else "Difusión desactivada",
                       error=self.broadcast)

    def broadcast_from(self, source, text):
        if not self.broadcast or self._feeding:
            return
        self._feeding = True
        try:
            data = text.encode()
            for p in self.panes:
                if p is not source and p.alive:
                    p.term.feed_child(data)
        finally:
            self._feeding = False

    def close(self):
        for p in self.panes:
            p.close()
