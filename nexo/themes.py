"""Temas: paleta de la terminal + colores de toda la interfaz derivados de ella."""
import json
import os

_CONFIG_BASE = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
CONFIG_DIR = os.path.join(_CONFIG_BASE, "nexo")
UI_CONFIG = os.path.join(CONFIG_DIR, "ui.json")
LEGACY_UI = os.path.join(_CONFIG_BASE, "enlace", "ui.json")

# fondo, texto, acento, 16 colores ANSI
THEMES = {
    "negro": ("Nexo Negro", "#0b0c0f", "#d7dce5", "#7cc0ff",
              ["#1c1f26", "#ff6b7a", "#8fd18a", "#f2c66d", "#6cb6ff", "#c79bf2", "#5fd4d4", "#c8ced9",
               "#4b5263", "#ff8796", "#a6e3a1", "#f9d98b", "#8ccaff", "#d7b4f8", "#7ee3e3", "#f2f4f8"]),
    "carbon": ("Carbón", "#000000", "#e4e4e4", "#3ddc84",
               ["#121212", "#ff5f56", "#5af78e", "#f3f99d", "#57c7ff", "#ff6ac1", "#9aedfe", "#d0d0d0",
                "#505050", "#ff7b72", "#7ef7a8", "#f8fbb8", "#7fd4ff", "#ff8fd0", "#b5f2fe", "#ffffff"]),
    "oceano": ("Océano profundo", "#0a1220", "#c9d4e5", "#4fb3ff",
               ["#16213a", "#ff6e7f", "#7fd6a4", "#f5c86a", "#4fb3ff", "#a98bff", "#4fd8e0", "#c9d4e5",
                "#3a4a6b", "#ff8a98", "#9be6bb", "#f9d68c", "#7cc6ff", "#c0a8ff", "#7be5ea", "#eef3fb"]),
    "onedark": ("One Dark", "#21252b", "#abb2bf", "#61afef",
                ["#282c34", "#e06c75", "#98c379", "#e5c07b", "#61afef", "#c678dd", "#56b6c2", "#abb2bf",
                 "#5c6370", "#e06c75", "#98c379", "#e5c07b", "#61afef", "#c678dd", "#56b6c2", "#ffffff"]),
    "dracula": ("Dracula", "#22212c", "#f8f8f2", "#bd93f9",
                ["#21222c", "#ff5555", "#50fa7b", "#f1fa8c", "#bd93f9", "#ff79c6", "#8be9fd", "#f8f8f2",
                 "#6272a4", "#ff6e6e", "#69ff94", "#ffffa5", "#d6acff", "#ff92df", "#a4ffff", "#ffffff"]),
    "tokyo": ("Tokyo Night", "#16161e", "#c0caf5", "#7aa2f7",
              ["#15161e", "#f7768e", "#9ece6a", "#e0af68", "#7aa2f7", "#bb9af7", "#7dcfff", "#a9b1d6",
               "#414868", "#f7768e", "#9ece6a", "#e0af68", "#7aa2f7", "#bb9af7", "#7dcfff", "#c0caf5"]),
    "mocha": ("Catppuccin Mocha", "#181825", "#cdd6f4", "#cba6f7",
              ["#45475a", "#f38ba8", "#a6e3a1", "#f9e2af", "#89b4fa", "#f5c2e7", "#94e2d5", "#bac2de",
               "#585b70", "#f38ba8", "#a6e3a1", "#f9e2af", "#89b4fa", "#f5c2e7", "#94e2d5", "#a6adc8"]),
    "nord": ("Nord", "#242933", "#d8dee9", "#88c0d0",
             ["#3b4252", "#bf616a", "#a3be8c", "#ebcb8b", "#81a1c1", "#b48ead", "#88c0d0", "#e5e9f0",
              "#4c566a", "#bf616a", "#a3be8c", "#ebcb8b", "#81a1c1", "#b48ead", "#8fbcbb", "#eceff4"]),
    "gruvbox": ("Gruvbox", "#1d2021", "#ebdbb2", "#fabd2f",
                ["#282828", "#cc241d", "#98971a", "#d79921", "#458588", "#b16286", "#689d6a", "#a89984",
                 "#928374", "#fb4934", "#b8bb26", "#fabd2f", "#83a598", "#d3869b", "#8ec07c", "#ebdbb2"]),
    "solarized": ("Solarized Oscuro", "#002b36", "#93a1a1", "#268bd2",
                  ["#073642", "#dc322f", "#859900", "#b58900", "#268bd2", "#d33682", "#2aa198", "#eee8d5",
                   "#586e75", "#cb4b16", "#859900", "#b58900", "#268bd2", "#6c71c4", "#2aa198", "#fdf6e3"]),
    "monokai": ("Monokai", "#1e1f1c", "#f8f8f2", "#a6e22e",
                ["#272822", "#f92672", "#a6e22e", "#f4bf75", "#66d9ef", "#ae81ff", "#a1efe4", "#f8f8f2",
                 "#75715e", "#f92672", "#a6e22e", "#f4bf75", "#66d9ef", "#ae81ff", "#a1efe4", "#f9f8f5"]),
    "vino": ("Vino", "#150a0f", "#ecdce2", "#ff6f91",
             ["#24121a", "#ff5c7a", "#9fd8a4", "#f6c177", "#7fb4ff", "#e48fd6", "#7fd8d0", "#ecdce2",
              "#4d2a38", "#ff7f97", "#b7e6bb", "#f9d29a", "#9cc6ff", "#efaae4", "#9ee5df", "#fff2f6"]),
    "fosforo": ("Fósforo verde", "#030703", "#33ff66", "#33ff66",
                ["#0a120a", "#ff5f5f", "#33ff66", "#d7ff5f", "#5fd7af", "#87ff87", "#5fffd7", "#33ff66",
                 "#1f3d1f", "#ff8787", "#66ff99", "#e4ff8a", "#87e7c4", "#a8ffa8", "#8affe4", "#b3ffc6"]),
    "ambar": ("Ámbar", "#0b0700", "#ffb000", "#ffb000",
              ["#1a1000", "#ff5f3f", "#d7c35f", "#ffb000", "#ff9f40", "#ffcf70", "#e8c07a", "#ffb000",
               "#4a3000", "#ff7f5f", "#e4d27a", "#ffc640", "#ffb870", "#ffdc95", "#f0d29b", "#ffe0a3"]),
}
DEFAULT = "negro"

# Color de acento: None = el que trae el tema
ACCENTS = {
    "tema": ("Del tema", None),
    "verde": ("Verde", "#3ddc84"),
    "esmeralda": ("Esmeralda", "#10b981"),
    "lima": ("Lima", "#a3e635"),
    "cian": ("Cian", "#22d3ee"),
    "azul": ("Azul", "#4fa3ff"),
    "morado": ("Morado", "#b18cff"),
    "rosa": ("Rosa", "#f472b6"),
    "rojo": ("Rojo", "#ff5c6c"),
    "naranja": ("Naranja", "#ff9f43"),
    "amarillo": ("Amarillo", "#facc15"),
}


def get(theme_id, accent=None):
    name, bg, fg, theme_accent, palette = THEMES.get(theme_id) or THEMES[DEFAULT]
    acc = ACCENTS.get(accent or "tema", ACCENTS["tema"])[1] or theme_accent
    return {"id": theme_id if theme_id in THEMES else DEFAULT, "name": name, "bg": bg, "fg": fg,
            "accent": acc, "accent_id": accent if accent in ACCENTS else "tema", "palette": palette}


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def mix(a, b, t):
    """Mezcla a→b en proporción t (0..1)."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex([ra[i] + (rb[i] - ra[i]) * t for i in range(3)])


def luminance(h):
    r, g, b = (c / 255 for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def load_ui():
    try:
        path = UI_CONFIG if os.path.exists(UI_CONFIG) else LEGACY_UI
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_ui(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = UI_CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1)
    os.replace(tmp, UI_CONFIG)


def colors(t):
    """Colores de la interfaz derivados del tema (los usan la app GTK y la de Windows)."""
    bg, fg, acc = t["bg"], t["fg"], t["accent"]
    return {
        "win": mix(bg, "#000000", 0.20),
        "side": mix(bg, "#000000", 0.35),
        "head": mix(bg, "#000000", 0.45),
        "surf": mix(bg, "#ffffff", 0.06),
        "surf2": mix(bg, "#ffffff", 0.11),
        "surf3": mix(bg, "#ffffff", 0.17),
        "border": mix(bg, "#ffffff", 0.10),
        "fg": fg,
        "dim": mix(fg, bg, 0.45),
        "acc": acc,
        "acc_fg": "#0b0c0f" if luminance(acc) > 0.45 else "#ffffff",
        "sel": mix(bg, acc, 0.28),
        "term": bg,
        "line": mix(bg, "#ffffff", 0.075),
        "border2": mix(bg, "#ffffff", 0.15),
        "rail": mix(bg, "#000000", 0.55),
    }


def build_css(t):
    c = colors(t)
    css = """
window, .background, dialog, dialog .dialog-vbox, messagedialog, popover, popover.background,
menu, .menu, .context-menu, stack, notebook > stack, scrolledwindow, viewport, .enlace-lock {
  background-color: @win; color: @fg; }
window.background, decoration { border-color: @border; }
label { color: inherit; }
.dim-label, .enlace-sub { color: @dim; opacity: 1; }
headerbar, .titlebar, headerbar.titlebar {
  background-image: none; background-color: @head; color: @fg; border-color: @border; box-shadow: none; }
headerbar .title { color: @fg; font-weight: bold; } headerbar .subtitle { color: @dim; }
button, menubutton > button, stackswitcher > button, spinbutton button, combobox button,
headerbar button {
  background-image: none; background-color: @surf; color: @fg; border-color: @border;
  box-shadow: none; text-shadow: none; -gtk-icon-shadow: none; }
button:hover, headerbar button:hover { background-color: @surf2; }
button:active, button:checked, stackswitcher > button:checked { background-color: @sel; color: @fg; }
button:disabled { background-color: @win; color: @dim; }
button.flat, button.titlebutton, .enlace-sidebar button.flat, row button, .enlace-pane-header button {
  background-color: transparent; border-color: transparent; }
button.flat:hover, row button:hover, .enlace-pane-header button:hover { background-color: @surf2; }
button.titlebutton:hover { background-color: @surf2; }
.suggested-action, button.suggested-action { background-color: @acc; color: @acc_fg; border-color: @acc; }
.suggested-action:hover { background-color: shade(@acc, 1.1); }
.destructive-action, button.destructive-action { background-color: #c0392b; color: #fff; border-color: #c0392b; }
entry, spinbutton, spinbutton entry, searchbar entry, textview, textview text {
  background-image: none; background-color: @head; color: @fg; border-color: @border; box-shadow: none; caret-color: @acc; }
entry:focus, spinbutton:focus { border-color: @acc; box-shadow: inset 0 0 0 1px @acc; }
entry selection, textview text selection, label selection { background-color: @sel; color: @fg; }
list, listview, .enlace-sidebar list { background-color: transparent; color: @fg; }
.enlace-sidebar { background-color: @side; border-right: 1px solid @border; }
.enlace-sidebar row { padding: 6px 8px; border-radius: 8px; margin: 1px 6px; }
row:hover { background-color: alpha(@fg, 0.05); }
row:selected, row:selected:hover { background-color: @sel; color: @fg; }
notebook > header { background-color: @head; border-color: @border; box-shadow: none; }
notebook > header tab { color: @dim; background-color: transparent; border: none; box-shadow: none; }
notebook > header tab:hover { color: @fg; background-color: alpha(@fg, 0.04); }
notebook > header tab:checked { color: @fg; background-color: @win; box-shadow: inset 0 -2px @acc; }
notebook > header.top > tabs > tab:checked { box-shadow: inset 0 -2px @acc; }
treeview.view { background-color: @term; color: @fg; }
treeview.view:hover { background-color: alpha(@fg, 0.04); }
treeview.view:selected { background-color: @sel; color: @fg; }
treeview.view header button { background-color: @head; color: @dim; border-color: @border; }
scrollbar, scrollbar trough { background-color: transparent; border: none; }
scrollbar slider { background-color: alpha(@fg, 0.25); min-width: 6px; min-height: 6px; border: none; }
scrollbar slider:hover { background-color: alpha(@fg, 0.45); }
switch { background-image: none; background-color: @surf2; border-color: @border; }
switch:checked { background-color: @acc; }
switch slider { background-image: none; background-color: @fg; border-color: @border; }
progressbar progress { background-image: none; background-color: @acc; border-color: @acc; }
progressbar trough { background-color: @surf; border-color: @border; }
menuitem, menu menuitem { color: @fg; } menuitem:hover { background-color: @sel; }
menu separator, separator { background-color: @border; }
tooltip, tooltip.background { background-color: @head; color: @fg; border: 1px solid @border; }
combobox window, combobox menu { background-color: @win; }
paned > separator { background-color: @border; background-image: none; min-width: 3px; min-height: 3px; }
paned > separator:hover { background-color: @acc; }

.enlace-group { font-size: 0.78em; font-weight: bold; letter-spacing: 1px; color: @dim;
                padding: 12px 14px 4px 14px; }
.enlace-host-name { font-weight: bold; }
.enlace-badge { font-size: 0.7em; font-weight: bold; padding: 1px 6px; border-radius: 6px;
                background-color: alpha(@acc, 0.22); color: @fg; }
.enlace-badge.rdp { background-color: alpha(#c678dd, 0.30); }
.enlace-badge.db { background-color: alpha(#f2c66d, 0.22); }
.enlace-toast { background-color: @head; color: @fg; padding: 10px 18px; border-radius: 10px;
                margin: 18px; border: 1px solid @acc; }
.enlace-toast.error { background-color: #8e2a33; border-color: #ff6b7a; color: #fff; }
.enlace-lock-title { font-size: 2.2em; font-weight: 800; }
.enlace-welcome-title { font-size: 1.8em; font-weight: 800; color: @acc; }
.enlace-state-activo { color: #7ee787; font-weight: bold; }
.enlace-state-conectando { color: #e5c07b; }
.enlace-state-error { color: #ff6b7a; }
.enlace-dead { opacity: 0.5; }
.enlace-toolbar { background-color: @head; border-bottom: 1px solid @border; }
.enlace-statusbar { background-color: @head; border-top: 1px solid @border; }
.enlace-pane-header { background-color: @head; color: @dim; font-size: 0.85em;
                      min-height: 22px; border-bottom: 2px solid transparent; }
.enlace-pane-header.active { color: @fg; border-bottom: 2px solid @acc; }
.enlace-pane-header button { min-height: 18px; min-width: 18px; padding: 0 4px; }
.enlace-bcast { color: #e5c07b; font-weight: bold; }
.enlace-drag-hint { color: @dim; font-size: 0.85em; }
.enlace-theme-card { border-radius: 10px; padding: 2px; }
.enlace-group-header { border-radius: 8px; margin: 6px 6px 0 6px; }
.enlace-group-header:hover { background-color: alpha(@fg, 0.05); }
.enlace-group-header.drop-target { background-color: alpha(@acc, 0.25); box-shadow: inset 0 0 0 2px @acc; }
.enlace-group-header button { min-height: 20px; min-width: 20px; padding: 0 3px; opacity: 0.7; }
.enlace-group-header button:hover { opacity: 1; }
.enlace-group-title { font-weight: bold; font-size: 0.92em; }
.enlace-count { font-size: 0.75em; color: @dim; background-color: alpha(@fg, 0.08);
                border-radius: 8px; padding: 0 7px; }
.enlace-emoji { font-size: 1.15em; }
.enlace-emoji-host { font-size: 1.55em; min-width: 30px; }
.enlace-emoji-big { font-size: 1.6em; padding: 4px; }
.enlace-icon-picker flowboxchild { border-radius: 8px; padding: 2px; }
.enlace-icon-picker flowboxchild:selected { background-color: @sel; box-shadow: inset 0 0 0 2px @acc; }
.enlace-icon-picker flowboxchild:hover { background-color: alpha(@fg, 0.08); }
"""
    from . import icons
    defs = "".join(f"@define-color {k} {v};\n" for k, v in c.items())
    return (defs + css + NX_CSS + icons.css()).encode()


# Capa de diseño de Nexo (minimalista): va después del CSS base y lo afina.
NX_CSS = """
* { font-family: "Inter Variable", "Inter", "Cantarell", sans-serif; -gtk-outline-radius: 6px; }

headerbar.nx-headerbar { background-color: @head; border-bottom: 1px solid @line; min-height: 42px;
                         padding: 0 6px; box-shadow: none; }
.nx-brand { font-weight: 700; font-size: 14px; letter-spacing: -0.2px; }
.nx-brand-sub { color: @dim; font-size: 12px; }
button.nx-update-pill { background-color: alpha(@acc, 0.14); border: 1px solid alpha(@acc, 0.45); border-radius: 999px; color: @acc; padding: 2px 12px; font-weight: 600; margin: 0 6px; }
button.nx-update-pill:hover { background-color: alpha(@acc, 0.24); }
button.nx-search-pill { background-color: @surf; border: 1px solid @line; border-radius: 8px; color: @dim;
                        padding: 3px 10px; min-height: 26px; font-size: 13px; box-shadow: none; }
button.nx-search-pill:hover { background-color: @surf2; border-color: @border2; color: @fg; }
.nx-kbd { font-family: "JetBrains Mono", monospace; font-size: 10.5px; color: @dim;
          background-color: alpha(@fg, 0.06); border: 1px solid @line; border-radius: 4px; padding: 0 5px; }

button.nx-flat, headerbar button.nx-flat, .nx-flat button {
  background: transparent; border: none; box-shadow: none; border-radius: 6px; padding: 4px; color: @dim;
  min-height: 24px; min-width: 24px; }
button.nx-flat:hover, .nx-flat button:hover { background-color: alpha(@fg, 0.07); color: @fg; }
button.nx-flat:checked, .nx-flat button:checked { color: @acc; background-color: alpha(@acc, 0.12); }

.nx-rail { background-color: @rail; border-right: 1px solid @line; padding: 8px 6px; }
button.nx-rail-btn { min-width: 36px; min-height: 36px; border-radius: 8px; color: @dim; background: transparent;
                     border: none; box-shadow: none; }
button.nx-rail-btn:hover { color: @fg; background-color: alpha(@fg, 0.06); }
button.nx-rail-btn:checked { color: @acc; background-color: alpha(@acc, 0.14); }
button.nx-rail-btn.nx-rail-alert { color: @acc; }
button.nx-rail-btn.nx-rail-alert:not(:checked) { background-color: alpha(@acc, 0.08); }

list.nx-releases { background: transparent; }
list.nx-releases row.nx-release { padding: 12px 14px; margin: 4px 10px; border-radius: 10px;
                                  background-color: @surf; border: 1px solid @line; }
list.nx-releases row.nx-release.is-new { border-color: alpha(@acc, 0.55); background-color: alpha(@acc, 0.06); }
.nx-release-notes { color: @dim; font-size: 12px; }
.nx-tag { font-size: 10.5px; font-weight: 600; border-radius: 999px; padding: 1px 8px; }
.nx-tag-new { color: @acc_fg; background-color: @acc; }
.nx-tag-current { color: @acc; background-color: alpha(@acc, 0.14); }
.nx-tag-old { color: @dim; background-color: alpha(@fg, 0.06); }
.nx-tag-pre { color: @dim; border: 1px dashed @border2; }
list.nx-releases button.nx-chip { padding: 3px 10px; font-size: 12px; }
list.nx-releases button.nx-chip.suggested-action { background-color: @acc; color: @acc_fg; border-color: @acc; }

.enlace-sidebar { background-color: @side; border-right: 1px solid @line; }
.nx-panel-header { padding: 12px 8px 6px 16px; }
.nx-panel-title { font-weight: 600; font-size: 13px; }
entry.nx-filter { margin: 2px 10px 8px 10px; border-radius: 7px; background-color: @surf; border: 1px solid @line;
                  min-height: 28px; font-size: 12.5px; box-shadow: none; }
entry.nx-filter:focus { border-color: alpha(@acc, 0.7); box-shadow: 0 0 0 2px alpha(@acc, 0.15); }

.enlace-sidebar row, row.nx-host-row { padding: 6px 8px 6px 12px; margin: 1px 8px; border-radius: 7px; }
row.nx-host-row:hover { background-color: alpha(@fg, 0.045); }
row.nx-host-row:selected { background-color: alpha(@acc, 0.13); }
.nx-row-actions { opacity: 0; }
row:hover .nx-row-actions, row:selected .nx-row-actions, .enlace-group-header:hover .nx-row-actions { opacity: 1; }
.enlace-host-name { font-weight: 500; font-size: 13px; }
.nx-mono-sub { font-family: "JetBrains Mono", monospace; font-size: 11px; color: @dim; }
.enlace-badge { font-size: 9.5px; font-weight: 600; letter-spacing: 0.4px; padding: 0 5px; border-radius: 4px; }

.enlace-group-header { margin: 12px 8px 2px 8px; border-radius: 6px; padding: 0 2px; }
.enlace-group-header:hover { background-color: alpha(@fg, 0.03); }
.enlace-group-title { font-size: 10.5px; font-weight: 600; letter-spacing: 0.9px; color: @dim; }
.enlace-count { font-size: 10px; color: @dim; background: alpha(@fg, 0.06); border-radius: 9px; padding: 0 6px; }

notebook.nx-tabs > header { background-color: @head; border-bottom: 1px solid @line; padding: 0; box-shadow: none; }
notebook.nx-tabs > header tab { padding: 6px 10px 6px 12px; min-height: 26px; color: @dim; border: none;
                                border-right: 1px solid @line; background: transparent; box-shadow: none;
                                border-radius: 0; margin: 0; font-size: 12.5px; }
notebook.nx-tabs > header tab:hover { color: @fg; background-color: alpha(@fg, 0.03); }
notebook.nx-tabs > header tab:checked { color: @fg; background-color: @term; box-shadow: inset 0 2px 0 @acc; }
button.nx-tab-close { opacity: 0; min-width: 18px; min-height: 18px; padding: 0; border-radius: 4px;
                      background: transparent; border: none; box-shadow: none; }
tab:hover button.nx-tab-close, tab:checked button.nx-tab-close { opacity: 0.75; }
button.nx-tab-close:hover { background-color: alpha(@fg, 0.12); opacity: 1; }

.enlace-pane-header { background-color: @head; min-height: 24px; font-size: 11.5px; border-bottom: 1px solid @line; }
.enlace-pane-header.active { border-bottom: 1px solid @acc; }
.enlace-pane-header button { opacity: 0.55; }
.enlace-pane-header button:hover { opacity: 1; }

.nx-welcome { background-color: @term; }
.nx-welcome scrolledwindow, .nx-welcome viewport { background-color: transparent; }
.nx-hero-title { font-size: 26px; font-weight: 700; letter-spacing: -0.6px; }
.nx-muted { color: @dim; }
.nx-mono { font-family: "JetBrains Mono", monospace; font-size: 12px; }
.nx-dialog-title { font-size: 15px; }
.nx-caption { color: @dim; font-size: 11.5px; }
.nx-section-label { color: @dim; font-size: 10.5px; font-weight: 600; letter-spacing: 1px; }
entry.nx-quick { min-height: 42px; font-size: 14px; border-radius: 10px; background-color: @surf;
                 border: 1px solid @line; padding: 0 12px; box-shadow: none; }
entry.nx-quick:focus { border-color: @acc; box-shadow: 0 0 0 3px alpha(@acc, 0.16); }
list.nx-recent { background: transparent; }
list.nx-recent row { padding: 9px 12px; border-radius: 8px; }
list.nx-recent row:hover { background-color: alpha(@fg, 0.05); }
button.nx-chip { background-color: @surf; border: 1px solid @line; border-radius: 8px; padding: 6px 12px;
                 font-size: 12.5px; color: @fg; box-shadow: none; }
button.nx-chip:hover { background-color: @surf2; border-color: @border2; }

.nx-card { background-color: @surf; border: 1px solid @line; border-radius: 16px; padding: 32px 34px 22px 34px; }
.nx-lock-title { font-size: 22px; font-weight: 700; letter-spacing: -0.4px; }
entry.nx-input-lg { min-height: 38px; font-size: 14px; border-radius: 9px; }
button.nx-btn-lg { min-height: 38px; border-radius: 9px; font-weight: 600; }

window.nx-palette { background-color: @surf; border: 1px solid @border2; border-radius: 12px; }
.nx-palette-input { padding: 12px 14px; border-bottom: 1px solid @line; }
.nx-palette-input entry { background: transparent; border: none; box-shadow: none; font-size: 15px; min-height: 26px; }
list.nx-palette-list { background: transparent; padding: 6px; }
list.nx-palette-list row { padding: 8px 10px; border-radius: 7px; }
list.nx-palette-list row:selected { background-color: alpha(@acc, 0.16); color: @fg; }
.nx-palette-hint { padding: 8px 14px; color: @dim; font-size: 11px; border-top: 1px solid @line; }

.enlace-toolbar { background-color: @head; border-bottom: 1px solid @line; }
.enlace-toolbar button { background: transparent; border: none; box-shadow: none; color: @dim; border-radius: 6px; }
.enlace-toolbar button:hover { color: @fg; background-color: alpha(@fg, 0.07); }
.enlace-toolbar button.suggested-action { background-color: @acc; color: @acc_fg; padding: 3px 12px; }
.enlace-toolbar button.suggested-action:hover { background-color: shade(@acc, 1.1); color: @acc_fg; }
.enlace-toast { border-radius: 10px; border: 1px solid @border2; font-size: 13px; }
paned > separator { min-width: 1px; min-height: 1px; background-color: @line; }
paned > separator:hover { background-color: alpha(@acc, 0.45); }
"""
