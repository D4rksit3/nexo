<#
  Instala o actualiza Nexo en Windows 10 (21H2+) / 11 usando WSL2 + WSLg.

  - Crea una distribución WSL propia llamada «Nexo» a partir de la imagen
    oficial de Ubuntu 24.04 para WSL (verificada con su SHA256). No toca
    ninguna otra distribución que ya tengas.
  - Instala dentro el paquete nexo.deb que viene junto a este script.
  - Si WSL no está instalado, lo instala (pide permiso de administrador),
    deja programada la continuación y pide reiniciar.

  Códigos de salida: 0 = listo, 3010 = falta reiniciar Windows, 1 = error.
#>
param(
    [string]$Deb = (Join-Path $PSScriptRoot 'nexo.deb'),
    [string]$Distro = 'Nexo',
    [switch]$Shortcuts,
    [switch]$NoPause
)

$ErrorActionPreference = 'Continue'
$env:WSL_UTF8 = '1'
$Base      = Join-Path $env:LOCALAPPDATA 'Nexo'
$DistroDir = Join-Path $Base 'wsl'
$Release   = 'https://cloud-images.ubuntu.com/wsl/releases/24.04/current'

New-Item -ItemType Directory -Force -Path $Base | Out-Null
try { Start-Transcript -Path (Join-Path $Base 'instalacion.log') -Force | Out-Null } catch {}
$Host.UI.RawUI.WindowTitle = 'Instalando Nexo'

function Say([string]$m)  { Write-Host ''; Write-Host "==> $m" -ForegroundColor Green }
function Finish([int]$code) {
    try { Stop-Transcript | Out-Null } catch {}
    if (-not $NoPause) { Write-Host ''; Read-Host 'Presiona Enter para cerrar' | Out-Null }
    exit $code
}
function Fail([string]$m) {
    Write-Host ''
    Write-Host "ERROR: $m" -ForegroundColor Red
    Write-Host "Registro completo: $(Join-Path $Base 'instalacion.log')"
    Finish 1
}
function Test-ModernWsl {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { return $false }
    & wsl.exe --version *> $null
    return ($LASTEXITCODE -eq 0)
}
function Get-Distros {
    & wsl.exe --list --quiet 2>$null | ForEach-Object { $_.Trim([char]0, ' ', "`t") } | Where-Object { $_ }
}
function ConvertTo-WslPath([string]$p) {
    $r = & wsl.exe -d $Distro -u root -- wslpath -a ($p -replace '\\', '/')
    if ($LASTEXITCODE -ne 0 -or -not $r) { Fail "No se pudo traducir la ruta $p dentro de WSL." }
    return ($r | Select-Object -First 1).Trim()
}

# --- 1. Requisitos ------------------------------------------------------------
$build = [Environment]::OSVersion.Version.Build
if ($build -lt 19044) {
    Fail "Nexo necesita Windows 10 21H2 (compilación 19044) o Windows 11. Este equipo tiene la compilación $build."
}
if (-not (Test-Path -LiteralPath $Deb)) { Fail "No se encontró el paquete $Deb." }
$Deb = (Resolve-Path -LiteralPath $Deb).Path
$Provision = Join-Path $PSScriptRoot 'provision.sh'
if (-not (Test-Path -LiteralPath $Provision)) { Fail "No se encontró $Provision." }

# --- 2. WSL -------------------------------------------------------------------
if (-not (Test-ModernWsl)) {
    Say 'Se necesita WSL (Subsistema de Windows para Linux). Se instalará ahora; Windows pedirá permiso de administrador.'
    try {
        if (Get-Command wsl.exe -ErrorAction SilentlyContinue) {
            # WSL antiguo integrado en Windows: se actualiza a la versión de la Store (trae WSLg).
            Start-Process wsl.exe -ArgumentList '--update' -Verb RunAs -Wait | Out-Null
        }
        if (-not (Test-ModernWsl)) {
            $p = Start-Process wsl.exe -ArgumentList '--install', '--no-distribution' -Verb RunAs -Wait -PassThru
            if ($p.ExitCode -ne 0) {
                Fail "La instalación de WSL devolvió el código $($p.ExitCode). Comprueba que la virtualización esté activada en la BIOS/UEFI."
            }
            $resume = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Deb `"$Deb`""
            if ($Shortcuts) { $resume += ' -Shortcuts' }
            Set-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' -Name 'NexoSetup' -Value $resume
            Say 'WSL quedó instalado. REINICIA Windows: la instalación de Nexo continuará sola al iniciar sesión.'
            Finish 3010
        }
    } catch {
        Fail 'No se concedió el permiso de administrador para instalar WSL.'
    }
}

# --- 3. Distribución «Nexo» ---------------------------------------------------
if ((Get-Distros) -contains $Distro) {
    Say "La distribución WSL «$Distro» ya existe: se actualizará Nexo dentro de ella."
} else {
    $arch = 'amd64'
    if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') { $arch = 'arm64' }
    $file = "ubuntu-noble-wsl-$arch-wsl.rootfs.tar.gz"
    $tar  = Join-Path $Base $file

    Say 'Descargando Ubuntu 24.04 para WSL (unos 350 MB, solo la primera vez)'
    & curl.exe -L --fail --retry 3 -o $tar "$Release/$file"
    if ($LASTEXITCODE -ne 0) { Fail 'No se pudo descargar la imagen de Ubuntu. Revisa la conexión a internet.' }

    Say 'Verificando la firma SHA256 de la imagen'
    $sums = & curl.exe -sL --fail "$Release/SHA256SUMS"
    $line = $sums | Where-Object { $_ -match ('\s\*?' + [regex]::Escape($file) + '$') } | Select-Object -First 1
    $expected = if ($line) { ($line -split '\s+')[0].ToLower() } else { '' }
    $actual = (Get-FileHash -LiteralPath $tar -Algorithm SHA256).Hash.ToLower()
    if (-not $expected -or $actual -ne $expected) {
        Remove-Item -LiteralPath $tar -Force -ErrorAction SilentlyContinue
        Fail 'La imagen descargada no coincide con el SHA256 publicado por Ubuntu. Se canceló la instalación.'
    }

    Say "Creando la distribución WSL «$Distro» en $DistroDir"
    New-Item -ItemType Directory -Force -Path $DistroDir | Out-Null
    & wsl.exe --import $Distro $DistroDir $tar --version 2
    $rc = $LASTEXITCODE
    Remove-Item -LiteralPath $tar -Force -ErrorAction SilentlyContinue
    if ($rc -ne 0) {
        Fail 'WSL no pudo crear la distribución. Si es la primera vez, reinicia Windows y vuelve a ejecutar el instalador; si persiste, activa la virtualización en la BIOS/UEFI.'
    }
}

# --- 4. Instalar Nexo dentro --------------------------------------------------
Say 'Instalando Nexo dentro de WSL'
$debL  = ConvertTo-WslPath $Deb
$provL = ConvertTo-WslPath $Provision
& wsl.exe -d $Distro -u root -- sh $provL $debL nexo
if ($LASTEXITCODE -ne 0) { Fail 'Falló la instalación del paquete dentro de WSL (revisa los mensajes de arriba).' }
& wsl.exe --terminate $Distro | Out-Null    # aplica /etc/wsl.conf (usuario por defecto)

# --- 5. Accesos directos (solo en la versión .zip; el .exe crea los suyos) ----
if ($Shortcuts) {
    $AppDir = Join-Path $Base 'app'
    New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'launcher.vbs') -Destination $AppDir -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'nexo.ico') -Destination $AppDir -Force
    $ws = New-Object -ComObject WScript.Shell
    $targets = @(
        (Join-Path ([Environment]::GetFolderPath('Programs')) 'Nexo.lnk'),
        (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Nexo.lnk')
    )
    foreach ($t in $targets) {
        $s = $ws.CreateShortcut($t)
        $s.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
        $s.Arguments = '"' + (Join-Path $AppDir 'launcher.vbs') + '"'
        $s.IconLocation = (Join-Path $AppDir 'nexo.ico') + ',0'
        $s.WorkingDirectory = $AppDir
        $s.Description = 'Nexo: SSH, SFTP, RDP y bases de datos'
        $s.Save()
    }
}

Say 'Nexo está listo. Ábrelo desde el menú Inicio («Nexo»).'
Finish 0
