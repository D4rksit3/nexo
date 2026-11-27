# Ficha de Nexo en Microsoft Store (Partner Center)

Textos listos para copiar en Partner Center → la app → **Listados de Store** (idioma: español).
Los límites de largo son los de Partner Center.

## Nombre

`Nexo` (o el nombre que hayas reservado; si «Nexo» está tomado: «Nexo SSH» o «Nexo — SSH y SFTP»).

## Descripción breve (máx. 200 caracteres para la vista de búsqueda)

> Cliente SSH, SFTP, túneles, escritorio remoto y bases de datos en una sola ventana, con tus
> hosts y llaves en una bóveda cifrada que no sale de tu equipo.

## Descripción

> Nexo reúne en una sola ventana todo lo que usas para administrar servidores: terminal SSH,
> transferencia de archivos por SFTP, túneles, escritorio remoto y consultas a bases de datos.
>
> Tus hosts, contraseñas y llaves se guardan en una bóveda cifrada con AES-256 que vive solo en
> tu equipo. Sin cuentas, sin nube y sin telemetría: Nexo solo se conecta a los servidores que
> tú agregas.
>
> • Terminal SSH con pestañas, por llave o contraseña, y a través de bastiones (saltos)
> • SFTP de dos paneles: arrastra archivos entre tu PC y el servidor, o suéltalos desde el Explorador
> • Edita archivos del servidor con tu editor de siempre: se suben solos al guardar
> • Túneles locales, remotos y SOCKS con un clic
> • Escritorio remoto (RDP) con la conexión de Windows, también a través de un bastión
> • Consultas a PostgreSQL, MySQL/MariaDB, SQL Server, MongoDB y Redis, con modo solo lectura
> • Llaves SSH: genera Ed25519/RSA o importa las que ya usas; importa tu ~/.ssh/config
> • PowerShell o cmd en una pestaña más
> • Organizaciones: entra a los hosts que te asigna tu empresa con Nexo Server, con doble factor
> • 14 temas oscuros, paleta de comandos (Ctrl+K) y bloqueo automático
>
> Compatible con la bóveda de Nexo para Linux: exporta e importa tus hosts entre equipos.

## Características del producto (máx. 20, una por línea)

```
Terminal SSH con pestañas y saltos por bastión
SFTP de dos paneles con arrastrar y soltar
Edición remota con tu editor y subida al guardar
Túneles locales, remotos y SOCKS
Escritorio remoto (RDP) también por bastión
PostgreSQL, MySQL, SQL Server, MongoDB y Redis
Bóveda local cifrada AES-256, sin nube ni cuentas
Generación e importación de llaves SSH
Importación de ~/.ssh/config
Bloqueo automático y al bloquear Windows
14 temas oscuros y paleta de comandos
```

## Palabras clave (máx. 7)

`ssh`, `sftp`, `terminal`, `rdp`, `túnel`, `servidor`, `base de datos`

## Categoría

**Herramientas para desarrolladores** (subcategoría: otras herramientas para desarrolladores).
Alternativa: **Utilidades y herramientas**.

## Política de privacidad (URL obligatoria)

Publica `docs/privacidad.md` y usa su enlace, por ejemplo:
`https://github.com/D4rksit3/nexo/blob/main/docs/privacidad.md`

## Sitio web y soporte

- Sitio web: `https://github.com/D4rksit3/nexo`
- Contacto de soporte: `https://github.com/D4rksit3/nexo/issues`

## Capturas (mínimo 1; recomendadas 4 a 6; 1366×768 o más, PNG)

Hay que tomarlas **en Windows**, con la app instalada y una bóveda de demostración (hosts con
nombres genéricos, sin IP ni rutas reales):

1. Inicio con hosts agrupados y recientes
2. Terminal SSH con dos pestañas
3. SFTP de dos paneles con una transferencia en curso
4. Pestaña de PostgreSQL con resultados
5. Panel de túneles con uno activo
6. Ajustes con la galería de temas

## Clasificación por edad (cuestionario IARC)

Herramienta sin contenido generado por usuarios visible para otros, sin compras, sin chat y sin
ubicación: corresponde **3+ / Todos**. En el cuestionario, todo «No», salvo «¿La app se conecta a
internet?»: «Sí».

## Notas para la certificación (Partner Center → Envío → Opciones de envío)

**Justificación de `runFullTrust`** (capacidad restringida, la piden siempre):

> Nexo es un cliente de administración de servidores (SSH, SFTP, RDP y bases de datos) empaquetado
> desde una aplicación de escritorio Win32 (Python + WebView2). Necesita runFullTrust para:
> abrir conexiones TCP a servidores elegidos por el usuario y escuchar en puertos locales para los
> túneles SSH; lanzar la terminal local (PowerShell/cmd mediante ConPTY) y la Conexión a Escritorio
> remoto (mstsc.exe); y leer o escribir los archivos que el usuario transfiere por SFTP en cualquier
> carpeta. No instala servicios ni controladores, ni se ejecuta en segundo plano al cerrarse.

**Notas para el revisor:**

> Al abrir, Nexo pide crear una contraseña maestra (mínimo 8 caracteres) para su bóveda local.
> Para probarlo sin servidores propios: botón «Terminal local» (abre PowerShell); o un servidor
> SSH público de pruebas con «Conexión rápida». Nexo no tiene cuentas ni inicio de sesión en línea.

## Precio y disponibilidad

Gratis (o el precio que decidas). Mercados: todos.
