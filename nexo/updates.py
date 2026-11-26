"""Aviso de nuevas versiones.

Consulta la última versión publicada en GitHub Releases (una petición GET anónima:
no se envía ningún dato de la bóveda ni del equipo). Se puede desactivar desde
Ajustes → «Avisarme de actualizaciones».
"""
import json
import os
import re
import threading
import urllib.request

from . import __version__

REPO = "D4rksit3/nexo"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
CHECK_EVERY_S = 12 * 3600


def parse(v):
    """'v2.10.1' -> (2, 10, 1). Lo que no sea número se ignora."""
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3]) or (0,)


def newer(remote, local=__version__):
    return parse(remote) > parse(local)


def install_kind():
    """Cómo se instaló esta copia, para dar las instrucciones correctas."""
    if os.environ.get("SNAP"):
        return "snap"
    if os.environ.get("WSL_DISTRO_NAME"):
        return "windows"
    if os.path.abspath(__file__).startswith("/usr/share/nexo/"):
        return "deb"
    return "source"


def _get(url, timeout):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"Nexo/{__version__}",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (URL fija https)
        return json.load(r)


def _release(data):
    return {
        "version": (data.get("tag_name") or "").lstrip("vV"),
        "url": data.get("html_url") or RELEASES_PAGE,
        "notes": data.get("body") or "",
        "assets": {a["name"]: a["browser_download_url"] for a in data.get("assets", [])},
        "date": (data.get("published_at") or "")[:10],
        "prerelease": bool(data.get("prerelease")),
    }


def fetch_latest(timeout=8):
    """Devuelve {'version', 'url', 'notes', 'assets', 'date'} de la última versión publicada."""
    return _release(_get(LATEST_API, timeout))


def fetch_releases(timeout=8):
    """Todas las versiones publicadas (sin borradores), de la más nueva a la más vieja."""
    out = [_release(d) for d in _get(RELEASES_API, timeout) if not d.get("draft")]
    out = [r for r in out if r["version"]]
    out.sort(key=lambda r: parse(r["version"]), reverse=True)
    return out


def releases_async(callback):
    """Como check_async, pero con la lista completa: callback(lista | None, error | None)."""
    def run():
        try:
            callback(fetch_releases(), None)
        except Exception as e:  # noqa: BLE001
            callback(None, e)
    threading.Thread(target=run, name="nexo-releases", daemon=True).start()


MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def nice_date(iso):
    """'2026-11-25' -> '25 nov 2026'."""
    try:
        y, m, d = (int(x) for x in iso.split("-"))
        return f"{d} {MONTHS[m - 1]} {y}"
    except (ValueError, IndexError):
        return iso


def check_async(callback):
    """Consulta en un hilo y llama callback(info | None, error | None) desde ese hilo."""
    def run():
        try:
            callback(fetch_latest(), None)
        except Exception as e:  # noqa: BLE001 — sin red, GitHub caído, límite de la API…
            callback(None, e)
    threading.Thread(target=run, name="nexo-updates", daemon=True).start()


def summary(notes, limit=6):
    """Primeras viñetas de «Novedades» (o del texto) para mostrarlas en el aviso."""
    lines = [ln.strip() for ln in notes.splitlines()]
    out, grab = [], False
    for ln in lines:
        if ln.lower().startswith("### novedades"):
            grab = True
            continue
        if grab and ln.startswith("#"):
            break
        if grab and ln.startswith(("-", "*")):
            out.append(ln.lstrip("-* ").strip())
    if not out:
        out = [ln.lstrip("-* ") for ln in lines if ln.startswith(("-", "*"))]
    clean = [re.sub(r"[*`]", "", x) for x in out[:limit]]
    return clean


def instructions(info):
    """(texto, comando_para_copiar | None, url_para_abrir) según el tipo de instalación.

    Sirve para la versión nueva y también para volver a una anterior.
    """
    v = info["version"]
    older = parse(v) < parse(__version__)
    kind = install_kind()
    assets = info.get("assets", {})
    if kind == "snap":
        if older:
            return ("La tienda de snaps instala siempre la última versión. Para volver a la que "
                    "tenías justo antes de la última actualización:",
                    "sudo snap revert nexo", info["url"])
        return ("Nexo se actualiza solo desde la tienda. Cierra Nexo y vuelve a abrirlo; "
                "si todavía no se aplicó, ejecútalo ya en una terminal:",
                "sudo snap refresh nexo", info["url"])
    if kind == "windows":
        exe = assets.get(f"NexoSetup-{v}.exe")
        return ("Descarga el instalador de esta versión y ejecútalo. Tu bóveda se conserva.",
                None, exe or info["url"])
    deb_name = f"nexo_{v}_all.deb"
    deb = assets.get(deb_name)
    if kind in ("deb", "source") and deb:
        flag = " --allow-downgrades" if older else ""
        what = "esta versión anterior" if older else "el paquete nuevo"
        cmd = f"cd /tmp && wget -q {deb} && sudo apt install -y{flag} ./{deb_name}"
        return (f"Descarga e instala {what} con este comando. Tu bóveda se conserva.", cmd, info["url"])
    return ("Descarga esta versión desde su página en GitHub.", None, info["url"])


def downloads(info):
    """[(etiqueta, url)] de los archivos que sirven en este equipo, para descarga directa."""
    v, assets = info["version"], info.get("assets", {})
    kind = install_kind()
    want = [(f"NexoSetup-{v}.exe", "Instalador .exe"), (f"nexo-windows-{v}.zip", ".zip")] if kind == "windows" \
        else [(f"nexo_{v}_all.deb", "Paquete .deb")]
    return [(lbl, assets[name]) for name, lbl in want if name in assets]
