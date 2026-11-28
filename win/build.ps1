# Construye Nexo para Windows (carpeta portable) con PyInstaller.
# Uso, desde la raíz del repositorio en PowerShell:
#   py -3.12 -m venv win\.venv ; win\.venv\Scripts\Activate.ps1
#   pip install -r win\requirements.txt pyinstaller
#   powershell -ExecutionPolicy Bypass -File win\build.ps1
# Resultado: dist\Nexo\Nexo.exe (+ dist\Nexo-windows-<versión>.zip)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$version = (Select-String -Path "nexo\__init__.py" -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value
Write-Host "Nexo $version para Windows"

python -m PyInstaller --noconfirm --clean --windowed `
  --name Nexo `
  --icon "$root\packaging\windows\nexo.ico" `
  --distpath dist --workpath build\pyinstaller --specpath build\pyinstaller `
  --paths . --paths win `
  --add-data "$root\win\ui;ui" `
  --collect-submodules nexo_win `
  --hidden-import nexo.vault --hidden-import nexo.conn --hidden-import nexo.keys --hidden-import nexo.themes `
  --hidden-import nexo.dbclient --hidden-import nexo.orgclient `
  --hidden-import psycopg2 --hidden-import pymysql --collect-all pymssql `
  --collect-submodules pymongo --collect-submodules bson --collect-submodules redis `
  --collect-submodules comtypes `
  win\run.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falló" }

$zip = "dist\Nexo-windows-$version.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "dist\Nexo\*" -DestinationPath $zip
Write-Host "Listo: dist\Nexo\Nexo.exe y $zip"
