"""Prueba del núcleo de Nexo para Windows sin ventana (sirve en Windows y en Linux).

Comprueba: bóveda nueva y desbloqueo, puente WebSocket con token, shell local
(ConPTY en Windows / pty en Linux) que ejecuta un comando, cambio de tamaño y
portapapeles. Sale con código 1 si algo falla.

    python win/tests/smoke_backend.py
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

TMP = tempfile.mkdtemp(prefix="nexo-smoke-")
os.environ["XDG_DATA_HOME"] = TMP       # bóveda de prueba, nunca la real
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["APPDATA"] = TMP

from nexo_win import IS_WINDOWS, setup_paths  # noqa: E402

setup_paths()
from websockets.sync.client import connect  # noqa: E402

from nexo_win import clipboard  # noqa: E402
from nexo_win.api import Api  # noqa: E402
from nexo_win.bridge import Bridge  # noqa: E402

failures = []


def check(name, ok, extra=""):
    print(("OK   " if ok else "FALLA"), name, extra, flush=True)
    if not ok:
        failures.append(name)


def read_until(ws, needle, timeout=20):
    out = b""
    end = time.time() + timeout
    while time.time() < end:
        try:
            msg = ws.recv(timeout=max(0.1, end - time.time()))
        except TimeoutError:
            break
        if isinstance(msg, bytes):
            out += msg
            if needle.encode() in out:
                return True, out
    return False, out


api = Api()
api._bridge = Bridge(api._sessions)
check("bóveda nueva", api.create_vault("clave-de-prueba", "clave-de-prueba")["ok"])
check("contraseña incorrecta rechazada", not api.unlock("otra")["ok"])
check("desbloqueo", api.unlock("clave-de-prueba")["ok"])
info = api.info()
check("info", info["unlocked"] and info["vault_exists"], info["local_shell"])

r = api.open_local(100, 30)
check("abre shell local", r["ok"], r.get("title", ""))
bad = r["ws"].replace("?t=", "?t=x")
try:
    with connect(bad) as w:
        w.recv(timeout=3)
    check("puente rechaza token falso", False)
except Exception:  # noqa: BLE001
    check("puente rechaza token falso", True)

with connect(r["ws"]) as ws:
    ws.send(json.dumps({"t": "resize", "cols": 100, "rows": 30}))
    time.sleep(2.0 if IS_WINDOWS else 0.8)
    cmd = 'Write-Output ("NEXO-" + (6*7))\r' if IS_WINDOWS else "echo NEXO-$((6*7))\r"
    ws.send(cmd.encode())
    ok, out = read_until(ws, "NEXO-42")
    check("el shell ejecuta un comando", ok, "" if ok else repr(out[-300:]))
    size_cmd = "Write-Output ('SIZE-' + $Host.UI.RawUI.WindowSize.Width)\r" if IS_WINDOWS else "echo SIZE-$(tput cols)\r"
    ws.send(json.dumps({"t": "resize", "cols": 91, "rows": 25}))
    time.sleep(0.8)
    ws.send(size_cmd.encode())
    ok, out = read_until(ws, "SIZE-91")
    check("cambio de tamaño llega al shell", ok, "" if ok else repr(out[-300:]))

api.close_session(r["sid"])
check("cierra la sesión", r["sid"] not in api._sessions)

if IS_WINDOWS or os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"):
    marker = "nexo-portapapeles-ñ-42"
    set_ok = clipboard.set_text(marker)
    got = clipboard.get_text()
    if os.environ.get("CI") and not (set_ok and got == marker):
        print("AVISO portapapeles no disponible en este equipo de CI:", repr(got))
    else:
        check("portapapeles ida y vuelta", set_ok and got == marker, repr(got))

api.lock()
check("bloqueo", not api.info()["unlocked"])
api._bridge.shutdown()
import shutil  # noqa: E402

shutil.rmtree(TMP, ignore_errors=True)
print("RESUMEN:", "todo bien" if not failures else f"{len(failures)} fallas: {failures}")
sys.exit(1 if failures else 0)
