#!/usr/bin/env bash
# Activa Wake-on-LAN (magic packet) de forma persistente en el PC objetivo.
#
# Uso:
#   sudo IFACE=enp6s0 bash scripts/enable-wol-on-roxy.sh
#
# IFACE: nombre de la interfaz ethernet (ip -br link)

set -euo pipefail

IFACE="${IFACE:-enp6s0}"
WOL_MODE="${WOL_MODE:-g}"  # g = magic packet

if [[ $EUID -ne 0 ]]; then
  echo "Ejecuta con sudo." >&2
  exit 1
fi

if ! command -v ethtool >/dev/null; then
  apt-get update -qq
  apt-get install -y ethtool
fi

if [[ ! -e "/sys/class/net/$IFACE" ]]; then
  echo "Interfaz '$IFACE' no existe. Disponibles:" >&2
  ip -br link >&2 || true
  exit 1
fi

echo "==> Interfaz: $IFACE"
ethtool "$IFACE" | grep -i wake || true

echo "==> Activando wol $WOL_MODE"
ethtool -s "$IFACE" wol "$WOL_MODE"

if [[ -w /sys/class/net/$IFACE/device/power/wakeup ]]; then
  echo enabled > "/sys/class/net/$IFACE/device/power/wakeup"
fi

echo "==> Estado actual:"
ethtool "$IFACE" | grep -i wake || true
cat "/sys/class/net/$IFACE/device/power/wakeup" 2>/dev/null || true

UNIT=/etc/systemd/system/wol@$IFACE.service
cat > "$UNIT" <<EOF
[Unit]
Description=Enable Wake-on-LAN on %i
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/sbin/ethtool -s %i wol ${WOL_MODE}
ExecStart=/bin/bash -c 'echo enabled > /sys/class/net/%i/device/power/wakeup || true'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "wol@${IFACE}.service"
systemctl status "wol@${IFACE}.service" --no-pager || true

echo
echo "OK. WoL debería quedar activo tras cada boot."
echo "IMPORTANTE — BIOS/UEFI:"
echo "  - Wake on LAN / PME / Power on by PCI-E → Enabled"
echo "  - ErP / Deep Sleep / EuP → Disabled (si existe)"
echo "MAC de esta interfaz: $(cat /sys/class/net/$IFACE/address)"
