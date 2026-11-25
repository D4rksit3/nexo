<#
  Desinstala Nexo de Windows: respalda la bóveda en Documentos y elimina la
  distribución WSL «Nexo», sus accesos directos y %LOCALAPPDATA%\Nexo.
  No toca ninguna otra distribución WSL.
#>
param(
    [string]$Distro = 'Nexo',
    [switch]$NoBackup,
    [switch]$NoPause
)

$ErrorActionPreference = 'Continue'
$env:WSL_UTF8 = '1'
$Base = Join-Path $env:LOCALAPPDATA 'Nexo'

function Say([string]$m) { Write-Host ''; Write-Host "==> $m" -ForegroundColor Green }

$exists = $false
if (Get-Command wsl.exe -ErrorAction SilentlyContinue) {
    $names = & wsl.exe --list --quiet 2>$null | ForEach-Object { $_.Trim([char]0, ' ', "`t") } | Where-Object { $_ }
    $exists = $names -contains $Distro
}

if ($exists -and -not $NoBackup) {
    $docs = [Environment]::GetFolderPath('MyDocuments')
    $dest = Join-Path $docs ("Nexo-respaldo-{0}.tar.gz" -f (Get-Date -Format 'yyyyMMdd-HHmm'))
    $destL = (& wsl.exe -d $Distro -u root -- wslpath -a ($dest -replace '\\', '/') | Select-Object -First 1)
    if ($destL) {
        $destL = $destL.Trim()
        & wsl.exe -d $Distro -u root -- sh -c 'cd /home/nexo 2>/dev/null && [ -d .local/share/nexo ] && tar czf "$1" .local/share/nexo $( [ -d .config/nexo ] && echo .config/nexo )' sh $destL
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $dest)) {
            Say "Bóveda respaldada en $dest (sigue cifrada con tu contraseña maestra)"
        }
    }
}

if ($exists) {
    Say "Eliminando la distribución WSL «$Distro»"
    & wsl.exe --unregister $Distro | Out-Null
}

foreach ($lnk in @(
        (Join-Path ([Environment]::GetFolderPath('Programs')) 'Nexo.lnk'),
        (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Nexo.lnk'))) {
    if (Test-Path -LiteralPath $lnk) { Remove-Item -LiteralPath $lnk -Force }
}
Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' -Name 'NexoSetup' -ErrorAction SilentlyContinue
if (Test-Path -LiteralPath $Base) { Remove-Item -LiteralPath $Base -Recurse -Force -ErrorAction SilentlyContinue }

Say 'Nexo se desinstaló.'
if (-not $NoPause) { Read-Host 'Presiona Enter para cerrar' | Out-Null }
