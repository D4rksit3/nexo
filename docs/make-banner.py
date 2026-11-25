"""Genera docs/img/nexo-banner.png (3:1, 2160x720) para la ficha de la Snap Store.
Uso: python3 docs/make-banner.py"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importlib import import_module  # noqa: E402

S = import_module("make-showcase")   # reutiliza fuentes, logo y estilo

W, H = 2160, 720
OUT = os.path.join(S.IMG, "nexo-banner.png")


def main():
    c = Image.new("RGBA", (W, H), S.BG + (255,))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse([-400, -500, 1100, 700], fill=(61, 220, 132, 50))
    g.ellipse([1300, 200, 2600, 1300], fill=(61, 160, 220, 28))
    c.alpha_composite(glow.filter(ImageFilter.GaussianBlur(150)))
    d = ImageDraw.Draw(c)

    # texto a la izquierda
    x0 = 110
    c.alpha_composite(S.logo(132), (x0, 150))
    d.text((x0 + 160, 140), "Nexo", font=S.font(112, 750), fill=S.FG)
    d.text((x0, 330), "SSH · SFTP · RDP · túneles · bases de datos", font=S.font(40, 560), fill=S.FG)
    d.text((x0, 392), "con bóveda cifrada, en una sola app ligera.", font=S.font(34, 420), fill=S.MUTED)
    chips = ["PostgreSQL", "MySQL", "SQL Server", "MongoDB", "Redis"]
    cf = S.font(24, 560)
    cx, cy = x0, 480
    for t in chips:
        tw = d.textlength(t, font=cf)
        d.rounded_rectangle([cx, cy, cx + tw + 36, cy + 48], 24, fill=(20, 26, 24), outline=(36, 74, 54), width=2)
        d.text((cx + 18, cy + 10), t, font=cf, fill=(170, 236, 198))
        cx += tw + 36 + 12
    d.text((x0, 580), "Código abierto (MIT)", font=S.font(26, 450), fill=(110, 118, 130))

    # captura a la derecha, recortada por el borde del banner
    shot = Image.open(os.path.join(S.IMG, "app-03-terminales-divididas.png")).convert("RGBA")
    sw = 1080
    shot = shot.resize((sw, round(shot.height * sw / shot.width)), Image.LANCZOS)
    sx, sy = 1180, 90
    sh = Image.new("RGBA", (sw + 120, shot.height + 120), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([60, 76, sw + 60, shot.height + 76], 20, fill=(0, 0, 0, 190))
    c.alpha_composite(sh.filter(ImageFilter.GaussianBlur(26)), (sx - 60, sy - 60))
    c.paste(shot, (sx, sy), S.rounded_mask(shot.size, 20))
    ImageDraw.Draw(c).rounded_rectangle([sx, sy, sx + sw - 1, sy + shot.height - 1], 20, outline=S.BORDER, width=2)

    c.convert("RGB").save(OUT, optimize=True)
    print(OUT, os.path.getsize(OUT) // 1024, "KB")


if __name__ == "__main__":
    main()
