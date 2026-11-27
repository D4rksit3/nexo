#!/usr/bin/env python3
"""Genera los logos del paquete MSIX (Microsoft Store) a partir de nexo/nexo.svg.

Se corre en Linux (usa librsvg por GObject) y los PNG quedan versionados en
packaging/msix/Assets, así la compilación en Windows no necesita rasterizar SVG.

    python3 packaging/msix/make-assets.py
"""
import io
import os

import gi

gi.require_version("Rsvg", "2.0")
import cairo  # noqa: E402
from gi.repository import Rsvg  # noqa: E402
from PIL import Image  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SVG = os.path.join(ROOT, "nexo", "nexo.svg")
OUT = os.path.join(HERE, "Assets")
BG = (11, 13, 16, 255)  # #0b0d10, el fondo del logo


def render(px):
    handle = Rsvg.Handle.new_from_file(SVG)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
    ctx = cairo.Context(surf)
    rect = Rsvg.Rectangle()
    rect.x, rect.y, rect.width, rect.height = 0, 0, px, px
    handle.render_document(ctx, rect)
    buf = io.BytesIO()
    surf.write_to_png(buf)
    buf.seek(0)
    return Image.open(buf).convert("RGBA")


def tile(w, h, logo_ratio, bg=BG):
    """Logo centrado en un lienzo de w×h; el lado del logo es logo_ratio × min(w, h)."""
    side = round(min(w, h) * logo_ratio)
    img = Image.new("RGBA", (w, h), bg)
    logo = render(side)
    img.alpha_composite(logo, ((w - side) // 2, (h - side) // 2))
    return img


def save(img, name):
    img.save(os.path.join(OUT, name), optimize=True)


def main():
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        if f.endswith(".png"):
            os.remove(os.path.join(OUT, f))
    clear = (0, 0, 0, 0)
    for scale in (100, 125, 150, 200, 400):
        k = scale / 100
        # Mosaicos del menú Inicio: fondo del logo, logo al 66 %.
        save(tile(round(150 * k), round(150 * k), 0.66), f"Square150x150Logo.scale-{scale}.png")
        save(tile(round(310 * k), round(150 * k), 0.66), f"Wide310x150Logo.scale-{scale}.png")
        save(tile(round(71 * k), round(71 * k), 0.80), f"Square71x71Logo.scale-{scale}.png")
        # Icono de la app (barra de tareas, lista de apps): el propio logo, transparente.
        save(tile(round(44 * k), round(44 * k), 1.0, clear), f"Square44x44Logo.scale-{scale}.png")
        save(tile(round(50 * k), round(50 * k), 1.0, clear), f"StoreLogo.scale-{scale}.png")
        save(tile(round(620 * k), round(300 * k), 0.50), f"SplashScreen.scale-{scale}.png")
    # Tamaños exactos de la barra de tareas, sin la placa de color del sistema.
    for size in (16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 80, 96, 256):
        img = tile(size, size, 1.0, clear)
        save(img, f"Square44x44Logo.targetsize-{size}.png")
        save(img, f"Square44x44Logo.targetsize-{size}_altform-unplated.png")
        save(img, f"Square44x44Logo.targetsize-{size}_altform-lightunplated.png")
    print(f"{len(os.listdir(OUT))} PNG en {OUT}")


if __name__ == "__main__":
    main()
