"""Puente WebSocket local entre cada pestaña (xterm.js) y su sesión.

- Escucha solo en 127.0.0.1, en un puerto libre que elige el sistema.
- Cada conexión debe traer el token aleatorio de esta ejecución (?t=...), que solo
  conoce la página de Nexo: otro programa o una web abierta en el navegador no
  pueden engancharse a una terminal.
- Mensajes binarios = bytes de teclado (página → sesión) o de salida (sesión → página).
  Mensajes de texto = control en JSON: {"t":"resize","cols":..,"rows":..} y estados.
"""
import hmac
import json
import secrets
import threading
from urllib.parse import parse_qs, urlsplit

from websockets.sync.server import serve


class Bridge:
    def __init__(self, sessions):
        self.sessions = sessions          # dict id -> Session (lo administra la Api)
        self.token = secrets.token_urlsafe(24)
        self._server = serve(self._handle, "127.0.0.1", 0, max_size=4 * 1024 * 1024,
                             compression=None)
        self.port = self._server.socket.getsockname()[1]
        threading.Thread(target=self._server.serve_forever, name="nexo-bridge", daemon=True).start()

    def url(self, sid):
        return f"ws://127.0.0.1:{self.port}/s/{sid}?t={self.token}"

    def _handle(self, ws):
        parts = urlsplit(ws.request.path)
        token = (parse_qs(parts.query).get("t") or [""])[0]
        if not hmac.compare_digest(token, self.token) or not parts.path.startswith("/s/"):
            ws.close(4401, "no autorizado")
            return
        session = self.sessions.get(parts.path[3:])
        if session is None:
            ws.close(4404, "sesión inexistente")
            return
        send_lock = threading.Lock()

        def sink(item):
            with send_lock:
                ws.send(item)

        session.attach(sink)
        try:
            for msg in ws:
                if isinstance(msg, bytes):
                    session.write(msg)
                    continue
                try:
                    ctl = json.loads(msg)
                except ValueError:
                    continue
                if ctl.get("t") == "resize":
                    cols, rows = int(ctl.get("cols", 0)), int(ctl.get("rows", 0))
                    if 2 <= cols <= 1000 and 1 <= rows <= 500:
                        session.resize(cols, rows)
        except Exception:  # noqa: BLE001 — la página se cerró o recargó
            pass
        finally:
            if self.sessions.get(session.id) is session:
                session.detach()

    def shutdown(self):
        self._server.shutdown()
