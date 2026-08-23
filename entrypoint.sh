#!/bin/sh
set -e
# Bind-Mounts auf /app/data koennen als root angelegt werden - Rechte korrigieren,
# bevor als nicht-root User weitergemacht wird.
mkdir -p /app/data
chown -R hlc20:hlc20 /app/data
exec gosu hlc20 "$@"
