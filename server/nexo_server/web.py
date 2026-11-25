"""Panel web de administración y API para la app Nexo."""
import html
import os
import secrets
import string
import time

import segno
from aiohttp import web

from . import gateway
from .store import hash_password, new_totp_secret, password_policy, totp_match, totp_uri

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
COOKIE = "nexo_s"
ICONS = ["", "linux", "ubuntu", "windows", "server", "db", "web", "docker", "cloud", "firewall", "router",
         "vpn", "camera", "backup", "ai", "mail", "monitor", "prod", "test"]
WEB_FAILS = {}


def e(x):
    return html.escape("" if x is None else str(x), quote=True)


def fmt_ts(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "—"


def fmt_dur(a, b):
    if not a:
        return "—"
    d = int((b or time.time()) - a)
    return f"{d // 3600}h {d % 3600 // 60}m" if d >= 3600 else f"{d // 60}m {d % 60}s"


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def temp_password():
    alpha = string.ascii_letters + string.digits
    while True:
        p = "".join(secrets.choice(alpha) for _ in range(14))
        if password_policy(p) is None:
            return p


CSS = """
:root{--bg:#0b0c0f;--panel:#111318;--surf:#16191f;--line:#22262e;--fg:#e6e8ec;--dim:#8a919e;--acc:#3ddc84;--bad:#ff6b7a;--warn:#f2c66d}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 Inter,"Inter Variable",system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
.layout{display:flex;min-height:100vh}
nav{width:220px;background:var(--panel);border-right:1px solid var(--line);padding:18px 12px;flex-shrink:0}
nav .brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:16px;padding:0 8px 18px}
nav .brand img{width:26px;height:26px}
nav a{display:block;color:var(--dim);padding:7px 10px;border-radius:7px;margin:1px 0}
nav a:hover{background:#1b1f26;color:var(--fg);text-decoration:none}
nav a.on{background:rgba(61,220,132,.12);color:var(--acc)}
nav .who{margin-top:24px;padding:10px;border-top:1px solid var(--line);color:var(--dim);font-size:12.5px}
main{flex:1;padding:28px 36px;max-width:1200px}
h1{font-size:22px;margin:0 0 4px;letter-spacing:-.3px}h2{font-size:15px;margin:28px 0 10px}
.sub{color:var(--dim);margin:0 0 22px}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:middle}
th{color:var(--dim);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.5px;background:#13161b}
tr:last-child td{border-bottom:none}
.mono{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:12.5px}
.pill{display:inline-block;padding:1px 8px;border-radius:9px;font-size:11.5px;background:#1d2128;color:var(--dim)}
.pill.ok{background:rgba(61,220,132,.14);color:var(--acc)}.pill.bad{background:rgba(255,107,122,.14);color:var(--bad)}
.pill.warn{background:rgba(242,198,109,.14);color:var(--warn)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:10px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card b{display:block;font-size:24px}.card span{color:var(--dim);font-size:12.5px}
form.inline{display:inline}
input,select,textarea{background:var(--surf);color:var(--fg);border:1px solid var(--line);border-radius:7px;padding:8px 10px;font:inherit;width:100%}
textarea{font-family:"JetBrains Mono",monospace;font-size:12px;min-height:110px}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--acc)}
input[type=checkbox]{width:auto}
label{display:block;color:var(--dim);font-size:12.5px;margin:12px 0 4px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:0 16px}
.box{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px 22px;max-width:720px}
button,.btn{background:#1d2128;color:var(--fg);border:1px solid var(--line);border-radius:7px;padding:7px 13px;font:inherit;cursor:pointer;display:inline-block}
button:hover,.btn:hover{background:#252a33;text-decoration:none}
button.primary{background:var(--acc);border-color:var(--acc);color:#06140c;font-weight:600}
button.danger{color:var(--bad)}.small,button.small,.btn.small{padding:3px 10px;font-size:12.5px;line-height:1.6}
div.actions{display:flex;gap:6px;flex-wrap:wrap}
td.actions{white-space:nowrap;text-align:right}td.actions>*{margin-left:6px;vertical-align:middle}
.flash{background:rgba(61,220,132,.1);border:1px solid rgba(61,220,132,.35);border-radius:9px;padding:10px 14px;margin-bottom:18px}
.flash.err{background:rgba(255,107,122,.1);border-color:rgba(255,107,122,.35)}
.center{min-height:100vh;display:flex;align-items:center;justify-content:center}
.login{width:380px;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:30px 32px}
.login img{width:56px;height:56px;display:block;margin:0 auto 10px}
.login h1{text-align:center}.login .sub{text-align:center}
.login button{width:100%;margin-top:18px;padding:10px}
.qr{background:#fff;border-radius:10px;padding:10px;display:inline-block}
.muted{color:var(--dim)}code{background:#1a1e25;padding:1px 6px;border-radius:5px}
"""


def layout(req, title, body, active=""):
    u = req.get("user")
    nav = ""
    if u is not None:
        links = [("/", "Resumen", "home"), ("/me", "Mi acceso", "me")]
        if u["role"] == "admin":
            links = [("/", "Resumen", "home"), ("/sessions", "Sesiones", "sessions"), ("/users", "Usuarios", "users"),
                     ("/teams", "Equipos", "teams"), ("/hosts", "Hosts", "hosts"), ("/audit", "Auditoría", "audit"),
                     ("/me", "Mi cuenta", "me")]
        items = "".join(f'<a href="{h}" class="{"on" if k == active else ""}">{t}</a>' for h, t, k in links)
        nav = (f'<nav><div class="brand"><img src="/static/nexo.svg" alt="">{e(req.app["cfg"].org_name)}</div>{items}'
               f'<div class="who">{e(u["username"])} · {e(u["role"])}<form method="post" action="/logout">'
               f'<input type="hidden" name="csrf" value="{e(req.get("csrf"))}"><button class="small" style="margin-top:8px">'
               f'Cerrar sesión</button></form></div></nav>')
    flash = ""
    msg, kind = req.query.get("ok"), "ok"
    if not msg:
        msg, kind = req.query.get("err"), "err"
    if msg:
        flash = f'<div class="flash {"err" if kind == "err" else ""}">{e(msg)}</div>'
    return web.Response(content_type="text/html", text=(
        f'<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{e(title)} · Nexo</title><link rel="icon" href="/static/nexo.svg"><style>{CSS}</style></head><body>'
        + (f'<div class="layout">{nav}<main>{flash}{body}</main></div>' if nav else f'{flash}{body}')
        + "</body></html>"))


def csrf_input(req):
    return f'<input type="hidden" name="csrf" value="{e(req.get("csrf"))}">'


def redirect(path, ok=None, err=None):
    from urllib.parse import quote
    if ok:
        path += ("&" if "?" in path else "?") + "ok=" + quote(ok)
    if err:
        path += ("&" if "?" in path else "?") + "err=" + quote(err)
    raise web.HTTPSeeOther(path)


def client_ip(req):
    if req.app["cfg"].trust_proxy:
        xf = req.headers.get("X-Forwarded-For", "")
        if xf:
            return xf.split(",")[0].strip()
    return req.remote or ""


# --- middleware: sesión, CSRF, permisos ---------------------------------------
PUBLIC = ("/login", "/static/", "/api/", "/healthz", "/setup-2fa")


@web.middleware
async def auth_mw(req, handler):
    store = req.app["store"]
    path = req.path
    if path.startswith(("/static/", "/api/", "/healthz")):
        return await handler(req)
    raw = req.cookies.get(COOKIE)
    u, row = store.token_user(raw, "web")
    if u is not None:
        req["user"], req["csrf"], req["token"] = u, row["csrf"], raw
    if path.startswith(("/login", "/setup-2fa")):
        return await handler(req)
    if u is None:
        raise web.HTTPSeeOther("/login")
    if req.method == "POST":
        data = await req.post()
        req["form"] = data
        if not secrets.compare_digest(data.get("csrf", ""), row["csrf"] or ""):
            raise web.HTTPForbidden(text="CSRF inválido")
    if u["must_change_pw"] and path not in ("/password", "/logout"):
        raise web.HTTPSeeOther("/password")
    admin_only = path.startswith(("/users", "/teams", "/hosts", "/sessions", "/audit", "/access"))
    if admin_only and u["role"] != "admin":
        raise web.HTTPForbidden(text="Solo administradores")
    return await handler(req)


def set_cookie(req, resp, token, hours):
    resp.set_cookie(COOKIE, token, max_age=int(hours * 3600), httponly=True, samesite="Strict",
                    secure=req.app["cfg"].cookie_secure(req), path="/")


# --- login y 2FA -----------------------------------------------------------------
async def login_get(req):
    body = ('<div class="center"><form class="login" method="post" action="/login" autocomplete="off">'
            '<img src="/static/nexo.svg" alt=""><h1>Nexo</h1>'
            f'<p class="sub">{e(req.app["cfg"].org_name)} · acceso administrado</p>'
            '<label>Usuario</label><input name="username" autofocus required>'
            '<label>Contraseña</label><input name="password" type="password" required>'
            '<label>Código 2FA <span class="muted">(si ya lo configuraste)</span></label>'
            '<input name="totp" inputmode="numeric" pattern="[0-9 ]*" maxlength="7" placeholder="123 456">'
            '<button class="primary">Entrar</button></form></div>')
    return layout(req, "Ingresar", body)


async def login_post(req):
    store, cfg = req.app["store"], req.app["cfg"]
    ip = client_ip(req)
    lst = [t for t in WEB_FAILS.get(ip, []) if time.time() - t < 300]
    if len(lst) >= 8:
        redirect("/login", err="Demasiados intentos. Espera unos minutos.")
    data = await req.post()
    u, err = store.check_login(data.get("username", ""), data.get("password", ""), data.get("totp", ""))
    if u is None:
        WEB_FAILS.setdefault(ip, []).append(time.time())
        store.audit(data.get("username", "")[:60], "web.login_fallido", err, ip)
        redirect("/login", err=err)
    if not u["totp_enabled"]:
        tok, _ = store.issue_token(u["id"], "setup", 0.25, "web")
        resp = web.HTTPSeeOther("/setup-2fa")
        resp.set_cookie("nexo_setup", tok, max_age=900, httponly=True, samesite="Strict",
                        secure=cfg.cookie_secure(req), path="/")
        raise resp
    tok, _ = store.issue_token(u["id"], "web", cfg.web_hours, "web")
    store.run("UPDATE users SET last_login = ? WHERE id = ?", time.time(), u["id"])
    store.audit(u["username"], "web.login", "", ip)
    resp = web.HTTPSeeOther("/")
    set_cookie(req, resp, tok, cfg.web_hours)
    raise resp


async def setup_2fa(req):
    store, cfg = req.app["store"], req.app["cfg"]
    raw = req.cookies.get("nexo_setup")
    u, _row = store.token_user(raw, "setup")
    if u is None:
        redirect("/login", err="La configuración de 2FA expiró; vuelve a ingresar")
    if req.method == "POST":
        data = await req.post()
        step = totp_match(u["totp_secret"], data.get("code", ""), u["totp_last_step"])
        if step is None:
            redirect("/setup-2fa", err="El código no coincide. Revisa la hora del teléfono e inténtalo otra vez.")
        store.run("UPDATE users SET totp_enabled = 1, totp_last_step = ? WHERE id = ?", step, u["id"])
        store.revoke_token(raw)
        store.audit(u["username"], "2fa.activado", "", client_ip(req))
        tok, _ = store.issue_token(u["id"], "web", cfg.web_hours, "web")
        resp = web.HTTPSeeOther("/")
        set_cookie(req, resp, tok, cfg.web_hours)
        resp.del_cookie("nexo_setup", path="/")
        raise resp
    if not u["totp_secret"]:
        store.run("UPDATE users SET totp_secret = ? WHERE id = ?", new_totp_secret(), u["id"])
        u = store.user(u["id"])
    uri = totp_uri(u["totp_secret"], u["username"], f"Nexo {cfg.org_name}")
    qr = segno.make(uri, error="m").svg_inline(scale=5, dark="#0b0c0f", light="#ffffff")
    secret = " ".join(u["totp_secret"][i:i + 4] for i in range(0, len(u["totp_secret"]), 4))
    body = ('<div class="center"><form class="login" method="post" style="width:420px">'
            '<h1>Activa tu 2FA</h1><p class="sub">Es obligatorio. Escanea el código con Google Authenticator, '
            'Microsoft Authenticator o similar.</p>'
            f'<div style="text-align:center"><div class="qr">{qr}</div></div>'
            f'<p class="muted" style="text-align:center;font-size:12px">o escribe la clave: <span class="mono">{e(secret)}</span></p>'
            '<label>Código de 6 dígitos</label><input name="code" inputmode="numeric" autofocus required maxlength="7">'
            '<button class="primary">Activar y entrar</button></form></div>')
    return layout(req, "2FA", body)


async def logout(req):
    req.app["store"].revoke_token(req["token"])
    resp = web.HTTPSeeOther("/login")
    resp.del_cookie(COOKIE, path="/")
    raise resp


async def password_page(req):
    store = req.app["store"]
    u = req["user"]
    if req.method == "POST":
        f = req["form"]
        from .store import verify_password
        if not verify_password(f.get("current", ""), u["pw_hash"]):
            redirect("/password", err="La contraseña actual no es correcta")
        if f.get("new") != f.get("new2"):
            redirect("/password", err="Las contraseñas nuevas no coinciden")
        err = password_policy(f.get("new", ""))
        if err:
            redirect("/password", err=err)
        store.run("UPDATE users SET pw_hash = ?, must_change_pw = 0 WHERE id = ?", hash_password(f["new"]), u["id"])
        store.audit(u["username"], "password.cambiada", "", client_ip(req))
        redirect("/", ok="Contraseña actualizada")
    forced = '<p class="flash">Debes cambiar la contraseña temporal antes de continuar.</p>' if u["must_change_pw"] else ""
    body = (f'<h1>Cambiar contraseña</h1><p class="sub">Mínimo 10 caracteres, con mayúsculas, minúsculas y números.</p>{forced}'
            f'<form class="box" method="post">{csrf_input(req)}'
            '<label>Contraseña actual</label><input type="password" name="current" required>'
            '<label>Nueva contraseña</label><input type="password" name="new" required>'
            '<label>Repetir nueva contraseña</label><input type="password" name="new2" required>'
            '<p><button class="primary">Guardar</button></p></form>')
    return layout(req, "Contraseña", body, "me")


# --- resumen y "mi acceso" ---------------------------------------------------------
async def home(req):
    u = req["user"]
    if u["role"] != "admin":
        raise web.HTTPSeeOther("/me")
    store = req.app["store"]
    live = gateway.live_sessions()
    n_users = store.one("SELECT COUNT(*) c FROM users")["c"]
    n_blocked = store.one("SELECT COUNT(*) c FROM users WHERE disabled = 1")["c"]
    n_hosts = store.one("SELECT COUNT(*) c FROM hosts")["c"]
    day = store.one("SELECT COUNT(*) c FROM sessions WHERE started > ?", time.time() - 86400)["c"]
    cards = (f'<div class="cards"><div class="card"><b>{len(live)}</b><span>sesiones en vivo</span></div>'
             f'<div class="card"><b>{day}</b><span>sesiones en 24 h</span></div>'
             f'<div class="card"><b>{n_users}</b><span>usuarios ({n_blocked} bloqueados)</span></div>'
             f'<div class="card"><b>{n_hosts}</b><span>hosts administrados</span></div></div>')
    body = (f'<h1>Resumen</h1><p class="sub">Puerta SSH en <span class="mono">{e(req.app["cfg"].public_host)}:'
            f'{req.app["cfg"].public_ssh_port}</span> · huella <span class="mono">{e(req.app["fingerprint"])}</span></p>'
            + cards + "<h2>En vivo</h2>" + sessions_table(req, live_only=True) + "<h2>Actividad reciente</h2>"
            + audit_table(store.q("SELECT * FROM audit ORDER BY ts DESC LIMIT 12")))
    return layout(req, "Resumen", body, "home")


async def me(req):
    store, cfg = req.app["store"], req.app["cfg"]
    u = req["user"]
    hosts = store.allowed_hosts(u["id"])
    rows = "".join(
        f'<tr><td>{e(h["name"])}</td><td>{e(h["group"])}</td><td>'
        + " ".join(f'<span class="pill ok">{k}</span>' for k, v in (("terminal", h["perms"]["shell"]),
                                                                  ("sftp", h["perms"]["sftp"]),
                                                                  ("túneles", h["perms"]["tunnel"])) if v)
        + f'</td><td class="mono">ssh -p {cfg.public_ssh_port} {e(u["username"])}:{e(h["name"])}@{e(cfg.public_host)}</td></tr>'
        for h in hosts) or '<tr><td colspan="4" class="muted">Aún no tienes hosts asignados.</td></tr>'
    body = (f'<h1>Mi acceso</h1><p class="sub">Hola {e(u["full_name"] or u["username"])}. Estos son los hosts a los que '
            'puedes entrar. Las credenciales las guarda el servidor: nunca se te entregan.</p>'
            '<table><tr><th>Host</th><th>Grupo</th><th>Permisos</th><th>Desde una terminal</th></tr>' + rows + '</table>'
            '<h2>Con la app Nexo</h2><p class="muted">En Nexo: menú <b>Organizaciones → Agregar</b>, escribe '
            f'<span class="mono">{e(cfg.public_url)}</span>, tu usuario, contraseña y código 2FA.</p>'
            '<h2>Seguridad</h2><p><a class="btn" href="/password">Cambiar contraseña</a></p>')
    return layout(req, "Mi acceso", body, "me")


# --- sesiones -------------------------------------------------------------------
def sessions_table(req, live_only=False, limit=200):
    store = req.app["store"]
    live = gateway.live_sessions()
    if live_only:
        rows = [r for r in store.q("SELECT * FROM sessions WHERE ended IS NULL ORDER BY started DESC") if r["id"] in live]
    else:
        rows = store.q("SELECT * FROM sessions ORDER BY started DESC LIMIT ?", limit)
    if not rows:
        return '<p class="muted">Sin sesiones.</p>'
    out = ['<table><tr><th>Inicio</th><th>Usuario</th><th>Host</th><th>Tipo</th><th>Duración</th>'
           '<th>Tráfico</th><th>Origen</th><th></th></tr>']
    for r in rows:
        is_live = r["id"] in live and not r["ended"]
        state = '<span class="pill ok">en vivo</span>' if is_live else ""
        acts = ""
        if r["recording"]:
            acts += f'<a class="btn small" href="/sessions/{e(r["id"])}/play">Ver grabación</a> '
        if is_live:
            acts += (f'<form class="inline" method="post" action="/sessions/{e(r["id"])}/kill">{csrf_input(req)}'
                     '<button class="small danger">Cortar</button></form>')
        out.append(f'<tr><td>{fmt_ts(r["started"])} {state}</td><td>{e(r["username"])}</td><td>{e(r["host_name"])}</td>'
                   f'<td>{e(r["kind"])} <span class="muted mono">{e(r["detail"])[:40]}</span></td>'
                   f'<td>{fmt_dur(r["started"], r["ended"])}</td><td class="muted">↑{human(r["bytes_in"])} ↓{human(r["bytes_out"])}</td>'
                   f'<td class="mono muted">{e(r["client_ip"])}</td><td class="actions">{acts}</td></tr>')
    out.append("</table>")
    return "".join(out)


async def sessions(req):
    body = ('<h1>Sesiones</h1><p class="sub">Terminal, comandos, SFTP y túneles que pasaron por Nexo. '
            'Las sesiones de terminal quedan grabadas.</p>' + sessions_table(req))
    return layout(req, "Sesiones", body, "sessions")


async def session_kill(req):
    sid = req.match_info["sid"]
    ok = gateway.kill_session(sid)
    req.app["store"].audit(req["user"]["username"], "admin.cortar_sesion", sid, client_ip(req))
    redirect("/sessions", ok="Sesión cortada" if ok else None, err=None if ok else "La sesión ya no estaba activa")


async def session_play(req):
    store = req.app["store"]
    r = store.one("SELECT * FROM sessions WHERE id = ?", req.match_info["sid"])
    if r is None or not r["recording"]:
        raise web.HTTPNotFound()
    store.audit(req["user"]["username"], "admin.ver_grabacion", r["id"], client_ip(req))
    body = (f'<h1>Grabación</h1><p class="sub">{e(r["username"])} → {e(r["host_name"])} · {fmt_ts(r["started"])} · '
            f'{fmt_dur(r["started"], r["ended"])}</p><link rel="stylesheet" href="/static/asciinema-player.css">'
            '<div id="p"></div><script src="/static/asciinema-player.min.js"></script>'
            f'<script>AsciinemaPlayer.create("/sessions/{e(r["id"])}/cast",document.getElementById("p"),'
            '{fit:"width",theme:"monokai",idleTimeLimit:2,poster:"npt:0:3",terminalFontFamily:"JetBrains Mono,monospace"});</script>'
            f'<p><a class="btn" href="/sessions/{e(r["id"])}/cast" download>Descargar .cast</a></p>')
    return layout(req, "Grabación", body, "sessions")


async def session_cast(req):
    store = req.app["store"]
    r = store.one("SELECT recording FROM sessions WHERE id = ?", req.match_info["sid"])
    if r is None or not r["recording"]:
        raise web.HTTPNotFound()
    path = os.path.join(store.data_dir, "recordings", os.path.basename(r["recording"]))
    if not os.path.exists(path):
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Content-Type": "application/x-asciicast", "Cache-Control": "no-store"})


# --- usuarios ---------------------------------------------------------------------
async def users(req):
    store = req.app["store"]
    live_users = {uid for uid, conns in gateway.LIVE.items() if conns}
    rows = []
    for u in store.q("SELECT * FROM users ORDER BY username"):
        teams = ", ".join(t["name"] for t in store.q(
            "SELECT t.name FROM teams t JOIN team_members m ON m.team_id = t.id WHERE m.user_id = ?", u["id"]))
        st = '<span class="pill bad">bloqueado</span>' if u["disabled"] else '<span class="pill ok">activo</span>'
        if not u["totp_enabled"]:
            st += ' <span class="pill warn">sin 2FA</span>'
        if u["id"] in live_users:
            st += ' <span class="pill ok">conectado</span>'
        toggle = "Desbloquear" if u["disabled"] else "Bloquear"
        rows.append(
            f'<tr><td><b>{e(u["username"])}</b><br><span class="muted">{e(u["full_name"])}</span></td><td>{e(u["role"])}</td>'
            f'<td>{e(teams)}</td><td>{st}</td><td class="muted">{fmt_ts(u["last_login"])}</td><td class="actions">'
            f'<form class="inline" method="post" action="/users/{u["id"]}/toggle">{csrf_input(req)}'
            f'<button class="small {"danger" if not u["disabled"] else ""}">{toggle}</button></form>'
            f'<a class="btn small" href="/users/{u["id"]}">Editar</a></td></tr>')
    body = ('<h1>Usuarios</h1><p class="sub">Bloquear corta al instante sus sesiones y anula sus tokens. '
            'No hace falta cambiar ninguna llave en los servidores.</p>'
            '<table><tr><th>Usuario</th><th>Rol</th><th>Equipos</th><th>Estado</th><th>Último ingreso</th><th></th></tr>'
            + "".join(rows) + '</table><h2>Nuevo usuario</h2>'
            f'<form class="box" method="post" action="/users/new">{csrf_input(req)}<div class="grid2">'
            '<div><label>Usuario</label><input name="username" required pattern="[A-Za-z0-9._-]{2,40}"></div>'
            '<div><label>Nombre completo</label><input name="full_name"></div>'
            '<div><label>Rol</label><select name="role"><option value="user">Usuario</option>'
            '<option value="admin">Administrador</option></select></div></div>'
            '<p class="muted">Se genera una contraseña temporal; al primer ingreso tendrá que cambiarla y activar 2FA.</p>'
            '<button class="primary">Crear usuario</button></form>')
    return layout(req, "Usuarios", body, "users")


async def user_new(req):
    store, f = req.app["store"], req["form"]
    name = f.get("username", "").strip()
    if not name or store.user_by_name(name):
        redirect("/users", err="Usuario vacío o ya existe")
    pw = temp_password()
    store.create_user(name, pw, "admin" if f.get("role") == "admin" else "user", f.get("full_name", ""))
    store.audit(req["user"]["username"], "admin.crear_usuario", name, client_ip(req))
    redirect("/users", ok=f"Usuario {name} creado. Contraseña temporal (se muestra solo esta vez): {pw}")


async def user_toggle(req):
    store = req.app["store"]
    uid = int(req.match_info["uid"])
    u = store.user(uid)
    if u is None:
        raise web.HTTPNotFound()
    if uid == req["user"]["id"]:
        redirect("/users", err="No puedes bloquearte a ti mismo")
    new = 0 if u["disabled"] else 1
    store.run("UPDATE users SET disabled = ? WHERE id = ?", new, uid)
    msg = f"{u['username']} desbloqueado"
    if new:
        store.revoke_user_tokens(uid)
        n = gateway.kill_user(uid)
        msg = f"{u['username']} bloqueado. Sesiones cortadas: {n}"
    store.audit(req["user"]["username"], "admin.bloquear" if new else "admin.desbloquear", u["username"], client_ip(req))
    redirect("/users", ok=msg)


async def user_edit(req):
    store = req.app["store"]
    uid = int(req.match_info["uid"])
    u = store.user(uid)
    if u is None:
        raise web.HTTPNotFound()
    if req.method == "POST":
        f = req["form"]
        action = f.get("action")
        actor = req["user"]["username"]
        if action == "save":
            role = "admin" if f.get("role") == "admin" else "user"
            if uid == req["user"]["id"] and role != "admin":
                redirect(f"/users/{uid}", err="No puedes quitarte el rol de administrador")
            store.run("UPDATE users SET full_name = ?, role = ? WHERE id = ?", f.get("full_name", ""), role, uid)
            store.run("DELETE FROM team_members WHERE user_id = ?", uid)
            for tid in f.getall("teams", []):
                store.run("INSERT OR IGNORE INTO team_members (team_id, user_id) VALUES (?,?)", int(tid), uid)
            store.audit(actor, "admin.editar_usuario", u["username"], client_ip(req))
            redirect(f"/users/{uid}", ok="Guardado")
        if action == "reset_pw":
            pw = temp_password()
            store.run("UPDATE users SET pw_hash = ?, must_change_pw = 1 WHERE id = ?", hash_password(pw), uid)
            store.revoke_user_tokens(uid)
            store.audit(actor, "admin.reset_password", u["username"], client_ip(req))
            redirect(f"/users/{uid}", ok=f"Nueva contraseña temporal (solo se muestra ahora): {pw}")
        if action == "reset_2fa":
            store.run("UPDATE users SET totp_enabled = 0, totp_secret = NULL, totp_last_step = 0 WHERE id = ?", uid)
            store.revoke_user_tokens(uid)
            gateway.kill_user(uid, "reiniciado")
            store.audit(actor, "admin.reset_2fa", u["username"], client_ip(req))
            redirect(f"/users/{uid}", ok="2FA reiniciado: lo configurará otra vez en su próximo ingreso")
        if action == "delete":
            if uid == req["user"]["id"]:
                redirect(f"/users/{uid}", err="No puedes eliminarte a ti mismo")
            gateway.kill_user(uid, "eliminado")
            store.run("DELETE FROM grants WHERE subject = 'user' AND subject_id = ?", uid)
            store.run("DELETE FROM users WHERE id = ?", uid)
            store.audit(actor, "admin.eliminar_usuario", u["username"], client_ip(req))
            redirect("/users", ok=f"{u['username']} eliminado")
    member = {r["team_id"] for r in store.q("SELECT team_id FROM team_members WHERE user_id = ?", uid)}
    teams = "".join(f'<label style="display:inline-flex;gap:6px;margin-right:14px"><input type="checkbox" name="teams" '
                    f'value="{t["id"]}" {"checked" if t["id"] in member else ""}> {e(t["name"])}</label>'
                    for t in store.q("SELECT * FROM teams ORDER BY name")) or '<span class="muted">No hay equipos.</span>'
    hosts = store.allowed_hosts(uid)
    hl = ", ".join(e(h["name"]) for h in hosts) or '<span class="muted">ninguno</span>'
    body = (f'<h1>{e(u["username"])}</h1><p class="sub">Puede entrar a: {hl}</p>'
            f'<form class="box" method="post">{csrf_input(req)}<input type="hidden" name="action" value="save">'
            f'<label>Nombre completo</label><input name="full_name" value="{e(u["full_name"])}">'
            '<label>Rol</label><select name="role">'
            f'<option value="user" {"selected" if u["role"] == "user" else ""}>Usuario</option>'
            f'<option value="admin" {"selected" if u["role"] == "admin" else ""}>Administrador</option></select>'
            f'<label>Equipos</label><div>{teams}</div><p><button class="primary">Guardar</button></p></form>'
            '<h2>Seguridad de la cuenta</h2><div class="actions">'
            + "".join(f'<form class="inline" method="post">{csrf_input(req)}<input type="hidden" name="action" value="{a}">'
                      f'<button class="{c}" onclick="return confirm(\'{q}\')">{t}</button></form>'
                      for a, t, c, q in (("reset_pw", "Restablecer contraseña", "", "¿Generar contraseña temporal?"),
                                         ("reset_2fa", "Reiniciar 2FA", "", "¿Reiniciar el 2FA de este usuario?"),
                                         ("delete", "Eliminar usuario", "danger", "¿Eliminar definitivamente?")))
            + "</div>")
    return layout(req, u["username"], body, "users")


# --- equipos ----------------------------------------------------------------------
async def teams(req):
    store = req.app["store"]
    if req.method == "POST":
        f = req["form"]
        if f.get("action") == "new" and f.get("name", "").strip():
            try:
                store.run("INSERT INTO teams (name) VALUES (?)", f["name"].strip())
            except Exception:  # noqa: BLE001
                redirect("/teams", err="Ya existe un equipo con ese nombre")
            store.audit(req["user"]["username"], "admin.crear_equipo", f["name"].strip(), client_ip(req))
        elif f.get("action") == "delete":
            tid = int(f.get("id", 0))
            store.run("DELETE FROM grants WHERE subject = 'team' AND subject_id = ?", tid)
            store.run("DELETE FROM teams WHERE id = ?", tid)
            store.audit(req["user"]["username"], "admin.eliminar_equipo", str(tid), client_ip(req))
        redirect("/teams", ok="Listo")
    rows = []
    for t in store.q("SELECT * FROM teams ORDER BY name"):
        members = ", ".join(e(r["username"]) for r in store.q(
            "SELECT u.username FROM users u JOIN team_members m ON m.user_id = u.id WHERE m.team_id = ?", t["id"]))
        rows.append(f'<tr><td><b>{e(t["name"])}</b></td><td>{members or "—"}</td><td>'
                    f'<form class="inline" method="post">{csrf_input(req)}<input type="hidden" name="action" value="delete">'
                    f'<input type="hidden" name="id" value="{t["id"]}"><button class="small danger" '
                    'onclick="return confirm(\'¿Eliminar equipo?\')">Eliminar</button></form></td></tr>')
    body = ('<h1>Equipos</h1><p class="sub">Agrupa personas (Soporte, Desarrollo, Proveedor X) y dale acceso a hosts '
            'por equipo. Los miembros se asignan al editar cada usuario.</p>'
            '<table><tr><th>Equipo</th><th>Miembros</th><th></th></tr>' + "".join(rows) + '</table>'
            f'<h2>Nuevo equipo</h2><form class="box" method="post">{csrf_input(req)}<input type="hidden" name="action" value="new">'
            '<label>Nombre</label><input name="name" required><p><button class="primary">Crear</button></p></form>')
    return layout(req, "Equipos", body, "teams")


# --- hosts y permisos ---------------------------------------------------------------
async def hosts(req):
    store = req.app["store"]
    rows = []
    for h in store.q("SELECT * FROM hosts ORDER BY grp, name"):
        n_grants = store.one("SELECT COUNT(*) c FROM grants WHERE host_id = ?", h["id"])["c"]
        rows.append(f'<tr><td><b>{e(h["name"])}</b><br><span class="muted">{e(h["grp"])}</span></td>'
                    f'<td class="mono">{e(h["username"])}@{e(h["address"])}:{h["port"]}</td>'
                    f'<td>{"llave" if h["auth"] == "key" else "contraseña"}</td>'
                    f'<td>{n_grants} regla(s)</td><td>{"sí" if h["record"] else "no"}</td>'
                    f'<td class="actions"><a class="btn small" href="/hosts/{h["id"]}">Editar y permisos</a></td></tr>')
    body = ('<h1>Hosts</h1><p class="sub">Servidores a los que Nexo da acceso. Las credenciales se guardan cifradas '
            '(AES-256-GCM) y nunca se muestran ni se entregan a los usuarios.</p>'
            '<p><a class="btn" href="/hosts/new">+ Nuevo host</a></p>'
            '<table><tr><th>Host</th><th>Destino</th><th>Credencial</th><th>Acceso</th><th>Graba</th><th></th></tr>'
            + "".join(rows) + "</table>")
    return layout(req, "Hosts", body, "hosts")


def host_form(req, h=None):
    h = h or {}
    v = lambda k, d="": e(h[k]) if h and h[k] is not None else d  # noqa: E731
    icons = "".join(f'<option value="{i}" {"selected" if h and h["icon"] == i else ""}>{i or "—"}</option>' for i in ICONS)
    has_secret = bool(h and h["secret"])
    return (f'<form class="box" method="post">{csrf_input(req)}<input type="hidden" name="action" value="save"><div class="grid2">'
            f'<div><label>Nombre</label><input name="name" required value="{v("name")}"></div>'
            f'<div><label>Grupo</label><input name="grp" value="{v("grp")}" placeholder="Producción, Linux…"></div>'
            f'<div><label>Dirección (IP o DNS)</label><input name="address" required value="{v("address")}"></div>'
            f'<div><label>Puerto</label><input name="port" type="number" value="{v("port", "22")}"></div>'
            f'<div><label>Usuario en el servidor</label><input name="username" required value="{v("username")}"></div>'
            '<div><label>Autenticación</label><select name="auth">'
            f'<option value="key" {"selected" if not h or h["auth"] == "key" else ""}>Llave privada</option>'
            f'<option value="password" {"selected" if h and h["auth"] == "password" else ""}>Contraseña</option></select></div>'
            f'</div><label>Llave privada o contraseña {"(déjalo vacío para conservar la actual)" if has_secret else ""}</label>'
            '<textarea name="secret" placeholder="-----BEGIN OPENSSH PRIVATE KEY-----  …  o la contraseña"></textarea>'
            f'<div class="grid2"><div><label>Icono</label><select name="icon">{icons}</select></div>'
            f'<div><label>Grabar sesiones</label><select name="record"><option value="1">Sí</option>'
            f'<option value="0" {"selected" if h and not h["record"] else ""}>No</option></select></div></div>'
            f'<label>Notas</label><input name="notes" value="{v("notes")}">'
            '<p><button class="primary">Guardar</button></p></form>')


async def host_new(req):
    if req.method == "POST":
        return await _save_host(req, None)
    return layout(req, "Nuevo host", '<h1>Nuevo host</h1><p class="sub">Después de guardarlo, asigna quién puede '
                  'entrar.</p>' + host_form(req), "hosts")


async def _save_host(req, hid):
    store, f = req.app["store"], req["form"]
    name, address, user = f.get("name", "").strip(), f.get("address", "").strip(), f.get("username", "").strip()
    if not (name and address and user):
        redirect(req.path, err="Faltan datos obligatorios")
    port = int(f.get("port") or 22)
    secret = f.get("secret", "")
    auth = "password" if f.get("auth") == "password" else "key"
    if auth == "key" and secret.strip():
        import asyncssh
        try:
            asyncssh.import_private_key(secret.strip())
        except Exception:  # noqa: BLE001
            redirect(req.path, err="La llave privada no es válida (¿tiene frase? quítasela antes de cargarla)")
        secret = secret.strip() + "\n"
    try:
        if hid is None:
            hid = store.run("INSERT INTO hosts (name, grp, address, port, username, auth, icon, notes, record, created)"
                            " VALUES (?,?,?,?,?,?,?,?,?,?)", name, f.get("grp", "").strip(), address, port, user, auth,
                            f.get("icon", ""), f.get("notes", ""), int(f.get("record", "1")), time.time())
            action = "admin.crear_host"
        else:
            old = store.one("SELECT address, port FROM hosts WHERE id = ?", hid)
            store.run("UPDATE hosts SET name=?, grp=?, address=?, port=?, username=?, auth=?, icon=?, notes=?, record=? WHERE id=?",
                      name, f.get("grp", "").strip(), address, port, user, auth, f.get("icon", ""), f.get("notes", ""),
                      int(f.get("record", "1")), hid)
            if old and (old["address"], old["port"]) != (address, port):
                store.run("UPDATE hosts SET host_key = NULL WHERE id = ?", hid)
            action = "admin.editar_host"
    except Exception:  # noqa: BLE001
        redirect(req.path, err="Ya existe un host con ese nombre")
    if secret.strip():
        store.run("UPDATE hosts SET secret = ? WHERE id = ?", store.seal(hid, secret), hid)
    store.audit(req["user"]["username"], action, name, client_ip(req))
    redirect(f"/hosts/{hid}", ok="Host guardado")


async def host_edit(req):
    store = req.app["store"]
    hid = int(req.match_info["hid"])
    h = store.one("SELECT * FROM hosts WHERE id = ?", hid)
    if h is None:
        raise web.HTTPNotFound()
    if req.method == "POST":
        f = req["form"]
        a = f.get("action")
        actor = req["user"]["username"]
        if a == "save":
            return await _save_host(req, hid)
        if a == "grant":
            subj, sid = f.get("subject", "user:0").split(":")
            store.run("INSERT INTO grants (subject, subject_id, host_id, shell, sftp, tunnel) VALUES (?,?,?,?,?,?) "
                      "ON CONFLICT(subject, subject_id, host_id) DO UPDATE SET shell=excluded.shell, sftp=excluded.sftp, "
                      "tunnel=excluded.tunnel", subj, int(sid), hid, int("shell" in f), int("sftp" in f), int("tunnel" in f))
            store.audit(actor, "admin.dar_acceso", f"{subj}:{sid} -> {h['name']}", client_ip(req))
            redirect(f"/hosts/{hid}", ok="Acceso actualizado")
        if a == "revoke":
            g = store.one("SELECT * FROM grants WHERE id = ?", int(f.get("gid", 0)))
            store.run("DELETE FROM grants WHERE id = ?", int(f.get("gid", 0)))
            if g and g["subject"] == "user":
                gateway.kill_user(g["subject_id"], "retirado para este host")
            store.audit(actor, "admin.quitar_acceso", f"{h['name']}", client_ip(req))
            redirect(f"/hosts/{hid}", ok="Acceso retirado")
        if a == "forget_key":
            store.run("UPDATE hosts SET host_key = NULL WHERE id = ?", hid)
            store.audit(actor, "admin.olvidar_huella", h["name"], client_ip(req))
            redirect(f"/hosts/{hid}", ok="Huella olvidada: se aceptará la próxima")
        if a == "delete":
            store.run("DELETE FROM hosts WHERE id = ?", hid)
            store.audit(actor, "admin.eliminar_host", h["name"], client_ip(req))
            redirect("/hosts", ok=f"{h['name']} eliminado")
    grants = []
    for g in store.q("SELECT * FROM grants WHERE host_id = ?", hid):
        if g["subject"] == "user":
            s = store.user(g["subject_id"])
            who = f'👤 {e(s["username"]) if s else "?"}'
        else:
            t = store.one("SELECT name FROM teams WHERE id = ?", g["subject_id"])
            who = f'👥 {e(t["name"]) if t else "?"}'
        perms = " ".join(f'<span class="pill ok">{n}</span>' for n, k in (("terminal", "shell"), ("sftp", "sftp"),
                                                                         ("túneles", "tunnel")) if g[k])
        grants.append(f'<tr><td>{who}</td><td>{perms}</td><td><form class="inline" method="post">{csrf_input(req)}'
                      f'<input type="hidden" name="action" value="revoke"><input type="hidden" name="gid" value="{g["id"]}">'
                      '<button class="small danger">Quitar</button></form></td></tr>')
    subjects = "".join(f'<option value="user:{u["id"]}">👤 {e(u["username"])}</option>'
                       for u in store.q("SELECT * FROM users ORDER BY username"))
    subjects += "".join(f'<option value="team:{t["id"]}">👥 {e(t["name"])}</option>'
                        for t in store.q("SELECT * FROM teams ORDER BY name"))
    body = (f'<h1>{e(h["name"])}</h1><p class="sub">Huella del servidor: <span class="mono">{e(h["host_key"] or "aún no conectado")}</span></p>'
            '<h2>Quién puede entrar</h2><table><tr><th>Persona o equipo</th><th>Permisos</th><th></th></tr>'
            + ("".join(grants) or '<tr><td colspan="3" class="muted">Nadie todavía.</td></tr>') + '</table>'
            f'<form class="box" method="post" style="margin-top:12px">{csrf_input(req)}<input type="hidden" name="action" value="grant">'
            f'<label>Dar acceso a</label><select name="subject">{subjects}</select><div style="margin-top:10px">'
            '<label style="display:inline-flex;gap:6px;margin-right:16px"><input type="checkbox" name="shell" checked> Terminal</label>'
            '<label style="display:inline-flex;gap:6px;margin-right:16px"><input type="checkbox" name="sftp" checked> SFTP</label>'
            '<label style="display:inline-flex;gap:6px"><input type="checkbox" name="tunnel"> Túneles (-L / -D)</label></div>'
            '<p><button class="primary">Dar acceso</button></p></form>'
            '<h2>Datos del host</h2>' + host_form(req, h)
            + '<h2>Zona peligrosa</h2><div class="actions">'
            f'<form class="inline" method="post">{csrf_input(req)}<input type="hidden" name="action" value="forget_key">'
            '<button onclick="return confirm(\'¿Aceptar una huella nueva? Hazlo solo si reinstalaste el servidor.\')">'
            'Olvidar huella</button></form>'
            f'<form class="inline" method="post">{csrf_input(req)}<input type="hidden" name="action" value="delete">'
            '<button class="danger" onclick="return confirm(\'¿Eliminar host y sus permisos?\')">Eliminar host</button></form></div>')
    return layout(req, h["name"], body, "hosts")


# --- auditoría -------------------------------------------------------------------
def audit_table(rows):
    if not rows:
        return '<p class="muted">Sin eventos.</p>'
    return ('<table><tr><th>Fecha</th><th>Quién</th><th>Acción</th><th>Detalle</th><th>IP</th></tr>' + "".join(
        f'<tr><td>{fmt_ts(r["ts"])}</td><td>{e(r["actor"])}</td><td class="mono">{e(r["action"])}</td>'
        f'<td>{e(r["detail"])}</td><td class="mono muted">{e(r["ip"])}</td></tr>' for r in rows) + "</table>")


async def audit(req):
    rows = req.app["store"].q("SELECT * FROM audit ORDER BY ts DESC LIMIT 500")
    return layout(req, "Auditoría", '<h1>Auditoría</h1><p class="sub">Últimos 500 eventos (ingresos, accesos, '
                  'cambios de administración).</p>' + audit_table(rows), "audit")


# --- API para la app ------------------------------------------------------------------
def _bearer(req):
    h = req.headers.get("Authorization", "")
    return h[7:] if h.startswith("Bearer ") else ""


async def api_info(req):
    cfg = req.app["cfg"]
    return web.json_response({"name": cfg.org_name, "ssh_host": cfg.public_host, "ssh_port": cfg.public_ssh_port,
                              "fingerprint": req.app["fingerprint"], "version": req.app["version"]})


async def api_login(req):
    store, cfg = req.app["store"], req.app["cfg"]
    ip = client_ip(req)
    lst = [t for t in WEB_FAILS.get(ip, []) if time.time() - t < 300]
    if len(lst) >= 8:
        return web.json_response({"error": "Demasiados intentos. Espera unos minutos."}, status=429)
    try:
        data = await req.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"error": "JSON inválido"}, status=400)
    u, err = store.check_login(data.get("username", ""), data.get("password", ""), data.get("totp", ""))
    if u is None:
        WEB_FAILS.setdefault(ip, []).append(time.time())
        store.audit(str(data.get("username", ""))[:60], "app.login_fallido", err, ip)
        return web.json_response({"error": err}, status=401)
    if not u["totp_enabled"]:
        return web.json_response({"error": f"Primero activa tu 2FA entrando a {cfg.public_url}"}, status=403)
    if u["must_change_pw"]:
        return web.json_response({"error": f"Debes cambiar tu contraseña temporal en {cfg.public_url}"}, status=403)
    tok, _ = store.issue_token(u["id"], "app", cfg.token_hours, str(data.get("client", "app"))[:80])
    store.audit(u["username"], "app.login", "", ip)
    return web.json_response({"token": tok, "expires": time.time() + cfg.token_hours * 3600,
                              "username": u["username"], "name": cfg.org_name, "ssh_host": cfg.public_host,
                              "ssh_port": cfg.public_ssh_port, "fingerprint": req.app["fingerprint"]})


async def api_hosts(req):
    store = req.app["store"]
    u, _ = store.token_user(_bearer(req), "app")
    if u is None:
        return web.json_response({"error": "Sesión expirada o revocada"}, status=401)
    return web.json_response({"username": u["username"], "hosts": store.allowed_hosts(u["id"])})


async def api_logout(req):
    req.app["store"].revoke_token(_bearer(req))
    return web.json_response({"ok": True})


async def healthz(req):
    return web.Response(text="ok")


@web.middleware
async def security_headers(req, handler):
    resp = await handler(req)
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Content-Security-Policy",
                            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                            "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
    return resp


def make_app(store, cfg, fingerprint, version):
    app = web.Application(middlewares=[security_headers, auth_mw], client_max_size=2 * 1024 * 1024)
    app["store"], app["cfg"], app["fingerprint"], app["version"] = store, cfg, fingerprint, version
    r = app.router
    r.add_get("/login", login_get)
    r.add_post("/login", login_post)
    r.add_route("*", "/setup-2fa", setup_2fa)
    r.add_post("/logout", logout)
    r.add_route("*", "/password", password_page)
    r.add_get("/", home)
    r.add_get("/me", me)
    r.add_get("/sessions", sessions)
    r.add_post("/sessions/{sid}/kill", session_kill)
    r.add_get("/sessions/{sid}/play", session_play)
    r.add_get("/sessions/{sid}/cast", session_cast)
    r.add_get("/users", users)
    r.add_post("/users/new", user_new)
    r.add_post("/users/{uid:\\d+}/toggle", user_toggle)
    r.add_route("*", "/users/{uid:\\d+}", user_edit)
    r.add_route("*", "/teams", teams)
    r.add_get("/hosts", hosts)
    r.add_route("*", "/hosts/new", host_new)
    r.add_route("*", "/hosts/{hid:\\d+}", host_edit)
    r.add_get("/audit", audit)
    r.add_get("/api/v1/info", api_info)
    r.add_post("/api/v1/login", api_login)
    r.add_get("/api/v1/hosts", api_hosts)
    r.add_post("/api/v1/logout", api_logout)
    r.add_get("/healthz", healthz)
    r.add_static("/static/", STATIC)
    return app
