#!/usr/bin/env bash
# Permite apagar el PC por SSH sin pedir password de sudo.
# Solo autoriza poweroff / systemctl poweroff (nada más).
#
# Uso (en el PC objetivo):
#   sudo bash scripts/setup-passwordless-poweroff.sh

set -euo pipefail

USER_NAME="${SUDO_USER:-${USER:-}}"
if [[ -z "$USER_NAME" || "$USER_NAME" == "root" ]]; then
  echo "No se pudo detectar el usuario. Ejecuta: sudo -u TU_USUARIO sudo bash $0" >&2
  exit 1
fi

FILE="/etc/sudoers.d/roxy-poweroff-${USER_NAME}"

if [[ $EUID -ne 0 ]]; then
  echo "Ejecuta con sudo." >&2
  exit 1
fi

cat > "$FILE" <<EOF
# Managed by roxy-power-bot — solo apagado remoto
${USER_NAME} ALL=(root) NOPASSWD: /sbin/poweroff, /usr/sbin/poweroff, /bin/systemctl poweroff, /usr/bin/systemctl poweroff
EOF
chmod 440 "$FILE"
visudo -cf "$FILE"

echo "OK. Sudoers escrito en $FILE"
echo "Prueba local (no pide password):"
echo "  sudo -n /sbin/poweroff --help"
echo "Desde el host del bot:"
echo "  ssh ${USER_NAME}@IP_DEL_PC 'sudo /sbin/poweroff'"
