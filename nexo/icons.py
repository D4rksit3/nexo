"""Iconos de hosts y grupos: Bootstrap Icons (MIT, https://icons.getbootstrap.com).

Los SVG están en nexo/bi/ como iconos «symbolic» de GTK, así que toman el color
por CSS (clase .bi-<clave>) y combinan con cualquier tema.
"""
import os

BI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bi")

# clave: (icono de Bootstrap, etiqueta, color)
ICONS = {
    "linux": ("terminal", "Linux", "#7ee787"),
    "ubuntu": ("ubuntu", "Ubuntu", "#f0794a"),
    "windows": ("windows", "Windows", "#4cc2ff"),
    "mac": ("apple", "macOS", "#d0d4dc"),
    "android": ("android2", "Android", "#8fd18a"),
    "server": ("hdd-rack", "Servidor", "#9aa7bd"),
    "pc": ("pc-display", "PC", "#8ccaff"),
    "laptop": ("laptop", "Laptop", "#8ccaff"),
    "db": ("database", "Base de datos", "#f2c66d"),
    "web": ("globe2", "Web", "#6cb6ff"),
    "docker": ("boxes", "Contenedores", "#3aa3ff"),
    "cloud": ("cloud", "Nube", "#8ccaff"),
    "firewall": ("bricks", "Firewall", "#ff7b72"),
    "router": ("router", "Router", "#c79bf2"),
    "network": ("diagram-3", "Red", "#c79bf2"),
    "wifi": ("wifi", "Wi-Fi", "#56d4d4"),
    "vpn": ("shield-lock", "VPN / seguridad", "#56d4d4"),
    "camera": ("camera-video", "Cámaras", "#ff9f43"),
    "backup": ("archive", "Respaldo", "#a6adc8"),
    "storage": ("hdd-stack", "Almacenamiento", "#a6adc8"),
    "cpu": ("cpu", "Hardware", "#9aa7bd"),
    "ai": ("robot", "IA", "#d7b4f8"),
    "mail": ("envelope", "Correo", "#6cb6ff"),
    "monitor": ("activity", "Monitoreo", "#7ee787"),
    "speed": ("speedometer2", "Rendimiento", "#7ee787"),
    "code": ("code-slash", "Desarrollo", "#c79bf2"),
    "git": ("git", "Git", "#f0794a"),
    "github": ("github", "GitHub", "#d0d4dc"),
    "test": ("bug", "Pruebas", "#f9d98b"),
    "prod": ("rocket-takeoff", "Producción", "#ff8796"),
    "printer": ("printer", "Impresora", "#a6adc8"),
    "phone": ("phone", "Teléfono", "#a6adc8"),
    "key": ("key", "Llaves / accesos", "#f2c66d"),
    "lock": ("lock", "Restringido", "#ff8796"),
    "gear": ("gear", "Configuración", "#9aa7bd"),
    "people": ("people", "Usuarios", "#8ccaff"),
    "shop": ("shop", "Tienda / retail", "#f0794a"),
    "bank": ("bank", "Finanzas", "#f2c66d"),
    "hospital": ("hospital", "Salud", "#ff8796"),
    "truck": ("truck", "Logística", "#f9d98b"),
    "home": ("house", "Casa", "#a6e3a1"),
    "office": ("building", "Oficina / sede", "#8ccaff"),
    "geo": ("geo-alt", "Ubicación", "#ff7b72"),
    "fire": ("fire", "Crítico", "#ff6b3d"),
    "star": ("star", "Favorito", "#f2c66d"),
    "warning": ("exclamation-triangle", "Cuidado", "#ffb000"),
    "folder": ("folder", "Carpeta", None),
    "box": ("inbox", "Otros", None),
}


# Iconos de la interfaz (también Bootstrap Icons): nombre lógico -> icono
UI = {
    "hosts": "hdd-network", "keys": "key", "tunnels": "arrow-left-right", "terminal": "terminal",
    "palette": "palette", "settings": "sliders", "lock": "lock", "plus": "plus-lg",
    "zoom-in": "zoom-in", "zoom-out": "zoom-out",
    "folder-plus": "folder-plus", "search": "search", "more": "three-dots-vertical", "play": "play-fill",
    "sftp": "folder2-open", "chevron-down": "chevron-down", "chevron-right": "chevron-right", "chevron-left": "chevron-left",
    "close": "x-lg", "split-right": "layout-split", "split-down": "window-split", "sidebar": "layout-sidebar",
    "popout": "box-arrow-up-right", "home": "house", "command": "command", "copy": "copy",
    "upload": "upload", "download": "download", "up": "arrow-up", "refresh": "arrow-clockwise",
    "trash": "trash3", "edit": "pencil", "grip": "grip-vertical", "broadcast": "broadcast",
    "shield": "shield-lock", "bolt": "lightning-charge", "plug": "plug", "recent": "clock-history",
    "import": "box-arrow-in-right", "new-folder": "folder-plus", "upload-folder": "file-earmark-arrow-up",
    "org": "building", "table": "table", "view": "eye", "collection": "collection", "database": "database",
    "key2": "key", "github": "github", "releases": "rocket-takeoff",
}


def ui_name(name):
    return f"bi-{UI[name]}-symbolic"


def ui_image(name, size=16):
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    img = Gtk.Image.new_from_icon_name(ui_name(name), Gtk.IconSize.BUTTON)
    img.set_pixel_size(size)
    return img


def icon_name(key, fallback="server"):
    bi = ICONS.get(key or "", ICONS[fallback])[0]
    return f"bi-{bi}-symbolic"


def label(key):
    return ICONS.get(key or "", ("", key or "", None))[1]


def host_icon(host):
    """Icono elegido o, si no hay, uno según el protocolo."""
    if host.get("icon") in ICONS:
        return host["icon"]
    p = host.get("protocol")
    if p in ("postgres", "mysql", "mssql", "mongodb", "redis"):
        return "db"
    return "windows" if p == "rdp" else "linux"


def image(key, size=22, fallback="server"):
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    k = key if key in ICONS else fallback
    img = Gtk.Image.new_from_icon_name(icon_name(k), Gtk.IconSize.BUTTON)
    img.set_pixel_size(size)
    img.get_style_context().add_class(f"bi-{k}")
    img.set_tooltip_text(label(k))
    return img


def css():
    """Color de cada icono (los que no tienen color usan el acento del tema)."""
    rules = [f".bi-{k} {{ color: {c}; }}" for k, (_, _, c) in ICONS.items() if c]
    rules.append(".bi-folder, .bi-box { color: @acc; }")
    return "\n".join(rules) + "\n"


def install():
    """Registra la carpeta de iconos en el tema de GTK (llamar una vez al iniciar)."""
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    Gtk.IconTheme.get_default().append_search_path(BI_DIR)
