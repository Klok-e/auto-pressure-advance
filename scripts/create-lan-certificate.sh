#!/usr/bin/env bash
set -euo pipefail

lan_ip=${1:?Usage: scripts/create-lan-certificate.sh LAN_IPV4_ADDRESS}
python3 - "$lan_ip" <<'PY'
import ipaddress
import sys

try:
    ipaddress.IPv4Address(sys.argv[1])
except ValueError as error:
    raise SystemExit(f"Invalid LAN IPv4 address: {error}")
PY

out=results/lan-tls
if [[ -e "$out/ca.key" ]]; then
    echo "Certificate already exists in $out; remove that directory to create a new one." >&2
    exit 1
fi
umask 077
mkdir -p "$out/public"
openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 365 \
    -keyout "$out/ca.key" -out "$out/ca.crt" \
    -subj '/CN=Adaptive PA local development CA' \
    -addext 'basicConstraints=critical,CA:TRUE' \
    -addext 'keyUsage=critical,keyCertSign,cRLSign' 2>/dev/null
openssl req -newkey rsa:2048 -nodes -sha256 \
    -keyout "$out/server.key" -out "$out/server.csr" \
    -subj "/CN=$lan_ip" 2>/dev/null
printf 'subjectAltName=IP:%s\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' "$lan_ip" > "$out/server.ext"
openssl x509 -req -in "$out/server.csr" -CA "$out/ca.crt" -CAkey "$out/ca.key" \
    -CAcreateserial -out "$out/server.crt" -days 30 -sha256 -extfile "$out/server.ext" 2>/dev/null
openssl x509 -in "$out/ca.crt" -outform DER -out "$out/public/ca.cer"
rm "$out/server.csr" "$out/server.ext" "$out/ca.srl"
openssl verify -CAfile "$out/ca.crt" "$out/server.crt"
echo "Import $out/public/ca.cer on the Android phone; use $out/server.crt and $out/server.key with Uvicorn."
