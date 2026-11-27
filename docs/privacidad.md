# Política de privacidad de Nexo

_Vigente desde el 26 de noviembre de 2026. Aplica a Nexo para Windows (incluida la versión de
Microsoft Store) y a Nexo para Linux._

## Resumen

Nexo no recopila, no envía ni vende datos personales. No tiene cuentas, no usa servicios en la
nube propios y no incluye telemetría, analítica ni publicidad.

## Qué guarda Nexo y dónde

- **Bóveda**: hosts, usuarios, contraseñas, llaves SSH, notas y ajustes se guardan solo en tu
  equipo, en un archivo cifrado con AES-256-GCM. La clave se deriva de tu contraseña maestra con
  scrypt. La contraseña maestra no se guarda en ningún lado y nadie puede recuperarla, tampoco
  el autor de Nexo.
  - Windows: `%APPDATA%\nexo\vault.enc`
  - Linux: `~/.local/share/nexo/vault.enc`
- **Llaves de servidor aceptadas** (`known_hosts`; en Windows, `%APPDATA%\nexo\known_hosts`, y en
  Linux, el `~/.ssh/known_hosts` habitual) y **preferencias de apariencia** (tema y color). No
  contienen secretos.
- **Archivos temporales**: al editar un archivo remoto, Nexo baja una copia a una carpeta
  temporal de tu equipo y la borra al cerrar la pestaña.

En la versión de Microsoft Store, Windows guarda estos archivos en la carpeta privada de la app
y **los borra al desinstalarla**. Antes de desinstalar, exporta una copia en **Ajustes → Exportar
copia cifrada**.

## A qué se conecta Nexo

Solo a los destinos que configuras tú:

- los servidores SSH, SFTP, RDP y de bases de datos que agregas como hosts, y los saltos o
  túneles que defines;
- si la usas, la función **Organizaciones**, que se conecta al servidor Nexo Server que indiques
  (normalmente el de tu empresa) para iniciar sesión y listar los hosts que te asignaron. Ese
  servidor lo administra tu organización, no el autor de Nexo.

Nexo no se conecta a ningún servidor del autor. La única excepción es Nexo para Linux, que
consulta la lista pública de versiones de Nexo en GitHub para avisarte de actualizaciones. La
versión de Windows no hace esa consulta: en Microsoft Store, las actualizaciones las entrega la
tienda.

## Portapapeles, archivos y escritorio remoto

- El portapapeles se usa solo cuando copias o pegas.
- Nexo lee los archivos que eliges para subir, importar o exportar, y escribe donde le indicas.
- Para abrir un escritorio remoto en Windows, Nexo deja la contraseña de ese host en el
  Administrador de credenciales de Windows solo durante la sesión y la borra cuando se cierra la
  conexión.

## Niños

Nexo es una herramienta técnica para administrar servidores y no está dirigida a menores.

## Cambios y contacto

Si esta política cambia, se publica la nueva versión en este mismo archivo, con su fecha.
Para consultas, abre un _issue_ en https://github.com/D4rksit3/nexo/issues.
