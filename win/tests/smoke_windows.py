"""Prueba de las piezas propias de Windows (y de las que no necesitan un servidor SSH).

En Windows comprueba lo que en Linux no se puede: lista de unidades, rutas de «Este equipo»,
papelera (SHFileOperation), Administrador de credenciales (RDP), archivo .rdp, detección de
paquete MSIX y que los controladores de bases de datos se importen. En Linux corre lo común.

    python win/tests/smoke_windows.py
"""
import os
import socket
import struct
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
TMP = tempfile.mkdtemp(prefix="nexo-win-")
os.environ["XDG_DATA_HOME"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["APPDATA"] = TMP

from nexo_win import IS_WINDOWS, setup_paths  # noqa: E402

setup_paths()
from nexo_win import files, forward, rdp  # noqa: E402
from nexo_win.api import Api, _is_packaged  # noqa: E402

failures = []


def check(name, ok, extra=""):
    print(("OK   " if ok else "FALLA"), name, "" if ok else extra, flush=True)
    if not ok:
        failures.append(name)


# --- SOCKS5 (sin red: un par de sockets) ---------------------------------------
a, b = socket.socketpair()
res = {}


def server():
    try:
        res["dest"] = forward.socks5_handshake(b)
        forward.socks5_reply(b, True)
    except Exception as e:  # noqa: BLE001
        res["err"] = e


th = threading.Thread(target=server)
th.start()
a.sendall(b"\x05\x01\x00")
check("SOCKS5: método sin autenticación", a.recv(2) == b"\x05\x00")
a.sendall(b"\x05\x01\x00\x03\x0bexample.com" + struct.pack("!H", 443))
th.join(5)
check("SOCKS5: destino por nombre", res.get("dest") == ("example.com", 443), res)
check("SOCKS5: respuesta OK", a.recv(10)[:2] == b"\x05\x00")
a.close()
b.close()

# --- archivo .rdp -------------------------------------------------------------------
txt = rdp.rdp_file_text("10.0.0.5:3390", "ana", {"domain": "EMPRESA", "resolution": "1920x1080", "clipboard": True})
check(".rdp: dirección y usuario con dominio", "full address:s:10.0.0.5:3390" in txt and "username:s:EMPRESA\\ana" in txt, txt)
check(".rdp: resolución fija", "desktopwidth:i:1920" in txt and "desktopheight:i:1080" in txt)
check(".rdp: sin contraseña dentro", "password" not in txt.lower())
txt = rdp.rdp_file_text("h", "", {"resolution": "auto", "fullscreen": True})
check(".rdp: ajustar a la ventana", "dynamic resolution:i:1" in txt and "screen mode id:i:2" in txt)

# --- este equipo ------------------------------------------------------------------------
os.makedirs(os.path.join(TMP, "carpeta"))
with open(os.path.join(TMP, "a.txt"), "w") as f:
    f.write("x")
r = files.local_list(TMP)
names = {e["name"]: e for e in r["entries"]}
check("listar carpeta local", names.get("carpeta", {}).get("dir") and names.get("a.txt", {}).get("size") == 1, names)
files.local_rename(os.path.join(TMP, "a.txt"), "b.txt")
check("renombrar local", os.path.exists(os.path.join(TMP, "b.txt")))
files.local_trash([os.path.join(TMP, "b.txt")])
check("papelera local", not os.path.exists(os.path.join(TMP, "b.txt")))

api = Api()
check("crear y abrir bóveda", api.create_vault("clave-de-prueba", "clave-de-prueba")["ok"] and api.unlock("clave-de-prueba")["ok"])
check("temas disponibles", len(api.themes()["themes"]) >= 14)
r = api.save_host({"name": "rdp", "protocol": "rdp", "host": "10.0.0.5", "port": 3389, "user": "ana", "password": "x",
                   "rdp": {"resolution": "auto"}})
check("guardar host RDP", r["ok"], r)
check("la página no recibe la contraseña", "password" not in api.host_get(r["id"])["host"])

# --- controladores de bases de datos -------------------------------------------------------
for mod in ("psycopg2", "pymysql", "pymssql", "pymongo", "redis"):
    try:
        __import__(mod)
        ok = True
    except ImportError as e:
        ok, err = False, e
    check(f"controlador {mod}", ok, locals().get("err"))

# --- solo Windows ------------------------------------------------------------------------------
if IS_WINDOWS:
    import subprocess

    r = files.local_list("")
    drives = [e["name"] for e in r["entries"]]
    check("lista de unidades", any(d.upper().startswith("C:") for d in drives), drives)
    check("subir desde C:\\ vuelve a las unidades", files.local_parent("C:\\") == "")
    check("subir desde C:\\Users", files.local_parent("C:\\Users") == "C:\\", files.local_parent("C:\\Users"))
    check("known_hosts propio en %APPDATA%", os.environ.get("NEXO_KNOWN_HOSTS", "").startswith(TMP))
    target = "TERMSRV/nexo-prueba.invalid"
    rdp.cred_write(target, "ana", "secreta")
    out = subprocess.run(["cmdkey", f"/list:{target}"], capture_output=True, text=True).stdout
    check("credencial RDP temporal creada", "nexo-prueba.invalid" in out, out)
    rdp.cred_delete(target)
    out = subprocess.run(["cmdkey", f"/list:{target}"], capture_output=True, text=True).stdout
    check("credencial RDP borrada", "nexo-prueba.invalid" not in out, out)
    check("fuera de un paquete MSIX", _is_packaged() is False)
    check("mstsc disponible", os.path.exists(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "mstsc.exe")))

print("\nTODO OK" if not failures else f"\nFALLAS: {', '.join(failures)}")
sys.exit(1 if failures else 0)
