#!/bin/sh
set -e
# hlc20-User zur Laufzeit an PUID/PGID anpassen (statt fixer Build-Time-UID) -
# so passt die Ownership direkt zum Host-Owner des Bind-Mounts, auch wenn
# chown auf dem darunterliegenden Dateisystem (NFS/CIFS) nicht zuverlaessig greift.
PUID=${PUID:-1000}
PGID=${PGID:-1000}
CUR_UID=$(id -u hlc20)
CUR_GID=$(id -g hlc20)
if [ "$CUR_GID" != "$PGID" ]; then
  groupmod -o -g "$PGID" hlc20
fi
if [ "$CUR_UID" != "$PUID" ]; then
  usermod -o -u "$PUID" hlc20
fi

mkdir -p /app/data
chown -R hlc20:hlc20 /app/data || true
exec gosu hlc20 "$@"
