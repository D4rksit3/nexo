"""Arranque: rutas, puente WebSocket, API y ventana."""
import os
import sys

from . import setup_paths

setup_paths()

import webview  # noqa: E402

from .api import Api  # noqa: E402
from .bridge import Bridge  # noqa: E402


def ui_dir():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "ui")


def _selftest(window, out_path, result):
    """NEXO_SELFTEST=<archivo>: abre la ventana real, comprueba que la página, xterm.js y el
    puente con Python respondan, escribe el resultado en JSON y cierra. Lo usa la CI de Windows."""
    import json
    import time

    checks = {}
    end = time.time() + 90
    while time.time() < end:
        try:
            if window.evaluate_js("typeof INFO !== 'undefined' && INFO !== null && !!INFO.version"):
                break
        except Exception:  # noqa: BLE001 — la página aún no cargó
            pass
        time.sleep(0.5)
    try:
        checks["pagina_y_api"] = bool(window.evaluate_js("!!(INFO && INFO.version)"))
        checks["xterm"] = bool(window.evaluate_js("typeof Terminal === 'function' && typeof FitAddon === 'object'"))
        checks["pantalla_bloqueo"] = bool(window.evaluate_js("!document.querySelector('#lock').hidden"))
        checks["version"] = window.evaluate_js("INFO.version")
        checks["shell_local"] = window.evaluate_js("INFO.local_shell")
    except Exception as e:  # noqa: BLE001
        checks["error"] = str(e)
    result["ok"] = all(checks.get(k) for k in ("pagina_y_api", "xterm", "pantalla_bloqueo"))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"ok": result["ok"], **checks}, f, ensure_ascii=False, indent=1)
    window.destroy()


def main():
    api = Api()
    api._bridge = Bridge(api._sessions)
    bg = api.theme()["ui"]["win"]
    window = webview.create_window(
        "Nexo", url=os.path.join(ui_dir(), "index.html"), js_api=api,
        width=1280, height=800, min_size=(820, 520), background_color=bg, text_select=False,
    )
    api._window = window
    window.events.closed += api._shutdown
    debug = os.environ.get("NEXO_DEBUG") == "1"
    selftest = os.environ.get("NEXO_SELFTEST")
    result = {"ok": True}
    if selftest:
        webview.start(_selftest, (window, selftest, result), http_server=True, private_mode=True)
    else:
        webview.start(http_server=True, debug=debug, private_mode=True)
    api._bridge.shutdown()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
