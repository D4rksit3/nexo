"""Pestaña de base de datos: árbol de objetos, editor de consultas y resultados."""
import csv
import queue
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, GObject, Gtk, Pango  # noqa: E402

from . import conn  # noqa: E402
from . import dbclient as DB  # noqa: E402
from . import icons as I  # noqa: E402

try:
    gi.require_version("GtkSource", "4")
    from gi.repository import GtkSource  # noqa: E402
except (ValueError, ImportError):
    GtkSource = None

PLACEHOLDER = {
    "postgres": "-- Ctrl+Enter ejecuta (la selección o todo)\nSELECT now(), current_user, version();",
    "mysql": "-- Ctrl+Enter ejecuta (la selección o todo)\nSELECT NOW(), CURRENT_USER(), VERSION();",
    "mssql": "-- Ctrl+Enter ejecuta (la selección o todo)\nSELECT GETDATE() AS ahora, SUSER_NAME() AS usuario, @@VERSION AS version;",
    "mongodb": "// Elige una colección a la izquierda o escribe:\n// coleccion.find({\"campo\": \"valor\"})\n",
    "redis": "# Un comando por línea. Ejemplos:\nINFO server\nDBSIZE",
}


class DbTab(Gtk.Box):
    def __init__(self, app, host):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.host = host
        self.title = host["name"]
        self.engine = host["protocol"]
        self.db = None
        self.tunnel = None
        self.alive = False
        self.closed = False
        self.jobs = queue.Queue()
        self.result = None
        opts = host.get("db") or {}
        self.readonly = bool(opts.get("readonly"))

        # --- barra
        bar = Gtk.Box(spacing=6)
        bar.get_style_context().add_class("enlace-toolbar")
        bar.set_border_width(6)
        badge = Gtk.Label(label=DB.SHORT.get(self.engine, self.engine))
        badge.get_style_context().add_class("enlace-badge")
        bar.pack_start(badge, False, False, 4)
        self.db_combo = Gtk.ComboBoxText()
        self.db_combo.set_tooltip_text("Base de datos")
        self._combo_lock = False
        self.db_combo.connect("changed", self._on_db_changed)
        bar.pack_start(self.db_combo, False, False, 0)

        def btn(icon, tip, cb, text=None):
            b = Gtk.Button()
            box = Gtk.Box(spacing=6)
            box.pack_start(I.ui_image(icon, 14), False, False, 0)
            if text:
                box.pack_start(Gtk.Label(label=text), False, False, 0)
            b.add(box)
            b.set_tooltip_text(tip)
            b.connect("clicked", lambda *_: cb())
            bar.pack_start(b, False, False, 0)
            return b

        self.run_btn = btn("play", "Ejecutar (Ctrl+Enter)", self.run_query, "Ejecutar")
        self.run_btn.get_style_context().add_class("suggested-action")
        btn("refresh", "Actualizar objetos (F5)", self.load_tree)
        btn("download", "Exportar resultados a CSV", self.export_csv)
        bar.pack_start(Gtk.Label(label="Límite"), False, False, 6)
        self.limit = Gtk.SpinButton.new_with_range(10, 100000, 100)
        self.limit.set_value(500)
        bar.pack_start(self.limit, False, False, 0)
        if self.readonly:
            ro = Gtk.Label(label="SOLO LECTURA")
            ro.get_style_context().add_class("enlace-bcast")
            ro.set_tooltip_text("Esta conexión no permite modificar datos")
            bar.pack_end(ro, False, False, 6)
        via = ""
        if host.get("jump"):
            j = app.vault.host(host["jump"])
            via = f" · túnel por {j['name']}" if j else ""
        self.conn_label = Gtk.Label(label=f"{conn.label(host)}{via}", ellipsize=Pango.EllipsizeMode.END)
        self.conn_label.get_style_context().add_class("nx-mono-sub")
        bar.pack_end(self.conn_label, False, False, 6)
        self.pack_start(bar, False, False, 0)

        # --- cuerpo
        hp = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.tree_store = Gtk.TreeStore(str, str, str, str)  # texto, icono, grupo, objeto
        self.tree = Gtk.TreeView(model=self.tree_store, headers_visible=False)
        col = Gtk.TreeViewColumn()
        ri, rt = Gtk.CellRendererPixbuf(), Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        col.pack_start(ri, False)
        col.pack_start(rt, True)
        col.add_attribute(ri, "icon-name", 1)
        col.add_attribute(rt, "text", 0)
        self.tree.append_column(col)
        self.tree.set_search_column(0)
        self.tree.connect("row-activated", self._on_tree_activate)
        self.tree_filter = Gtk.SearchEntry(placeholder_text="Filtrar objetos…")
        self.tree_filter.connect("search-changed", lambda *_: self._fill_tree(self._last_tree or []))
        self._last_tree = None
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.pack_start(self.tree_filter, False, False, 4)
        sw = Gtk.ScrolledWindow()
        sw.add(self.tree)
        left.pack_start(sw, True, True, 0)
        left.set_size_request(230, -1)
        hp.pack1(left, False, False)

        vp = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        if GtkSource is not None:
            self.buffer = GtkSource.Buffer()
            lang = GtkSource.LanguageManager.get_default().get_language(
                "json" if self.engine == "mongodb" else "sql" if self.engine != "redis" else "sh")
            if lang:
                self.buffer.set_language(lang)
            scheme = GtkSource.StyleSchemeManager.get_default().get_scheme("oblivion")
            if scheme:
                self.buffer.set_style_scheme(scheme)
            self.editor = GtkSource.View(buffer=self.buffer, show_line_numbers=True, auto_indent=True,
                                         highlight_current_line=True, tab_width=2, insert_spaces_instead_of_tabs=True)
        else:
            self.buffer = Gtk.TextBuffer()
            self.editor = Gtk.TextView(buffer=self.buffer)
        self.editor.set_monospace(True)
        self.editor.set_left_margin(8)
        self.editor.set_top_margin(6)
        self.buffer.set_text(PLACEHOLDER.get(self.engine, ""))
        self.editor.connect("key-press-event", self._on_key)
        esw = Gtk.ScrolledWindow()
        esw.add(self.editor)
        esw.set_size_request(-1, 140)
        vp.pack1(esw, False, False)

        self.results = Gtk.TreeView(enable_grid_lines=Gtk.TreeViewGridLines.BOTH, rubber_banding=True)
        self.results.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.results.connect("button-press-event", self._on_results_click)
        rsw = Gtk.ScrolledWindow()
        rsw.add(self.results)
        vp.pack2(rsw, True, False)
        vp.set_position(190)
        hp.pack2(vp, True, False)
        hp.set_position(240)
        self.pack_start(hp, True, True, 0)

        st = Gtk.Box(spacing=8)
        st.set_border_width(6)
        st.get_style_context().add_class("enlace-statusbar")
        self.status = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.status.get_style_context().add_class("dim-label")
        self.spinner = Gtk.Spinner()
        st.pack_start(self.spinner, False, False, 0)
        st.pack_start(self.status, True, True, 0)
        self.pack_start(st, False, False, 0)

        self.show_all()
        threading.Thread(target=self._worker, daemon=True).start()
        self._set_busy(True, f"Conectando a {DB.ENGINES[self.engine][0]}…")
        self.submit(self._connect, self._connected)

    # --- hilo de trabajo -----------------------------------------------------
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
        self._set_busy(False)
        if err is not None:
            msg = str(err) or type(err).__name__
            self.status.set_markup(f'<span foreground="#ff6b7a">✖ {GLib.markup_escape_text(msg)}</span>')
        elif done:
            done(res)
        return False

    def submit(self, fn, done=None):
        self.jobs.put((fn, done))

    def _set_busy(self, busy, text=None):
        (self.spinner.start if busy else self.spinner.stop)()
        self.run_btn.set_sensitive(not busy)
        if text:
            self.status.set_text(text)

    # --- conexión ----------------------------------------------------------------
    def _connect(self):
        h = self.host
        target_host, target_port = h["host"], int(h.get("port") or DB.default_port(self.engine))
        if h.get("jump"):
            jump = self.app.vault.host(h["jump"])
            if not jump:
                raise DB.DBError("El host para el túnel ya no existe")
            lport = conn.free_port()
            fw = {"type": "L", "bind": "127.0.0.1", "port": lport, "dest_host": target_host, "dest_port": target_port}
            self.tunnel = conn.Tunnel(self.app.builder, jump, [fw])
            self.tunnel.start()
            if not conn.wait_port(lport, timeout=25, proc=self.tunnel.proc):
                raise DB.DBError(f"No se pudo abrir el túnel por {jump['name']}: {self.tunnel.error or 'sin respuesta'}")
            target_host, target_port = "127.0.0.1", lport
        opts = h.get("db") or {}
        self.db = DB.connect(self.engine, target_host, target_port, h.get("user", ""), h.get("password", ""),
                             opts.get("database", ""), self.readonly, bool(opts.get("tls")), opts.get("auth_db") or None)
        dbs = []
        try:
            dbs = self.db.databases()
        except DB.DBError:
            pass
        return dbs, self.db.tree()

    def _connected(self, res):
        dbs, tree = res
        self.alive = True
        self.app.tab_state_changed(self)
        self._combo_lock = True
        self.db_combo.remove_all()
        for d in dbs:
            self.db_combo.append(d, d)
        if self.db.database and self.db.database not in dbs:
            self.db_combo.append(self.db.database, self.db.database)
        self.db_combo.set_active_id(self.db.database)
        self._combo_lock = False
        self._fill_tree(tree)
        self.status.set_text(f"Conectado a {DB.ENGINES[self.engine][0]} · base «{self.db.database}»"
                             + (" · solo lectura" if self.readonly else ""))
        self.editor.grab_focus()

    def _on_db_changed(self, combo):
        if self._combo_lock or self.db is None:
            return
        name = combo.get_active_id()
        if not name or name == self.db.database:
            return
        self._set_busy(True, f"Cambiando a «{name}»…")

        def job():
            self.db.use(name)
            return self.db.tree()

        def done(tree):
            self._fill_tree(tree)
            self.status.set_text(f"Base «{name}»")

        self.submit(job, done)

    # --- árbol ------------------------------------------------------------------------
    def load_tree(self):
        if self.db is None:
            return
        self._set_busy(True, "Actualizando objetos…")
        self.submit(self.db.tree, self._fill_tree)

    def _fill_tree(self, tree):
        self._last_tree = tree
        q = self.tree_filter.get_text().strip().lower()
        self.tree_store.clear()
        icon = {"tabla": I.ui_name("table"), "vista": I.ui_name("view"), "colección": I.ui_name("collection"),
                "clave": I.ui_name("key2"), "base": I.ui_name("database")}
        total = 0
        for group, objs in tree:
            shown = [(o, k) for o, k in objs if not q or q in o.lower()]
            if q and not shown:
                continue
            it = self.tree_store.append(None, [f"{group}  ({len(objs)})", I.ui_name("database"), group, ""])
            for o, kind in shown:
                self.tree_store.append(it, [o, icon.get(kind, I.ui_name("table")), group, o])
                total += 1
        self.tree.expand_all() if (q or total < 80) else self.tree.expand_row(Gtk.TreePath.new_first(), False)

    def _on_tree_activate(self, view, path, col):
        row = self.tree_store[path]
        group, obj = row[2], row[3]
        if not obj:
            return
        self.buffer.set_text(self.db.default_query(group, obj))
        self.run_query()

    # --- consultas -------------------------------------------------------------------
    def _query_text(self):
        b = self.buffer
        if b.get_has_selection():
            s, e = b.get_selection_bounds()
        else:
            s, e = b.get_bounds()
        return b.get_text(s, e, False)

    def run_query(self):
        if self.db is None:
            return
        text = self._query_text()
        limit = self.limit.get_value_as_int()
        self._set_busy(True, "Ejecutando…")
        self.submit(lambda: self.db.run(text, limit), self._show_result)

    def _show_result(self, res):
        self.result = res
        for c in self.results.get_columns():
            self.results.remove_column(c)
        if not res.columns:
            self.results.set_model(None)
            self.status.set_text(res.info)
            if self.engine == "mysql" and self.db.database:
                self._combo_lock = True
                if self.db_combo.get_active_id() != self.db.database:
                    self.db_combo.append(self.db.database, self.db.database)
                    self.db_combo.set_active_id(self.db.database)
                self._combo_lock = False
            return
        store = Gtk.ListStore(*([str] * len(res.columns)))
        for r in res.rows:
            store.append([(v if len(v) < 2000 else v[:2000] + "…").replace("\n", " ⏎ ") for v in r])
        for i, name in enumerate(res.columns):
            rend = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END, family="JetBrains Mono", size_points=10)
            c = Gtk.TreeViewColumn(str(name), rend, text=i)
            c.set_resizable(True)
            c.set_sort_column_id(i)
            c.set_min_width(60)
            c.set_max_width(480)
            self.results.append_column(c)
        self.results.set_model(store)
        self.status.set_text(res.info)

    def _on_key(self, w, ev):
        ctrl = ev.state & Gdk.ModifierType.CONTROL_MASK
        if ctrl and ev.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.run_query()
            return True
        if ev.keyval == Gdk.KEY_F5:
            self.load_tree()
            return True
        return False

    def _on_results_click(self, view, ev):
        if ev.button != 3 or not self.result or not self.result.columns:
            return False
        res = view.get_path_at_pos(int(ev.x), int(ev.y))
        if not res:
            return False
        path, col = res[0], res[1]
        idx = self.results.get_columns().index(col)
        row = self.result.rows[path.get_indices()[0]] if path.get_indices()[0] < len(self.result.rows) else None
        if row is None:
            return False
        menu = Gtk.Menu()
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        for text, value in (("Copiar valor", row[idx]), ("Copiar fila (separada por tabulaciones)", "\t".join(row)),
                            ("Copiar nombre de la columna", self.result.columns[idx])):
            mi = Gtk.MenuItem(label=text)
            mi.connect("activate", lambda _m, v=value: (clip.set_text(v, -1), self.app.toast("Copiado")))
            menu.append(mi)
        menu.show_all()
        self._menu = menu
        menu.popup_at_pointer(ev)
        return True

    def export_csv(self):
        if not self.result or not self.result.columns:
            self.app.toast("No hay resultados para exportar")
            return
        d = Gtk.FileChooserNative.new("Exportar a CSV", self.app.win, Gtk.FileChooserAction.SAVE, None, None)
        d.set_current_name(f"{self.host['name']}-{time.strftime('%Y%m%d-%H%M')}.csv")
        d.set_do_overwrite_confirmation(True)
        if d.run() == Gtk.ResponseType.ACCEPT:
            path = d.get_filename()
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(self.result.columns)
                w.writerows(self.result.rows)
            self.app.toast(f"Exportadas {len(self.result.rows)} fila(s)")
        d.destroy()

    # --- ciclo de vida -------------------------------------------------------------
    def close(self):
        self.closed = True
        if self.db is not None:
            threading.Thread(target=self.db.close, daemon=True).start()
        if self.tunnel is not None:
            self.tunnel.stop()

    def focus(self):
        self.editor.grab_focus()


GObject.type_register(DbTab)
