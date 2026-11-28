"""Escritorio remoto DENTRO de Nexo (Windows): el control RDP de Windows (mstscax.dll).

Es el mismo motor que usa «Conexión a Escritorio remoto», pero sin su ventana ni sus
avisos. No se abre un .rdp, así que no aparece «No se puede identificar al editor de esta
conexión remota». El certificado del servidor lo verifica Nexo por su cuenta (rdp.trust_check:
lo recuerda la primera vez y avisa si cambia), y por eso el control conecta sin preguntar.

- El control vive en una ventana hija de la ventana de Nexo, encima del área de la pestaña.
  La página informa el rectángulo (place) y Nexo la mueve, la muestra o la oculta.
- Todo lo que toca el control corre en el hilo de la interfaz (STA de WinForms) con
  form.Invoke. Los eventos (conectado, desconectado) llegan por comtypes en ese mismo hilo.
- La contraseña va directo al control (IMsTscNonScriptable.ClearTextPassword): no pasa por
  el disco ni por el Administrador de credenciales.
"""
import ctypes
import os
import threading
import time
from ctypes import wintypes

from . import IS_WINDOWS

# Clases del control, de la más nueva a la más vieja. Primero se usan las del typelib.
COCLASSES = ("MsRdpClient11NotSafeForScripting", "MsRdpClient10NotSafeForScripting",
             "MsRdpClient9NotSafeForScripting", "MsRdpClient8NotSafeForScripting",
             "MsRdpClient7NotSafeForScripting")
FALLBACK_CLSIDS = ("{A0C63C30-F08D-4AB4-907C-34905D770C7D}",   # v10
                   "{8B918B82-7985-4C24-89DF-C33AD2BBFBCD}",   # v9
                   "{54D38BF7-B1EF-4479-9674-1BD6EA465258}")   # v7

WS_CHILD, WS_VISIBLE, WS_CLIPSIBLINGS, WS_CLIPCHILDREN = 0x40000000, 0x10000000, 0x04000000, 0x02000000
SWP_NOACTIVATE, SWP_SHOWWINDOW, SWP_HIDEWINDOW = 0x0010, 0x0040, 0x0080
SW_HIDE = 0
HWND_TOP = 0

# Motivos de desconexión que no son errores (el usuario cerró sesión o desconectó).
NORMAL_REASONS = {1, 2, 3}
SCALES = (100, 125, 150, 175, 200, 250, 300, 400, 500)

_mod = None
_mod_lock = threading.Lock()
_atl_ready = False


def _user32():
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.CreateWindowExW.restype = wintypes.HWND
    u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, wintypes.UINT]
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.DestroyWindow.argtypes = [wintypes.HWND]
    u.SetFocus.argtypes = [wintypes.HWND]
    u.GetDpiForWindow.argtypes = [wintypes.HWND]
    u.GetDpiForWindow.restype = wintypes.UINT
    return u


def _atl():
    a = ctypes.WinDLL("atl")
    a.AtlAxWinInit.restype = wintypes.BOOL
    a.AtlAxGetControl.argtypes = [wintypes.HWND, ctypes.c_void_p]
    a.AtlAxGetControl.restype = ctypes.HRESULT
    return a


def typelib():
    """Wrappers de comtypes para mstscax.dll (se generan la primera vez y quedan en caché)."""
    global _mod
    with _mod_lock:
        if _mod is None:
            import comtypes.client

            dll = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "mstscax.dll")
            _mod = comtypes.client.GetModule(dll)
        return _mod


def available():
    """¿Se puede incrustar? (Windows con mstscax.dll y comtypes)."""
    if not IS_WINDOWS or os.environ.get("NEXO_RDP_EXTERNAL") == "1":
        return False
    try:
        typelib()
        return True
    except Exception:  # noqa: BLE001
        return False


def on_ui(form, fn):
    """Ejecuta fn en el hilo de la ventana (WinForms) y devuelve su resultado."""
    if form is None or not getattr(form, "InvokeRequired", False):
        return fn()
    from System import Action  # pythonnet, lo trae pywebview en Windows

    box = {}

    def run():
        try:
            box["v"] = fn()
        except BaseException as e:  # noqa: BLE001 — se relanza en el hilo que llamó
            box["e"] = e

    form.Invoke(Action(run))
    if "e" in box:
        raise box["e"]
    return box.get("v")


def later(form, fn):
    """Encola fn en el hilo de la ventana sin esperar."""
    def run():
        try:
            fn()
        except Exception:  # noqa: BLE001
            pass

    if form is None:
        return run()
    from System import Action

    form.BeginInvoke(Action(run))


def _try_set(obj, name, value):
    try:
        setattr(obj, name, value)
        return True
    except Exception:  # noqa: BLE001 — versiones viejas del control no tienen todo
        return False


def _first_attr(obj, names):
    for n in names:
        try:
            v = getattr(obj, n)
            if v is not None:
                return v
        except Exception:  # noqa: BLE001
            continue
    return None


class _Sink:
    """Recibe los eventos del control (IMsTscAxEvents)."""

    def __init__(self, owner):
        self.o = owner

    def _dbg(self, name, a):
        if os.environ.get("NEXO_RDP_DEBUG") == "1":
            print(f"[rdp] evento {name} {a!r}", flush=True)

    def OnConnecting(self, *a):
        self._dbg("OnConnecting", a)
        self.o._event("connecting")

    def OnConnected(self, *a):
        self._dbg("OnConnected", a)
        self.o._event("connecting")

    def OnLoginComplete(self, *a):
        self._dbg("OnLoginComplete", a)
        self.o._on_login()

    def OnDisconnected(self, *a):
        self._dbg("OnDisconnected", a)
        self.o._on_disconnected(int(a[-1]) if a else 0)

    def OnFatalError(self, *a):
        self._dbg("OnFatalError", a)
        self.o._on_disconnected(-1, f"Error interno del control RDP ({a[-1] if a else '?'})")

    # solo para diagnosticar (NEXO_RDP_DEBUG=1)
    def OnWarning(self, *a):
        self._dbg("OnWarning", a)

    def OnLogonError(self, *a):
        self._dbg("OnLogonError", a)

    def OnAuthenticationWarningDisplayed(self, *a):
        self._dbg("OnAuthenticationWarningDisplayed", a)

    def OnAutoReconnecting2(self, *a):
        self._dbg("OnAutoReconnecting2", a)

    def OnLeaveFullScreenMode(self, *a):
        self.o._event("windowed")

    def OnEnterFullScreenMode(self, *a):
        self.o._event("fullscreen")


class EmbeddedRdp:
    """Una sesión RDP incrustada. on_event(sesión, estado, mensaje) con estados:
    connecting, connected, fullscreen, windowed, closed."""

    def __init__(self, form, host, address, port, password, on_event, tunnel=None):
        self.form = form
        self.host = host
        self.address = address
        self.port = int(port)
        self._password = password or ""
        self.on_event = on_event
        self.tunnel = tunnel
        self.hwnd = None
        self.ctl = None
        self._events = None
        self._logged = False
        self._closed = False
        self._rect = None
        self._visible = False
        self._resize_timer = None
        self.started = False
        self.state = "connecting"

    # --- desde cualquier hilo ------------------------------------------------------------
    def attach(self, x, y, w, h, visible=True):
        """Crea el control en ese rectángulo (píxeles CSS) y conecta."""
        if self.started:
            return
        self.started = True
        typelib()  # fuera del hilo de la interfaz: generar los wrappers tarda la primera vez
        on_ui(self.form, lambda: self._create(x, y, w, h, visible))

    def place(self, x, y, w, h, visible):
        if self._closed:
            return
        on_ui(self.form, lambda: self._place(x, y, w, h, visible))
        if self._logged and visible:
            self._schedule_resize()

    def focus(self):
        if self.hwnd and not self._closed:
            on_ui(self.form, lambda: _user32().SetFocus(self.hwnd))

    def set_fullscreen(self, on):
        if self.ctl is not None and not self._closed:
            on_ui(self.form, lambda: _try_set(self.ctl, "FullScreen", bool(on)))

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            on_ui(self.form, self._destroy)
        except Exception:  # noqa: BLE001 — la ventana ya se cerró
            pass
        self._password = ""
        if self.tunnel:
            self.tunnel.stop()
            self.tunnel = None

    # --- hilo de la interfaz ---------------------------------------------------------------
    def _scale(self):
        try:
            return _user32().GetDpiForWindow(self._parent()) / 96.0 or 1.0
        except Exception:  # noqa: BLE001
            return 1.0

    def _parent(self):
        return wintypes.HWND(int(self.form.Handle.ToInt64()))

    def _px(self, x, y, w, h):
        s = self._scale()
        return round(x * s), round(y * s), max(1, round(w * s)), max(1, round(h * s))

    def _create(self, x, y, w, h, visible):
        global _atl_ready
        import comtypes
        import comtypes.client

        mod = typelib()
        atl, u32 = _atl(), _user32()
        if not _atl_ready:
            atl.AtlAxWinInit()
            _atl_ready = True
        px = self._px(x, y, w, h)
        clsids = [str(getattr(mod, n)._reg_clsid_) for n in COCLASSES if hasattr(mod, n)] + list(FALLBACK_CLSIDS)
        last = "no se pudo crear el control de escritorio remoto"
        for clsid in clsids:
            hwnd = u32.CreateWindowExW(0, "AtlAxWin", clsid, WS_CHILD | WS_CLIPSIBLINGS | WS_CLIPCHILDREN,
                                       *px, self._parent(), None, None, None)
            if not hwnd:
                last = f"CreateWindowEx falló ({ctypes.get_last_error()})"
                continue
            punk = ctypes.POINTER(comtypes.IUnknown)()
            try:
                atl.AtlAxGetControl(hwnd, ctypes.byref(punk))
            except OSError as e:
                punk = None
                last = str(e)
            if not punk:
                u32.DestroyWindow(hwnd)
                continue
            self.hwnd = hwnd
            self.ctl = comtypes.client.GetBestInterface(punk)
            self._punk = punk
            break
        if self.ctl is None:
            raise RuntimeError(last)
        self._configure(px[2], px[3])
        self._events = comtypes.client.GetEvents(self.ctl, _Sink(self), interface=mod.IMsTscAxEvents)
        self._place(x, y, w, h, visible)
        self.ctl.Connect()
        threading.Thread(target=self._watch, name="rdp-watch", daemon=True).start()

    def _configure(self, wpx, hpx):
        h, o = self.host, self.host.get("rdp") or {}
        mod, ctl = typelib(), self.ctl
        ctl.Server = self.address
        user, domain = h.get("user") or "", (o.get("domain") or "").strip()
        if "\\" in user and not domain:
            domain, user = user.split("\\", 1)
        if user:
            ctl.UserName = user
        if domain:
            ctl.Domain = domain
        res = o.get("resolution") or "auto"
        if res == "auto":
            dw, dh = wpx, hpx
        else:
            dw, dh = (int(v) for v in res.split("x"))
        ctl.DesktopWidth = max(200, min(8192, dw - dw % 2))
        ctl.DesktopHeight = max(200, min(8192, dh - dh % 2))
        _try_set(ctl, "ColorDepth", 32)
        _try_set(ctl, "FullScreenTitle", f"{h.get('name') or self.address} — Nexo")
        _try_set(ctl, "ConnectingText", "Conectando…")
        _try_set(ctl, "DisconnectedText", "Desconectado")

        adv = _first_attr(ctl, ("AdvancedSettings9", "AdvancedSettings8", "AdvancedSettings7",
                                "AdvancedSettings6", "AdvancedSettings5", "AdvancedSettings2"))
        if adv is not None:
            _try_set(adv, "RDPPort", self.port)
            _try_set(adv, "EnableCredSspSupport", True)      # NLA
            # 0 = no mostrar el aviso de certificado: Nexo ya lo verificó (rdp.trust_check)
            _try_set(adv, "AuthenticationLevel", 0)
            _try_set(adv, "RedirectClipboard", bool(o.get("clipboard", True)))
            _try_set(adv, "RedirectDrives", bool(o.get("share_home")))
            _try_set(adv, "EnableAutoReconnect", True)
            _try_set(adv, "SmartSizing", res != "auto")
            _try_set(adv, "BitmapPeristence", 1)              # así se llama en la API (sic)
            _try_set(adv, "DisplayConnectionBar", True)
            _try_set(adv, "ConnectionBarShowRestoreButton", True)
            _try_set(adv, "ConnectionBarShowMinimizeButton", False)
            _try_set(adv, "ContainerHandledFullScreen", 0)
            _try_set(adv, "GrabFocusOnConnect", True)
            _try_set(adv, "allowBackgroundInput", 1)
        sec = _first_attr(ctl, ("SecuredSettings3", "SecuredSettings2"))
        if sec is not None:
            _try_set(sec, "KeyboardHookMode", 2)  # Win, Alt+Tab… van al remoto solo en pantalla completa
        try:
            ns = self._punk.QueryInterface(mod.IMsRdpClientNonScriptable5)
        except Exception:  # noqa: BLE001
            ns = None
        try:
            base_ns = self._punk.QueryInterface(mod.IMsTscNonScriptable)
            if self._password:
                base_ns.ClearTextPassword = self._password
        except Exception:  # noqa: BLE001
            base_ns = None
        if ns is not None:
            _try_set(ns, "AllowCredentialSaving", False)
            _try_set(ns, "PromptForCredentials", not self._password)
            _try_set(ns, "PromptForCredsOnClient", not self._password)
            _try_set(ns, "NegotiateSecurityLayer", True)
            _try_set(ns, "DisableConnectionBar", False)
        self._password = ""
        if o.get("fullscreen"):
            _try_set(ctl, "FullScreen", True)
        try:
            ext = self._punk.QueryInterface(mod.IMsRdpExtendedSettings)
            scale = min(SCALES, key=lambda v: abs(v - self._scale() * 100))
            ext.Property["DesktopScaleFactor"] = scale
            ext.Property["DeviceScaleFactor"] = 100
        except Exception:  # noqa: BLE001
            pass

    def _place(self, x, y, w, h, visible):
        if not self.hwnd:
            return
        u32 = _user32()
        self._rect = self._px(x, y, w, h)
        self._visible = bool(visible) and w > 2 and h > 2
        if self._visible:
            u32.SetWindowPos(self.hwnd, HWND_TOP, *self._rect, SWP_NOACTIVATE | SWP_SHOWWINDOW)
        else:
            u32.ShowWindow(self.hwnd, SW_HIDE)

    def _schedule_resize(self):
        if (self.host.get("rdp") or {}).get("resolution", "auto") != "auto":
            return
        if self._resize_timer:
            self._resize_timer.cancel()
        self._resize_timer = threading.Timer(0.4, lambda: self._closed or on_ui(self.form, self._resize_remote))
        self._resize_timer.daemon = True
        self._resize_timer.start()

    def _resize_remote(self):
        if not self._rect or self.ctl is None:
            return
        w, h = self._rect[2], self._rect[3]
        w, h = max(200, min(8192, w - w % 2)), max(200, min(8192, h - h % 2))
        scale = min(SCALES, key=lambda v: abs(v - self._scale() * 100))
        try:
            self.ctl.UpdateSessionDisplaySettings(w, h, w, h, 0, scale, 100)
        except Exception:  # noqa: BLE001 — servidor viejo: se escala la imagen
            adv = _first_attr(self.ctl, ("AdvancedSettings9", "AdvancedSettings8", "AdvancedSettings2"))
            if adv is not None:
                _try_set(adv, "SmartSizing", True)

    def _destroy(self):
        if self._resize_timer:
            self._resize_timer.cancel()
        ctl, self.ctl = self.ctl, None
        if ctl is not None:
            try:
                if ctl.Connected:
                    ctl.Disconnect()
            except Exception:  # noqa: BLE001
                pass
        self._events = None
        self._punk = None
        if self.hwnd:
            _user32().DestroyWindow(self.hwnd)
            self.hwnd = None

    def _watch(self):
        """Respaldo de los eventos: mira el estado del control cada segundo
        (0 desconectado, 1 conectado, 2 conectando)."""
        start, seen = time.time(), 0
        while not self._closed:
            time.sleep(1)
            try:
                c = on_ui(self.form, lambda: -1 if self.ctl is None else int(self.ctl.Connected))
            except Exception:  # noqa: BLE001 — la ventana se cerró
                return
            if c < 0 or self._closed:
                return
            if os.environ.get("NEXO_RDP_DEBUG") == "1":
                print(f"[rdp] Connected={c}", flush=True)
            seen = max(seen, c)
            if c == 1 and not self._logged:
                on_ui(self.form, self._on_login)
            elif c == 0 and (seen or time.time() - start > 4):
                on_ui(self.form, lambda: self._on_disconnected(0))
                return

    # --- eventos (hilo de la interfaz) -------------------------------------------------------
    def _event(self, state, msg=""):
        self.state = state
        threading.Thread(target=self.on_event, args=(self, state, msg), daemon=True).start()

    def _on_login(self):
        if self._logged:
            return
        self._logged = True
        self._event("connected")
        if self._visible:
            self._schedule_resize()

    def _on_disconnected(self, reason, msg=""):
        if self._closed:
            return
        if not msg and (reason not in NORMAL_REASONS or not self._logged):
            msg = self._describe(reason)
        self._closed = True
        # no se destruye el control dentro de su propio evento: se deja para después
        later(self.form, self._destroy)
        if self.tunnel:
            t, self.tunnel = self.tunnel, None
            threading.Thread(target=t.stop, daemon=True).start()
        self._event("closed", msg)

    def _describe(self, reason):
        ext = 0
        try:
            ext = int(self.ctl.ExtendedDisconnectReason)
        except Exception:  # noqa: BLE001
            pass
        try:
            text = self.ctl.GetErrorDescription(reason, ext)
            if text:
                return str(text).strip()
        except Exception:  # noqa: BLE001
            pass
        if reason in NORMAL_REASONS or reason == 0:
            if ext:
                return f"No se pudo iniciar la sesión (motivo {ext})"
            return "No se pudo iniciar la sesión" if not self._logged else ""
        return f"Se cortó la conexión (código {reason}, {ext})"


def wait_closed(session, timeout=10):
    """Para pruebas: espera a que la sesión termine."""
    end = time.time() + timeout
    while session.state != "closed" and time.time() < end:
        time.sleep(0.1)
    return session.state == "closed"
