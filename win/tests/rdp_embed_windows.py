"""Prueba del escritorio remoto incrustado con el control RDP REAL de Windows (solo Windows).

1. Crea el control dentro de una ventana WinForms (como en Nexo), lo configura y conecta a un
   puerto cerrado: tiene que llegar el evento de desconexión con un mensaje legible.
2. Si hay NEXO_RDP_TEST_HOST/USER/PASSWORD, inicia sesión de verdad y espera OnLoginComplete
   (la CI lo hace contra el propio runner con un usuario temporal).

Uso: python win/tests/rdp_embed_windows.py
"""
import os
import sys
import tempfile
import threading
import time

TMP = tempfile.mkdtemp(prefix="nexo-rdp-")
os.environ.update(XDG_DATA_HOME=TMP, XDG_CONFIG_HOME=TMP, APPDATA=TMP)
sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]

from nexo_win import IS_WINDOWS, rdp, rdp_embed  # noqa: E402

if not IS_WINDOWS:
    print("Solo en Windows")
    sys.exit(0)

import clr  # noqa: E402,F401  (pythonnet, lo instala pywebview)

clr.AddReference("System.Windows.Forms")
from System.Windows.Forms import Application, Form  # noqa: E402

failures = []


def check(name, ok, extra=""):
    print(("OK   " if ok else "FALLA ") + name + (f"  → {extra}" if extra else ""), flush=True)
    if not ok:
        failures.append(name)


def session(form, host, address, port, password):
    events = []
    s = rdp_embed.EmbeddedRdp(form, host, address, port, password,
                              lambda sess, st, msg: events.append((st, msg)))
    return s, events


def wait_for(events, states, timeout):
    end = time.time() + timeout
    while time.time() < end:
        for st, msg in events:
            if st in states:
                return st, msg
        time.sleep(0.2)
    return None, None


def scenario(form):
    try:
        check("typelib de mstscax.dll", rdp_embed.available())
        mod = rdp_embed.typelib()
        check("interfaz de eventos IMsTscAxEvents", hasattr(mod, "IMsTscAxEvents"))
        check("IMsTscNonScriptable (contraseña directa)", hasattr(mod, "IMsTscNonScriptable"))

        # 1) puerto cerrado: crear, configurar, conectar y recibir la desconexión con texto
        host = {"id": "x", "name": "cerrado", "host": "127.0.0.1", "port": 1, "user": "nadie", "rdp": {}}
        s, ev = session(form, host, "127.0.0.1", 1, "clave")
        s.attach(0, 0, 800, 600, True)
        check("control creado (ventana hija)", bool(s.hwnd), s.hwnd)
        st, msg = wait_for(ev, {"closed"}, 60)
        check("evento de desconexión recibido", st == "closed", ev)
        check("mensaje legible del motivo", bool(msg), repr(msg))
        s.close()

        # 2) inicio de sesión real (opcional)
        th, tu, tp = (os.environ.get(k) for k in ("NEXO_RDP_TEST_HOST", "NEXO_RDP_TEST_USER", "NEXO_RDP_TEST_PASSWORD"))
        if th and tu and tp:
            try:
                ok, fp, old = rdp.trust_check(f"{th}:3389", th, 3389)
                check("huella del certificado leída por Nexo", ok and bool(fp), fp)
            except Exception as e:  # noqa: BLE001
                check("huella del certificado leída por Nexo", False, e)
            host = {"id": "y", "name": "runner", "host": th, "port": 3389, "user": tu, "rdp": {}}
            s, ev = session(form, host, th, 3389, tp)
            s.attach(0, 0, 1024, 700, True)
            st, msg = wait_for(ev, {"connected", "closed"}, 90)
            check("inicio de sesión RDP dentro de la ventana (sin diálogos)", st == "connected", f"{st} {msg}")
            s.place(0, 0, 1200, 760, True)
            time.sleep(2)
            s.close()
        else:
            print("(sin NEXO_RDP_TEST_*: se omite el inicio de sesión real)")
    except Exception as e:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        failures.append(f"excepción: {e}")
    finally:
        rdp_embed.later(form, form.Close)


form = Form()
form.Text = "Nexo — prueba RDP"
form.Width, form.Height = 1280, 800
form.Shown += lambda *a: threading.Thread(target=scenario, args=(form,), daemon=True).start()
Application.Run(form)
print("\nTODO OK" if not failures else f"\nFALLAS: {', '.join(failures)}")
sys.exit(1 if failures else 0)
