"""Arranque de Nexo Server y órdenes de administración.

  python -m nexo_server                 inicia la puerta SSH y el panel web
  python -m nexo_server create-admin U  crea un administrador (muestra su contraseña temporal)
  python -m nexo_server reset-2fa U     reinicia el 2FA de un usuario
  python -m nexo_server unblock U       desbloquea a un usuario
"""
import asyncio
import logging
import os
import signal
import sys

import asyncssh
from aiohttp import web

from . import __version__, gateway
from .config import Config
from .store import Store
from .web import make_app, temp_password

log = logging.getLogger("nexo")


def bootstrap_admin(store):
    if store.one("SELECT COUNT(*) c FROM users")["c"]:
        return
    name = os.environ.get("NEXO_ADMIN_USER", "admin")
    pw = os.environ.get("NEXO_ADMIN_PASSWORD") or temp_password()
    store.create_user(name, pw, "admin", "Administrador", must_change=True)
    store.audit("sistema", "bootstrap.admin", name)
    bar = "=" * 64
    print(f"\n{bar}\n  Nexo Server: primer administrador creado\n  usuario:    {name}\n"
          f"  contraseña: {pw}   (temporal; se pide cambiarla y activar 2FA)\n{bar}\n", flush=True)


async def serve(cfg, store):
    gw = await gateway.start(store, cfg)
    fp = asyncssh.read_private_key(os.path.join(store.data_dir, "ssh_host_ed25519_key")).get_fingerprint()
    app = make_app(store, cfg, fp, __version__)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, cfg.http_bind, cfg.http_port)
    await site.start()
    log.info("Panel web en %s (escuchando %s:%s)", cfg.public_url, cfg.http_bind, cfg.http_port)
    # al arrancar, las sesiones que quedaron abiertas por un reinicio se marcan cerradas
    store.run("UPDATE sessions SET ended = started WHERE ended IS NULL")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, stop.set)
        except NotImplementedError:
            pass
    await stop.wait()
    gw.close()
    await runner.cleanup()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.umask(0o077)
    logging.basicConfig(level=os.environ.get("NEXO_LOG", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("asyncssh").setLevel(logging.WARNING)
    cfg = Config()
    store = Store(cfg.data_dir)
    if argv and argv[0] in ("create-admin", "reset-2fa", "unblock"):
        if len(argv) < 2:
            sys.exit(f"Uso: python -m nexo_server {argv[0]} <usuario>")
        name = argv[1]
        u = store.user_by_name(name)
        if argv[0] == "create-admin":
            if u:
                sys.exit("Ese usuario ya existe")
            pw = temp_password()
            store.create_user(name, pw, "admin", must_change=True)
            store.audit("consola", "admin.crear_usuario", name)
            print(f"Administrador {name} creado. Contraseña temporal: {pw}")
        elif u is None:
            sys.exit("No existe ese usuario")
        elif argv[0] == "reset-2fa":
            store.run("UPDATE users SET totp_enabled = 0, totp_secret = NULL, totp_last_step = 0 WHERE id = ?", u["id"])
            store.revoke_user_tokens(u["id"])
            store.audit("consola", "admin.reset_2fa", name)
            print(f"2FA de {name} reiniciado")
        else:
            store.run("UPDATE users SET disabled = 0 WHERE id = ?", u["id"])
            store.audit("consola", "admin.desbloquear", name)
            print(f"{name} desbloqueado")
        return
    bootstrap_admin(store)
    log.info("Nexo Server %s · organización: %s · datos en %s", __version__, cfg.org_name, cfg.data_dir)
    asyncio.run(serve(cfg, store))


if __name__ == "__main__":
    main()
