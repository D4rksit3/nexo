"""Fondo animado en ASCII: plasma de caracteres, flujos de datos y «pings» de red.

Se dibuja con Cairo detrás de la pantalla de Inicio y de la de bloqueo, teñido con el
acento del tema. Solo anima mientras está visible (se detiene al cambiar de pestaña).
"""
import math
import random

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

RAMP = " .,:;-=+*x#%@"        # de tenue a denso
HEX = "0123456789abcdef"
STREAM_CHARS = HEX + "<>/\\|$#{}[]"
LEVELS = 9                    # niveles de intensidad (0 = vacío)
FRAME_MS = 70                 # ~14 fps: fluido y barato
FONT_PX = 12


def _rgb(h):
    c = Gdk.RGBA()
    c.parse(h)
    return c.red, c.green, c.blue


class _Stream:
    __slots__ = ("col", "y", "speed", "length", "chars")

    def __init__(self, cols, rows, start_above=True):
        self.col = random.randrange(max(1, cols))
        self.length = random.randint(5, 16)
        self.y = -random.uniform(0, rows) if start_above else random.uniform(0, rows)
        self.speed = random.uniform(0.25, 0.8)
        self.chars = [random.choice(STREAM_CHARS) for _ in range(self.length)]


class _Ping:
    __slots__ = ("x", "y", "r", "rmax")

    def __init__(self, x, y):
        self.x, self.y, self.r = x, y, 0.0
        self.rmax = random.uniform(14, 26)


class AsciiBackdrop(Gtk.DrawingArea):
    """`focus`: widget (tarjeta o columna) cuyo fondo se atenúa para que el texto se lea bien."""

    def __init__(self, app, focus=None):
        super().__init__()
        self.app = app
        self.focus = focus
        self.t = random.uniform(0, 100)
        self._timer = None
        self._idle = 0
        self._grid = None          # (cols, rows, cw, ch)
        self._mask = None
        self._mask_key = None
        self._dist = None
        self.streams = []
        self.pings = []
        self.set_can_focus(False)
        self.connect("draw", self._draw)
        self.connect("map", lambda *_: self._start())
        self.connect("unmap", lambda *_: self._stop())
        self.connect("size-allocate", lambda *_: setattr(self, "_grid", None))

    # --- ciclo de animación ------------------------------------------------
    def enabled(self):
        return self.app.ui.get("ascii_bg", True)

    def _animate(self):
        s = Gtk.Settings.get_default()
        return self.enabled() and (s is None or s.get_property("gtk-enable-animations"))

    def _start(self):
        if self._timer is None and self._animate():
            self._timer = GLib.timeout_add(FRAME_MS, self._tick)

    def _stop(self):
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def refresh(self):
        """Tras activar/desactivar el fondo en los ajustes."""
        self._stop()
        if self.get_mapped():
            self._start()
        self.queue_draw()

    def _tick(self):
        if not self._animate():
            self._timer = None
            self.queue_draw()
            return False
        top = self.get_toplevel()
        if isinstance(top, Gtk.Window) and not top.is_active():
            self._idle = (self._idle + 1) % 3          # sin foco: ~1/3 de los cuadros
            if self._idle:
                return True
        self.t += FRAME_MS / 1000
        if self._grid:
            cols, rows = self._grid[0], self._grid[1]
            for s in self.streams:
                s.y += s.speed
                if random.random() < 0.25:
                    s.chars[random.randrange(s.length)] = random.choice(STREAM_CHARS)
            self.streams = [s for s in self.streams if s.y - s.length < rows] or self.streams
            while len(self.streams) < max(3, cols // 9):
                self.streams.append(_Stream(cols, rows))
            for p in self.pings:
                p.r += 0.45
            self.pings = [p for p in self.pings if p.r < p.rmax]
            if len(self.pings) < 2 and random.random() < 0.012:
                self.pings.append(_Ping(random.uniform(0, cols), random.uniform(0, rows)))
        self.queue_draw()
        return True

    # --- geometría -----------------------------------------------------------
    def _layout(self, cr, w, h):
        cr.select_font_face("JetBrains Mono", 0, 0)
        cr.set_font_size(FONT_PX)
        fe = cr.font_extents()
        cw = cr.text_extents("M").x_advance or FONT_PX * 0.6
        ch = math.ceil(fe[2]) + 2
        cols, rows = int(w // cw) + 1, int(h // ch) + 1
        self._grid = (cols, rows, cw, ch, fe[0])
        cx, cy = cols / 2, rows * 0.45
        k = cw / ch
        self._dist = [[math.hypot((x - cx) * k, y - cy) for x in range(cols)] for y in range(rows)]
        self.streams = [_Stream(cols, rows, start_above=False) for _ in range(max(3, cols // 9))]
        self.pings = []
        self._mask_key = None

    def _focus_rect(self):
        f = self.focus
        if f is None or not f.get_mapped():
            return None
        pos = f.translate_coordinates(self, 0, 0)
        if not pos:
            return None
        a = f.get_allocation()
        return (pos[0], pos[1], a.width, a.height)

    def _build_mask(self, rect):
        """Peso 0..1 por celda: bajo detrás del contenido, sube suavemente hacia afuera."""
        cols, rows, cw, ch = self._grid[:4]
        if rect is None:
            self._mask = [[1.0] * cols for _ in range(rows)]
            return
        rx, ry, rw, rh = rect
        pad, ramp = 18, 140.0
        mask = []
        for y in range(rows):
            py = y * ch + ch / 2
            dy = max(ry - pad - py, 0, py - (ry + rh + pad))
            row = []
            for x in range(cols):
                px = x * cw + cw / 2
                dx = max(rx - pad - px, 0, px - (rx + rw + pad))
                d = math.hypot(dx, dy) / ramp
                d = 1.0 if d > 1 else d * d * (3 - 2 * d)
                row.append(0.12 + 0.88 * d)
            mask.append(row)
        self._mask = mask

    # --- dibujo ----------------------------------------------------------------
    def _draw(self, w, cr):
        if not self.enabled():
            return False
        W, H = w.get_allocated_width(), w.get_allocated_height()
        if W < 10 or H < 10:
            return False
        if self._grid is None:
            self._layout(cr, W, H)
        else:
            cr.select_font_face("JetBrains Mono", 0, 0)
            cr.set_font_size(FONT_PX)
        cols, rows, cw, ch, asc = self._grid
        rect = self._focus_rect()
        key = (rect, cols, rows)
        if key != self._mask_key:
            self._build_mask(rect)
            self._mask_key = key

        t = self.t
        sin = math.sin
        k = cw / ch
        # plasma con deformación de dominio → curvas de nivel tipo mapa topográfico
        warp_r = [1.7 * sin(y * 0.09 + t * 0.33) for y in range(rows)]
        warp_c = [1.5 * sin(x * k * 0.065 - t * 0.27) for x in range(cols)]
        ux = [x * k * 0.075 for x in range(cols)]
        nr = len(RAMP) - 1
        a1, a2, a3 = t * 0.4, t * 0.5, t * 0.9

        lv = [[0] * cols for _ in range(rows)]
        chs = [[" "] * cols for _ in range(rows)]
        for y in range(rows):
            dist, mrow, lrow, crow = self._dist[y], self._mask[y], lv[y], chs[y]
            wr, yy = warp_r[y], y * 0.12 - a2
            for x in range(cols):
                n = (sin(ux[x] + wr + a1) + sin(yy + warp_c[x]) + sin(dist[x] * 0.14 - a3)) * 0.1667 + 0.5
                q = n * 6
                d = abs(q - round(q))                       # distancia a la curva de nivel
                line = 1 - d / 0.2 if d < 0.2 else 0.0
                v = (line * (0.35 + 0.65 * n) + n * n * n * n * 0.26) * mrow[x]
                if v > 0.06:
                    lrow[x] = min(LEVELS - 1, int(v * LEVELS) + 1)
                    crow[x] = RAMP[min(nr, int(v * nr * 1.15) + 1)]

        for p in self.pings:
            life = 1 - p.r / p.rmax
            y0, y1 = max(0, int(p.y - p.r - 2)), min(rows, int(p.y + p.r + 3))
            span = (p.r + 2) / k
            x0, x1 = max(0, int(p.x - span)), min(cols, int(p.x + span + 1))
            for y in range(y0, y1):
                mrow, lrow, crow = self._mask[y], lv[y], chs[y]
                for x in range(x0, x1):
                    g = abs(math.hypot((x - p.x) * k, y - p.y) - p.r)
                    if g < 1.0:
                        b = int((1 - g) * life * mrow[x] * (LEVELS - 1))
                        if b > lrow[x]:
                            lrow[x] = b
                            crow[x] = "o" if g < 0.35 else "."

        heads = []
        for s in self.streams:
            hy = int(s.y)
            for i in range(s.length):
                y = hy - i
                if 0 <= y < rows and s.col < cols:
                    m = self._mask[y][s.col]
                    b = int((1 - i / s.length) * m * (LEVELS - 1)) if i else 0
                    if i == 0:
                        if m > 0.4:
                            heads.append((s.col, y, s.chars[0], m))
                        lv[y][s.col] = 0
                    elif b > lv[y][s.col]:
                        lv[y][s.col] = b
                        chs[y][s.col] = s.chars[i]

        # agrupa por nivel: una línea de texto por fila y nivel (monoespaciado)
        th = self.app.theme
        acc, fg = _rgb(th["accent"]), _rgb(th["fg"])
        buckets = {}
        for y in range(rows):
            lrow, crow = lv[y], chs[y]
            for x in range(cols):
                l = lrow[x]
                if l:
                    line = buckets.setdefault(l, {}).get(y)
                    if line is None:
                        line = buckets[l][y] = [" "] * cols
                    line[x] = crow[x]
        for l, lines in buckets.items():
            f = l / (LEVELS - 1)
            mix = 0.35 + 0.65 * f
            cr.set_source_rgba(fg[0] + (acc[0] - fg[0]) * mix, fg[1] + (acc[1] - fg[1]) * mix,
                               fg[2] + (acc[2] - fg[2]) * mix, 0.06 + 0.30 * f)
            for y, line in lines.items():
                cr.move_to(0, y * ch + asc + 1)
                cr.show_text("".join(line).rstrip())
        for x, y, c, m in heads:
            cr.set_source_rgba((acc[0] + fg[0]) / 2, (acc[1] + fg[1]) / 2, (acc[2] + fg[2]) / 2, 0.75 * m)
            cr.move_to(x * cw, y * ch + asc + 1)
            cr.show_text(c)
        return False
