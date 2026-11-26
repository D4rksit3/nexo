"""Diálogos: editar host, generar/importar llave, contraseña."""
import copy
import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from . import icons as I  # noqa: E402
from . import dbclient as DB  # noqa: E402
from . import keys as K  # noqa: E402
from .vault import blank_host  # noqa: E402

RESOLUTIONS = [("auto", "Ajustar a la ventana"), ("1920x1080", "1920 × 1080"), ("1600x900", "1600 × 900"),
               ("1366x768", "1366 × 768"), ("1280x720", "1280 × 720")]


def msg(parent, text, secondary="", kind=Gtk.MessageType.ERROR):
    d = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=kind,
                          buttons=Gtk.ButtonsType.OK, text=text)
    if secondary:
        d.format_secondary_text(secondary)
    d.run()
    d.destroy()


def confirm(parent, text, secondary="", ok="Eliminar", destructive=True):
    d = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
                          buttons=Gtk.ButtonsType.NONE, text=text)
    if secondary:
        d.format_secondary_text(secondary)
    d.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, ok, Gtk.ResponseType.OK)
    if destructive:
        d.get_widget_for_response(Gtk.ResponseType.OK).get_style_context().add_class("destructive-action")
    r = d.run()
    d.destroy()
    return r == Gtk.ResponseType.OK


def ask_text(parent, title, label, text="", secret=False, ok="Aceptar"):
    d = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    d.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, ok, Gtk.ResponseType.OK)
    d.set_default_response(Gtk.ResponseType.OK)
    box = d.get_content_area()
    box.set_border_width(14)
    box.set_spacing(8)
    box.add(Gtk.Label(label=label, xalign=0, wrap=True))
    e = Gtk.Entry(text=text, activates_default=True, visibility=not secret)
    e.set_width_chars(38)
    box.add(e)
    d.show_all()
    r = d.run()
    val = e.get_text()
    d.destroy()
    return val if r == Gtk.ResponseType.OK else None


def secret_entry(text=""):
    e = Gtk.Entry(text=text, visibility=False)
    e.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "view-reveal-symbolic")
    e.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, "Mostrar / ocultar")

    def toggle(entry, *_):
        entry.set_visibility(not entry.get_visibility())
        entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY,
                                      "view-conceal-symbolic" if entry.get_visibility() else "view-reveal-symbolic")

    e.connect("icon-press", toggle)
    return e


class HostDialog(Gtk.Dialog):
    def __init__(self, app, host=None, group=None):
        editing = host is not None
        super().__init__(title="Editar host" if editing else "Nuevo host", transient_for=app.win, modal=True)
        self.app = app
        self.vault = app.vault
        self.h = copy.deepcopy(host) if host else blank_host()
        if group and not host:
            self.h["group"] = group
        self.h.setdefault("rdp", blank_host()["rdp"])
        self.set_default_size(560, 620)
        self.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Guardar", Gtk.ResponseType.OK)
        self.get_widget_for_response(Gtk.ResponseType.OK).get_style_context().add_class("suggested-action")
        self.set_default_response(Gtk.ResponseType.OK)

        nb = Gtk.Notebook()
        self.get_content_area().pack_start(nb, True, True, 0)

        # --- General
        g = self._grid()
        r = 0
        self.e_name = Gtk.Entry(text=self.h["name"], placeholder_text="ej. nodo-aplicaciones")
        r = self._row(g, r, "Nombre", self.e_name)
        self.e_group = Gtk.ComboBoxText.new_with_entry()
        for grp in self.vault.groups():
            self.e_group.append_text(grp)
        self.e_group.get_child().set_text(self.h.get("group") or "")
        self.e_group.get_child().set_placeholder_text("ej. Producción")
        r = self._row(g, r, "Grupo", self.e_group)
        self._icon_touched = bool(self.h.get("icon"))
        self.icon_picker = IconPicker(I.host_icon(self.h), on_change=lambda v: setattr(self, "_icon_touched", True))
        r = self._row(g, r, "Icono", self.icon_picker)
        self.c_proto = Gtk.ComboBoxText()
        self.c_proto.append("ssh", "SSH (terminal + SFTP)")
        self.c_proto.append("rdp", "RDP (escritorio remoto)")
        for pid, (label, _port, _m, _pkg) in DB.ENGINES.items():
            self.c_proto.append(pid, f"{label} (base de datos)")
        self.c_proto.set_active_id(self.h["protocol"])
        r = self._row(g, r, "Protocolo", self.c_proto)
        self.e_host = Gtk.Entry(text=self.h["host"], placeholder_text="IP o nombre DNS", activates_default=True)
        r = self._row(g, r, "Host", self.e_host)
        self.s_port = Gtk.SpinButton.new_with_range(1, 65535, 1)
        self.s_port.set_value(int(self.h.get("port") or 22))
        r = self._row(g, r, "Puerto", self.s_port)
        self.e_user = Gtk.Entry(text=self.h.get("user") or "", placeholder_text="ej. ubuntu / Administrador")
        r = self._row(g, r, "Usuario", self.e_user)
        self.c_auth = Gtk.ComboBoxText()
        self.c_auth.append("key", "Llave SSH")
        self.c_auth.append("password", "Contraseña")
        self.c_auth.set_active_id(self.h.get("auth") or "key")
        self.l_auth = Gtk.Label(label="Autenticación", xalign=1)
        g.attach(self.l_auth, 0, r, 1, 1)
        g.attach(self.c_auth, 1, r, 1, 1)
        r += 1
        self.c_key = Gtk.ComboBoxText()
        self.c_key.append("", "— elige una llave —")
        for k in self.vault.keys:
            self.c_key.append(k["id"], f"{k['name']}  ({k['kind']})")
        self.c_key.set_active_id(self.h.get("key") or "")
        self.l_key = Gtk.Label(label="Llave", xalign=1)
        g.attach(self.l_key, 0, r, 1, 1)
        g.attach(self.c_key, 1, r, 1, 1)
        r += 1
        self.e_pass = secret_entry(self.h.get("password") or "")
        self.e_pass.set_placeholder_text("vacío = preguntar al conectar")
        self.l_pass = Gtk.Label(label="Contraseña", xalign=1)
        g.attach(self.l_pass, 0, r, 1, 1)
        g.attach(self.e_pass, 1, r, 1, 1)
        r += 1
        self.c_jump = Gtk.ComboBoxText()
        self.c_jump.append("", "— directo —")
        for o in self.vault.orgs:
            for oh in self.vault.org_hosts(o):
                if oh.get("perms", {}).get("tunnel"):
                    self.c_jump.append(oh["id"], f"{oh['name']}  (vía {o['name']})")
        for h in sorted(self.vault.hosts, key=lambda x: x["name"].lower()):
            if h["protocol"] == "ssh" and h["id"] != self.h.get("id"):
                self.c_jump.append(h["id"], f"{h['name']}  ({h['host']})")
        self.c_jump.set_active_id(self.h.get("jump") or "")
        r = self._row(g, r, "Saltar por", self.c_jump)
        hint = Gtk.Label(xalign=0, wrap=True, max_width_chars=50)
        hint.set_markup("<small>«Saltar por» usa otro host SSH como bastión. El salto puede entrar con "
                        "llave o con contraseña (la suya, guardada en ese host). "
                        "En RDP abre un túnel automático por ese host.</small>")
        hint.get_style_context().add_class("dim-label")
        g.attach(hint, 1, r, 1, 1)
        nb.append_page(self._wrap(g), Gtk.Label(label="General"))

        # --- Túneles
        tb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        tb.set_border_width(14)
        info = Gtk.Label(xalign=0, wrap=True)
        info.set_markup("<small><b>Local (L)</b>: un puerto de tu PC llega a un destino visto desde el servidor "
                        "(ej. 5433 → 127.0.0.1:5432 para una BD).\n<b>Remoto (R)</b>: un puerto del servidor llega a tu PC.\n"
                        "<b>SOCKS (D)</b>: proxy dinámico en tu PC.\nSe encienden desde la pestaña «Túneles».</small>")
        tb.pack_start(info, False, False, 0)
        self.fw_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        tb.pack_start(self.fw_box, False, False, 0)
        add = Gtk.Button.new_with_label("Agregar reenvío")
        add.set_halign(Gtk.Align.START)
        add.connect("clicked", lambda *_: self._add_fw({"type": "L", "bind": "127.0.0.1", "port": "",
                                                        "dest_host": "127.0.0.1", "dest_port": ""}))
        tb.pack_start(add, False, False, 0)
        self.fw_rows = []
        for fw in self.h.get("forwards") or []:
            self._add_fw(fw)
        self.tunnels_page = self._wrap(tb)
        nb.append_page(self.tunnels_page, Gtk.Label(label="Túneles"))

        # --- RDP
        o = self.h["rdp"]
        rg = self._grid()
        r = 0
        self.e_domain = Gtk.Entry(text=o.get("domain") or "", placeholder_text="opcional, ej. EMPRESA")
        r = self._row(rg, r, "Dominio", self.e_domain)
        self.c_res = Gtk.ComboBoxText()
        for rid, txt in RESOLUTIONS:
            self.c_res.append(rid, txt)
        self.c_res.set_active_id(o.get("resolution") or "auto")
        r = self._row(rg, r, "Resolución", self.c_res)
        self.sw_full = Gtk.Switch(active=bool(o.get("fullscreen")), halign=Gtk.Align.START)
        r = self._row(rg, r, "Pantalla completa", self.sw_full)
        self.sw_clip = Gtk.Switch(active=o.get("clipboard", True), halign=Gtk.Align.START)
        r = self._row(rg, r, "Portapapeles compartido", self.sw_clip)
        self.sw_home = Gtk.Switch(active=bool(o.get("share_home")), halign=Gtk.Align.START)
        r = self._row(rg, r, "Compartir mi carpeta personal", self.sw_home)
        self.rdp_page = self._wrap(rg)
        nb.append_page(self.rdp_page, Gtk.Label(label="RDP"))

        # --- Base de datos
        dbo = self.h.get("db") or {}
        dg = self._grid()
        r = 0
        self.e_dbname = Gtk.Entry(text=dbo.get("database") or "", placeholder_text="postgres, app_prod, 0 (Redis)…")
        r = self._row(dg, r, "Base de datos", self.e_dbname)
        self.e_authdb = Gtk.Entry(text=dbo.get("auth_db") or "", placeholder_text="admin")
        self.l_authdb = Gtk.Label(label="Base de autenticación", xalign=1)
        dg.attach(self.l_authdb, 0, r, 1, 1)
        self.e_authdb.set_hexpand(True)
        dg.attach(self.e_authdb, 1, r, 1, 1)
        r += 1
        self.sw_ro = Gtk.Switch(active=bool(dbo.get("readonly")), halign=Gtk.Align.START)
        r = self._row(dg, r, "Solo lectura", self.sw_ro)
        self.sw_tls = Gtk.Switch(active=bool(dbo.get("tls")), halign=Gtk.Align.START)
        r = self._row(dg, r, "Cifrar con TLS/SSL", self.sw_tls)
        dh = Gtk.Label(xalign=0, wrap=True, max_width_chars=52)
        dh.set_markup("<small><b>Solo lectura</b> impide modificar datos: recomendado para producción.\n"
                      "Si la base no está expuesta, usa <b>«Saltar por»</b> (pestaña General): Nexo abre un túnel SSH "
                      "automático hacia ella, incluso por un host de tu organización con permiso de túneles.</small>")
        dh.get_style_context().add_class("dim-label")
        dg.attach(dh, 1, r, 1, 1)
        self.db_page = self._wrap(dg)
        nb.append_page(self.db_page, Gtk.Label(label="Base de datos"))

        # --- Notas
        self.notes = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=8, right_margin=8,
                                  top_margin=8, bottom_margin=8)
        self.notes.get_buffer().set_text(self.h.get("notes") or "")
        sw = Gtk.ScrolledWindow()
        sw.add(self.notes)
        nb.append_page(sw, Gtk.Label(label="Notas"))

        self.c_proto.connect("changed", self._sync)
        self.c_auth.connect("changed", self._sync)
        self.show_all()
        self._sync(None)
        self.e_name.grab_focus() if not editing else self.e_host.grab_focus()

    def _grid(self):
        g = Gtk.Grid(column_spacing=12, row_spacing=10)
        g.set_border_width(16)
        return g

    def _wrap(self, w):
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(w)
        return sw

    def _row(self, g, r, label, widget):
        g.attach(Gtk.Label(label=label, xalign=1), 0, r, 1, 1)
        widget.set_hexpand(True)
        g.attach(widget, 1, r, 1, 1)
        return r + 1

    def _sync(self, widget):
        from .conn import DEFAULT_PORTS
        proto = self.c_proto.get_active_id()
        is_rdp = proto == "rdp"
        is_db = DB.is_db(proto)
        if widget is self.c_proto:
            port = int(self.s_port.get_value())
            if port in DEFAULT_PORTS.values():
                self.s_port.set_value(DEFAULT_PORTS.get(proto, 22))
        if widget is self.c_proto and not self._icon_touched:
            self.icon_picker.on_change = None
            self.icon_picker.set_value("windows" if is_rdp else "db" if is_db else "linux")
            self.icon_picker.on_change = lambda v: setattr(self, "_icon_touched", True)
        if is_rdp or is_db:
            self.c_auth.set_active_id("password")
        for w in (self.l_auth, self.c_auth):
            w.set_visible(not (is_rdp or is_db))
        use_key = not (is_rdp or is_db) and self.c_auth.get_active_id() == "key"
        for w in (self.l_key, self.c_key):
            w.set_visible(use_key)
        for w in (self.l_pass, self.e_pass):
            w.set_visible(not use_key)
        self.rdp_page.set_visible(is_rdp)
        self.db_page.set_visible(is_db)
        for w in (self.l_authdb, self.e_authdb):
            w.set_visible(proto == "mongodb")
        self.tunnels_page.set_visible(proto == "ssh")
        self.e_pass.set_placeholder_text("contraseña de la base de datos" if is_db else "vacío = preguntar al conectar")

    def _add_fw(self, fw):
        row = Gtk.Box(spacing=6)
        t = Gtk.ComboBoxText()
        for tid, txt in (("L", "Local"), ("R", "Remoto"), ("D", "SOCKS")):
            t.append(tid, txt)
        t.set_active_id(fw.get("type", "L"))
        port = Gtk.Entry(text=str(fw.get("port") or ""), placeholder_text="puerto", width_chars=7)
        dh = Gtk.Entry(text=fw.get("dest_host") or "", placeholder_text="destino", width_chars=14)
        dp = Gtk.Entry(text=str(fw.get("dest_port") or ""), placeholder_text="puerto", width_chars=7)
        arrow = Gtk.Label(label="→")
        rm = Gtk.Button.new_from_icon_name("list-remove-symbolic", Gtk.IconSize.BUTTON)
        rm.set_relief(Gtk.ReliefStyle.NONE)
        for w in (t, port, arrow, dh, dp):
            row.pack_start(w, w is dh, w is dh, 0)
        row.pack_end(rm, False, False, 0)
        rec = {"row": row, "type": t, "port": port, "dest_host": dh, "dest_port": dp,
               "bind": fw.get("bind") or "127.0.0.1"}

        def on_type(*_):
            socks = t.get_active_id() == "D"
            for w in (arrow, dh, dp):
                w.set_visible(not socks)

        t.connect("changed", on_type)
        rm.connect("clicked", lambda *_: (self.fw_rows.remove(rec), row.destroy()))
        self.fw_rows.append(rec)
        self.fw_box.pack_start(row, False, False, 0)
        row.show_all()
        on_type()

    def _collect(self):
        h = self.h
        h["host"] = self.e_host.get_text().strip()
        if not h["host"]:
            raise ValueError("Falta el host (IP o nombre)")
        h["name"] = self.e_name.get_text().strip() or h["host"]
        h["group"] = self.e_group.get_child().get_text().strip()
        h["icon"] = self.icon_picker.get_value() if self._icon_touched else h.get("icon")
        h["protocol"] = self.c_proto.get_active_id()
        h["port"] = int(self.s_port.get_value())
        h["user"] = self.e_user.get_text().strip()
        h["auth"] = "password" if h["protocol"] != "ssh" else self.c_auth.get_active_id()
        h["password"] = self.e_pass.get_text() if h["auth"] == "password" else ""
        h["key"] = (self.c_key.get_active_id() or None) if h["auth"] == "key" else None
        if h["auth"] == "key" and not h["key"]:
            raise ValueError("Elige una llave (o créala en la pestaña «Llaves»)")
        h["jump"] = self.c_jump.get_active_id() or None
        fws = []
        for rec in self.fw_rows:
            typ = rec["type"].get_active_id()
            port = rec["port"].get_text().strip()
            if not port:
                continue
            if not port.isdigit():
                raise ValueError(f"Puerto inválido en túnel: {port}")
            fw = {"type": typ, "bind": rec["bind"], "port": int(port)}
            if typ != "D":
                dport = rec["dest_port"].get_text().strip()
                if not dport.isdigit() or not rec["dest_host"].get_text().strip():
                    raise ValueError("Cada túnel L/R necesita destino y puerto de destino")
                fw["dest_host"] = rec["dest_host"].get_text().strip()
                fw["dest_port"] = int(dport)
            fws.append(fw)
        h["forwards"] = fws if h["protocol"] == "ssh" else []
        h["db"] = {
            "database": self.e_dbname.get_text().strip(),
            "auth_db": self.e_authdb.get_text().strip(),
            "readonly": self.sw_ro.get_active(),
            "tls": self.sw_tls.get_active(),
        }
        h["rdp"] = {
            "domain": self.e_domain.get_text().strip(),
            "resolution": self.c_res.get_active_id(),
            "fullscreen": self.sw_full.get_active(),
            "clipboard": self.sw_clip.get_active(),
            "share_home": self.sw_home.get_active(),
        }
        buf = self.notes.get_buffer()
        h["notes"] = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        return h

    def run_and_get(self):
        while True:
            if self.run() != Gtk.ResponseType.OK:
                self.destroy()
                return None
            try:
                h = self._collect()
            except ValueError as e:
                msg(self, str(e))
                continue
            self.destroy()
            return h


def generate_key_dialog(parent):
    d = Gtk.Dialog(title="Generar llave", transient_for=parent, modal=True)
    d.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Generar", Gtk.ResponseType.OK)
    d.set_default_response(Gtk.ResponseType.OK)
    g = Gtk.Grid(column_spacing=12, row_spacing=10)
    g.set_border_width(16)
    name = Gtk.Entry(placeholder_text="ej. juan-ociscl-2026", activates_default=True, hexpand=True)
    kind = Gtk.ComboBoxText()
    kind.append("ed25519", "ED25519 (recomendada)")
    kind.append("rsa", "RSA 4096 (equipos antiguos)")
    kind.append("ecdsa", "ECDSA P-256")
    kind.set_active_id("ed25519")
    g.attach(Gtk.Label(label="Nombre", xalign=1), 0, 0, 1, 1)
    g.attach(name, 1, 0, 1, 1)
    g.attach(Gtk.Label(label="Tipo", xalign=1), 0, 1, 1, 1)
    g.attach(kind, 1, 1, 1, 1)
    d.get_content_area().add(g)
    d.show_all()
    r = d.run()
    res = (name.get_text().strip() or "llave", kind.get_active_id()) if r == Gtk.ResponseType.OK else None
    d.destroy()
    return res


def import_key_dialog(parent):
    """Devuelve un registro de llave listo para la bóveda, o None."""
    d = Gtk.FileChooserNative.new("Importar llave privada", parent, Gtk.FileChooserAction.OPEN, None, None)
    ssh_dir = os.path.join(os.environ.get("SNAP_REAL_HOME") or os.path.expanduser("~"), ".ssh")
    if os.path.isdir(ssh_dir):
        d.set_current_folder(ssh_dir)
    ok = d.run() == Gtk.ResponseType.ACCEPT
    path = d.get_filename() if ok else None
    d.destroy()
    if not path:
        return None
    return load_key_file(parent, path)


def load_key_file(parent, path, name=None):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        msg(parent, "No se pudo leer el archivo", str(e))
        return None
    base = name or os.path.basename(path)
    for suf in (".pem", ".key"):
        if base.endswith(suf):
            base = base[: -len(suf)]
    return load_key_text(parent, text, base, os.path.basename(path))


def load_key_text(parent, text, name, label=None):
    """Convierte el texto de una llave privada en un registro; pide la frase si hace falta."""
    label = label or name
    passphrase = None
    while True:
        try:
            pk = K.load_private(text, passphrase)
            break
        except K.NeedsPassphrase:
            passphrase = ask_text(parent, "Frase de paso",
                                  f"La llave {label} está protegida. Escribe su frase de paso:",
                                  secret=True)
            if passphrase is None:
                return None
        except K.KeyError_ as e:
            if passphrase is not None:
                passphrase = ask_text(parent, "Frase de paso", "Frase incorrecta. Inténtalo de nuevo:", secret=True)
                if passphrase is None:
                    return None
                continue
            msg(parent, "No se pudo importar la llave", str(e))
            return None
    return K.make_key_record(name, pk)


def paste_key_dialog(parent):
    """Agregar una llave privada pegando su texto. Devuelve el registro o None."""
    d = Gtk.Dialog(title="Agregar llave manualmente", transient_for=parent, modal=True)
    d.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Agregar", Gtk.ResponseType.OK)
    d.set_default_response(Gtk.ResponseType.OK)
    d.set_default_size(560, 420)
    box = d.get_content_area()
    box.set_border_width(16)
    box.set_spacing(8)
    name = Gtk.Entry(placeholder_text="Nombre, ej. servidor-produccion", activates_default=False)
    box.add(Gtk.Label(label="Nombre", xalign=0))
    box.add(name)
    lbl = Gtk.Label(xalign=0, wrap=True)
    lbl.set_markup("Llave <b>privada</b> (OpenSSH o PEM). Pega el contenido completo, desde "
                   "<tt>-----BEGIN …</tt> hasta <tt>-----END …</tt>:")
    lbl.set_margin_top(6)
    box.add(lbl)
    tv = Gtk.TextView(monospace=True, wrap_mode=Gtk.WrapMode.CHAR, accepts_tab=False)
    tv.set_left_margin(8)
    tv.get_style_context().add_class("nx-mono")
    tv.set_top_margin(6)
    sw = Gtk.ScrolledWindow(vexpand=True)
    sw.set_shadow_type(Gtk.ShadowType.IN)
    sw.add(tv)
    box.pack_start(sw, True, True, 0)
    paste = Gtk.Button(label="Pegar del portapapeles")
    paste.set_halign(Gtk.Align.START)

    def do_paste(_b):
        t = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()
        if t:
            tv.get_buffer().set_text(t.strip() + "\n")
    paste.connect("clicked", do_paste)
    box.add(paste)
    hint = Gtk.Label(label="Se guarda cifrada en la bóveda; no se escribe en disco.", xalign=0)
    hint.get_style_context().add_class("dim-label")
    box.add(hint)
    d.show_all()
    rec = None
    while d.run() == Gtk.ResponseType.OK:
        buf = tv.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        if not text:
            msg(d, "Pega el contenido de la llave privada")
            continue
        if "PUBLIC KEY" in text or text.startswith(("ssh-", "ecdsa-")):
            msg(d, "Eso es una llave pública",
                "Para conectarte Nexo necesita la llave privada (el archivo sin .pub).")
            continue
        rec = load_key_text(d, text, name.get_text().strip() or "llave")
        if rec:
            break
    d.destroy()
    return rec


SSH_CONNECT_CMD = "sudo snap connect nexo:ssh-keys"


def ssh_permission_dialog(parent, what, on_copy):
    """El snap no puede leer ~/.ssh: explica cómo dar permiso.

    Devuelve "retry" (ya dio permiso), "pick" (elegir el archivo a mano) o None.
    """
    d = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
                          buttons=Gtk.ButtonsType.NONE,
                          text="Nexo necesita permiso para leer tu carpeta ~/.ssh")
    d.format_secondary_markup(
        f"Para {what}, Nexo (instalado como snap) debe poder leer <tt>~/.ssh</tt>. "
        "Ubuntu protege esa carpeta y solo tú puedes darle acceso.\n\n"
        "<b>1.</b> Copia este comando y ejecútalo en una terminal (te pedirá tu contraseña):\n"
        f"<tt>    {SSH_CONNECT_CMD}</tt>\n"
        "<b>2.</b> Vuelve aquí y pulsa <b>Ya di permiso</b>. No hace falta reiniciar Nexo.\n\n"
        "Si prefieres no darlo, elige el archivo a mano (en el selector, Ctrl+H muestra las carpetas ocultas).")
    d.add_button("Cancelar", Gtk.ResponseType.CANCEL)
    d.add_button("Elegir archivo…", 2)
    d.add_button("Copiar comando", 3)
    d.add_button("Ya di permiso", Gtk.ResponseType.OK)
    d.get_widget_for_response(Gtk.ResponseType.OK).get_style_context().add_class("suggested-action")
    d.set_default_response(Gtk.ResponseType.OK)
    while True:
        r = d.run()
        if r == 3:
            on_copy(SSH_CONNECT_CMD)
            continue
        break
    d.destroy()
    return {Gtk.ResponseType.OK: "retry", 2: "pick"}.get(r)


def change_password_dialog(parent):
    d = Gtk.Dialog(title="Cambiar contraseña maestra", transient_for=parent, modal=True)
    d.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Cambiar", Gtk.ResponseType.OK)
    g = Gtk.Grid(column_spacing=12, row_spacing=10)
    g.set_border_width(16)
    p1, p2 = secret_entry(), secret_entry()
    p2.set_activates_default(True)
    d.set_default_response(Gtk.ResponseType.OK)
    g.attach(Gtk.Label(label="Nueva", xalign=1), 0, 0, 1, 1)
    g.attach(p1, 1, 0, 1, 1)
    g.attach(Gtk.Label(label="Repetir", xalign=1), 0, 1, 1, 1)
    g.attach(p2, 1, 1, 1, 1)
    d.get_content_area().add(g)
    d.show_all()
    while True:
        if d.run() != Gtk.ResponseType.OK:
            d.destroy()
            return None
        a, b = p1.get_text(), p2.get_text()
        if len(a) < 8:
            msg(d, "Usa al menos 8 caracteres")
        elif a != b:
            msg(d, "Las contraseñas no coinciden")
        else:
            d.destroy()
            return a


AUTOLOCK_CHOICES = [(0, "Nunca"), (1, "1 minuto"), (5, "5 minutos"), (10, "10 minutos"), (15, "15 minutos"),
                    (30, "30 minutos"), (60, "1 hora"), (120, "2 horas")]


def autolock_dialog(parent, minutes, on_screen):
    """Devuelve (minutos, bloquear_con_pantalla) o None."""
    d = Gtk.Dialog(title="Autobloqueo", transient_for=parent, modal=True)
    d.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Guardar", Gtk.ResponseType.OK)
    d.set_default_response(Gtk.ResponseType.OK)
    g = Gtk.Grid(column_spacing=12, row_spacing=12)
    g.set_border_width(16)
    combo = Gtk.ComboBoxText()
    ids = [m for m, _ in AUTOLOCK_CHOICES]
    if minutes not in ids:
        AUTOLOCK_CHOICES.append((minutes, f"{minutes} minutos"))
    for m, txt in AUTOLOCK_CHOICES:
        combo.append(str(m), txt)
    combo.set_active_id(str(minutes))
    g.attach(Gtk.Label(label="Bloquear tras inactividad", xalign=1), 0, 0, 1, 1)
    g.attach(combo, 1, 0, 1, 1)
    sw = Gtk.Switch(active=on_screen, halign=Gtk.Align.START)
    g.attach(Gtk.Label(label="Bloquear al bloquear la pantalla\no suspender el equipo", xalign=1), 0, 1, 1, 1)
    g.attach(sw, 1, 1, 1, 1)
    note = Gtk.Label(xalign=0, wrap=True, max_width_chars=48)
    note.set_markup("<small>Inactividad = sin teclado ni ratón dentro de Nexo. Al bloquearse se ocultan los "
                    "hosts y se descargan las llaves del agente; las sesiones, túneles y SFTP ya abiertos "
                    "siguen vivos.</small>")
    note.get_style_context().add_class("dim-label")
    g.attach(note, 0, 2, 2, 1)
    d.get_content_area().add(g)
    d.show_all()
    r = d.run()
    res = (int(combo.get_active_id()), sw.get_active()) if r == Gtk.ResponseType.OK else None
    d.destroy()
    return res


class IconPicker(Gtk.FlowBox):
    """Rejilla de iconos para elegir uno."""

    def __init__(self, selected=None, on_change=None):
        super().__init__(selection_mode=Gtk.SelectionMode.SINGLE, max_children_per_line=12,
                         min_children_per_line=6, column_spacing=2, row_spacing=2, homogeneous=True)
        self.get_style_context().add_class("enlace-icon-picker")
        self.on_change = on_change
        self._keys = []
        for key, (_bi, text, _c) in I.ICONS.items():
            img = I.image(key, 22)
            img.set_margin_top(5)
            img.set_margin_bottom(5)
            child = Gtk.FlowBoxChild()
            child.add(img)
            child.set_tooltip_text(text)
            self.add(child)
            self._keys.append(key)
            if key == selected:
                self.select_child(child)
        self.connect("selected-children-changed", lambda *_: self.on_change and self.on_change(self.get_value()))

    def get_value(self):
        sel = self.get_selected_children()
        return self._keys[sel[0].get_index()] if sel else None

    def set_value(self, key):
        if key in self._keys:
            self.select_child(self.get_child_at_index(self._keys.index(key)))


def group_dialog(parent, name="", icon="folder", title="Nuevo grupo"):
    """Devuelve (nombre, icono) o None."""
    d = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    d.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Guardar", Gtk.ResponseType.OK)
    d.get_widget_for_response(Gtk.ResponseType.OK).get_style_context().add_class("suggested-action")
    d.set_default_response(Gtk.ResponseType.OK)
    box = d.get_content_area()
    box.set_border_width(16)
    box.set_spacing(10)
    e = Gtk.Entry(text=name, activates_default=True, placeholder_text="ej. Linux, Windows, Producción, Cámaras…")
    e.set_width_chars(36)
    box.add(Gtk.Label(label="Nombre del grupo", xalign=0))
    box.add(e)
    box.add(Gtk.Label(label="Icono", xalign=0))
    picker = IconPicker(icon)
    box.add(picker)
    d.show_all()
    while True:
        if d.run() != Gtk.ResponseType.OK:
            d.destroy()
            return None
        n = e.get_text().strip()
        if not n:
            msg(d, "Escribe un nombre para el grupo")
            continue
        res = (n, picker.get_value() or "folder")
        d.destroy()
        return res


def org_login_dialog(parent, url="", username="", title="Conectar a una organización"):
    """Devuelve dict(url, username, password, totp) o None."""
    d = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    d.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Ingresar", Gtk.ResponseType.OK)
    d.get_widget_for_response(Gtk.ResponseType.OK).get_style_context().add_class("suggested-action")
    d.set_default_response(Gtk.ResponseType.OK)
    box = d.get_content_area()
    box.set_border_width(18)
    box.set_spacing(6)
    info = Gtk.Label(xalign=0, wrap=True, max_width_chars=48)
    info.set_markup("<small>Tu organización administra los accesos desde su servidor Nexo. Las llaves de los "
                    "servidores nunca llegan a tu equipo: entras con tu cuenta y tu código 2FA.</small>")
    info.get_style_context().add_class("dim-label")
    box.add(info)
    fields = {}
    for key, label, placeholder, value, secret in (
            ("url", "Dirección del servidor", "https://nexo.miempresa.com", url, False),
            ("username", "Usuario", "", username, False),
            ("password", "Contraseña", "", "", True),
            ("totp", "Código 2FA", "123456", "", False)):
        lab = Gtk.Label(label=label, xalign=0)
        lab.set_margin_top(8)
        box.add(lab)
        e = secret_entry() if secret else Gtk.Entry()
        e.set_text(value or "")
        e.set_placeholder_text(placeholder)
        e.set_activates_default(True)
        if key == "totp":
            e.set_max_length(7)
            e.set_input_purpose(Gtk.InputPurpose.DIGITS)
        box.add(e)
        fields[key] = e
    d.show_all()
    (fields["password"] if url and username else fields["url"]).grab_focus()
    while True:
        if d.run() != Gtk.ResponseType.OK:
            d.destroy()
            return None
        vals = {k: w.get_text().strip() for k, w in fields.items()}
        vals["password"] = fields["password"].get_text()
        if not all(vals[k] for k in ("url", "username", "password", "totp")):
            msg(d, "Completa todos los campos")
            continue
        if vals["url"].startswith("http://") and not any(h in vals["url"] for h in ("127.0.0.1", "localhost")):
            if not confirm(d, "La conexión no está cifrada (http://)",
                           "Tu contraseña viajaría sin cifrar. Usa https:// salvo en pruebas locales.",
                           ok="Continuar igual", destructive=True):
                continue
        d.destroy()
        return vals
