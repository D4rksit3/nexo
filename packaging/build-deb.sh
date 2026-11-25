#!/bin/sh
# Construye dist/nexo_<versión>_all.deb
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VER="$(python3 -c "import sys; sys.path.insert(0,'$ROOT'); import nexo; print(nexo.__version__)")"
B="$(mktemp -d)"; trap 'rm -rf "$B"' EXIT
P="$B/nexo_${VER}_all"

mkdir -p "$P/DEBIAN" "$P/usr/bin" "$P/usr/share/nexo" "$P/usr/share/applications" \
         "$P/usr/share/icons/hicolor/scalable/apps" "$P/usr/share/doc/nexo"
cp -r "$ROOT/nexo" "$P/usr/share/nexo/"
find "$P/usr/share/nexo" -name __pycache__ -prune -exec rm -rf {} +

cat > "$P/usr/bin/nexo" <<'EOS'
#!/usr/bin/python3 -I
import sys
sys.path.insert(0, "/usr/share/nexo")
from nexo.app import main
sys.exit(main())
EOS
chmod 755 "$P/usr/bin/nexo"

install -m 644 "$ROOT/nexo/nexo.svg" "$P/usr/share/icons/hicolor/scalable/apps/com.seguricloud.Nexo.svg"
cat > "$P/usr/share/applications/com.seguricloud.Nexo.desktop" <<'EOS'
[Desktop Entry]
Type=Application
Name=Nexo
GenericName=SSH, SFTP y RDP
Comment=SSH, SFTP, túneles y RDP con bóveda cifrada
Exec=nexo
Icon=com.seguricloud.Nexo
Terminal=false
Categories=Network;RemoteAccess;
Keywords=ssh;sftp;rdp;terminal;tunnel;termius;enlace;
StartupWMClass=nexo
StartupNotify=true
EOS

cp "$ROOT/LICENSE" "$P/usr/share/doc/nexo/copyright"

SIZE="$(du -sk "$P/usr" | cut -f1)"
cat > "$P/DEBIAN/control" <<EOS
Package: nexo
Version: $VER
Section: net
Priority: optional
Architecture: all
Installed-Size: $SIZE
Depends: python3 (>= 3.10), fonts-inter-variable | fonts-inter, fonts-jetbrains-mono, python3-gi, gir1.2-gtk-3.0, gir1.2-vte-2.91, python3-paramiko (>= 3.0), python3-cryptography, openssh-client
Recommends: sshpass, freerdp3-x11
Conflicts: enlace
Replaces: enlace
Provides: enlace
Maintainer: Juan Roque <nexo@localhost>
Description: Cliente SSH, SFTP, túneles y RDP con bóveda cifrada
 Nexo guarda hosts, contraseñas y llaves en una bóveda local cifrada
 (AES-256-GCM + scrypt) y abre terminales SSH en pestañas y paneles
 divididos, un explorador SFTP, túneles de puertos y escritorio remoto RDP.
EOS
cat > "$P/DEBIAN/postinst" <<'EOS'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
EOS
cp "$P/DEBIAN/postinst" "$P/DEBIAN/postrm"
chmod 755 "$P/DEBIAN/postinst" "$P/DEBIAN/postrm"

mkdir -p "$ROOT/dist"
dpkg-deb --root-owner-group --build "$P" "$ROOT/dist/nexo_${VER}_all.deb" >/dev/null
echo "$ROOT/dist/nexo_${VER}_all.deb"
