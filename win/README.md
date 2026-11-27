# Nexo para Windows (nativo)

Nexo corre directo en Windows, sin WSL. Usa el **mismo núcleo** que la app de Linux (bóveda,
conexiones, llaves, temas, bases de datos y organizaciones del paquete `nexo/`), con una interfaz
web dentro de una ventana nativa.

| Pieza | En Windows | En Linux (para desarrollar) |
|---|---|---|
| Ventana | pywebview + WebView2 (viene con Windows 10/11) | pywebview + WebKitGTK |
| Terminal | xterm.js 6 | xterm.js 6 |
| SSH, SFTP y túneles | paramiko (sin `ssh`, `sshpass` ni `ssh-agent`) | igual |
| Shell local | PowerShell 7 → Windows PowerShell → cmd, por ConPTY (`pywinpty`) | `$SHELL` por pty |
| Escritorio remoto | `mstsc` (Conexión a Escritorio remoto de Windows) | FreeRDP |
| Bases de datos | `nexo/dbclient.py` (PostgreSQL, MySQL/MariaDB, SQL Server, MongoDB, Redis) | igual |
| Bóveda | `%APPDATA%\nexo\vault.enc` | `~/.local/share/nexo/vault.enc` (la misma de la app GTK) |
| Llaves de servidor | `%APPDATA%\nexo\known_hosts` | `~/.ssh/known_hosts` |

El formato de la bóveda es idéntico: **Ajustes → Exportar copia cifrada** en un equipo e
**Importar una bóveda** en la pantalla de bloqueo del otro (sirve también con el `vault.enc` de
Linux). Se abre con la misma contraseña maestra.

## Qué hace

- **Bóveda**: crear, desbloquear, bloquear (Ctrl+Shift+L), autobloqueo por inactividad y al
  bloquear Windows (Win+L o suspensión), cambiar la contraseña maestra, exportar e importar.
- **Hosts**: crear, editar, duplicar y eliminar; grupos (crear, renombrar, ordenar, plegar y
  arrastrar hosts a un grupo); iconos; notas; importar `~/.ssh/config` con sus llaves y
  `ProxyJump`; conexión rápida `usuario@host:puerto` sin guardar nada.
- **SSH**: pestañas, llave o contraseña (si no está guardada, la pide), saltos encadenados, Enter
  reconecta y Ctrl+Shift+C/V copian y pegan. El clic derecho copia lo seleccionado o pega.
- **SFTP de dos paneles**: «Este equipo» (con la lista de unidades) y el servidor. Para
  transferir: Subir/Bajar (Ctrl+→ / Ctrl+←), arrastrar entre paneles o soltar desde el
  Explorador. Avance con cancelación y pregunta antes de reemplazar u omitir. Sin archivos a
  medias: escribe a `.nexo-parcial` y renombra al final. También crea carpetas, renombra
  (F2), elimina (Supr; en tu equipo va a la papelera) y abre los archivos con su programa.
- **Edición remota**: doble clic en un archivo del servidor lo abre con tu editor y lo sube cada
  vez que guardas. Si cambió en el servidor mientras tanto, avisa antes de sobrescribirlo.
- **Túneles**: local (L), remoto (R) y SOCKS5 (D), con paramiko, desde el panel «Túneles». El
  riel muestra cuántos hay activos.
- **Bases de datos**: árbol de objetos, cambio de base, editor (Ctrl+Enter ejecuta lo
  seleccionado o todo), resultados ordenables, copiar valores y exportar a CSV. Modo solo
  lectura y túnel automático por «Saltar por».
- **RDP**: `mstsc` con un `.rdp` temporal (resolución, pantalla completa, portapapeles y
  unidades). La contraseña va al Administrador de credenciales solo durante la sesión. Con
  salto, abre un túnel automático.
- **Llaves**: generar (Ed25519, RSA 4096 o ECDSA), importar un archivo o pegar la llave (con
  frase de paso), copiar o guardar la pública, renombrar y eliminar. Las `.ppk` de PuTTY se
  rechazan con instrucciones para convertirlas.
- **Organizaciones (Nexo Server)**: ingresar con usuario, contraseña y 2FA. Los hosts asignados
  aparecen en la lista. También actualizar, volver a ingresar, cerrar sesión y quitar.
- **Apariencia**: 14 temas y 11 colores de acento (comparten `ui.json` con Linux), y paleta de
  comandos **Ctrl+K**.

No tiene actualizador propio: en la Store actualiza la tienda y fuera de ella, el instalador.

## Seguridad

- La página nunca recibe secretos guardados: ni contraseñas, ni llaves privadas, ni tokens. Al
  editar un host solo sabe *si* hay una contraseña guardada. Al importar una llave desde un
  archivo, el texto lo lee Python y no pasa por la página.
- Las terminales viajan por un WebSocket solo en `127.0.0.1`, con un token aleatorio por
  ejecución.
- La página tiene una política de contenido (CSP) que solo permite los archivos propios de Nexo.
- Llaves de servidor: se aceptan las nuevas, se guardan en `known_hosts` y una que **cambió**
  se rechaza (aviso de posible intermediario).

## Desarrollar y probar

```sh
# Linux (comparte la bóveda de la app GTK)
python3 -m venv --system-site-packages win/.venv
win/.venv/bin/pip install -r win/requirements.txt
win/.venv/bin/python win/run.py
win/.venv/bin/python win/tests/smoke_backend.py      # bóveda, puente, shell local
win/.venv/bin/python win/tests/smoke_windows.py      # SOCKS, .rdp, este equipo, controladores (+ lo de Windows)
```

```powershell
# Windows
py -3.12 -m venv win\.venv ; win\.venv\Scripts\Activate.ps1
pip install -r win\requirements.txt pyinstaller
python win\run.py
powershell -ExecutionPolicy Bypass -File win\build.ps1        # → dist\Nexo\Nexo.exe y el .zip
powershell -ExecutionPolicy Bypass -File win\build-msix.ps1   # → dist\Nexo-<versión>.msix
```

`NEXO_DEBUG=1` abre las herramientas de desarrollador de la ventana.
`NEXO_SELFTEST=<archivo.json>` abre la ventana, comprueba página + xterm.js + Python y se cierra.

## Compilación automática

`.github/workflows/nexo-windows.yml` corre en un Windows real de GitHub con cada push que toque
`win/`, el núcleo o el empaquetado:

1. pruebas `smoke_backend.py` y `smoke_windows.py` (unidades, papelera, credenciales de RDP,
   controladores de BD);
2. `Nexo.exe` con PyInstaller y su autoprueba con WebView2;
3. **instalador nativo** `Nexo-nativo-Setup-<versión>.exe` (Inno Setup, por usuario y sin
   administrador): lo instala en silencio, ejecuta la autoprueba del programa instalado y lo
   desinstala;
4. **MSIX** para la Store: lo instala, ejecuta la autoprueba con el alias `nexo` y lo
   desinstala.

Los artefactos quedan en la ejecución: `nexo-windows-instalador`, `nexo-msix` y
`nexo-windows-portable`.

El instalador con WSL (`packaging/build-windows.sh`, `NexoSetup-<versión>.exe`) sigue igual.
El actualizador de la app de Linux todavía apunta a ese nombre.

## Microsoft Store (MSIX)

La versión de la Store es **esta, la nativa** (sin WSL). `win\build-msix.ps1` empaqueta
`dist\Nexo\` como `dist\Nexo-<versión>.msix`, con el manifiesto `packaging/msix/AppxManifest.xml`
y los logos de `packaging/msix/Assets` (se regeneran desde `nexo/nexo.svg` con
`python3 packaging/msix/make-assets.py`).

- **Identidad:** `Name`, `Publisher` y `PublisherDisplayName` los asigna Partner Center al reservar
  el nombre (la app → *Identidad del producto*). En GitHub van como variables del repositorio
  `MSIX_NAME`, `MSIX_PUBLISHER` y `MSIX_PUBLISHER_DISPLAY_NAME`; sin ellas el paquete sale con
  identidad de prueba y la Store lo rechaza.
- **Firma:** el `.msix` que se sube va sin firmar; la Store lo firma. `-SignWithTestCert` crea además
  `Nexo-<versión>-prueba.msix` y `build\msix\nexo-prueba.cer` para instalarlo a mano: importar el
  `.cer` en *Equipo local → Personas de confianza* y abrir el `.msix`.
- **Versión:** sale de `nexo/__init__.py` con un `.0` al final (2.5.5 → 2.5.5.0), como exige la Store.
- **Alias:** instalado, `nexo` abre la app desde PowerShell, cmd o Ejecutar.
- **Datos:** dentro del paquete, Windows redirige `%APPDATA%\nexo` a la carpeta privada del paquete.
  **Desinstalar Nexo borra la bóveda**: antes hay que respaldarla con **Ajustes → Exportar copia
  cifrada** (la app lo advierte ahí cuando corre desde la Store).
- La CI instala el MSIX en el runner, abre la app con el alias en modo autoprueba y la desinstala.
- **Ficha de la tienda:** textos, palabras clave, categoría, justificación de `runFullTrust` y
  notas para el revisor en `packaging/msix/ficha-store.md`. La política de privacidad está en
  `docs/privacidad.md`.
