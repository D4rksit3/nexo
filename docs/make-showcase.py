"""Genera docs/img/nexo-todo-en-uno.png: una sola imagen con todas las funciones.
Uso: python3 docs/make-showcase.py   (requiere Pillow, Inter y el logo SVG vía GdkPixbuf)"""
import os
import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "docs", "img")
INTER = "/usr/share/fonts/truetype/inter-vf/InterVariable.ttf"
MONO = "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf"

W, H = 2400, 1800
M, G = 60, 36                      # margen exterior y separación
BG = (9, 10, 13)
FG = (228, 231, 236)
MUTED = (140, 148, 160)
ACC = (61, 220, 132)
BORDER = (38, 42, 50)


def font(size, weight=400):
    f = ImageFont.truetype(INTER, size)
    try:
        f.set_variation_by_axes([14 if size < 20 else 32, weight])
    except Exception:
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
    return f


def logo(size):
    pb = GdkPixbuf.Pixbuf.new_from_file_at_size(os.path.join(ROOT, "nexo", "nexo.svg"), size, size)
    ok, buf = pb.save_to_bufferv("png", [], [])
    import io
    return Image.open(io.BytesIO(buf)).convert("RGBA")


def rounded_mask(size, r):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], r, fill=255)
    return m


def tile(canvas, path, box, title, sub, crop=None):
    x, y, w, h = box
    im = Image.open(os.path.join(IMG, path)).convert("RGB")
    if crop:
        im = im.crop(crop)
    # «cover» anclado arriba a la izquierda: ahí está lo importante de cada captura
    s = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS).crop((0, 0, w, h))
    # sombra
    sh = Image.new("RGBA", (w + 80, h + 80), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([40, 52, w + 40, h + 52], 18, fill=(0, 0, 0, 170))
    canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(22)), (x - 40, y - 40))
    # degradado inferior para el rótulo
    im = im.convert("RGBA")
    grad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    band = 190
    for i in range(band):
        a = int(250 * min(1, (i / band) * 1.5) ** 1.3)
        gd.line([(0, h - band + i), (w, h - band + i)], fill=(6, 7, 9, a))
    im.alpha_composite(grad)
    d = ImageDraw.Draw(im)
    tf, sf = font(30 if w > 900 else 24, 650), font(20 if w > 900 else 17, 420)
    ty = h - (82 if w > 900 else 70)
    d.ellipse([22, ty + 11, 34, ty + 23], fill=ACC)
    d.text((46, ty), title, font=tf, fill=FG)
    d.text((46, ty + (40 if w > 900 else 33)), sub, font=sf, fill=MUTED)
    canvas.paste(im, (x, y), rounded_mask((w, h), 18))
    ImageDraw.Draw(canvas).rounded_rectangle([x, y, x + w - 1, y + h - 1], 18, outline=BORDER, width=2)


def main():
    c = Image.new("RGBA", (W, H), BG + (255,))
    # resplandor verde de fondo
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-300, -500, 1300, 500], fill=(61, 220, 132, 46))
    gd.ellipse([1500, 1200, 2900, 2300], fill=(61, 160, 220, 26))
    c.alpha_composite(glow.filter(ImageFilter.GaussianBlur(160)))
    d = ImageDraw.Draw(c)

    # --- cabecera
    lg = logo(104)
    c.alpha_composite(lg, (M, 58))
    d.text((M + 132, 52), "Nexo", font=font(84, 750), fill=FG)
    d.text((M + 136, 150), "SSH, SFTP, RDP, túneles y bases de datos con bóveda cifrada · servidor propio para tu organización",
           font=font(29, 420), fill=MUTED)
    chips = ["SSH", "SFTP", "RDP", "Túneles", "PostgreSQL", "MySQL", "SQL Server", "MongoDB", "Redis",
             "2FA", "Grabación", "Linux · Windows"]
    cf = font(21, 560)
    cx, cy = M, 222
    for t in chips:
        tw = d.textlength(t, font=cf)
        d.rounded_rectangle([cx, cy, cx + tw + 34, cy + 42], 21, fill=(20, 26, 24), outline=(36, 74, 54), width=2)
        d.text((cx + 17, cy + 9), t, font=cf, fill=(170, 236, 198))
        cx += tw + 34 + 12

    # --- cuadrícula
    top = 300
    usable = W - 2 * M
    w2 = 730
    w1 = usable - w2 - G
    h1 = round(w1 * 876 / 1370)
    h2 = (h1 - G) // 2
    tile(c, "app-03-terminales-divididas.png", (M, top, w1, h1),
         "Terminales SSH en pestañas y paneles", "Arrastra pestañas a los costados para dividir · saltos con contraseña o llave")
    tile(c, "app-08-postgres.png", (M + w1 + G, top, w2, h2),
         "Bases de datos", "PostgreSQL · MySQL · SQL Server · MongoDB · Redis", (392, 85, 1370, 713))
    tile(c, "web-03-resumen.png", (M + w1 + G, top + h2 + G, w2, h2),
         "Nexo Server (Docker)", "Usuarios con 2FA, permisos, bloqueo y auditoría", (220, 0, 1360, 728))

    y2 = top + h1 + G
    n = 4
    w3 = (usable - (n - 1) * G) // n
    h3 = H - y2 - 92
    row = [
        ("app-06-organizaciones.png", "Organizaciones", "Accesos sin entregar llaves", (60, 40, 1160, 858)),
        ("web-07-grabacion.png", "Grabación de sesiones", "Reproduce lo que se hizo", (240, 2, 1340, 820)),
        ("app-09-mongodb.png", "MongoDB y Redis", "Filtros JSON · solo lectura", (80, 58, 1180, 876)),
        ("app-05-temas.png", "14 temas oscuros", "Toda la app se tiñe", (300, 40, 1370, 836)),
    ]
    for i, (p, t, s, cr) in enumerate(row):
        tile(c, p, (M + i * (w3 + G), y2, w3, h3), t, s, cr)

    # --- pie
    pf = font(21, 450)
    foot = "Bóveda local AES-256-GCM + scrypt  ·  Código abierto (MIT)  ·  github.com/D4rksit3/nexo"
    d.text(((W - d.textlength(foot, font=pf)) / 2, H - 58), foot, font=pf, fill=(110, 118, 130))

    out = os.path.join(IMG, "nexo-todo-en-uno.png")
    c.convert("RGB").save(out, optimize=True)
    print(out)


if __name__ == "__main__":
    main()
