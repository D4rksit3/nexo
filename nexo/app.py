"""Ventana principal de Nexo."""
import json
import time
import math
import weakref
import os
import shlex
import shutil
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Vte", "2.91")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango  # noqa: E402

from . import __version__  # noqa: E402
from . import conn  # noqa: E402
from . import dialogs as D  # noqa: E402
from . import icons as I  # noqa: E402
from . import keys as K  # noqa: E402
from . import dbclient as DBC  # noqa: E402
from .sftp import SftpTab  # noqa: E402
from .sidebar import GroupSection  # noqa: E402
from . import themes as T  # noqa: E402
from .asciibg import AsciiBackdrop  # noqa: E402
from . import updates as U  # noqa: E402
from .terminal import DRAG_HOST, DRAG_PANE, DRAG_TAB, SplitTab, TerminalPane  # noqa: E402
from .widgets import AccentDot, ThemeCard  # noqa: E402
from .vault import Vault, VaultError, blank_host  # noqa: E402

APP_ID = "com.seguricloud.Nexo"
HERE = os.path.dirname(os.path.abspath(__file__))


def _ago(ts):
    d = max(0, time.time() - ts)
    if d < 60:
        return "ahora"
    if d < 3600:
        return f"hace {int(d // 60)} min"
    if d < 86400:
        return f"hace {int(d // 3600)} h"
    return f"hace {int(d // 86400)} d"



class Window(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Nexo")
        self.app = app
        self.set_default_size(1280, 780)
        self.set_icon_from_file(os.path.join(HERE, "nexo.svg"))

        hb = Gtk.HeaderBar(show_close_button=True)
        hb.get_style_context().add_class("nx-headerbar")
        self.set_titlebar(hb)
        self.hb = hb

        def flat(widget, tip):
            widget.set_relief(Gtk.ReliefStyle.NONE)
            widget.set_tooltip_text(tip)
            widget.set_valign(Gtk.Align.CENTER)
            widget.get_style_context().add_class("nx-flat")
            return widget

        # izquierda: panel lateral + marca
        self.b_side = flat(Gtk.ToggleButton(), "Mostrar / ocultar el panel (F9)")
        self.b_side.add(I.ui_image("sidebar", 16))
        self.b_side.set_active(app.ui.get("sidebar", True))
        self.b_side.connect("toggled", lambda b: app.set_sidebar(b.get_active()))
        hb.pack_start(self.b_side)
        brand = Gtk.Box(spacing=8)
        brand.set_margin_start(4)
        logo = Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_size(os.path.join(HERE, "nexo.svg"), 20, 20))
        brand.pack_start(logo, False, False, 0)
        name = Gtk.Label(label="Nexo")
        name.get_style_context().add_class("nx-brand")
        brand.pack_start(name, False, False, 0)
        self.subtitle = Gtk.Label()
        self.subtitle.get_style_context().add_class("nx-brand-sub")
        brand.pack_start(self.subtitle, False, False, 2)
        hb.pack_start(brand)

        # centro: buscador / paleta de comandos
        self.b_palette = Gtk.Button()
        self.b_palette.get_style_context().add_class("nx-search-pill")
        pill = Gtk.Box(spacing=8)
        pill.pack_start(I.ui_image("search", 14), False, False, 0)
        pl = Gtk.Label(label="Buscar hosts o acciones…", xalign=0)
        pill.pack_start(pl, True, True, 0)
        kb = Gtk.Label(label="Ctrl K")
        kb.get_style_context().add_class("nx-kbd")
        pill.pack_start(kb, False, False, 0)
        self.b_palette.add(pill)
        self.b_palette.set_size_request(380, -1)
        self.b_palette.connect("clicked", lambda *_: app.open_palette())
        hb.set_custom_title(self.b_palette)

        # derecha: tema, bloquear, menú
        menu = Gio.Menu()
        menu.append("Conectar a una organización…", "app.add-org")
        menu.append("Importar hosts de ~/.ssh/config", "app.import-config")
        menu.append("Cambiar contraseña maestra", "app.change-password")
        menu.append("Autobloqueo…", "app.autolock")
        look = Gio.Menu()
        look.append("Fondo animado (ASCII)", "app.ascii-bg")
        menu.append_section(None, look)
        upd = Gio.Menu()
        upd.append("Buscar actualizaciones", "app.check-updates")
        upd.append("Avisarme de actualizaciones", "app.update-notify")
        menu.append_section(None, upd)
        sec = Gio.Menu()
        sec.append("Bloquear (Ctrl+L)", "app.lock")
        sec.append("Acerca de Nexo", "app.about")
        menu.append_section(None, sec)
        self.b_menu = flat(Gtk.MenuButton(menu_model=menu), "Ajustes")
        self.b_menu.add(I.ui_image("settings", 16))
        hb.pack_end(self.b_menu)
        self.b_lock = flat(Gtk.Button(), "Bloquear bóveda (Ctrl+L)")
        self.b_lock.add(I.ui_image("lock", 16))
        self.b_lock.connect("clicked", lambda *_: app.lock())
        hb.pack_end(self.b_lock)
        self.b_theme = flat(Gtk.MenuButton(), "Tema y color")
        self.b_theme.add(I.ui_image("palette", 16))
        self.b_theme.set_popover(self._build_theme_popover())
        hb.pack_end(self.b_theme)
        self.b_update = Gtk.Button()
        self.b_update.get_style_context().add_class("nx-update-pill")
        self.b_update.set_valign(Gtk.Align.CENTER)
        ub = Gtk.Box(spacing=6)
        ub.pack_start(I.ui_image("download", 14), False, False, 0)
        self.update_lbl = Gtk.Label(label="Actualización")
        ub.pack_start(self.update_lbl, False, False, 0)
        self.b_update.add(ub)
        self.b_update.set_no_show_all(True)
        ub.show_all()
        self.b_update.connect("clicked", lambda *_: app.show_update())
        hb.pack_end(self.b_update)

        # se ubican en el riel / encabezados (se mantienen como atributos)
        self.b_new = Gtk.Button()
        self.b_local = Gtk.Button()

        overlay = Gtk.Overlay()
        self.add(overlay)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        overlay.add(self.stack)

        # toast
        self.toast_rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP)
        self.toast_rev.set_halign(Gtk.Align.CENTER)
        self.toast_rev.set_valign(Gtk.Align.END)
        self.toast_lbl = Gtk.Label(wrap=True, max_width_chars=80)
        self.toast_lbl.get_style_context().add_class("enlace-toast")
        self.toast_rev.add(self.toast_lbl)
        overlay.add_overlay(self.toast_rev)
        overlay.set_overlay_pass_through(self.toast_rev, True)
        self._toast_id = None

        self.stack.add_named(self._build_lock(), "lock")
        self.stack.add_named(self._build_main(), "main")

    # --- popovers de distribución y tema --------------------------------
    def _build_theme_popover(self):
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(14)
        t = Gtk.Label(xalign=0)
        t.set_markup("<b>Tema</b>  <small>— terminal e interfaz</small>")
        box.pack_start(t, False, False, 0)
        flow = Gtk.FlowBox(max_children_per_line=3, min_children_per_line=3,
                           selection_mode=Gtk.SelectionMode.NONE, column_spacing=8, row_spacing=8)
        current = self.app.theme["id"]

        def pick(tid):
            # Primero cerrar el selector; el tema se aplica cuando GTK terminó con el clic.
            pop.popdown()
            GLib.timeout_add(60, lambda: (self.app.apply_theme(tid), False)[1])

        self.theme_cards = []
        for tid in T.THEMES:
            card = ThemeCard(tid, tid == current, pick)
            self.theme_cards.append(card)
            flow.add(card)
        box.pack_start(flow, False, False, 0)

        at = Gtk.Label(xalign=0)
        at.set_markup("<b>Color de acento</b>  <small>— bordes, selección, botones</small>")
        at.set_margin_top(6)
        box.pack_start(at, False, False, 0)
        dots = Gtk.Box(spacing=4)

        def pick_accent(aid):
            GLib.timeout_add(40, lambda: (self.app.apply_theme(self.app.theme["id"], aid), False)[1])

        self.accent_dots = []
        base_acc = T.THEMES[self.app.theme["id"]][3]
        for aid in T.ACCENTS:
            dot = AccentDot(aid, base_acc, aid == self.app.theme.get("accent_id", "tema"), pick_accent)
            self.accent_dots.append(dot)
            dots.pack_start(dot, False, False, 0)
        box.pack_start(dots, False, False, 0)
        box.show_all()
        pop.add(box)
        return pop

    # --- pantalla de bloqueo ---------------------------------------------
    def _build_lock(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.get_style_context().add_class("nx-card")
        card.set_halign(Gtk.Align.CENTER)
        card.set_valign(Gtk.Align.CENTER)
        card.set_size_request(380, -1)
        img = Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_size(os.path.join(HERE, "nexo.svg"), 64, 64))
        img.set_margin_bottom(6)
        card.pack_start(img, False, False, 0)
        t = Gtk.Label(label="Nexo")
        t.get_style_context().add_class("nx-lock-title")
        card.pack_start(t, False, False, 0)
        self.lock_msg = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=44)
        self.lock_msg.get_style_context().add_class("nx-muted")
        self.lock_msg.set_margin_bottom(10)
        card.pack_start(self.lock_msg, False, False, 0)
        self.lock_p1 = D.secret_entry()
        self.lock_p1.set_placeholder_text("Contraseña maestra")
        self.lock_p2 = D.secret_entry()
        self.lock_p2.set_placeholder_text("Repetir contraseña")
        for e in (self.lock_p1, self.lock_p2):
            e.get_style_context().add_class("nx-input-lg")
            e.connect("activate", lambda *_: self._lock_submit())
            card.pack_start(e, False, False, 0)
        self.lock_err = Gtk.Label()
        self.lock_err.get_style_context().add_class("enlace-state-error")
        card.pack_start(self.lock_err, False, False, 0)
        self.lock_btn = Gtk.Button()
        self.lock_btn.get_style_context().add_class("suggested-action")
        self.lock_btn.get_style_context().add_class("nx-btn-lg")
        self.lock_btn.connect("clicked", lambda *_: self._lock_submit())
        card.pack_start(self.lock_btn, False, False, 0)
        foot = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        foot.set_margin_top(8)
        foot.pack_start(I.ui_image("shield", 12), False, False, 0)
        fl = Gtk.Label(label="Cifrado local AES-256-GCM · sin nube")
        fl.get_style_context().add_class("nx-caption")
        foot.pack_start(fl, False, False, 0)
        card.pack_start(foot, False, False, 0)
        ov = Gtk.Overlay()
        ov.get_style_context().add_class("enlace-lock")
        self.lock_bg = AsciiBackdrop(self.app, focus=card)
        ov.add(self.lock_bg)
        ov.add_overlay(card)
        return ov

    def show_lock(self):
        creating = not self.app.vault.exists()
        self.lock_msg.set_text(
            "Crea una contraseña maestra. Cifra tus hosts, contraseñas y llaves "
            "(AES-256-GCM + scrypt). Si la olvidas no hay forma de recuperarla."
            if creating else "Bóveda bloqueada. Escribe tu contraseña maestra."
        )
        self.lock_btn.set_label("Crear bóveda" if creating else "Desbloquear")
        self.lock_p2.set_visible(creating)
        self.lock_p1.set_text("")
        self.lock_p2.set_text("")
        self.lock_err.set_text("")
        for w in (self.b_menu, self.b_lock, self.b_palette, self.b_side):
            w.set_sensitive(False)
        self.subtitle.set_text("")
        self.stack.set_visible_child_name("lock")
        self.lock_p1.grab_focus()

    def _lock_submit(self):
        v = self.app.vault
        p1 = self.lock_p1.get_text()
        if not v.exists():
            if len(p1) < 8:
                self.lock_err.set_text("Usa al menos 8 caracteres")
                return
            if p1 != self.lock_p2.get_text():
                self.lock_err.set_text("Las contraseñas no coinciden")
                return
            v.create(p1)
        else:
            try:
                v.unlock(p1)
            except VaultError as e:
                self.lock_err.set_text(str(e))
                self.lock_p1.select_region(0, -1)
                return
            except Exception as e:  # noqa: BLE001
                self.lock_err.set_text(f"Bóveda dañada: {e}")
                return
        self.lock_p1.set_text("")
        self.lock_p2.set_text("")
        self.app.on_unlocked()

    def show_main(self):
        self.side.set_visible(self.b_side.get_active())
        for w in (self.b_menu, self.b_lock, self.b_palette, self.b_side):
            w.set_sensitive(True)
        self.stack.set_visible_child_name("main")

    # --- principal -------------------------------------------------------
    def _panel_header(self, title, actions):
        """Encabezado de panel: título + acciones de icono."""
        hb = Gtk.Box(spacing=2)
        hb.get_style_context().add_class("nx-panel-header")
        t = Gtk.Label(label=title, xalign=0)
        t.get_style_context().add_class("nx-panel-title")
        hb.pack_start(t, True, True, 0)
        for icon, tip, cb in actions:
            b = Gtk.Button()
            b.add(I.ui_image(icon, 15))
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.set_tooltip_text(tip)
            b.get_style_context().add_class("nx-flat")
            b.connect("clicked", lambda _b, f=cb: f())
            hb.pack_start(b, False, False, 0)
        return hb

    def _build_rail(self):
        rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        rail.get_style_context().add_class("nx-rail")
        self.rail_buttons = {}
        for page, icon, tip in (("hosts", "hosts", "Hosts"), ("orgs", "org", "Organizaciones (Nexo Server)"),
                                ("keys", "keys", "Llaves SSH"), ("tunnels", "tunnels", "Túneles")):
            b = Gtk.ToggleButton()
            b.add(I.ui_image(icon, 18))
            b.set_tooltip_text(tip)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("nx-rail-btn")
            b.connect("button-release-event", lambda w, e, pg=page: (self.app.show_panel(pg), True)[1])
            rail.pack_start(b, False, False, 0)
            self.rail_buttons[page] = b
        sep = Gtk.Separator()
        sep.set_margin_top(4)
        sep.set_margin_bottom(4)
        sep.set_margin_start(12)
        sep.set_margin_end(12)
        rail.pack_start(sep, False, False, 0)
        lt = Gtk.Button()
        lt.add(I.ui_image("terminal", 18))
        lt.set_tooltip_text("Terminal local (Ctrl+Shift+T)")
        lt.set_relief(Gtk.ReliefStyle.NONE)
        lt.get_style_context().add_class("nx-rail-btn")
        lt.connect("clicked", lambda *_: self.app.open_local())
        rail.pack_start(lt, False, False, 0)
        # versiones: abajo del todo, aparte de las herramientas
        vb = Gtk.ToggleButton()
        vb.add(I.ui_image("releases", 18))
        vb.set_tooltip_text("Versiones y actualizaciones")
        vb.set_relief(Gtk.ReliefStyle.NONE)
        vb.get_style_context().add_class("nx-rail-btn")
        vb.connect("button-release-event", lambda w, e: (self.app.show_panel("releases"), True)[1])
        rail.pack_end(vb, False, False, 0)
        self.rail_buttons["releases"] = vb
        return rail

    def sync_rail(self):
        current = self.side_stack.get_visible_child_name()
        visible = self.side.get_visible()
        for name, b in self.rail_buttons.items():
            b.set_active(visible and name == current)

    def _build_main(self):
        outer = Gtk.Box()
        outer.pack_start(self._build_rail(), False, False, 0)
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        outer.pack_start(paned, True, True, 0)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side.get_style_context().add_class("enlace-sidebar")
        side.set_size_request(310, -1)

        self.side_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120)
        self.side_stack.connect("notify::visible-child-name", lambda *_: self.sync_rail())
        side.pack_start(self.side_stack, True, True, 0)

        # hosts
        hosts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        hosts.pack_start(self._panel_header("Hosts", [
            ("shield", "Conectar a una organización (Nexo Server)", self.app.add_org),
            ("folder-plus", "Nuevo grupo", self.app.new_group),
            ("plus", "Nuevo host (Ctrl+N)", self.app.new_host),
        ]), False, False, 0)
        self.search = Gtk.SearchEntry(placeholder_text="Filtrar…  (Ctrl+F)")
        self.search.get_style_context().add_class("nx-filter")
        self.search.connect("search-changed", lambda *_: self._apply_search())
        self.search.connect("activate", self._search_activate)
        hosts.pack_start(self.search, False, False, 0)
        self.sections = []
        self.groups_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.groups_box.set_margin_bottom(12)
        self.hosts_empty = self._empty("Sin hosts todavía", "Crea uno con + o importa tu ~/.ssh/config")
        self.hosts_empty.set_no_show_all(True)
        gb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        gb.pack_start(self.hosts_empty, False, False, 0)
        gb.pack_start(self.groups_box, False, False, 0)
        s1 = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        s1.add(gb)
        hosts.pack_start(s1, True, True, 0)
        self.side_stack.add_titled(hosts, "hosts", "Hosts")

        # organizaciones
        ob = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        ob.pack_start(self._panel_header("Organizaciones", [
            ("refresh", "Actualizar", lambda: self.app.refresh_orgs(quiet=False)),
            ("plus", "Conectar a una organización", self.app.add_org),
        ]), False, False, 0)
        self.org_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        so = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        so.add(self.org_list)
        ob.pack_start(so, True, True, 0)
        self.side_stack.add_titled(ob, "orgs", "Organizaciones")

        # llaves
        kb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        kb.pack_start(self._panel_header("Llaves SSH", [
            ("import", "Importar llave…", self.app.import_key),
            ("plus", "Generar llave", self.app.generate_key),
        ]), False, False, 0)
        self.key_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.key_list.set_placeholder(self._empty("Sin llaves", "Genera una o importa desde ~/.ssh"))
        s2 = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        s2.add(self.key_list)
        kb.pack_start(s2, True, True, 0)
        self.side_stack.add_titled(kb, "keys", "Llaves")

        # túneles
        tb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tb.pack_start(self._panel_header("Túneles", []), False, False, 0)
        self.tun_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.tun_list.set_placeholder(self._empty("Sin túneles", "Agrégalos al editar un host SSH"))
        s3 = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        s3.add(self.tun_list)
        tb.pack_start(s3, True, True, 0)
        self.side_stack.add_titled(tb, "tunnels", "Túneles")

        # versiones publicadas en GitHub
        rb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        rb.pack_start(self._panel_header("Versiones", [
            ("github", "Abrir las versiones en GitHub", lambda: self.app.open_url(U.RELEASES_PAGE.rsplit("/", 1)[0])),
            ("refresh", "Buscar versiones nuevas", lambda: self.app.load_releases(manual=True)),
        ]), False, False, 0)
        self.rel_status = Gtk.Label(xalign=0, wrap=True)
        self.rel_status.get_style_context().add_class("nx-caption")
        self.rel_status.set_margin_start(16)
        self.rel_status.set_margin_end(16)
        self.rel_status.set_margin_bottom(8)
        rb.pack_start(self.rel_status, False, False, 0)
        self.rel_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.rel_list.get_style_context().add_class("nx-releases")
        self.rel_list.set_placeholder(self._empty("Cargando versiones…", "Se consultan en GitHub"))
        s4 = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        s4.add(self.rel_list)
        rb.pack_start(s4, True, True, 0)
        self.side_stack.add_titled(rb, "releases", "Versiones")

        self.side = side
        paned.pack1(side, False, False)

        self.nb = Gtk.Notebook(scrollable=True, show_border=False)
        self.nb.get_style_context().add_class("nx-tabs")
        self.nb.connect("switch-page", lambda nb, page, n: GLib.idle_add(self._focus_tab, page))
        self.nb.connect("page-removed", lambda *_: self._update_subtitle())
        self.welcome = self._build_welcome()
        self.nb.append_page(self.welcome, self._tab_label(None, "Inicio", I.ui_name("home"), closable=False))
        paned.pack2(self.nb, True, False)
        paned.set_position(320)
        return outer

    def _empty(self, title, sub):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        b.set_margin_top(40)
        b.set_margin_start(16)
        b.set_margin_end(16)
        a = Gtk.Label(label=title)
        a.get_style_context().add_class("enlace-host-name")
        c = Gtk.Label(label=sub, wrap=True, justify=Gtk.Justification.CENTER)
        c.get_style_context().add_class("enlace-sub")
        b.pack_start(a, False, False, 0)
        b.pack_start(c, False, False, 0)
        b.show_all()
        return b

    def _build_welcome(self):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        col.set_halign(Gtk.Align.CENTER)
        col.set_valign(Gtk.Align.START)
        col.set_margin_top(70)
        col.set_margin_bottom(40)
        col.set_size_request(560, -1)

        head = Gtk.Box(spacing=14)
        head.pack_start(Gtk.Image.new_from_pixbuf(
            GdkPixbuf.Pixbuf.new_from_file_at_size(os.path.join(HERE, "nexo.svg"), 52, 52)), False, False, 0)
        ht = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
        t = Gtk.Label(label="Nexo", xalign=0)
        t.get_style_context().add_class("nx-hero-title")
        ht.pack_start(t, False, False, 0)
        self.welcome_stats = Gtk.Label(xalign=0)
        self.welcome_stats.get_style_context().add_class("nx-muted")
        ht.pack_start(self.welcome_stats, False, False, 0)
        head.pack_start(ht, True, True, 0)
        col.pack_start(head, False, False, 0)

        self.quick = Gtk.SearchEntry(placeholder_text="Conectar a…  escribe un nombre o IP y presiona Enter")
        self.quick.get_style_context().add_class("nx-quick")
        self.quick.set_margin_top(28)
        self.quick.connect("search-changed", lambda *_: self.reload_welcome())
        self.quick.connect("activate", self._quick_activate)
        col.pack_start(self.quick, False, False, 0)

        self.recent_title = Gtk.Label(label="RECIENTES", xalign=0)
        self.recent_title.get_style_context().add_class("nx-section-label")
        self.recent_title.set_margin_top(22)
        self.recent_title.set_margin_bottom(6)
        col.pack_start(self.recent_title, False, False, 0)
        self.recent_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.recent_list.get_style_context().add_class("nx-recent")
        self.recent_list.connect("row-activated", lambda lb, row: self.app.connect_host(row.host))
        col.pack_start(self.recent_list, False, False, 0)
        self.recent_empty = Gtk.Label(label="Aún no te has conectado a ningún host.", xalign=0)
        self.recent_empty.get_style_context().add_class("nx-muted")
        self.recent_empty.set_no_show_all(True)
        col.pack_start(self.recent_empty, False, False, 0)

        acts = Gtk.Box(spacing=8)
        acts.set_margin_top(26)
        for icon, text, cb in (("plus", "Nuevo host", self.app.new_host),
                               ("org", "Conectar organización", self.app.add_org),
                               ("import", "Importar ~/.ssh/config", self.app.import_config),
                               ("terminal", "Terminal local", self.app.open_local)):
            b = Gtk.Button()
            bx = Gtk.Box(spacing=8)
            bx.pack_start(I.ui_image(icon, 14), False, False, 0)
            bx.pack_start(Gtk.Label(label=text), False, False, 0)
            b.add(bx)
            b.get_style_context().add_class("nx-chip")
            b.connect("clicked", lambda _b, f=cb: f())
            acts.pack_start(b, False, False, 0)
        col.pack_start(acts, False, False, 0)

        sc = Gtk.Label(xalign=0, wrap=True)
        sc.set_markup(
            "<span>Ctrl K</span> paleta  ·  <span>Ctrl F</span> filtrar  ·  <span>F9</span> panel  ·  "
            "<span>Ctrl Shift E / O</span> dividir  ·  arrastra una pestaña al borde de la terminal para ponerla al costado"
        )
        sc.get_style_context().add_class("nx-caption")
        sc.set_margin_top(30)
        col.pack_start(sc, False, False, 0)

        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.add(col)
        self.welcome_bg = AsciiBackdrop(self.app, focus=col)
        ov = Gtk.Overlay()
        ov.add(self.welcome_bg)
        ov.add_overlay(sw)
        outer = Gtk.EventBox()
        outer.add(ov)
        outer.get_style_context().add_class("nx-welcome")
        outer.drag_dest_set(Gtk.DestDefaults.ALL, [DRAG_HOST], Gdk.DragAction.COPY)
        outer.connect("drag-data-received", lambda w, ctx, x, y, data, info, t: self._welcome_drop(data))
        outer.show_all()
        outer.focus = lambda: self.quick.grab_focus()
        return outer

    def _match(self, h, q):
        hay = " ".join(str(h.get(k) or "") for k in ("name", "host", "user", "group", "notes")).lower()
        return all(part in hay for part in q.lower().split())

    def reload_welcome(self):
        if not hasattr(self, "recent_list"):
            return
        for c in self.recent_list.get_children():
            c.destroy()
        v = self.app.vault
        if not v.unlocked:
            return
        q = self.quick.get_text().strip()
        if q:
            hosts = [h for h in v.hosts if self._match(h, q)][:8]
            self.recent_title.set_text("RESULTADOS")
        else:
            hosts = sorted((h for h in v.hosts if h.get("last_used")), key=lambda h: -h["last_used"])[:6]
            self.recent_title.set_text("RECIENTES")
        for h in hosts:
            row = Gtk.ListBoxRow()
            row.host = h
            box = Gtk.Box(spacing=12)
            box.pack_start(I.image(I.host_icon(h), 20), False, False, 0)
            n = Gtk.Label(label=h["name"], xalign=0, ellipsize=Pango.EllipsizeMode.END)
            n.get_style_context().add_class("enlace-host-name")
            box.pack_start(n, False, True, 0)
            sub = Gtk.Label(label=conn.label(h), xalign=0, ellipsize=Pango.EllipsizeMode.END)
            sub.get_style_context().add_class("nx-mono-sub")
            box.pack_start(sub, True, True, 0)
            if h.get("last_used") and not q:
                ago = Gtk.Label(label=_ago(h["last_used"]))
                ago.get_style_context().add_class("nx-caption")
                box.pack_start(ago, False, False, 0)
            go = I.ui_image("play", 14)
            go.get_style_context().add_class("nx-row-actions")
            box.pack_start(go, False, False, 0)
            row.add(box)
            self.recent_list.add(row)
        self.recent_list.show_all()
        self.recent_list.set_visible(bool(hosts))
        self.recent_empty.set_visible(not hosts and not q)

    def _quick_activate(self, entry):
        rows = self.recent_list.get_children()
        if rows:
            self.app.connect_host(rows[0].host)
            entry.set_text("")

    def _welcome_drop(self, data):
        raw = data.get_data()
        h = self.app.vault.host(bytes(raw).decode()) if raw and self.app.vault.unlocked else None
        if h:
            GLib.idle_add(lambda: (self.app.connect_host(h), False)[1])

    # --- lista de hosts --------------------------------------------------
    def _filter(self, row):
        q = self.search.get_text().strip().lower()
        if not q:
            return True
        h = row.host
        hay = " ".join(str(h.get(k) or "") for k in ("name", "host", "user", "group", "notes")).lower()
        return all(part in hay for part in q.split())

    def _apply_search(self):
        q = self.search.get_text().strip()
        for sec in self.sections:
            sec.apply_search(q)

    def _search_activate(self, entry):
        for sec in self.sections:
            if sec.get_visible():
                rows = sec.visible_rows()
                if rows:
                    self.app.connect_host(rows[0].host)
                    return

    def reload_hosts(self):
        for c in self.groups_box.get_children():
            c.destroy()
        self.sections = []
        v = self.app.vault
        groups = list(v.group_list())
        groups.append({"name": "", "icon": "box", "collapsed": self.app.ui.get("ungrouped_collapsed", False)})
        for g in groups:
            hosts = [h for h in v.hosts if (h.get("group") or "") == g["name"]]
            if not g["name"] and not hosts:
                continue
            sec = GroupSection(self, g, hosts)
            self.sections.append(sec)
            self.groups_box.pack_start(sec, False, False, 0)
        for org in v.orgs:
            g = {"name": org["name"], "icon": "office", "org": org["id"],
                 "collapsed": self.app.ui.get("org_collapsed", {}).get(org["id"], False)}
            sec = GroupSection(self, g, v.org_hosts(org))
            self.sections.append(sec)
            self.groups_box.pack_start(sec, False, False, 0)
        self.hosts_empty.set_visible(not v.hosts and not v.group_list() and not v.orgs)
        self.reload_orgs()
        self._apply_search()
        self._update_subtitle()
        self.reload_welcome()

    def reload_orgs(self):
        for c in self.org_list.get_children():
            c.destroy()
        v = self.app.vault
        if not v.unlocked:
            return
        if not v.orgs:
            row = Gtk.ListBoxRow(activatable=False, selectable=False)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            box.set_border_width(18)
            img = I.ui_image("org", 34)
            img.get_style_context().add_class("nx-muted")
            box.pack_start(img, False, False, 4)
            t = Gtk.Label(label="Sin organizaciones")
            t.get_style_context().add_class("enlace-host-name")
            box.pack_start(t, False, False, 0)
            d = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=34)
            d.set_text("Si tu empresa usa Nexo Server, conéctate con tu usuario, contraseña y código 2FA. "
                       "Verás los servidores que te asignaron, sin recibir sus llaves.")
            d.get_style_context().add_class("nx-caption")
            box.pack_start(d, False, False, 0)
            b = Gtk.Button(label="Conectar a una organización")
            b.get_style_context().add_class("suggested-action")
            b.set_margin_top(6)
            b.connect("clicked", lambda *_: self.app.add_org())
            box.pack_start(b, False, False, 0)
            row.add(box)
            self.org_list.add(row)
            self.org_list.show_all()
            return
        for o in v.orgs:
            row = Gtk.ListBoxRow(activatable=False)
            box = Gtk.Box(spacing=10)
            box.set_border_width(8)
            box.pack_start(I.image("office", 22), False, False, 4)
            t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            n = Gtk.Label(label=o["name"], xalign=0, ellipsize=Pango.EllipsizeMode.END)
            n.get_style_context().add_class("enlace-host-name")
            t.pack_start(n, False, False, 0)
            sub = Gtk.Label(label=f"{o['username']} · {o['url'].split('://')[-1]}", xalign=0,
                            ellipsize=Pango.EllipsizeMode.END)
            sub.get_style_context().add_class("nx-mono-sub")
            t.pack_start(sub, False, False, 0)
            if o.get("expired") or not o.get("token"):
                st = Gtk.Label(label="sesión expirada — vuelve a ingresar", xalign=0)
                st.get_style_context().add_class("enlace-state-error")
            else:
                st = Gtk.Label(label=f"conectado · {len(o.get('hosts', []))} host(s)", xalign=0)
                st.get_style_context().add_class("enlace-state-activo")
            st.get_style_context().add_class("nx-caption")
            t.pack_start(st, False, False, 0)
            box.pack_start(t, True, True, 0)
            mb = Gtk.MenuButton(relief=Gtk.ReliefStyle.NONE, valign=Gtk.Align.CENTER)
            mb.get_style_context().add_class("nx-flat")
            mb.add(I.ui_image("more", 14))
            menu = Gtk.Menu()
            for text, cb in (("Ver sus hosts", lambda: self.app.show_panel("hosts")),
                             ("Actualizar", lambda: self.app.refresh_orgs(quiet=False)),
                             ("Volver a ingresar…", lambda oo=o: self.app.add_org(oo)),
                             (None, None),
                             ("Cerrar sesión", lambda oid=o["id"]: self.app.org_logout(oid)),
                             ("Quitar…", lambda oid=o["id"]: self.app.org_logout(oid, remove=True))):
                if text is None:
                    menu.append(Gtk.SeparatorMenuItem())
                    continue
                mi = Gtk.MenuItem(label=text)
                mi.connect("activate", lambda _m, f=cb: f())
                menu.append(mi)
            menu.show_all()
            mb.set_popup(menu)
            box.pack_start(mb, False, False, 0)
            row.add(box)
            self.org_list.add(row)
        self.org_list.show_all()

    def _host_row(self, h):
        row = Gtk.ListBoxRow()
        row.host = h
        box = Gtk.Box(spacing=10)
        icon = I.image(I.host_icon(h), 24)
        icon.set_margin_start(2)
        icon.set_margin_end(2)
        box.pack_start(icon, False, False, 0)
        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        top = Gtk.Box(spacing=6)
        n = Gtk.Label(label=h["name"], xalign=0, ellipsize=Pango.EllipsizeMode.END)
        n.get_style_context().add_class("enlace-host-name")
        top.pack_start(n, False, True, 0)
        if h["protocol"] != "ssh":
            badge = Gtk.Label(label="RDP" if h["protocol"] == "rdp" else DBC.SHORT.get(h["protocol"], h["protocol"]))
            badge.get_style_context().add_class("enlace-badge")
            badge.get_style_context().add_class("rdp" if h["protocol"] == "rdp" else "db")
            if (h.get("db") or {}).get("readonly"):
                badge.set_text(badge.get_text() + " · RO")
                badge.set_tooltip_text("Solo lectura")
            top.pack_start(badge, False, False, 0)
        txt.pack_start(top, False, False, 0)
        sub = conn.label(h) if not h.get("org") else f"vía {h['org_name']}"
        if h.get("jump"):
            j = self.app.vault.host(h["jump"])
            if j:
                sub += f"  ⤷ vía {j['name']}"
        s = Gtk.Label(label=sub, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        s.get_style_context().add_class("nx-mono-sub")
        txt.pack_start(s, False, False, 0)
        box.pack_start(txt, True, True, 0)
        actions = Gtk.Box(spacing=0)
        actions.get_style_context().add_class("nx-row-actions")

        def small(icon_name, tip, cb):
            b = Gtk.Button()
            b.add(I.ui_image(icon_name, 14))
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.set_tooltip_text(tip)
            b.set_valign(Gtk.Align.CENTER)
            b.get_style_context().add_class("nx-flat")
            b.connect("clicked", lambda *_: cb())
            return b

        perms = h.get("perms") or {"shell": True, "sftp": True}
        if h["protocol"] == "ssh" and perms.get("sftp"):
            actions.pack_start(small("sftp", "Abrir SFTP", lambda: self.app.open_sftp(row.host)), False, False, 0)
        if perms.get("shell", True):
            actions.pack_start(small("play", "Conectar", lambda: self.app.connect_host(row.host)), False, False, 0)

        mb = Gtk.MenuButton(relief=Gtk.ReliefStyle.NONE, valign=Gtk.Align.CENTER)
        mb.get_style_context().add_class("nx-flat")
        mb.add(I.ui_image("more", 14))
        menu = Gtk.Menu()
        items = []
        if h.get("org"):
            items = [("Abrir en panel a la derecha", lambda: self.app.split_with(row.host, Gtk.Orientation.HORIZONTAL)),
                     ("Abrir en panel abajo", lambda: self.app.split_with(row.host, Gtk.Orientation.VERTICAL)),
                     (None, None),
                     ("Copiar comando ssh", lambda: self.app.copy_text(
                         f"ssh -p {row.host['port']} {row.host['user']}@{row.host['host']}", "Comando copiado"))]
        elif h["protocol"] == "ssh":
            items += [("Abrir en panel a la derecha", lambda: self.app.split_with(row.host, Gtk.Orientation.HORIZONTAL)),
                      ("Abrir en panel abajo", lambda: self.app.split_with(row.host, Gtk.Orientation.VERTICAL)),
                      (None, None)]
        if not h.get("org"):
            items += [("Editar…", lambda: self.app.edit_host(row.host)),
                      ("Duplicar", lambda: self.app.duplicate_host(row.host))]
        if h["protocol"] == "ssh" and not h.get("org"):
            items.append(("Copiar comando ssh", lambda: self.app.copy_text(self.app.builder.command_text(row.host),
                                                                         "Comando copiado")))
        if not h.get("org"):
            items += [("Copiar IP / host", lambda: self.app.copy_text(row.host["host"], "Host copiado")),
                      (None, None),
                      ("Eliminar…", lambda: self.app.delete_host(row.host))]
        for text, cb in items:
            if text is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            mi = Gtk.MenuItem(label=text)
            mi.connect("activate", lambda _m, f=cb: f())
            menu.append(mi)
        menu.show_all()
        mb.set_popup(menu)
        actions.pack_start(mb, False, False, 0)
        box.pack_start(actions, False, False, 0)
        row.get_style_context().add_class("nx-host-row")
        if h.get("notes"):
            row.set_tooltip_text(h["notes"][:400])
        # Las filas de GtkListBox no tienen ventana propia: el EventBox recibe el clic
        # (arrastrar el host y menú con clic derecho).
        ev_box = Gtk.EventBox()
        ev_box.add(box)
        row.add(ev_box)
        ev_box.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [DRAG_HOST], Gdk.DragAction.COPY)
        ev_box.connect("drag-begin", lambda w, ctx: Gtk.drag_set_icon_name(
            ctx, "computer-symbolic" if h["protocol"] == "rdp" else "network-server-symbolic", 0, 0))
        ev_box.connect("drag-data-get",
                       lambda w, ctx, data, info, t: data.set(data.get_target(), 8, h["id"].encode()))

        def on_click(widget, ev):
            if ev.button == 3:
                row._menu = menu
                menu.popup_at_pointer(ev)
                return True
            return False

        ev_box.connect("button-press-event", on_click)
        return row

    def _update_subtitle(self):
        v = self.app.vault
        if not v.unlocked:
            return
        pages = [self.nb.get_nth_page(i) for i in range(1, self.nb.get_n_pages())]
        n_tabs = sum(len(p.panes) if isinstance(p, SplitTab) else 1 for p in pages)
        active = sum(1 for t in self.app.tunnels.values() if t.state == "activo")
        parts = [f"{len(v.hosts)} hosts"]
        if n_tabs:
            parts.append(f"{n_tabs} sesiones")
        if active:
            parts.append(f"{active} túneles activos")
        self.subtitle.set_text(" · ".join(parts[1:]))
        self.welcome_stats.set_text(f"{len(v.hosts)} hosts · {len(v.keys)} llaves · bóveda cifrada AES-256")

    # --- llaves ----------------------------------------------------------
    def reload_keys(self):
        for c in self.key_list.get_children():
            c.destroy()
        for k in sorted(self.app.vault.keys, key=lambda x: x["name"].lower()):
            row = Gtk.ListBoxRow(activatable=False)
            box = Gtk.Box(spacing=10)
            box.set_border_width(4)
            kimg = I.ui_image("keys", 18)
            kimg.get_style_context().add_class("bi-key")
            box.pack_start(kimg, False, False, 4)
            t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            n = Gtk.Label(label=k["name"], xalign=0, ellipsize=Pango.EllipsizeMode.END)
            n.get_style_context().add_class("enlace-host-name")
            uses = len(self.app.vault.hosts_using_key(k["id"]))
            s = Gtk.Label(label=f"{k['kind']} · {uses} host(s)", xalign=0)
            s.get_style_context().add_class("enlace-sub")
            f = Gtk.Label(label=k["fingerprint"], xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE, selectable=True)
            f.get_style_context().add_class("enlace-sub")
            for w in (n, s, f):
                t.pack_start(w, False, False, 0)
            box.pack_start(t, True, True, 0)
            cp = Gtk.Button()
            cp.add(I.ui_image("copy", 14))
            cp.set_relief(Gtk.ReliefStyle.NONE)
            cp.set_valign(Gtk.Align.CENTER)
            cp.set_tooltip_text("Copiar llave pública (para authorized_keys)")
            cp.connect("clicked", lambda _b, key=k: self.app.copy_text(key["public"], "Llave pública copiada"))
            box.pack_start(cp, False, False, 0)
            mb = Gtk.MenuButton(relief=Gtk.ReliefStyle.NONE, valign=Gtk.Align.CENTER)
            mb.add(I.ui_image("more", 14))
            menu = Gtk.Menu()
            for text, cb in (("Guardar pública como .pub…", lambda key=k: self.app.export_public(key)),
                             ("Renombrar…", lambda key=k: self.app.rename_key(key)),
                             ("Eliminar…", lambda key=k: self.app.delete_key(key))):
                mi = Gtk.MenuItem(label=text)
                mi.connect("activate", lambda _m, f=cb: f())
                menu.append(mi)
            menu.show_all()
            mb.set_popup(menu)
            box.pack_start(mb, False, False, 0)
            row.add(box)
            self.key_list.add(row)
        self.key_list.show_all()

    # --- túneles ---------------------------------------------------------
    def reload_tunnels(self):
        for c in self.tun_list.get_children():
            c.destroy()
        for h in sorted(self.app.vault.hosts, key=lambda x: x["name"].lower()):
            if h["protocol"] != "ssh" or not h.get("forwards"):
                continue
            hdr = Gtk.Label(label=h["name"].upper(), xalign=0)
            hdr.get_style_context().add_class("enlace-group")
            first = True
            for fw in h["forwards"]:
                tid = self.app.tunnel_id(h, fw)
                tun = self.app.tunnels.get(tid)
                row = Gtk.ListBoxRow(activatable=False)
                if first:
                    row.set_header(hdr)
                    first = False
                box = Gtk.Box(spacing=8)
                box.set_border_width(4)
                t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                t.pack_start(Gtk.Label(label=conn.forward_text(fw), xalign=0,
                                       ellipsize=Pango.EllipsizeMode.END), False, False, 0)
                state = tun.state if tun else "detenido"
                st = Gtk.Label(label=state + (f" — {tun.error}" if tun and state == "error" and tun.error else ""),
                               xalign=0, ellipsize=Pango.EllipsizeMode.END)
                st.get_style_context().add_class("enlace-sub")
                st.get_style_context().add_class(f"enlace-state-{state}")
                if tun and tun.error:
                    st.set_tooltip_text(tun.error)
                t.pack_start(st, False, False, 0)
                box.pack_start(t, True, True, 0)
                sw = Gtk.Switch(valign=Gtk.Align.CENTER)
                sw.set_active(bool(tun and tun.state in ("activo", "conectando")))
                sw.connect("state-set", lambda _s, on, host=h, f=fw: self.app.toggle_tunnel(host, f, on) or True)
                box.pack_start(sw, False, False, 0)
                row.add(box)
                self.tun_list.add(row)
        self.tun_list.show_all()
        self._update_subtitle()

    # --- pestañas --------------------------------------------------------
    def _tab_label(self, page, text, icon, closable=True):
        box = Gtk.Box(spacing=6)
        img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU)
        img.set_pixel_size(14)
        lbl = Gtk.Label(label=text, ellipsize=Pango.EllipsizeMode.END, max_width_chars=24,
                        width_chars=min(len(text), 24))
        box.pack_start(img, False, False, 0)
        box.pack_start(lbl, True, True, 0)
        if closable:
            b = Gtk.Button()
            b.add(I.ui_image("close", 10))
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.set_focus_on_click(False)
            b.get_style_context().add_class("nx-tab-close")
            b.connect("clicked", lambda *_: self.app.close_tab(page))
            box.pack_start(b, False, False, 0)
        ev = Gtk.EventBox()
        ev.add(box)
        def on_press(w, e):
            if e.button == 2 and page:
                self.app.close_tab(page)
                return True
            # recordar qué se veía antes de que el clic cambie de pestaña (para arrastrar)
            self._page_before_press = self.nb.get_nth_page(self.nb.get_current_page())
            return False

        ev.connect("button-press-event", on_press)
        ev.show_all()
        ev.lbl = lbl
        if page is not None:
            # arrastrar la pestaña: al borde de una terminal = dividir; sobre otra pestaña = reordenar
            ev.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [DRAG_TAB], Gdk.DragAction.MOVE)
            ev.connect("drag-begin", self._tab_drag_begin, icon, page)
            ev.connect("drag-data-get", lambda w, ctx, data, info, t: data.set(data.get_target(), 8,
                                                                                page.uid.encode()))
        # soltar sobre una pestaña (o pasar por encima: se abre tras un momento)
        ev.drag_dest_set(0, [DRAG_TAB, DRAG_PANE, DRAG_HOST], Gdk.DragAction.MOVE | Gdk.DragAction.COPY)
        ev.connect("drag-motion", self._tab_drag_motion, page)
        ev.connect("drag-leave", lambda *_: self._cancel_tab_hover())
        ev.connect("drag-drop", lambda w, ctx, x, y, t: (w.drag_get_data(ctx, w.drag_dest_find_target(ctx, None), t),
                                                         True)[1] if w.drag_dest_find_target(ctx, None) else False)
        ev.connect("drag-data-received", self._tab_drop, page)
        return ev

    def _tab_drag_begin(self, w, ctx, icon, page):
        Gtk.drag_set_icon_name(ctx, icon, 0, 0)
        prev = getattr(self, "_page_before_press", None)
        # volver a mostrar la terminal que se veía: ahí es donde se va a soltar
        if prev is not None and prev is not page and self.nb.page_num(prev) >= 0:
            GLib.idle_add(lambda: (self.nb.set_current_page(self.nb.page_num(prev)), False)[1])

    def _cancel_tab_hover(self):
        if getattr(self, "_hover_id", None):
            GLib.source_remove(self._hover_id)
            self._hover_id = None

    def _tab_drag_motion(self, w, ctx, x, y, time, page):
        target = w.drag_dest_find_target(ctx, None)
        if target is None:
            return False
        kind = target.name()
        Gdk.drag_status(ctx, Gdk.DragAction.COPY if kind.endswith("host") else Gdk.DragAction.MOVE, time)
        n = self.nb.page_num(page) if page is not None else 0
        if n != self.nb.get_current_page() and not getattr(self, "_hover_id", None):
            def switch():
                self._hover_id = None
                self.nb.set_current_page(n)
                return False
            self._hover_id = GLib.timeout_add(450, switch)
        return True

    def _tab_drop(self, w, ctx, x, y, data, info, time, page):
        self._cancel_tab_hover()
        raw = data.get_data()
        payload = bytes(raw).decode() if raw else ""
        GLib.idle_add(lambda: (self.app.drop_on_tab(info, payload, page), False)[1])
        Gtk.drag_finish(ctx, True, False, time)

    def add_tab(self, page, text, icon):
        lab = self._tab_label(page, text, icon)
        page.tab_label = lab
        if hasattr(page, "update_title"):
            page.update_title()
        page.uid = getattr(page, "uid", None) or f"t{id(page):x}"
        self.app.tab_registry[page.uid] = page
        n = self.nb.append_page(page, lab)
        self.nb.set_current_page(n)
        self._update_subtitle()

    def _focus_tab(self, page):
        if hasattr(page, "focus"):
            page.focus()
        return False

    # --- avisos ----------------------------------------------------------
    def toast(self, text, error=False):
        ctx = self.toast_lbl.get_style_context()
        (ctx.add_class if error else ctx.remove_class)("error")
        self.toast_lbl.set_text(text)
        self.toast_rev.show_all()
        self.toast_rev.set_reveal_child(True)
        if self._toast_id:
            GLib.source_remove(self._toast_id)
        self._toast_id = GLib.timeout_add(6000 if error else 3000, self._hide_toast)

    def _hide_toast(self):
        self.toast_rev.set_reveal_child(False)
        self._toast_id = None
        return False


class NexoApp(Gtk.Application):
    def __init__(self):
        # En el snap AppArmor no deja tomar el nombre D-Bus com.seguricloud.Nexo:
        # se ejecuta sin instancia única en lugar de fallar al iniciar.
        flags = Gio.ApplicationFlags.NON_UNIQUE if os.environ.get("SNAP") else Gio.ApplicationFlags.FLAGS_NONE
        super().__init__(application_id=APP_ID, flags=flags)
        self.vault = Vault()
        self.agent = None
        self.builder = None
        self.win = None
        self.tunnels = {}
        self.pane_registry = weakref.WeakValueDictionary()
        self.tab_registry = weakref.WeakValueDictionary()
        self.ui = T.load_ui()
        self.theme = T.get(self.ui.get("theme", T.DEFAULT), self.ui.get("accent"))
        self._css = None
        self.rdp_sessions = []

    @property
    def settings(self):
        return self.vault.data["settings"] if self.vault.unlocked else {}

    # --- ciclo de vida ---------------------------------------------------
    def do_startup(self):
        Gtk.Application.do_startup(self)
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
        self._load_css()
        self.agent = K.Agent()
        self.builder = conn.Builder(self.vault, self.agent)
        I.install()
        for name, cb, accels in (
            ("import-config", self.import_config, []),
            ("change-password", self.change_password, []),
            ("lock", self.lock, ["<Control>l"]),
            ("about", self.about, []),
            ("new-host", self.new_host, ["<Control>n"]),
            ("local", self.open_local, ["<Control><Shift>t"]),
            ("close-tab", self.close_current, ["<Control><Shift>w"]),
            ("search", self.focus_search, ["<Control>f"]),
            ("toggle-sidebar", lambda: self.win.b_side.set_active(not self.win.b_side.get_active()), ["F9"]),
            ("palette", self.open_palette, ["<Control>k"]),
            ("add-org", self.add_org, []),
            ("split-right", lambda: self.split_active(Gtk.Orientation.HORIZONTAL), []),
            ("split-down", lambda: self.split_active(Gtk.Orientation.VERTICAL), []),
            ("broadcast", lambda: self._with_split(lambda t: t.toggle_broadcast()), []),
        ):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda *_a, f=cb: f())
            self.add_action(a)
            if accels:
                self.set_accels_for_action(f"app.{name}", accels)
        a = Gio.SimpleAction.new("autolock", None)
        a.connect("activate", lambda *_: self.autolock_settings())
        self.add_action(a)
        a = Gio.SimpleAction.new("check-updates", None)
        a.connect("activate", lambda *_: self.check_updates(manual=True))
        self.add_action(a)
        a = Gio.SimpleAction.new_stateful("update-notify", None,
                                          GLib.Variant.new_boolean(self.ui.get("update_check", True)))
        a.connect("change-state", self._toggle_update_notify)
        self.add_action(a)
        a = Gio.SimpleAction.new_stateful("ascii-bg", None, GLib.Variant.new_boolean(self.ui.get("ascii_bg", True)))
        a.connect("change-state", self._toggle_ascii_bg)
        self.add_action(a)
        self._setup_autolock()
        self.update_info = None
        self.releases = None
        self.releases_at = 0.0
        self.releases_loading = False
        GLib.timeout_add_seconds(4, lambda: self.check_updates() and False)
        GLib.timeout_add_seconds(U.CHECK_EVERY_S, lambda: self.check_updates() or True)

    def _toggle_ascii_bg(self, action, value):
        action.set_state(value)
        self.ui["ascii_bg"] = value.get_boolean()
        try:
            T.save_ui(self.ui)
        except OSError:
            pass
        if self.win:
            for bg in (self.win.welcome_bg, self.win.lock_bg):
                bg.refresh()

    # --- actualizaciones -------------------------------------------------
    def _toggle_update_notify(self, action, value):
        action.set_state(value)
        self.ui["update_check"] = value.get_boolean()
        T.save_ui(self.ui)
        if not value.get_boolean() and self.win:
            self.win.b_update.hide()
        self.toast("Avisos de actualización " + ("activados" if value.get_boolean() else "desactivados"))

    def check_updates(self, manual=False):
        if not manual and not self.ui.get("update_check", True):
            return False

        def done(info, err):
            GLib.idle_add(lambda: self._on_update_info(info, err, manual) and False)
        U.check_async(done)
        return False

    def _on_update_info(self, info, err, manual):
        if err or not info or not info.get("version"):
            if manual:
                self.toast("No se pudo consultar si hay versiones nuevas (¿sin conexión?)", error=True)
            return False
        if not U.newer(info["version"]):
            if manual:
                self.toast(f"Estás al día: Nexo {__version__} es la última versión")
            return False
        self._mark_update(info)
        skipped = self.ui.get("update_skip") == info["version"]
        if self.win and (manual or not skipped):
            self.win.update_lbl.set_text(f"Actualización {info['version']}")
            self.win.b_update.set_tooltip_text(f"Hay una versión nueva de Nexo: {info['version']} (tienes {__version__})")
            self.win.b_update.show()
        if manual:
            self.show_update()
        return False

    def show_update(self, info=None):
        info = info or self.update_info
        if not info:
            return
        is_new = U.newer(info["version"])
        text, cmd, url = U.instructions(info)
        d = Gtk.Dialog(title="Actualización disponible" if is_new else f"Nexo {info['version']}",
                       transient_for=self.win, modal=True)
        d.set_default_size(520, -1)
        box = d.get_content_area()
        box.set_spacing(10)
        for m in ("start", "end", "top", "bottom"):
            getattr(box, f"set_margin_{m}")(18)
        t = Gtk.Label(xalign=0)
        t.set_markup(f"<b>Nexo {GLib.markup_escape_text(info['version'])}</b> "
                     + ("está disponible" if is_new else "es anterior a la tuya") + f" (tienes la {__version__}).")
        t.get_style_context().add_class("nx-dialog-title")
        box.pack_start(t, False, False, 0)
        notes = U.summary(info.get("notes", ""))
        if notes:
            nl = Gtk.Label(xalign=0, wrap=True, max_width_chars=60)
            nl.set_text("\n".join(f"•  {n}" for n in notes))
            nl.get_style_context().add_class("nx-muted")
            box.pack_start(nl, False, False, 0)
        il = Gtk.Label(label=text, xalign=0, wrap=True, max_width_chars=60)
        box.pack_start(il, False, False, 4)
        if cmd:
            row = Gtk.Box(spacing=6)
            e = Gtk.Entry(text=cmd, editable=False, hexpand=True)
            e.get_style_context().add_class("nx-mono")
            row.pack_start(e, True, True, 0)
            cb = Gtk.Button()
            cb.add(I.ui_image("copy", 14))
            cb.set_tooltip_text("Copiar comando")
            cb.connect("clicked", lambda *_: self.copy_text(cmd, "Comando copiado"))
            row.pack_start(cb, False, False, 0)
            box.pack_start(row, False, False, 0)
        if is_new:
            d.add_button("Omitir esta versión", 1)
        d.add_button("Ahora no" if is_new else "Cerrar", Gtk.ResponseType.CLOSE)
        d.add_button("Descargar" if U.install_kind() == "windows" else "Ver novedades", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        d.get_widget_for_response(Gtk.ResponseType.OK).get_style_context().add_class("suggested-action")
        d.show_all()
        r = d.run()
        d.destroy()
        if r == Gtk.ResponseType.OK:
            self.open_url(url)
        elif r == 1:
            self.ui["update_skip"] = info["version"]
            T.save_ui(self.ui)
            self.win.b_update.hide()

    def open_url(self, url):
        try:
            Gtk.show_uri_on_window(self.win, url, Gdk.CURRENT_TIME)
        except GLib.Error:
            self.copy_text(url, "No se pudo abrir el navegador: enlace copiado")

    # --- panel de versiones ------------------------------------------------
    RELEASES_TTL_S = 15 * 60

    def load_releases(self, manual=False):
        """Pide la lista a GitHub (en un hilo) si no la hay o ya es vieja."""
        fresh = self.releases is not None and time.monotonic() - self.releases_at < self.RELEASES_TTL_S
        if self.releases_loading or (fresh and not manual):
            return
        self.releases_loading = True
        if self.win:
            self.win.rel_status.set_text("Consultando GitHub…")

        def done(rels, err):
            GLib.idle_add(lambda: self._on_releases(rels, err, manual) and False)
        U.releases_async(done)

    def _on_releases(self, rels, err, manual):
        self.releases_loading = False
        if err or rels is None:
            if self.win:
                self.win.rel_status.set_text("No se pudo consultar GitHub (¿sin conexión?). "
                                             "Prueba de nuevo con ⟳.")
            if manual:
                self.toast("No se pudo consultar las versiones", error=True)
            return False
        self.releases, self.releases_at = rels, time.monotonic()
        newest = next((r for r in rels if not r["prerelease"]), None)
        if newest and U.newer(newest["version"]):
            self._mark_update(newest)
        self._fill_releases()
        if manual:
            self.toast("Versiones actualizadas")
        return False

    def _mark_update(self, info):
        self.update_info = info
        if not self.win:
            return
        ctx = self.win.rail_buttons["releases"].get_style_context()
        ctx.add_class("nx-rail-alert")
        self.win.rail_buttons["releases"].set_tooltip_text(
            f"Versiones y actualizaciones — hay una nueva: {info['version']}")

    def _fill_releases(self):
        w = self.win
        if not w:
            return
        for child in w.rel_list.get_children():
            w.rel_list.remove(child)
        kinds = {"snap": "snap (App Center)", "deb": "paquete .deb", "windows": "Windows (WSL)",
                 "source": "código fuente"}
        newer = [r for r in self.releases if U.newer(r["version"]) and not r["prerelease"]]
        state = (f"Hay {len(newer)} versión nueva" + ("s" if len(newer) > 1 else "") if newer
                 else "Estás al día")
        w.rel_status.set_text(f"Tienes la {__version__} · {kinds.get(U.install_kind(), '')}.  {state}.")
        if not self.releases:
            w.rel_list.set_placeholder(self._empty_releases())
        for r in self.releases:
            w.rel_list.add(self._release_row(r))
        w.rel_list.show_all()

    def _empty_releases(self):
        return self.win._empty("Sin versiones publicadas", "Todavía no hay versiones en GitHub")

    def _release_row(self, r):
        v = r["version"]
        cmp = (U.parse(v) > U.parse(__version__)) - (U.parse(v) < U.parse(__version__))
        row = Gtk.ListBoxRow(activatable=False)
        row.get_style_context().add_class("nx-release")
        if cmp > 0:
            row.get_style_context().add_class("is-new")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        top = Gtk.Box(spacing=8)
        name = Gtk.Label(xalign=0)
        name.set_markup(f"<b>Nexo {GLib.markup_escape_text(v)}</b>")
        top.pack_start(name, False, False, 0)
        tag_text, tag_cls = (("Nueva", "new") if cmp > 0 else ("Instalada", "current") if cmp == 0
                             else ("Anterior", "old"))
        if r["prerelease"]:
            tag_text, tag_cls = "Pre-release", "pre"
        tag = Gtk.Label(label=tag_text)
        tag.get_style_context().add_class("nx-tag")
        tag.get_style_context().add_class(f"nx-tag-{tag_cls}")
        top.pack_start(tag, False, False, 0)
        date = Gtk.Label(label=U.nice_date(r["date"]), xalign=1)
        date.get_style_context().add_class("nx-caption")
        top.pack_end(date, False, False, 0)
        box.pack_start(top, False, False, 0)

        notes = U.summary(r.get("notes", ""), limit=5 if cmp > 0 else 3)
        if notes:
            nl = Gtk.Label(xalign=0, wrap=True, max_width_chars=34)
            nl.set_text("\n".join(f"•  {n}" for n in notes))
            nl.get_style_context().add_class("nx-release-notes")
            box.pack_start(nl, False, False, 0)

        acts = Gtk.Box(spacing=6)
        acts.set_margin_top(4)
        if cmp != 0:
            b = Gtk.Button(label="Actualizar" if cmp > 0 else "Volver a esta")
            b.get_style_context().add_class("nx-chip")
            if cmp > 0:
                b.get_style_context().add_class("suggested-action")
            b.connect("clicked", lambda *_: self.show_update(r))
            acts.pack_start(b, False, False, 0)
        if U.install_kind() != "snap":
            for lbl, url in U.downloads(r):
                d = Gtk.Button()
                db = Gtk.Box(spacing=5)
                db.pack_start(I.ui_image("download", 12), False, False, 0)
                db.pack_start(Gtk.Label(label=lbl), False, False, 0)
                d.add(db)
                d.set_tooltip_text(f"Descargar {url.rsplit('/', 1)[-1]}")
                d.get_style_context().add_class("nx-chip")
                d.connect("clicked", lambda *_a, u=url: self.open_url(u))
                acts.pack_start(d, False, False, 0)
        gh = Gtk.Button()
        gh.add(I.ui_image("github", 13))
        gh.set_tooltip_text("Ver esta versión en GitHub")
        gh.get_style_context().add_class("nx-flat")
        gh.connect("clicked", lambda *_: self.open_url(r["url"]))
        acts.pack_end(gh, False, False, 0)
        box.pack_start(acts, False, False, 0)
        row.add(box)
        return row

    # --- autobloqueo -----------------------------------------------------
    AUTOLOCK_DEFAULT_MIN = 15
    ACTIVITY_EVENTS = {
        Gdk.EventType.KEY_PRESS, Gdk.EventType.BUTTON_PRESS, Gdk.EventType.SCROLL,
        Gdk.EventType.MOTION_NOTIFY, Gdk.EventType.TOUCH_BEGIN,
    }

    def _setup_autolock(self):
        self.last_activity = GLib.get_monotonic_time()
        self._warned = False

        # Toda interacción con cualquier ventana de la app pasa por aquí.
        def handler(event):
            if event.type in self.ACTIVITY_EVENTS:
                self.last_activity = GLib.get_monotonic_time()
            Gtk.main_do_event(event)

        Gdk.event_handler_set(handler)
        GLib.timeout_add_seconds(5, self._autolock_tick)

        # Bloqueo de pantalla del escritorio y suspensión del equipo.
        def on_signal(conn_, sender, path, iface, signal, params, *_):
            active = params.unpack()[0]
            if active and self.settings.get("lock_on_screen", True):
                GLib.idle_add(lambda: self.lock(reason="pantalla bloqueada") and False)

        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            for iface, path in (("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver"),
                                ("org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver")):
                bus.signal_subscribe(None, iface, "ActiveChanged", path, None,
                                     Gio.DBusSignalFlags.NONE, on_signal)
        except GLib.Error:
            pass
        try:
            sysbus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            sysbus.signal_subscribe("org.freedesktop.login1", "org.freedesktop.login1.Manager",
                                    "PrepareForSleep", "/org/freedesktop/login1", None,
                                    Gio.DBusSignalFlags.NONE, on_signal)
        except GLib.Error:
            pass

    def autolock_minutes(self):
        return int(self.settings.get("autolock_min", self.AUTOLOCK_DEFAULT_MIN))

    def _autolock_tick(self):
        if not self.vault.unlocked or not self.win:
            return True
        minutes = self.autolock_minutes()
        if minutes <= 0:
            return True
        idle = (GLib.get_monotonic_time() - self.last_activity) / 1e6
        left = minutes * 60 - idle
        if left <= 0:
            self.lock(reason=f"{minutes} min sin actividad")
        elif left <= 30 and not self._warned:
            self._warned = True
            self.toast("Nexo se bloqueará en 30 s por inactividad (mueve el ratón para seguir)", error=True)
        elif left > 30:
            self._warned = False
        return True

    def autolock_settings(self):
        res = D.autolock_dialog(self.win, self.autolock_minutes(), self.settings.get("lock_on_screen", True))
        if res is None:
            return
        minutes, on_screen = res
        self.vault.data["settings"]["autolock_min"] = minutes
        self.vault.data["settings"]["lock_on_screen"] = on_screen
        self.vault.save()
        self.last_activity = GLib.get_monotonic_time()
        self.toast("Autobloqueo desactivado" if minutes == 0 else f"Autobloqueo: {minutes} min sin actividad")

    def do_activate(self):
        if not self.win:
            self.win = Window(self)
            self.win.connect("delete-event", self._on_close)
        self.win.show_all()
        self.win.toast_rev.set_reveal_child(False)
        if self.vault.unlocked:
            self.win.show_main()
        else:
            self.win.show_lock()
        self.win.present()

    def _on_close(self, *_):
        live = [p for p in self._pages() if getattr(p, "alive", False)]
        running = [t for t in self.tunnels.values() if t.running]
        if live or running:
            parts = []
            if live:
                parts.append(f"{len(live)} sesión(es) abierta(s)")
            if running:
                parts.append(f"{len(running)} túnel(es) activo(s)")
            if not D.confirm(self.win, "¿Cerrar Nexo?", " y ".join(parts) + " se cerrarán.", ok="Cerrar"):
                return True
        return False

    def do_shutdown(self):
        for p in self._pages():
            p.close()
        for t in self.tunnels.values():
            t.stop()
        for r in self.rdp_sessions:
            r.stop()
        if self.agent:
            self.agent.close()
        Gtk.Application.do_shutdown(self)

    def on_unlocked(self):
        GLib.idle_add(lambda: (self.win.sync_rail(), False)[1])
        GLib.timeout_add(600, lambda: (self.refresh_orgs(), False)[1])
        self.last_activity = GLib.get_monotonic_time()
        self.win.reload_hosts()
        self.win.reload_keys()
        self.win.reload_tunnels()
        self.win.show_main()
        GLib.idle_add(lambda: (self.win.quick.grab_focus(), False)[1])

    def lock(self, reason=None):
        if not self.vault.unlocked:
            return
        # cerrar diálogos abiertos (editar host, etc.) como «Cancelar» antes de borrar los datos
        for w in Gtk.Window.list_toplevels():
            if isinstance(w, Gtk.Dialog) and w.get_visible():
                w.response(Gtk.ResponseType.CANCEL)
        self.vault.lock()
        self.agent.clear()
        for lst in (self.win.groups_box, self.win.key_list, self.win.tun_list):
            for c in lst.get_children():
                c.destroy()
        self.win.show_lock()
        if reason:
            self.win.lock_err.set_text("")
            self.win.lock_msg.set_text(f"Bóveda bloqueada automáticamente ({reason}).\n"
                                       "Tus sesiones y túneles siguen abiertos.")

    def _pages(self):
        if not self.win:
            return []
        return [self.win.nb.get_nth_page(i) for i in range(1, self.win.nb.get_n_pages())]

    # --- utilidades ------------------------------------------------------
    def toast(self, text, error=False):
        self.win.toast(text, error)

    def copy_text(self, text, note="Copiado"):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
        self.toast(note)

    def focus_search(self):
        if self.vault.unlocked:
            if not self.win.b_side.get_active():
                self.win.b_side.set_active(True)
            self.win.side_stack.set_visible_child_name("hosts")
            self.win.search.grab_focus()

    def save_ui(self):
        try:
            T.save_ui(self.ui)
        except OSError:
            pass

    def set_sidebar(self, visible):
        self.win.side.set_visible(visible)
        self.ui["sidebar"] = visible
        self.save_ui()
        self.win.sync_rail()
        if not visible:
            page = self.win.nb.get_nth_page(self.win.nb.get_current_page())
            if hasattr(page, "focus"):
                page.focus()

    def _save_all(self):
        self.win.reload_hosts()
        self.win.reload_keys()
        self.win.reload_tunnels()

    # --- hosts -----------------------------------------------------------
    def new_host(self, group=None):
        if not self.vault.unlocked:
            return
        h = D.HostDialog(self, group=group).run_and_get()
        if h:
            self.vault.upsert_host(h)
            self._save_all()
            self.toast(f"Host «{h['name']}» guardado")

    # --- organizaciones (Nexo Server) -------------------------------------
    def add_org(self, org=None):
        if not self.vault.unlocked:
            return
        vals = D.org_login_dialog(self.win, org["url"] if org else "", org["username"] if org else "",
                                  title=f"Volver a ingresar a {org['name']}" if org else "Conectar a una organización")
        if not vals:
            return
        from . import orgclient
        self.toast("Conectando con el servidor de la organización…")

        def work():
            try:
                info = orgclient.login(vals["url"], vals["username"], vals["password"], vals["totp"])
                info["hosts"] = orgclient.hosts(info)
                return info, None
            except orgclient.OrgError as e:
                return None, str(e)

        def done(res):
            info, err = res
            if err:
                D.msg(self.win, "No se pudo ingresar a la organización", err)
                return
            existing = next((o for o in self.vault.orgs if o["url"] == info["url"]
                             and o["username"].lower() == info["username"].lower()), None)
            if existing:
                info["id"] = existing["id"]
            info["updated"] = time.time()
            self.vault.upsert_org(info)
            self.win.reload_hosts()
            self.toast(f"{info['name']}: {len(info['hosts'])} host(s) disponibles")

        self._bg(work, done)

    def _bg(self, work, done):
        import threading

        def run():
            res = work()
            GLib.idle_add(lambda: (done(res), False)[1])

        threading.Thread(target=run, daemon=True).start()

    def refresh_orgs(self, quiet=True):
        if not self.vault.unlocked or not self.vault.orgs:
            return
        from . import orgclient
        orgs = [dict(o) for o in self.vault.orgs]

        def work():
            out = []
            for o in orgs:
                try:
                    out.append((o["id"], orgclient.hosts(o), None))
                except orgclient.OrgExpired:
                    out.append((o["id"], None, "expirada"))
                except orgclient.OrgError as e:
                    out.append((o["id"], None, str(e)))
            return out

        def done(results):
            if not self.vault.unlocked:
                return
            for oid, hosts, err in results:
                o = self.vault.org(oid)
                if not o:
                    continue
                if hosts is not None:
                    o["hosts"], o["updated"], o["expired"] = hosts, time.time(), False
                elif err == "expirada":
                    o["expired"], o["hosts"] = True, []
                    self.toast(f"Tu sesión en {o['name']} expiró o fue revocada", error=True)
                elif not quiet:
                    self.toast(f"{o['name']}: {err}", error=True)
            self.vault.save()
            self.win.reload_hosts()

        self._bg(work, done)

    def org_logout(self, org_id, remove=False):
        o = self.vault.org(org_id)
        if not o:
            return
        if remove and not D.confirm(self.win, f"¿Quitar la organización «{o['name']}»?",
                                    "Se borra de este equipo; tu cuenta en el servidor sigue igual."):
            return
        from . import orgclient
        self._bg(lambda: orgclient.logout(o), lambda _r: None)
        if remove:
            self.vault.delete_org(org_id)
        else:
            o["token"], o["hosts"], o["expired"] = "", [], True
            self.vault.save()
        self.win.reload_hosts()

    # --- grupos ------------------------------------------------------------
    def new_group(self):
        if not self.vault.unlocked:
            return
        res = D.group_dialog(self.win)
        if res:
            try:
                self.vault.add_group(*res)
            except VaultError as e:
                D.msg(self.win, str(e))
                return
            self.win.reload_hosts()
            self.toast(f"Grupo «{res[0]}» creado — arrastra hosts a su encabezado")

    def edit_group(self, name):
        g = self.vault.group(name)
        if not g:
            return
        res = D.group_dialog(self.win, g["name"], g.get("icon", "folder"), title="Editar grupo")
        if res:
            try:
                self.vault.update_group(name, *res)
            except VaultError as e:
                D.msg(self.win, str(e))
                return
            self._save_all()

    def delete_group(self, name):
        n = sum(1 for h in self.vault.hosts if (h.get("group") or "") == name)
        extra = f"Sus {n} host(s) pasan a «Sin grupo»; no se borran." if n else "El grupo está vacío."
        if D.confirm(self.win, f"¿Eliminar el grupo «{name}»?", extra):
            self.vault.delete_group(name)
            self._save_all()

    def move_group(self, name, delta):
        self.vault.move_group(name, delta)
        self.win.reload_hosts()

    def move_host_to_group(self, host_id, name):
        h = self.vault.host(host_id)
        if h and self.vault.set_host_group(host_id, name):
            self.win.reload_hosts()
            self.toast(f"«{h['name']}» movido a {name or 'Sin grupo'}")

    def connect_group(self, name):
        hosts = sorted((h for h in self.vault.hosts if (h.get("group") or "") == name and h["protocol"] == "ssh"),
                       key=lambda h: h["name"].lower())
        if not hosts:
            self.toast("Este grupo no tiene hosts SSH")
            return
        if len(hosts) > SplitTab.MAX_PANES:
            self.toast(f"Se abren los primeros {SplitTab.MAX_PANES} hosts", error=True)
            hosts = hosts[:SplitTab.MAX_PANES]
        first = hosts[0]
        tab = SplitTab(self, self.make_pane(first))
        g = self.vault.group(name) if name else None
        tab.custom_title = name or "Sin grupo"
        self.win.add_tab(tab, tab.custom_title, I.icon_name(g.get("icon") if g else "box", "folder"))
        for h in hosts[1:]:
            tab._adopt(self.make_pane(h))
        cols = math.ceil(math.sqrt(len(hosts)))
        tab.grid(math.ceil(len(hosts) / cols), cols, fill=False)

    def edit_host(self, host):
        h = D.HostDialog(self, self.vault.host(host["id"])).run_and_get()
        if h:
            self.vault.upsert_host(h)
            self._save_all()
            self.toast(f"Host «{h['name']}» actualizado")

    def duplicate_host(self, host):
        h = json.loads(json.dumps(self.vault.host(host["id"])))
        h["id"] = None
        h["name"] += " (copia)"
        self.vault.upsert_host(h)
        self._save_all()
        self.edit_host(h)

    def delete_host(self, host):
        if D.confirm(self.win, f"¿Eliminar el host «{host['name']}»?",
                     "Se borra de la bóveda junto con su contraseña y túneles guardados."):
            for fw in host.get("forwards") or []:
                t = self.tunnels.pop(self.tunnel_id(host, fw), None)
                if t:
                    t.stop()
            self.vault.delete_host(host["id"])
            self._save_all()

    def _touch(self, host):
        """Marca el host como usado recién (lista de recientes)."""
        h = self.vault.host(host["id"])
        if h is not None and not h.get("org"):
            h["last_used"] = time.time()
            try:
                self.vault.save()
            except Exception:  # noqa: BLE001
                pass
            self.win.reload_welcome()

    def show_panel(self, page):
        """Clic en el riel: abre ese panel; si ya estaba abierto, lo oculta."""
        if not self.vault.unlocked:
            return
        w = self.win
        if w.side.get_visible() and w.side_stack.get_visible_child_name() == page:
            w.b_side.set_active(False)
        else:
            w.side_stack.set_visible_child_name(page)
            if not w.b_side.get_active():
                w.b_side.set_active(True)
            if page == "releases":
                self.load_releases()
        w.sync_rail()

    def open_palette(self):
        if not self.vault.unlocked:
            return
        from .palette import CommandPalette
        CommandPalette(self)

    def connect_host(self, host):
        host = self.vault.host(host["id"]) or host
        self._touch(host)
        if DBC.is_db(host["protocol"]):
            self.open_db(host)
        elif host["protocol"] == "rdp":
            self.open_rdp(host)
        else:
            self.open_ssh(host)

    def open_ssh(self, host, cwd=None):
        hid = host["id"]

        def factory():
            h = self.vault.host(hid)
            if not h:
                raise conn.ConnError(self._missing_host_msg(hid))
            if cwd:
                return self.builder.ssh(h, extra=["-t"], remote=f"cd {shlex.quote(cwd)} && exec \"$SHELL\" -l")
            return self.builder.ssh(h)

        pane = TerminalPane(self, host["name"], factory, host=host)
        self.win.add_tab(SplitTab(self, pane), host["name"], I.icon_name(I.host_icon(host)))

    def open_local(self):
        if not self.vault.unlocked:
            return
        self.win.add_tab(SplitTab(self, self.make_pane(None)), "Local", I.ui_name("terminal"))

    def pane_target(self, host):
        """(fábrica de argv, título) para un panel: host SSH o terminal local (None)."""
        if host is None:
            if os.environ.get("SNAP"):
                return (lambda: (self._snap_local_shell(), {})), "Local"
            shell = os.environ.get("SHELL") or shutil.which("bash") or "/bin/sh"
            return (lambda: ([shell, "-l"], {})), "Local"
        hid = host["id"]

        def factory():
            h = self.vault.host(hid)
            if not h:
                raise conn.ConnError(self._missing_host_msg(hid))
            return self.builder.ssh(h)

        return factory, host["name"]

    @staticmethod
    def _snap_local_shell():
        """En el snap la terminal local está aislada: no puede leer /etc/profile.d ni el
        ~/.bashrc real. Arranca bash sin perfiles, con un prompt propio y un aviso."""
        rc = os.path.join(os.environ.get("SNAP_USER_DATA") or os.path.expanduser("~"), "nexo-local.bashrc")
        with open(rc, "w", encoding="utf-8") as f:
            f.write(
                'PS1=\'\\[\\e[1;32m\\]\\u@\\h\\[\\e[0m\\]:\\[\\e[1;34m\\]\\w\\[\\e[0m\\]\\$ \'\n'
                "alias ls='ls --color=auto' grep='grep --color=auto'\n"
                "cd \"${SNAP_REAL_HOME:-$HOME}\" 2>/dev/null\n"
                "printf '\\e[2mTerminal local aislada (Nexo instalado como snap). "
                "Para administrar este equipo usa la terminal del sistema.\\e[0m\\n'\n"
            )
        return ["/bin/bash", "--noprofile", "--rcfile", rc, "-i"]

    # --- tema --------------------------------------------------------------
    def _load_css(self):
        screen = Gdk.Screen.get_default()
        if self._css is not None:
            Gtk.StyleContext.remove_provider_for_screen(screen, self._css)
        self._css = Gtk.CssProvider()
        self._css.load_from_data(T.build_css(self.theme))
        Gtk.StyleContext.add_provider_for_screen(screen, self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)

    def apply_theme(self, theme_id, accent=None):
        accent = accent or self.theme.get("accent_id", "tema")
        if theme_id == self.theme["id"] and accent == self.theme.get("accent_id"):
            return
        self.theme = T.get(theme_id, accent)
        self.ui["theme"] = self.theme["id"]
        self.ui["accent"] = self.theme["accent_id"]
        try:
            T.save_ui(self.ui)
        except OSError:
            pass
        self._load_css()
        for p in self._pages():
            if isinstance(p, SplitTab):
                p.apply_theme(self.theme)
        if self.win:
            for card in getattr(self.win, "theme_cards", []):
                card.set_selected(card.t["id"] == self.theme["id"])
            base_acc = T.THEMES[self.theme["id"]][3]
            for dot in getattr(self.win, "accent_dots", []):
                dot.set_selected(dot.accent_id == self.theme["accent_id"], base_acc)
        self.toast(f"Tema: {self.theme['name']}")

    # --- cuadrícula ----------------------------------------------------------
    def apply_grid(self, rows, cols):
        if not self.vault.unlocked:
            return
        t = self.current_split()
        if t is None:
            self.open_local()
            t = self.current_split()
        t.grid(rows, cols)

    # --- arrastrar pestañas -------------------------------------------------
    def merge_tab_into(self, uid, target_pane, zone):
        """Pestaña `uid` soltada en el borde `zone` de un panel: se pega ahí (pantalla dividida)."""
        from .terminal import ZONES
        src = self.tab_registry.get(uid)
        dst = target_pane.owner
        if src is None or dst is None or src is dst:
            return
        if not isinstance(src, SplitTab):
            self.toast("Solo las pestañas de terminal se pueden poner al costado", error=True)
            return
        if len(dst.panes) + len(src.panes) > SplitTab.MAX_PANES:
            self.toast(f"Máximo {SplitTab.MAX_PANES} paneles por pestaña", error=True)
            return
        orient, before = ZONES[zone]
        dst.absorb(src, target_pane, orient, before)
        self.win.nb.set_current_page(self.win.nb.page_num(dst))

    def drop_on_tab(self, info, payload, page):
        """Algo soltado sobre la etiqueta de una pestaña."""
        nb = self.win.nb
        if info == 4:  # otra pestaña: reordenar
            src = self.tab_registry.get(payload)
            if src is not None and src is not page:
                nb.reorder_child(src, max(1, nb.page_num(page)) if page is not None else 1)
        elif info == 2:  # un panel: moverlo a esa pestaña
            pane = self.pane_registry.get(payload)
            if pane is None or page is None or pane.owner is page:
                return
            if isinstance(page, SplitTab):
                pane.owner.detach(pane)
                page.insert(pane, page.active or page.panes[-1], Gtk.Orientation.HORIZONTAL, False)
                nb.set_current_page(nb.page_num(page))
        elif info == 1:  # un host
            h = self.vault.host(payload) if self.vault.unlocked else None
            if h and isinstance(page, SplitTab) and h["protocol"] == "ssh":
                nb.set_current_page(nb.page_num(page))
                page.split(page.active, Gtk.Orientation.HORIZONTAL, target=h)
            elif h:
                self.connect_host(h)

    def pane_to_new_tab(self, pane):
        owner = pane.owner
        if owner is None or len(owner.panes) < 2:
            return
        owner.detach(pane)
        tab = SplitTab(self, pane)
        self.win.add_tab(tab, pane.title, I.icon_name(I.host_icon(pane.host)) if pane.host
                         else "utilities-terminal-symbolic")
        pane.show_header(False)

    def discard_tab(self, tab):
        """Quita una pestaña que se quedó sin paneles (se movieron a otra), sin cerrar sesiones."""
        n = self.win.nb.page_num(tab)
        if n >= 0:
            self.win.nb.remove_page(n)
        tab.destroy()

    def _missing_host_msg(self, hid):
        if isinstance(hid, str) and hid.startswith("org:"):
            o = self.vault.org(hid.split(":")[1]) if self.vault.unlocked else None
            if o is not None and o.get("expired"):
                return (f"Tu acceso a «{o['name']}» fue revocado o tu sesión expiró. "
                        "Si fue un error, vuelve a ingresar o consulta a tu administrador.")
            return "Tu organización ya no te da acceso a este host."
        return "La bóveda está bloqueada o el host ya no existe"

    def make_pane(self, host):
        factory, title = self.pane_target(host)
        return TerminalPane(self, title, factory, host=host)

    def current_split(self):
        page = self.win.nb.get_nth_page(self.win.nb.get_current_page())
        return page if isinstance(page, SplitTab) else None

    def _with_split(self, fn):
        if not self.vault.unlocked:
            return
        t = self.current_split()
        if t is None:
            self.toast("Abre primero una terminal (doble clic en un host)")
            return
        fn(t)

    def split_active(self, orientation):
        self._with_split(lambda t: t.split(t.active, orientation))

    def split_with(self, host, orientation):
        t = self.current_split()
        if t is None:
            self.open_ssh(host)
            return
        t.split(t.active, orientation, target=self.vault.host(host["id"]) or host)

    def open_db(self, host):
        from .dbtab import DbTab
        tab = DbTab(self, host)
        self.win.add_tab(tab, host["name"], I.icon_name(I.host_icon(host)))

    def open_sftp(self, host):
        host = self.vault.host(host["id"]) or host
        self._touch(host)
        tab = SftpTab(self, host)
        self.win.add_tab(tab, f"{host['name']} · SFTP", I.ui_name("sftp"))

    def open_rdp(self, host):
        def on_exit(sess, err):
            GLib.idle_add(self._rdp_done, sess, err)

        sess = conn.RdpSession(self.builder, host, on_exit)
        try:
            sess.start()
        except conn.ConnError as e:
            D.msg(self.win, "No se pudo abrir RDP", str(e))
            return
        self.rdp_sessions.append(sess)
        self.toast(f"Abriendo escritorio remoto de {host['name']}…")

    def _rdp_done(self, sess, err):
        if sess in self.rdp_sessions:
            self.rdp_sessions.remove(sess)
        if err:
            D.msg(self.win, f"RDP {sess.host['name']}: la conexión falló", err)
        return False

    def close_tab(self, page):
        if page is None:
            return
        if isinstance(page, SplitTab) and page.has_remote():
            n = sum(1 for p in page.panes if p.alive and p.host)
            what = f"la sesión con {page.title}" if n == 1 else f"las {n} sesiones de esta pestaña"
            if not D.confirm(self.win, f"¿Cerrar {what}?", ok="Cerrar", destructive=False):
                return
        page.close()
        n = self.win.nb.page_num(page)
        if n >= 0:
            self.win.nb.remove_page(n)
        page.destroy()

    def close_current(self):
        n = self.win.nb.get_current_page()
        if n > 0:
            page = self.win.nb.get_nth_page(n)
            if isinstance(page, SplitTab) and len(page.panes) > 1:
                page.close_pane(page.active)
            else:
                self.close_tab(page)

    def tab_state_changed(self, page):
        page = getattr(page, "owner", None) or page
        lab = getattr(page, "tab_label", None)
        if lab:
            ctx = lab.lbl.get_style_context()
            (ctx.remove_class if page.alive else ctx.add_class)("enlace-dead")
        self.win._update_subtitle()


    # --- túneles ---------------------------------------------------------
    @staticmethod
    def tunnel_id(host, fw):
        return host["id"] + ":" + json.dumps(fw, sort_keys=True)

    def toggle_tunnel(self, host, fw, on):
        tid = self.tunnel_id(host, fw)
        tun = self.tunnels.get(tid)
        if on:
            if tun and tun.running:
                return
            tun = conn.Tunnel(self.builder, self.vault.host(host["id"]) or host, [fw],
                              on_change=lambda t: GLib.idle_add(self._tunnel_changed, t))
            self.tunnels[tid] = tun
            try:
                tun.start()
            except Exception as e:  # noqa: BLE001
                tun.error = str(e)
                tun.state = "error"
                self.toast(str(e), error=True)
        elif tun:
            tun.stop()
        GLib.idle_add(lambda: self.win.reload_tunnels() and False)

    def _tunnel_changed(self, tun):
        if tun.state == "error":
            self.toast(f"Túnel {tun.host['name']}: {tun.error}", error=True)
        elif tun.state == "activo":
            self.toast(f"Túnel activo: {conn.forward_text(tun.forwards[0])}")
        if self.vault.unlocked:
            self.win.reload_tunnels()
        return False

    # --- llaves ----------------------------------------------------------
    def generate_key(self):
        res = D.generate_key_dialog(self.win)
        if not res:
            return
        rec = K.generate(*res)
        self.vault.upsert_key(rec)
        self.win.reload_keys()
        self.copy_text(rec["public"], "Llave generada; la pública quedó copiada al portapapeles")

    def import_key(self):
        rec = D.import_key_dialog(self.win)
        if rec:
            self._add_key(rec)

    def _add_key(self, rec):
        for k in self.vault.keys:
            if k["fingerprint"] == rec["fingerprint"]:
                self.toast(f"Esa llave ya está en la bóveda como «{k['name']}»")
                return k
        self.vault.upsert_key(rec)
        self.win.reload_keys()
        self.toast(f"Llave «{rec['name']}» importada")
        return rec

    def export_public(self, key):
        d = Gtk.FileChooserNative.new("Guardar llave pública", self.win, Gtk.FileChooserAction.SAVE, None, None)
        d.set_current_name(key["name"] + ".pub")
        d.set_do_overwrite_confirmation(True)
        if d.run() == Gtk.ResponseType.ACCEPT:
            with open(d.get_filename(), "w") as f:
                f.write(key["public"] + "\n")
            self.toast("Llave pública guardada")
        d.destroy()

    def rename_key(self, key):
        name = D.ask_text(self.win, "Renombrar llave", "Nuevo nombre:", key["name"])
        if name and name.strip():
            key["name"] = name.strip()
            self.vault.upsert_key(key)
            self._save_all()

    def delete_key(self, key):
        users = self.vault.hosts_using_key(key["id"])
        extra = ""
        if users:
            extra = "La usan: " + ", ".join(h["name"] for h in users[:6]) + \
                    ("…" if len(users) > 6 else "") + ". Esos hosts quedarán sin llave.\n\n"
        if D.confirm(self.win, f"¿Eliminar la llave «{key['name']}»?",
                     extra + "Si no tienes otra copia de la privada, perderás el acceso con ella."):
            self.vault.delete_key(key["id"])
            self._save_all()

    # --- menú ------------------------------------------------------------
    def import_config(self):
        if not self.vault.unlocked:
            return
        path = os.path.join(conn.REAL_HOME, ".ssh", "config")
        if not os.access(path, os.R_OK):
            # En el snap la carpeta oculta ~/.ssh no es visible: se elige el archivo
            # con el selector del sistema, que da acceso solo a ese archivo.
            d = Gtk.FileChooserNative.new("Elige tu archivo de configuración SSH (~/.ssh/config)",
                                          self.win, Gtk.FileChooserAction.OPEN, None, None)
            ok = d.run() == Gtk.ResponseType.ACCEPT
            path = d.get_filename() if ok else None
            d.destroy()
            if not path:
                return
        entries = conn.parse_ssh_config(path)
        existing = {(h["host"], int(h.get("port") or 22), h.get("user") or "") for h in self.vault.hosts}
        by_alias = {h["name"]: h for h in self.vault.hosts}
        added, skipped = [], 0
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
                kp = e["identityfile"]
                kp = os.path.join(conn.REAL_HOME, kp[2:]) if kp.startswith("~/") else os.path.expanduser(kp)
                rec = D.load_key_file(self.win, kp) if os.access(kp, os.R_OK) else None
                if rec:
                    h["key"] = self._add_key(rec)["id"]
                    h["auth"] = "key"
            if not h["key"]:
                h["auth"] = "password"
            h["_proxyjump"] = e.get("proxyjump")
            self.vault.upsert_host(h)
            by_alias[h["name"]] = h
            existing.add((hostname, port, user))
            added.append(h)
        for h in added:
            pj = h.pop("_proxyjump", None)
            if pj:
                alias = pj.split(",")[0].split("@")[-1].split(":")[0]
                if alias in by_alias:
                    h["jump"] = by_alias[alias]["id"]
        self.vault.save()
        self._save_all()
        self.toast(f"Importados {len(added)} host(s)" + (f", {skipped} ya existían" if skipped else ""))

    def change_password(self):
        pw = D.change_password_dialog(self.win)
        if pw:
            self.vault.change_password(pw)
            self.toast("Contraseña maestra cambiada")

    def about(self):
        d = Gtk.AboutDialog(transient_for=self.win, modal=True)
        d.set_program_name("Nexo")
        d.set_version(__version__)
        d.set_comments("SSH, SFTP, túneles y RDP en una sola ventana.\n"
                       "Bóveda cifrada local (AES-256-GCM + scrypt). Sin nube, sin telemetría.")
        d.set_logo(Gtk.Image.new_from_file(os.path.join(HERE, "nexo.svg")).get_pixbuf())
        d.run()
        d.destroy()


def main():
    GLib.set_prgname("nexo")
    GLib.set_application_name("Nexo")
    return NexoApp().run(sys.argv)
