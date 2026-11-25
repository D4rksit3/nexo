#!/bin/sh
# Construye los paquetes de Windows a partir del .deb:
#   dist/NexoSetup-<versión>.exe   instalador (Inno Setup, compilado en Docker)
#   dist/nexo-windows-<versión>.zip  versión sin instalador (Instalar-Nexo.cmd)
# Requiere Docker (imagen amake/innosetup).
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VER="$(python3 -c "import sys; sys.path.insert(0,'$ROOT'); import nexo; print(nexo.__version__)")"
W="$ROOT/packaging/windows"
DEB="$ROOT/dist/nexo_${VER}_all.deb"
[ -f "$DEB" ] || sh "$ROOT/packaging/build-deb.sh" >/dev/null

B="$(mktemp -d)"; trap 'rm -rf "$B"' EXIT
cp "$DEB" "$B/nexo.deb"
cp "$W/setup-wsl.ps1" "$W/uninstall-wsl.ps1" "$W/provision.sh" "$W/launcher.vbs" \
   "$W/nexo.ico" "$W/nexo.iss" "$W/Instalar-Nexo.cmd" "$W/Desinstalar-Nexo.cmd" "$B/"
cp "$ROOT/LICENSE" "$B/LICENSE.txt"

# Archivos de Windows: CRLF, y BOM UTF-8 en .ps1/.iss para que las tildes
# se lean bien en Windows PowerShell 5.1 e Inno Setup.
for f in setup-wsl.ps1 uninstall-wsl.ps1 launcher.vbs nexo.iss Instalar-Nexo.cmd Desinstalar-Nexo.cmd LICENSE.txt; do
    sed -i 's/\r$//; s/$/\r/' "$B/$f"
done
for f in setup-wsl.ps1 uninstall-wsl.ps1 nexo.iss; do
    printf '\357\273\277' | cat - "$B/$f" > "$B/$f.tmp" && mv "$B/$f.tmp" "$B/$f"
done
# launcher.vbs y los .cmd se quedan en ASCII (wscript/cmd usan la página de códigos ANSI)

chmod -R a+rwX "$B"
docker run --rm -v "$B:/work" amake/innosetup "/DAppVersion=$VER" nexo.iss >"$B/iscc.log" 2>&1 \
    || { cat "$B/iscc.log"; exit 1; }
mkdir -p "$ROOT/dist"
cp "$B/out/NexoSetup-$VER.exe" "$ROOT/dist/"

python3 - "$B" "$ROOT/dist/nexo-windows-$VER.zip" <<'EOF'
import sys, zipfile, os
src, out = sys.argv[1], sys.argv[2]
files = ["Instalar-Nexo.cmd", "Desinstalar-Nexo.cmd", "setup-wsl.ps1", "uninstall-wsl.ps1",
         "provision.sh", "launcher.vbs", "nexo.ico", "nexo.deb", "LICENSE.txt"]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in files:
        z.write(os.path.join(src, f), "Nexo/" + f)
EOF
echo "$ROOT/dist/NexoSetup-$VER.exe"
echo "$ROOT/dist/nexo-windows-$VER.zip"
