"""Armado de conexiones: ssh (terminal y túneles), SFTP con paramiko y RDP."""
import os
import shlex
import shutil
import socket
import subprocess
import threading
import time

from . import keys as K

SSH = shutil.which("ssh") or "/usr/bin/ssh"
SSHPASS = shutil.which("sshpass")


class ConnError(Exception):
    pass


DEFAULT_PORTS = {"ssh": 22, "rdp": 3389, "postgres": 5432, "mysql": 3306, "mssql": 1433, "mongodb": 27017, "redis": 6379}


def label(host):
    user = f"{host['user']}@" if host.get("user") else ""
    default = DEFAULT_PORTS.get(host["protocol"], 22)
    port = host.get("port") or default
    return f"{user}{host['host']}" + (f":{port}" if int(port) != default else "")


class Builder:
    """Arma la línea de ssh para un host guardado en la bóveda."""

    def __init__(self, vault, agent):
        self.vault = vault
        self.agent = agent

    def org_token(self, host):
        org = self.vault.org(host.get("org")) if host.get("org") else None
        if not org or not org.get("token"):
            raise ConnError("Tu sesión en la organización expiró. Vuelve a ingresar (menú del grupo de la organización).")
        import time as _t
        if org.get("expires") and org["expires"] < _t.time():
            raise ConnError(f"Tu sesión en «{org['name']}» expiró. Vuelve a ingresar.")
        return org["token"]

    def _auth_opts(self, host, batch=False):
        opts = []
        if host.get("auth") == "org":
            return ["-o", "PubkeyAuthentication=no", "-o", "PreferredAuthentications=password",
                    "-o", "NumberOfPasswordPrompts=1"]
        if host.get("auth") == "key":
            key = self.vault.key(host.get("key")) if host.get("key") else None
            if not key:
                raise ConnError(f"El host «{host['name']}» no tiene una llave asignada")
            pub = self.agent.ensure(key)
            opts += ["-o", "IdentitiesOnly=yes", "-i", pub]
        else:
            opts += [
                "-o", "PubkeyAuthentication=no",
                "-o", "PreferredAuthentications=password,keyboard-interactive",
            ]
        if batch:
            opts += ["-o", "BatchMode=yes"]
        return opts

    def _common(self):
        return [
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "LogLevel=ERROR",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-o", "ConnectTimeout=15",
        ]

    def _jump_opts(self, host, env, seen=None, depth=1):
        """ProxyCommand para llegar a `host` a través de su salto (y los saltos del salto).

        Si el salto usa contraseña, va en su propia variable de entorno (NEXO_JP1, NEXO_JP2…)
        y la lee sshpass: no se mezcla con la del destino, no toca el disco ni sale en `ps`.
        """
        jid = host.get("jump")
        if not jid:
            return []
        seen = (seen or set()) | {host["id"]}
        jump = self.vault.host(jid)
        if not jump:
            raise ConnError("El host de salto ya no existe")
        if jump["id"] in seen:
            raise ConnError("Hay un ciclo en los saltos")
        if jump.get("protocol", "ssh") != "ssh":
            raise ConnError(f"El salto «{jump['name']}» tiene que ser un host SSH")
        by_password = jump.get("auth") == "password"
        inner = [SSH] + self._common() + self._auth_opts(jump, batch=not by_password)
        # el ssh de afuera expande %h/%p en TODO su ProxyCommand: los del salto anidado van
        # escapados (%%) para que los expanda el ssh que les corresponde
        inner += [x.replace("%", "%%") for x in self._jump_opts(jump, env, seen, depth + 1)]
        inner += ["-W", "%h:%p", "-p", str(jump.get("port") or 22)]
        inner += [f"{jump['user']}@{jump['host']}" if jump.get("user") else jump["host"]]
        if by_password and jump.get("password"):
            if not SSHPASS:
                raise ConnError("Para un salto con contraseña instala sshpass: sudo apt install sshpass")
            var = f"NEXO_JP{depth}"
            env[var] = jump["password"]
            inner = [SSHPASS, f"-e{var}", "-P", "assword"] + inner
        # sin contraseña guardada: el ssh del salto la pedirá en la terminal
        return ["-o", "ProxyCommand=" + shlex.join(inner)]

    def ssh(self, host, extra=None, remote=None):
        """Devuelve (argv, env_extra) para abrir ssh hacia el host."""
        env = dict(self.agent.env())
        argv = [SSH] + self._common() + self._auth_opts(host) + self._jump_opts(host, env)
        argv += extra or []
        argv += ["-p", str(host.get("port") or 22)]
        argv += [f"{host['user']}@{host['host']}" if host.get("user") else host["host"]]
        if remote:
            argv += [remote]
        if host.get("auth") == "org":
            if not SSHPASS:
                raise ConnError("Para entrar por una organización instala sshpass: sudo apt install sshpass")
            argv = [SSHPASS, "-e", "-P", "assword"] + argv
            env["SSHPASS"] = self.org_token(host)
        elif host.get("auth") == "password":
            if not host.get("password"):
                pass  # ssh pedirá la contraseña en la terminal
            elif SSHPASS:
                argv = [SSHPASS, "-e", "-P", "assword"] + argv
                env["SSHPASS"] = host["password"]
        return argv, env

    def command_text(self, host):
        """Comando equivalente para copiar (sin secretos)."""
        parts = ["ssh"]
        if host.get("port") and int(host["port"]) != 22:
            parts += ["-p", str(host["port"])]
        if host.get("jump"):
            j = self.vault.host(host["jump"])
            if j:
                parts += ["-J", f"{j.get('user') + '@' if j.get('user') else ''}{j['host']}:{j.get('port') or 22}"]
        parts.append(f"{host['user']}@{host['host']}" if host.get("user") else host["host"])
        return shlex.join(parts)


def forward_spec(fw):
    bind = fw.get("bind") or "127.0.0.1"
    if fw["type"] == "D":
        return ["-D", f"{bind}:{fw['port']}"]
    flag = "-L" if fw["type"] == "L" else "-R"
    return [flag, f"{bind}:{fw['port']}:{fw['dest_host']}:{fw['dest_port']}"]


def forward_text(fw):
    bind = fw.get("bind") or "127.0.0.1"
    if fw["type"] == "D":
        return f"SOCKS {bind}:{fw['port']}"
    arrow = "→" if fw["type"] == "L" else "←"
    side = "local" if fw["type"] == "L" else "remoto"
    return f"{side} {bind}:{fw['port']} {arrow} {fw['dest_host']}:{fw['dest_port']}"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_port(port, timeout=15, proc=None):
    end = time.time() + timeout
    while time.time() < end:
        if proc is not None and proc.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


class Tunnel:
    """Un proceso `ssh -N` con uno o más reenvíos."""

    def __init__(self, builder, host, forwards, on_change=None):
        self.builder = builder
        self.host = host
        self.forwards = forwards
        self.on_change = on_change
        self.proc = None
        self.state = "detenido"
        self.error = ""

    def start(self):
        extra = ["-N", "-T", "-o", "ExitOnForwardFailure=yes"]
        for fw in self.forwards:
            extra += forward_spec(fw)
        if self.host.get("auth") == "password" and not self.host.get("password"):
            raise ConnError("Para un túnel con contraseña, guárdala en el host")
        j, seen = self.host, set()
        while j.get("jump") and j["id"] not in seen:
            seen.add(j["id"])
            j = self.builder.vault.host(j["jump"]) or {}
            if j.get("auth") == "password" and not j.get("password"):
                raise ConnError(f"Para usar el salto «{j.get('name')}» en un túnel, guarda su contraseña")
        argv, env = self.builder.ssh(self.host, extra)
        self.proc = subprocess.Popen(
            argv,
            env={**os.environ, **env},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        self._set("conectando")
        threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self):
        proc = self.proc
        local = [fw for fw in self.forwards if fw["type"] in ("L", "D")]
        if local:
            ok = wait_port(int(local[0]["port"]), timeout=20, proc=proc)
        else:
            time.sleep(3)
            ok = proc.poll() is None
        if ok and proc.poll() is None:
            self._set("activo")
        err = proc.stderr.read().decode(errors="replace").strip()
        proc.wait()
        if self.proc is proc:
            self.error = err.splitlines()[-1] if err else f"ssh terminó (código {proc.returncode})"
            self._set("detenido" if self.state == "deteniendo" else "error")

    def _set(self, state):
        self.state = state
        if self.on_change:
            self.on_change(self)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.state = "deteniendo"
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None


# --- SFTP ----------------------------------------------------------------

def paramiko_client(vault, host, _seen=None):
    import paramiko

    sock = None
    jump_client = None
    _seen = (_seen or set()) | {host["id"]}
    if host.get("jump"):
        jump = vault.host(host["jump"])
        if not jump or jump["id"] in _seen:
            raise ConnError("Salto no válido")
        jump_client = paramiko_client(vault, jump, _seen)
        sock = jump_client.get_transport().open_channel(
            "direct-tcpip", (host["host"], int(host.get("port") or 22)), ("127.0.0.1", 0)
        )
    client = paramiko.SSHClient()
    try:
        client.load_system_host_keys()
    except Exception:  # noqa: BLE001
        pass
    # Llave nueva: se acepta. Llave distinta a la de known_hosts: paramiko la rechaza.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kw = dict(
        hostname=host["host"],
        port=int(host.get("port") or 22),
        username=host.get("user") or os.environ.get("USER"),
        timeout=15,
        banner_timeout=15,
        auth_timeout=20,
        sock=sock,
        allow_agent=False,
        look_for_keys=False,
    )
    if host.get("auth") == "org":
        kw["password"] = Builder(vault, None).org_token(host)
    elif host.get("auth") == "key":
        key = vault.key(host.get("key"))
        if not key:
            raise ConnError("El host no tiene llave asignada")
        kw["pkey"] = K.paramiko_pkey(key["private"])
    else:
        if not host.get("password"):
            raise ConnError("SFTP con contraseña necesita la contraseña guardada en el host")
        kw["password"] = host["password"]
    try:
        client.connect(**kw)
    except paramiko.BadHostKeyException:
        raise ConnError(
            "¡La llave del servidor NO coincide con la de ~/.ssh/known_hosts! "
            "Puede ser un ataque de intermediario o un servidor reinstalado."
        )
    client._nexo_jump = jump_client  # mantener viva la conexión de salto
    return client


# --- RDP -----------------------------------------------------------------

RDP_BINARIES = ["xfreerdp3", "sdl-freerdp3", "xfreerdp", "sdl-freerdp"]


def rdp_binary():
    for b in RDP_BINARIES:
        p = shutil.which(b)
        if p:
            return p
    return None


class RdpSession:
    def __init__(self, builder, host, on_exit):
        self.builder = builder
        self.host = host
        self.on_exit = on_exit
        self.tunnel = None
        self.proc = None

    def start(self):
        binary = rdp_binary()
        if not binary:
            raise ConnError("No hay cliente FreeRDP. Instala: sudo apt install freerdp3-x11")
        threading.Thread(target=self._run, args=(binary,), daemon=True).start()

    def _run(self, binary):
        h = self.host
        target_host, target_port = h["host"], int(h.get("port") or 3389)
        try:
            if h.get("jump"):
                jump = self.builder.vault.host(h["jump"])
                if not jump:
                    raise ConnError("El host de salto ya no existe")
                lport = free_port()
                fw = {"type": "L", "bind": "127.0.0.1", "port": lport,
                      "dest_host": target_host, "dest_port": target_port}
                self.tunnel = Tunnel(self.builder, jump, [fw])
                self.tunnel.start()
                if not wait_port(lport, timeout=20, proc=self.tunnel.proc):
                    raise ConnError("No se pudo abrir el túnel por el salto: " + (self.tunnel.error or ""))
                target_host, target_port = "127.0.0.1", lport

            o = h.get("rdp") or {}
            args = [f"/v:{target_host}:{target_port}", "/cert:tofu", "+auto-reconnect",
                    "/auto-reconnect-max-retries:10", f"/title:{h['name']} — Nexo"]
            if h.get("user"):
                args.append(f"/u:{h['user']}")
            if o.get("domain"):
                args.append(f"/d:{o['domain']}")
            if h.get("password"):
                args.append(f"/p:{h['password']}")
            if o.get("fullscreen"):
                args.append("/f")
            res = o.get("resolution") or "auto"
            if res == "auto":
                args += ["+dynamic-resolution", "/size:90%"]
            else:
                args.append(f"/size:{res}")
            if o.get("clipboard", True):
                args.append("+clipboard")
            if o.get("share_home"):
                args.append(f"/drive:home,{os.path.expanduser('~')}")

            if "freerdp3" in os.path.basename(binary):
                # Los argumentos (incluida la contraseña) van por stdin: no quedan en `ps`.
                self.proc = subprocess.Popen(
                    [binary, "/args-from:stdin"], stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
                )
                self.proc.stdin.write(("\n".join(args) + "\n").encode())
                self.proc.stdin.close()
            else:
                self.proc = subprocess.Popen(
                    [binary] + args, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
                )
            started = time.time()
            out = self.proc.stdout.read().decode(errors="replace")
            code = self.proc.wait()
            err = ""
            if code != 0 and time.time() - started < 20:
                lines = [l for l in out.splitlines() if "ERROR" in l or "error" in l.lower()]
                err = "\n".join((lines or out.splitlines())[-4:]) or f"FreeRDP terminó con código {code}"
            self.on_exit(self, err)
        except Exception as e:  # noqa: BLE001
            self.on_exit(self, str(e))
        finally:
            if self.tunnel:
                self.tunnel.stop()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


# --- Importar ~/.ssh/config ----------------------------------------------

def parse_ssh_config(path):
    hosts, cur = [], None
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.replace("=", " ", 1).split(None, 1)
            if len(parts) < 2:
                continue
            k, v = parts[0].lower(), parts[1].strip().strip('"')
            if k == "host":
                cur = None
                aliases = [a for a in v.split() if not any(c in a for c in "*?!")]
                if aliases:
                    cur = {"alias": aliases[0]}
                    hosts.append(cur)
            elif k == "match":
                cur = None
            elif cur is not None:
                cur.setdefault(k, v)
    return hosts
