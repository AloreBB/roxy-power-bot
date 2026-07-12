#!/usr/bin/env bash
# Envía un magic packet de prueba (desde otra máquina de la LAN).
#
# Uso:
#   bash scripts/test-wol-local.sh <MAC> [broadcast] [puerto]
#   bash scripts/test-wol-local.sh aa:bb:cc:dd:ee:ff 192.168.1.255 9

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Uso: $0 <MAC> [broadcast=192.168.1.255] [puerto=9]" >&2
  exit 1
fi

MAC="$1"
BCAST="${2:-192.168.1.255}"
PORT="${3:-9}"

python3 - "$MAC" "$BCAST" "$PORT" <<'PY'
import socket
import sys

mac, bcast, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
mac = mac.replace("-", ":").lower()
parts = bytes(int(p, 16) for p in mac.split(":"))
if len(parts) != 6:
    raise SystemExit(f"MAC inválida: {mac}")
packet = b"\xff" * 6 + parts * 16
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.sendto(packet, (bcast, port))
print(f"Magic packet enviado a {mac} via {bcast}:{port} ({len(packet)} bytes)")
PY
