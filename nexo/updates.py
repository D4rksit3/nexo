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


def fetch_latest(timeout=8):
    """Devuelve {'version', 'url', 'notes', 'assets'} de la última versión publicada."""
    req = urllib.request.Request(LATEST_API, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"Nexo/{__version__}",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (URL fija https)
        data = json.load(r)
    return {
        "version": (data.get("tag_name") or "").lstrip("vV"),
        "url": data.get("html_url") or RELEASES_PAGE,
        "notes": data.get("body") or "",
        "assets": {a["name"]: a["browser_download_url"] for a in data.get("assets", [])},
    }


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
    """(texto, comando_para_copiar | None, url_para_abrir) según el tipo de instalación."""
    v = info["version"]
    kind = install_kind()
    assets = info.get("assets", {})
    if kind == "snap":
        return ("Nexo se actualiza solo desde la tienda. Cierra Nexo y vuelve a abrirlo; "
                "si todavía no se aplicó, ejecútalo ya en una terminal:",
                "sudo snap refresh nexo", info["url"])
    if kind == "windows":
        exe = assets.get(f"NexoSetup-{v}.exe")
        return ("Descarga el instalador nuevo y ejecútalo. Tu bóveda se conserva.",
                None, exe or info["url"])
    deb_name = f"nexo_{v}_all.deb"
    deb = assets.get(deb_name)
    if kind == "deb" and deb:
        cmd = f"cd /tmp && wget -q {deb} && sudo apt install -y ./{deb_name}"
        return ("Descarga e instala el paquete nuevo con este comando. Tu bóveda se conserva.",
                cmd, info["url"])
    return ("Descarga la versión nueva desde la página de la versión.", None, info["url"])
