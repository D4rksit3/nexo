# Nexo para Windows (nativo) — fase 1

Versión de Nexo que corre directo en Windows, sin WSL. Usa el **mismo núcleo** que la app de
Linux (bóveda, conexiones, llaves y temas del paquete `nexo/`) con una interfaz web dentro de una
ventana nativa.

| Pieza | En Windows | En Linux (para desarrollar) |
|---|---|---|
| Ventana | pywebview + WebView2 (viene con Windows 10/11) | pywebview + WebKitGTK |
| Terminal | xterm.js 6 | xterm.js 6 |
| SSH | paramiko (sin `ssh`, `sshpass` ni `ssh-agent`) | igual |
| Shell local | PowerShell 7 → Windows PowerShell → cmd, por ConPTY (`pywinpty`) | `$SHELL` por pty |
| Bóveda | `%APPDATA%\nexo\vault.enc` | `~/.local/share/nexo/vault.enc` (la misma de la app GTK) |

El formato de la bóveda es idéntico: copiar `vault.enc` de Linux a `%APPDATA%\nexo\` en Windows
lleva todos los hosts y llaves.

## Qué hace la fase 1

- Crear la bóveda o desbloquearla; bloquear con **Ctrl+Shift+L** (cierra todas las sesiones).
- Hosts por grupos, filtro (**Ctrl+F**) y recientes en el inicio.
- SSH con llave o contraseña (si no está guardada, la pide), también **por salto**.
- Terminal local (**Ctrl+Shift+T**). Pestañas: **Ctrl+Tab**, cerrar con **Ctrl+Shift+W** o clic central.
- Copiar y pegar: **Ctrl+Shift+C / V**; clic derecho copia lo seleccionado o, si no hay, pega.
- Si la conexión se cae, **Enter** reconecta en la misma pestaña.
- El tema y el acento son los que elegiste en Nexo.

Todavía no: crear o editar hosts (se hacen en Nexo para Linux, la bóveda es la misma), SFTP,
túneles, bases de datos, RDP, organizaciones, cambio de tema e instalador. Eso es fase 2 a 4.

## Seguridad

- La página nunca recibe secretos: ni contraseñas, ni llaves privadas, ni tokens.
- Las terminales viajan por un WebSocket solo en `127.0.0.1`, con un token aleatorio por ejecución:
  otro programa del equipo o una web abierta en el navegador no puede engancharse a una sesión.
- La página tiene una política de contenido (CSP) que solo permite los archivos propios de Nexo.
- Llaves del servidor: se aceptan las nuevas y se rechaza una que **cambió** respecto a
  `known_hosts` (aviso de posible intermediario). Guardarlas en Windows llega en la fase 2.

## Desarrollar

```sh
# Linux (comparte la bóveda de la app GTK)
python3 -m venv --system-site-packages win/.venv
win/.venv/bin/pip install -r win/requirements.txt
win/.venv/bin/python win/run.py
win/.venv/bin/python win/tests/smoke_backend.py      # prueba sin ventana
```

```powershell
# Windows
py -3.12 -m venv win\.venv ; win\.venv\Scripts\Activate.ps1
pip install -r win\requirements.txt pyinstaller
python win\run.py
python win\tests\smoke_backend.py
powershell -ExecutionPolicy Bypass -File win\build.ps1   # → dist\Nexo\Nexo.exe y el .zip
```

`NEXO_DEBUG=1` abre las herramientas de desarrollador de la ventana.
`NEXO_SELFTEST=<archivo.json>` abre la ventana, comprueba página + xterm.js + Python y se cierra.

## Compilación automática

`.github/workflows/nexo-windows.yml` corre en un Windows real de GitHub en cada push que toque
`win/` o el núcleo: prueba el núcleo (bóveda, puente, ConPTY, portapapeles), compila `Nexo.exe`,
lo abre en modo autoprueba con WebView2 y deja el `.zip` portable en los *Artifacts* de la ejecución.
