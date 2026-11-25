"""Widgets visuales: selector de cuadrícula y tarjetas de tema."""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from . import themes as T  # noqa: E402


def _rgb(h):
    c = Gdk.RGBA()
    c.parse(h)
    return c.red, c.green, c.blue


def _round_rect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.close_path()


class GridPicker(Gtk.Box):
    """Pasa el ratón sobre los cuadros y haz clic: filas × columnas, como al insertar una tabla."""

    CELL, GAP, MAX_R, MAX_C = 26, 4, 6, 6

    def __init__(self, app, on_pick):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.app = app
        self.on_pick = on_pick
        self.hover = (0, 0)
        self.area = Gtk.DrawingArea()
        w = self.MAX_C * (self.CELL + self.GAP)
        h = self.MAX_R * (self.CELL + self.GAP)
        self.area.set_size_request(w, h)
        self.area.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK |
                             Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.area.connect("draw", self._draw)
        self.area.connect("motion-notify-event", self._motion)
        self.area.connect("leave-notify-event", lambda *_: self._set(0, 0))
        self.area.connect("button-press-event", self._click)
        self.label = Gtk.Label(label="Elige filas × columnas")
        self.label.get_style_context().add_class("dim-label")
        self.pack_start(self.area, False, False, 0)
        self.pack_start(self.label, False, False, 0)

    def _cell_at(self, x, y):
        step = self.CELL + self.GAP
        return (min(self.MAX_R, int(y // step) + 1), min(self.MAX_C, int(x // step) + 1))

    def _set(self, r, c):
        if (r, c) != self.hover:
            self.hover = (r, c)
            self.label.set_text(f"{r} × {c}  =  {r * c} paneles" if r and c else "Elige filas × columnas")
            self.area.queue_draw()

    def _motion(self, w, ev):
        self._set(*self._cell_at(ev.x, ev.y))

    def _click(self, w, ev):
        r, c = self._cell_at(ev.x, ev.y)
        self.on_pick(r, c)
        return True

    def _draw(self, w, cr):
        t = self.app.theme
        acc, fg = _rgb(t["accent"]), _rgb(t["fg"])
        step = self.CELL + self.GAP
        hr, hc = self.hover
        for r in range(self.MAX_R):
            for c in range(self.MAX_C):
                on = r < hr and c < hc
                _round_rect(cr, c * step, r * step, self.CELL, self.CELL, 4)
                if on:
                    cr.set_source_rgba(*acc, 0.85)
                    cr.fill()
                else:
                    cr.set_source_rgba(*fg, 0.10)
                    cr.fill_preserve()
                    cr.set_source_rgba(*fg, 0.25)
                    cr.set_line_width(1)
                    cr.stroke()
        return False


class AccentDot(Gtk.EventBox):
    """Círculo de color para elegir el acento."""

    def __init__(self, accent_id, theme_accent, selected, on_pick):
        super().__init__()
        name, color = T.ACCENTS[accent_id]
        self.accent_id = accent_id
        self.color = color or theme_accent
        self.is_theme = color is None
        self.selected = selected
        self.set_tooltip_text(name if color else f"Del tema ({name.lower()})")
        self.area = Gtk.DrawingArea()
        self.area.set_size_request(30, 30)
        self.area.connect("draw", self._draw)
        self.add(self.area)
        self.connect("button-release-event", lambda *_: (on_pick(accent_id), True)[1])

    def set_selected(self, sel, theme_accent=None):
        if theme_accent and self.is_theme:
            self.color = theme_accent
        self.selected = sel
        self.area.queue_draw()

    def _draw(self, w, cr):
        W, H = w.get_allocated_width(), w.get_allocated_height()
        r = min(W, H) / 2 - 4
        cr.arc(W / 2, H / 2, r, 0, 6.2832)
        cr.set_source_rgb(*_rgb(self.color))
        cr.fill()
        if self.is_theme:  # anillo: «el del tema»
            cr.arc(W / 2, H / 2, r - 4, 0, 6.2832)
            cr.set_source_rgba(0, 0, 0, 0.45)
            cr.fill()
        if self.selected:
            cr.arc(W / 2, H / 2, r + 2.5, 0, 6.2832)
            cr.set_source_rgba(1, 1, 1, 0.9)
            cr.set_line_width(2)
            cr.stroke()
        return False


class ThemeCard(Gtk.EventBox):
    """Vista previa de un tema: fondo, texto, colores y acento."""

    def __init__(self, theme_id, selected, on_pick):
        super().__init__()
        self.t = T.get(theme_id)
        self.selected = selected
        self.set_tooltip_text(self.t["name"])
        area = Gtk.DrawingArea()
        area.set_size_request(168, 104)
        area.connect("draw", self._draw)
        self.add(area)
        self.connect("button-release-event", lambda *_: (on_pick(theme_id), True)[1])
        self.connect("enter-notify-event", lambda *_: (setattr(self, "hover", True), area.queue_draw()))
        self.connect("leave-notify-event", lambda *_: (setattr(self, "hover", False), area.queue_draw()))
        self.hover = False
        self.area = area

    def set_selected(self, selected):
        if selected != self.selected:
            self.selected = selected
            self.area.queue_draw()

    def _draw(self, w, cr):
        t = self.t
        W, H = w.get_allocated_width(), w.get_allocated_height()
        _round_rect(cr, 2, 2, W - 4, H - 4, 9)
        cr.set_source_rgb(*_rgb(t["bg"]))
        cr.fill_preserve()
        if self.selected or self.hover:
            cr.set_source_rgb(*_rgb(t["accent"]))
            cr.set_line_width(3 if self.selected else 1.5)
        else:
            cr.set_source_rgba(1, 1, 1, 0.12)
            cr.set_line_width(1)
        cr.stroke()
        cr.select_font_face("Monospace")
        cr.set_font_size(11)
        p = t["palette"]
        lines = [[(p[2], "juan@nodo"), (t["fg"], ":"), (p[4], "~"), (t["fg"], "$ ls")],
                 [(p[4], "conf/ "), (p[2], "run.sh "), (t["fg"], "log")],
                 [(p[1], "error "), (p[3], "aviso "), (p[6], "ok")]]
        y = 20
        for line in lines:
            x = 12
            for color, text in line:
                cr.set_source_rgb(*_rgb(color))
                cr.move_to(x, y)
                cr.show_text(text)
                x += cr.text_extents(text).x_advance
            y += 15
        sy = H - 36
        cr.set_source_rgb(*_rgb(t["accent"]))
        cr.rectangle(12, sy, 26, 7)
        cr.fill()
        for i, c in enumerate((p[1], p[2], p[3], p[4], p[5], p[6])):
            cr.set_source_rgb(*_rgb(c))
            cr.rectangle(44 + i * 12, sy, 9, 7)
            cr.fill()
        cr.select_font_face("Sans", 0, 1)
        cr.set_font_size(10.5)
        cr.set_source_rgb(*_rgb(t["accent"] if self.selected else t["fg"]))
        cr.move_to(12, H - 12)
        cr.show_text(t["name"] + ("  (actual)" if self.selected else ""))
        return False
