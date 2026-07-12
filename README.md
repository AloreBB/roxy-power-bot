# ⚡ Roxy Power Bot

Bot de **Telegram** minimalista para **encender y apagar un PC** (servidor, torre, mini‑PC, lab…) con pocos comandos y **cero dependencias de pip**.

| Comando   | Acción                                      |
|-----------|---------------------------------------------|
| `/on`     | Enciende el PC con **Wake-on-LAN**          |
| `/off`    | Lo apaga por **SSH** (`sudo poweroff`)      |
| `/status` | Comprueba si responde el puerto SSH         |
| `/help`   | Ayuda                                       |

Al arrancar, el bot registra el **menú de comandos** de Telegram (`setMyCommands`): al escribir `/` en el chat aparecen las opciones (como en BotFather).

**Stack:** Python 3 (solo stdlib) + cliente `ssh` del sistema.

---

## ¿Por qué existe?

Quieres despertar o apagar un equipo de forma limpia desde el móvil, sin panel de Home Assistant ni abrir el router a mano.

Telegram ya está en el teléfono. Un bot con **allowlist de usuarios** es suficiente.

> **Regla de oro:** el bot **no puede vivir solo en el PC que quieres encender**.  
> Si ese PC está apagado, nadie recibe el `/on`.  
> Corre el bot en un **host siempre encendido**: otra PC de la LAN, un Raspberry Pi, un VPS, un NAS, etc.

---

## Arquitectura

```text
┌────────────┐     Telegram      ┌──────────────────┐
│  Tu móvil  │ ───────────────►  │  Host del bot    │
│            │                   │  (siempre ON)    │
└────────────┘                   └────────┬─────────┘
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    │ /on                 │                     │ /off
                    ▼                     │                     ▼
           Magic packet WoL               │              SSH + poweroff
           (UDP)                          │
                    │                     │
                    ▼                     ▼
              ┌───────────────────────────────────┐
              │   PC objetivo                     │
              │   Ethernet + WoL en BIOS/OS       │
              └───────────────────────────────────┘
```

| Pieza | Rol |
|-------|-----|
| **PC objetivo** | Se enciende con WoL y se apaga por SSH. BIOS + `ethtool` + sudoers. |
| **Host del bot** | Siempre online. Corre `bot.py`, manda el magic packet y el SSH de apagado. |
| **Telegram** | Solo retransmite comandos de usuarios autorizados. |

### ¿Dónde pongo el bot?

| Host del bot | `/on` (WoL) | `/off` (SSH) | Recomendado |
|--------------|-------------|--------------|-------------|
| Otra máquina **en la misma LAN** (Pi, NAS, mini‑PC) | Broadcast local | IP LAN o VPN | **Sí (lo más fiable)** |
| **VPS en internet** | Port‑forward **UDP 9** o un relay en casa | Mejor por VPN / Tailscale | Si no hay nada 24/7 en casa |
| El propio PC objetivo | No sirve para encenderlo | Solo mientras esté on | **No** para `/on` |

---

## Requisitos

### En el PC objetivo

- Cable **Ethernet** (Wi‑Fi casi nunca hace WoL en apagado real)
- BIOS/UEFI: **Wake on LAN** / Power on by PCI‑E / PME
- Preferible **ErP / Deep Sleep / EuP desactivado**
- Linux con `ethtool` (scripts pensados para systemd; Ubuntu/Debian ok)
- SSH accesible desde el host del bot
- Usuario con `poweroff` sin contraseña (script incluido)

### En el host del bot

- Python **3.10+**
- Cliente `ssh`
- Salida a Internet hacia `api.telegram.org` (**DNS que funcione**; ojo si Tailscale MagicDNS deja la red sin resolución)
- Misma LAN que el PC objetivo **o** port‑forward / VPN

---

## Guía rápida

### 1. Clonar

```bash
git clone https://github.com/AloreBB/roxy-power-bot.git
cd roxy-power-bot
```

### 2. BIOS del PC objetivo

- **Wake on LAN** / **Power on by PCI‑E** / **PME** → Enabled  
- **ErP** / **Deep Sleep** / **EuP** → Disabled  

### 3. Activar WoL en Linux (PC objetivo)

```bash
ip -br link   # elige la interfaz ethernet, p. ej. enp6s0
sudo IFACE=enp6s0 bash scripts/enable-wol-on-roxy.sh
sudo ethtool enp6s0 | grep -i wake
# Esperado:  Wake-on: g

cat /sys/class/net/enp6s0/address
# anota la MAC, p. ej. aa:bb:cc:dd:ee:ff
```

### 4. Apagado por SSH sin password (PC objetivo)

```bash
sudo bash scripts/setup-passwordless-poweroff.sh
```

Solo autoriza `poweroff` / `systemctl poweroff`.

### 5. Bot en Telegram

1. [@BotFather](https://t.me/BotFather) → `/newbot` → **token** (no lo subas a git).
2. [@userinfobot](https://t.me/userinfobot) → **Id numérico**.

### 6. Clave SSH (en el host del bot)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/roxy_power_bot -N "" -C "roxy-power-bot"
ssh-copy-id -i ~/.ssh/roxy_power_bot.pub USUARIO@IP_DEL_PC_OBJETIVO

# Prueba (¡apaga la máquina!):
ssh -i ~/.ssh/roxy_power_bot USUARIO@IP_DEL_PC_OBJETIVO 'sudo /sbin/poweroff'
```

### 7. Configurar y arrancar

```bash
cp .env.example .env
nano .env    # token, ALLOWED_USER_IDS, MAC, host, usuario, ruta de la clave
python3 bot.py
```

En Telegram, escribe `/` y elige un comando del menú, o manda:

```text
/status
/on
/off
/help
```

### 8. systemd (recomendado en el host del bot)

```bash
sudo mkdir -p /opt/roxy-power-bot
sudo cp bot.py /opt/roxy-power-bot/
sudo cp .env /opt/roxy-power-bot/          # solo en el servidor, nunca a git
sudo cp systemd/roxy-power-bot.service /etc/systemd/system/
sudo nano /etc/systemd/system/roxy-power-bot.service   # User= y rutas
sudo systemctl daemon-reload
sudo systemctl enable --now roxy-power-bot
sudo journalctl -u roxy-power-bot -f
```

---

## Menú de comandos en Telegram

Al iniciar, el bot llama a `setMyCommands` y deja:

| Comando   | Descripción en el menú        |
|-----------|-------------------------------|
| `/on`     | Encender (Wake-on-LAN)        |
| `/off`    | Apagar por SSH                |
| `/status` | ¿Está encendida?              |
| `/help`   | Ayuda y lista de comandos     |

Si no ves el menú al escribir `/`: cierra y reabre el chat, o reinicia la app de Telegram (a veces tarda unos segundos en refrescar).

---

## Variables de entorno

Copia [`.env.example`](.env.example) → `.env` (local, **gitignored**).

| Variable | Descripción |
|----------|-------------|
| `TELEGRAM_TOKEN` | Token de BotFather |
| `ALLOWED_USER_IDS` | IDs de Telegram autorizados (separados por coma) |
| `TARGET_NAME` | Nombre amigable en los mensajes (default `Roxy`) |
| `ROXY_MAC` | MAC ethernet del PC objetivo |
| `ROXY_BROADCAST` | Broadcast de la LAN o IP pública si hay port‑forward |
| `ROXY_WOL_PORT` | Puerto UDP del magic packet (default `9`) |
| `ROXY_HOST` | Host/IP para SSH |
| `ROXY_SSH_USER` | Usuario SSH |
| `ROXY_SSH_PORT` | Puerto SSH (default `22`) |
| `ROXY_SSH_KEY` | Ruta a la clave privada en el **host del bot** |
| `ROXY_SSH_POWEROFF_CMD` | Comando remoto de apagado |
| `LOG_LEVEL` | `INFO`, `DEBUG`, … |

Los prefijos `ROXY_*` son históricos (nombre del proyecto); valen para **cualquier** PC objetivo.

---

## Bot fuera de la LAN (VPS)

El magic packet es de red local. Desde Internet no llega solo.

**A) Port‑forward UDP 9** en el router hacia el PC o el broadcast (muchos ISP lo hacen mal).  
**B) Relay en casa** (Pi/NAS 24/7) — lo más fiable.  
**C) VPN/Tailscale** para `/off`; el `/on` sigue necesitando alguien en la LAN o el port‑forward.

---

## Probar WoL a mano

```bash
# En el PC objetivo
sudo ethtool IFACE | grep -i wake   # → g
sudo poweroff

# Desde otra máquina de la misma LAN
bash scripts/test-wol-local.sh aa:bb:cc:dd:ee:ff 192.168.1.255 9
```

En 30–90 s debería arrancar.

---

## Estructura del repo

```text
roxy-power-bot/
├── bot.py                              # Long polling, menú, WoL, SSH
├── .env.example                        # Plantilla (sin secretos reales)
├── .gitignore                          # .env, notas locales, etc.
├── scripts/
│   ├── enable-wol-on-roxy.sh           # WoL persistente (systemd oneshot)
│   ├── setup-passwordless-poweroff.sh
│   └── test-wol-local.sh
├── systemd/
│   └── roxy-power-bot.service
├── LICENSE                             # MIT
└── README.md
```

---

## Seguridad

### Qué **nunca** va al repositorio

| Secreto | Dónde |
|---------|--------|
| `TELEGRAM_TOKEN` | `.env` local (gitignored) |
| Claves SSH privadas | `~/.ssh/…` en el host del bot |
| IDs, MAC e IPs reales de tu red | Solo en tu `.env` local |
| Notas de deploy personales | p. ej. `deploy.local.md` (gitignored) |

- [`.env.example`](.env.example) solo tiene **placeholders**.
- El bot **no imprime el token** en logs (tampoco en errores HTTP de Telegram).
- Si un token se filtró en un chat o un commit: [@BotFather](https://t.me/BotFather) → `/revoke` y genera uno nuevo.

### Buenas prácticas

- Allowlist estricta con `ALLOWED_USER_IDS`.
- Clave SSH dedicada solo a este bot.
- Sudoers mínimo (solo `poweroff`).
- Evita exponer UDP 9 a Internet si puedes; preferible bot en LAN.

### Auditoría rápida antes de publicar cambios

```bash
# No debe haber .env versionado
git status
git check-ignore -v .env

# Buscar cadenas peligrosas en lo trackeado
git grep -nE 'TELEGRAM_TOKEN=[0-9]|BEGIN OPENSSH|sk-live' || true
```

---

## Solución de problemas

| Síntoma | Qué revisar |
|---------|-------------|
| Menú `/` vacío | Reinicia el bot; cierra/abre el chat; espera unos segundos |
| Bot no responde | `systemctl status roxy-power-bot`, DNS a `api.telegram.org`, logs |
| DNS roto con Tailscale | `tailscale set --accept-dns=false` y DNS públicos en `/etc/resolv.conf` |
| `/on` no enciende | BIOS, `Wake-on: g`, ethernet, misma LAN / port‑forward |
| `/off` falla | Clave SSH, `ROXY_HOST`, sudoers `NOPASSWD` |
| “No autorizado” | `ALLOWED_USER_IDS` debe ser el **id numérico**, no el @username |
| Conflicto 409 en logs | Otro proceso está haciendo `getUpdates` con el mismo token |

```bash
python3 bot.py
# o
journalctl -u roxy-power-bot -f
```

---

## Detalles de implementación (resumen)

- Long polling (`getUpdates`); limpia webhook al arrancar.
- Menú de comandos con `setMyCommands`.
- Preferencia **IPv4** al resolver `api.telegram.org` (evita cuelgues por IPv6 roto).
- Reintentos de red; log de cada comando (user id + texto, **sin token**).
- Magic packet WoL en pure Python (UDP).

---

## Licencia

[MIT](LICENSE).

Issues y PRs: [AloreBB/roxy-power-bot](https://github.com/AloreBB/roxy-power-bot).
