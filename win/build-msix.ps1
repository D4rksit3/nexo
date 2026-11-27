# Empaqueta Nexo nativo como MSIX para la Microsoft Store.
# Requiere haber corrido win\build.ps1 (deja dist\Nexo\Nexo.exe) y el Windows SDK
# (makeappx/makepri; en los runners windows-latest de GitHub ya viene).
#
#   powershell -ExecutionPolicy Bypass -File win\build-msix.ps1 `
#     -Name "12345SeguriCloud.Nexo" -Publisher "CN=XXXXXXXX-XXXX-..." -PublisherDisplayName "SeguriCloud"
#
# Name, Publisher y PublisherDisplayName salen de Partner Center → la app → Identidad del producto.
# Sin ellos se usan valores de prueba: el .msix sirve para instalar localmente (firmado con
# -SignWithTestCert) pero la Store lo rechazaría.
# Resultado: dist\Nexo-<versión>.msix (sin firmar: la Store lo firma al publicarlo).
param(
  [string]$Name = "SeguriCloud.Nexo.Dev",
  [string]$Publisher = "CN=SeguriCloud Dev",
  [string]$PublisherDisplayName = "SeguriCloud",
  [string]$DisplayName = "Nexo",
  [switch]$SignWithTestCert
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$version = (Select-String -Path "nexo\__init__.py" -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value
# La Store exige 4 números y el último en 0: 2.5.5 → 2.5.5.0
$parts = @($version.Split(".") | ForEach-Object { [int]($_ -replace '\D.*$', '') })
while ($parts.Count -lt 3) { $parts += 0 }
$msixVersion = "{0}.{1}.{2}.0" -f $parts[0], $parts[1], $parts[2]
Write-Host "Nexo $version → MSIX $msixVersion ($Name)"

if (-not (Test-Path "dist\Nexo\Nexo.exe")) { throw "Falta dist\Nexo\Nexo.exe: corre antes win\build.ps1" }

# Herramientas del Windows SDK (la versión más nueva instalada).
$kits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
$sdkBin = Get-ChildItem $kits -Directory | Where-Object { $_.Name -match '^10\.' -and (Test-Path (Join-Path $_.FullName "x64\makeappx.exe")) } |
  Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
if (-not $sdkBin) { throw "No encontré makeappx.exe en $kits (instala el Windows SDK)" }
$makeappx = Join-Path $sdkBin.FullName "x64\makeappx.exe"
$makepri = Join-Path $sdkBin.FullName "x64\makepri.exe"
$signtool = Join-Path $sdkBin.FullName "x64\signtool.exe"
Write-Host "Windows SDK $($sdkBin.Name)"

# Carpeta del paquete: Nexo\ (lo que deja PyInstaller), Assets\ y el manifiesto.
$layout = "build\msix\layout"
if (Test-Path $layout) { Remove-Item -Recurse -Force $layout }
New-Item -ItemType Directory -Force $layout | Out-Null
Copy-Item -Recurse "dist\Nexo" "$layout\Nexo"
Copy-Item -Recurse "packaging\msix\Assets" "$layout\Assets"

$manifest = Get-Content -Raw -Encoding UTF8 "packaging\msix\AppxManifest.xml"
$esc = { param($s) [System.Security.SecurityElement]::Escape($s) }
$manifest = $manifest.Replace("@NAME@", (& $esc $Name)).Replace("@PUBLISHER@", (& $esc $Publisher)).
  Replace("@PUBLISHER_DISPLAY_NAME@", (& $esc $PublisherDisplayName)).Replace("@DISPLAY_NAME@", (& $esc $DisplayName)).
  Replace("@VERSION@", $msixVersion)
[System.IO.File]::WriteAllText((Join-Path $root "$layout\AppxManifest.xml"), $manifest, (New-Object System.Text.UTF8Encoding $false))

# resources.pri: elige el logo correcto según escala, tamaño y tema claro/oscuro.
$priCfg = "build\msix\priconfig.xml"
& $makepri createconfig /cf $priCfg /dq es-PE /pv 10.0.0 /o
if ($LASTEXITCODE -ne 0) { throw "makepri createconfig falló" }
& $makepri new /pr $layout /cf $priCfg /mn "$layout\AppxManifest.xml" /of "$layout\resources.pri" /o
if ($LASTEXITCODE -ne 0) { throw "makepri new falló" }

$msix = "dist\Nexo-$version.msix"
if (Test-Path $msix) { Remove-Item $msix }
& $makeappx pack /d $layout /p $msix /o
if ($LASTEXITCODE -ne 0) { throw "makeappx pack falló" }
Write-Host "Listo: $msix (para subir a Partner Center)"

if ($SignWithTestCert) {
  # Solo para probar en este equipo: certificado propio con el mismo Publisher, de confianza local.
  $cert = New-SelfSignedCertificate -Type Custom -Subject $Publisher -KeyUsage DigitalSignature `
    -FriendlyName "Nexo prueba MSIX" -CertStoreLocation "Cert:\CurrentUser\My" `
    -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3", "2.5.29.19={text}")
  $signed = "dist\Nexo-$version-prueba.msix"
  Copy-Item $msix $signed -Force
  & $signtool sign /fd SHA256 /sha1 $cert.Thumbprint /s My $signed
  if ($LASTEXITCODE -ne 0) { throw "signtool falló" }
  $cer = "build\msix\nexo-prueba.cer"
  Export-Certificate -Cert $cert -FilePath $cer | Out-Null
  Write-Host "Firmado para pruebas: $signed (certificado: $cer, hay que confiar en él para instalar)"
}
