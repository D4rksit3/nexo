#!/bin/sh
# Se ejecuta como root DENTRO de la distribución WSL «Nexo».
# Instala (o actualiza) el .deb y deja un usuario normal por defecto.
#   uso: provision.sh /ruta/nexo.deb [usuario]
set -eu
DEB="$1"
USR="${2:-nexo}"
export DEBIAN_FRONTEND=noninteractive

# apt lee el paquete como usuario _apt: se copia a un sitio legible.
cp "$DEB" /tmp/nexo-install.deb
chmod 644 /tmp/nexo-install.deb

echo "-> Actualizando índices de paquetes"
apt-get update -q
echo "-> Instalando Nexo y sus dependencias (la primera vez tarda unos minutos)"
apt-get install -y -q --no-install-recommends ca-certificates locales
apt-get install -y -q /tmp/nexo-install.deb
rm -f /tmp/nexo-install.deb

# Español UTF-8 para que los textos y nombres de archivo con tildes se vean bien.
if ! locale -a 2>/dev/null | grep -qi '^es_ES.utf8$'; then
    sed -i 's/^# *es_ES.UTF-8/es_ES.UTF-8/' /etc/locale.gen
    locale-gen es_ES.UTF-8 >/dev/null
fi
update-locale LANG=es_ES.UTF-8

if ! id "$USR" >/dev/null 2>&1; then
    echo "-> Creando el usuario $USR"
    useradd -m -s /bin/bash "$USR"
fi

cat > /etc/wsl.conf <<EOF
[user]
default=$USR

[boot]
systemd=false

[interop]
appendWindowsPath=false
EOF

echo "-> Nexo $(dpkg-query -W -f='${Version}' nexo) instalado"
