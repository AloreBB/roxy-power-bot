# ⚡ Roxy Power Bot

Bot de **Telegram** minimalista para **encender y apagar un PC de casa** (servidor, torre, mini-PC…) con dos comandos:

| Comando    | Qué hace                                      |
|------------|-----------------------------------------------|
| `/on`      | Enciende el PC con **Wake-on-LAN**            |
| `/off`     | Lo apaga por **SSH** (`sudo poweroff`)        |
| `/status`  | Comprueba si responde el puerto SSH           |
| `/help`    | Lista de comandos                             |

Sin frameworks raros: **solo Python 3 de la stdlib** + `ssh` del sistema. Cero `pip install`.

---

## ¿Por qué existe?

Quieres llegar a casa (o despertar el lab) y que tu servidor esté listo… o apagarlo desde el móvil sin abrir el router ni un panel de Home Assistant.

Telegram ya está en el teléfono. Un bot con allowlist de usuarios es suficiente.

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
           (UDP, capa 2/3)                │
                    │                     │
                    ▼                     ▼
              ┌───────────────────────────────────┐
              │   PC objetivo  (ej. “Roxy”)       │
              │   Ethernet + WoL en BIOS/OS       │
              └───────────────────────────────────┘
```

| Pieza | Rol |
|-------|-----|
| **PC objetivo** | Se enciende con WoL y se apaga por SSH. Aquí configuras BIOS + `ethtool` + sudoers. |
| **Host del bot** | Siempre online. Corre `bot.py`, envía el magic packet y ejecuta el SSH de apagado. |
| **Telegram** | Solo retransmite comandos de usuarios autorizados. |

### ¿Dónde pongo el bot?

| Host del bot | `/on` (WoL) | `/off` (SSH) | Recomendado |
|--------------|-------------|--------------|-------------|
| Otra máquina **en la misma LAN** (Pi, NAS, mini-PC) | Broadcast local → suele funcionar al instante | IP LAN o Tailscale | **Sí (lo más fiable)** |
| **VPS en internet** | Hay que reenviar **UDP 9** en el router (o un relay en casa) | Mejor por **Tailscale / VPN** | Si no tienes nada siempre on en casa |
| El propio PC objetivo | Solo sirve para `/off` mientras esté encendido | Local | **No** para `/on` |

---

## Requisitos

### En el PC objetivo

- Cable **Ethernet** (Wi‑Fi casi nunca hace WoL en apagado real)
- BIOS/UEFI con **Wake on LAN** (o Power on by PCI‑E / PME)
- Preferible **ErP / Deep Sleep / EuP desactivado** (si está activo, el NIC se queda sin energía)
- Linux con `ethtool` (los scripts asumen systemd; Ubuntu/Debian van perfecto)
- SSH accesible desde el host del bot
- Usuario con permiso de `poweroff` sin contraseña (script incluido)

### En el host del bot

- Python **3.10+** (3.11/3.12/3.14 ok)
- Cliente `ssh`
- Conectividad a Telegram (`api.telegram.org`)
- Misma LAN que el PC objetivo **o** port-forward / VPN configurada

---

## Guía rápida (15 minutos)

### 1. Clonar

```bash
git clone https://github.com/AloreBB/roxy-power-bot.git
cd roxy-power-bot
```

### 2. BIOS del PC objetivo

Entra a la BIOS y activa algo equivalente a:

- **Wake on LAN** / **Power on by PCI‑E** / **PME Event** → *Enabled*
- **ErP Ready** / **Deep Sleep** / **EuP** → *Disabled*

Guarda y arranca el sistema.

### 3. Activar WoL en Linux (PC objetivo)

```bash
# Detecta la interfaz cableada si no sabes el nombre:
ip -br link

# Por defecto usa enp6s0; cámbialo si hace falta:
sudo IFACE=enp6s0 bash scripts/enable-wol-on-roxy.sh
```

Comprueba:

```bash
sudo ethtool enp6s0 | grep -i wake
# Esperado:  Wake-on: g
```

Anota la **MAC**:

```bash
cat /sys/class/net/enp6s0/address
# ejemplo: aa:bb:cc:dd:ee:ff
```

### 4. Apagado por SSH sin contraseña (PC objetivo)

```bash
sudo bash scripts/setup-passwordless-poweroff.sh
```

Eso deja un sudoers mínimo: solo `poweroff` / `systemctl poweroff` para tu usuario.

### 5. Crear el bot en Telegram

1. Habla con [@BotFather](https://t.me/BotFather) → `/newbot` → guarda el **token**.
2. Habla con [@userinfobot](https://t.me/userinfobot) → guarda tu **Id numérico** (no el @username).

### 6. Clave SSH desde el host del bot

```bash
# En el HOST DEL BOT (no en el PC objetivo)
ssh-keygen -t ed25519 -f ~/.ssh/roxy_power_bot -N "" -C "roxy-power-bot"
ssh-copy-id -i ~/.ssh/roxy_power_bot.pub USUARIO@IP_DEL_PC_OBJETIVO

# Prueba (¡apaga la máquina!):
ssh -i ~/.ssh/roxy_power_bot USUARIO@IP_DEL_PC_OBJETIVO 'sudo /sbin/poweroff'
```

### 7. Configurar y arrancar el bot

```bash
# En el HOST DEL BOT
cp .env.example .env
nano .env   # token, user id, MAC, host, usuario SSH, ruta de la clave
python3 bot.py
```

En Telegram:

```text
/status
/on
/off
```

### 8. (Opcional) systemd

```bash
sudo mkdir -p /opt/roxy-power-bot
sudo cp bot.py /opt/roxy-power-bot/
sudo cp .env /opt/roxy-power-bot/
sudo cp systemd/roxy-power-bot.service /etc/systemd/system/
sudo nano /etc/systemd/system/roxy-power-bot.service   # User= y rutas
sudo systemctl daemon-reload
sudo systemctl enable --now roxy-power-bot
sudo journalctl -u roxy-power-bot -f
```

---

## Variables de entorno

Copia [`.env.example`](.env.example) a `.env`. Las importantes:

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `TELEGRAM_TOKEN` | Token de BotFather | `7123…:AA…` |
| `ALLOWED_USER_IDS` | IDs de Telegram autorizados (coma) | `123456789` |
| `TARGET_NAME` | Nombre amigable en los mensajes | `Roxy` |
| `ROXY_MAC` | MAC ethernet del PC objetivo | `aa:bb:cc:dd:ee:ff` |
| `ROXY_BROADCAST` | Broadcast de la LAN **o** IP pública si usas port-forward | `192.168.1.255` |
| `ROXY_WOL_PORT` | Puerto UDP del magic packet | `9` |
| `ROXY_HOST` | Host/IP para SSH (LAN, hostname o Tailscale) | `192.168.1.50` |
| `ROXY_SSH_USER` | Usuario SSH | `ubuntu` |
| `ROXY_SSH_PORT` | Puerto SSH | `22` |
| `ROXY_SSH_KEY` | Ruta a la clave privada en el **host del bot** | `~/.ssh/roxy_power_bot` |
| `ROXY_SSH_POWEROFF_CMD` | Comando remoto de apagado | `sudo /sbin/poweroff` |

El archivo `.env` **nunca** se sube a git (está en `.gitignore`).

---

## Bot en un VPS (fuera de casa)

El magic packet es esencialmente un datagrama de red local. Desde internet no “aparece” en tu LAN solo.

### Opción A — Port forward en el router

1. Reserva DHCP / IP fija del PC objetivo por MAC.
2. Reenvía **UDP 9** (a veces 7) del WAN hacia la IP del PC o al broadcast de la LAN (según permita el router).
3. En el `.env` del VPS:

```env
ROXY_BROADCAST=TU_IP_PUBLICA
ROXY_WOL_PORT=9
ROXY_HOST=100.x.y.z          # IP Tailscale del PC, ideal para /off
```

Muchos routers de ISP **no reenvían bien a broadcast**. Si `/on` falla desde el VPS, usa la opción B.

### Opción B — Relay en casa (recomendado si tienes un Pi/NAS)

Deja un dispositivo barato siempre encendido en la LAN y corre el bot ahí. Cero port-forward, WoL fiable.

### Opción C — Tailscale + máquina en casa

El bot en el VPS hace `/off` por Tailscale. Para `/on`, igual necesitas alguien en la LAN que emita el magic packet (script, router con WoL, Home Assistant, etc.).

---

## Probar WoL a mano

1. En el PC objetivo: `sudo ethtool IFACE | grep -i wake` → `g`.
2. Apágalo de verdad: `sudo poweroff` (no solo suspender, si quieres probar S5).
3. Desde **otra máquina de la misma LAN**:

```bash
bash scripts/test-wol-local.sh aa:bb:cc:dd:ee:ff 192.168.1.255 9
```

4. En 30–90 s debería arrancar (LED de red en standby suele seguir vivo).

---

## Estructura del repo

```text
roxy-power-bot/
├── bot.py                          # Bot (long polling, stdlib)
├── .env.example                    # Plantilla de configuración
├── scripts/
│   ├── enable-wol-on-roxy.sh       # Activa WoL + unidad systemd persistente
│   ├── setup-passwordless-poweroff.sh
│   └── test-wol-local.sh           # Envía un magic packet de prueba
├── systemd/
│   └── roxy-power-bot.service      # Unidad para el host del bot
├── LICENSE
└── README.md
```

---

## Seguridad (importante)

### Qué **nunca** va al repositorio

| Secreto | Dónde vive |
|---------|------------|
| `TELEGRAM_TOKEN` | Solo en `.env` local (gitignored) |
| Claves SSH privadas | `~/.ssh/…` en el host del bot |
| User IDs reales, MAC/IP de tu casa | Solo en tu `.env` local |

- `.env` está en [`.gitignore`](.gitignore).
- [`.env.example`](.env.example) solo tiene **placeholders** (`123456789:AA…`, `aa:bb:cc:dd:ee:ff`).
- El bot **no loguea** el token (ni en errores HTTP de Telegram).

Si alguna vez filtraste un token: revócalo en [@BotFather](https://t.me/BotFather) con `/revoke` y genera uno nuevo.

### Buenas prácticas

- **Allowlist** con `ALLOWED_USER_IDS`: el resto recibe “No autorizado”.
- Clave SSH del bot **solo** para este uso.
- El sudoers del script solo permite `poweroff` / `systemctl poweroff`.
- Si expones UDP 9 a internet, cualquiera puede *intentar* despertar el PC si conoce la MAC. Prefiere bot en LAN o VPN.

---

## Solución de problemas

| Síntoma | Qué revisar |
|---------|-------------|
| `/on` no enciende | BIOS WoL, `Wake-on: g`, cable ethernet, misma LAN o port-forward, ErP desactivado |
| Enciende “a veces” | Ahorro de energía del NIC, switch barato, prueba otro puerto del router |
| `/off` falla por SSH | Clave, `ROXY_HOST`, firewall, Tailscale, sudoers `NOPASSWD` |
| Bot sordo | Token, proceso vivo, `ALLOWED_USER_IDS` es el **número**, no el @nick |
| “No autorizado” | Tu id de [@userinfobot](https://t.me/userinfobot) no está en la lista |
| WoL desde VPS no va | El router no reenvía broadcast; mueve el bot a la LAN |

Ver logs del bot:

```bash
# foreground
python3 bot.py

# systemd
journalctl -u roxy-power-bot -f
```

---

## Comandos del bot (referencia)

```text
/start   → ayuda
/help    → ayuda
/on      → Wake-on-LAN
/off     → apagado por SSH
/status  → ¿responde SSH?
```

Mensajes en HTML sencillo; el nombre visible se controla con `TARGET_NAME`.

---

## Licencia

[MIT](LICENSE) — úsalo, modifícalo, publícalo. Si te sirve, una ⭐ en GitHub siempre anima.

---

## Créditos / contexto

Nacido para gestionar **Roxy**, un servidor casero Linux, desde el móvil con la menor superficie de ataque posible: dos acciones, un allowlist, cero dependencias de pip.

¿Issues o mejoras? Ábrelo en GitHub: [AloreBB/roxy-power-bot](https://github.com/AloreBB/roxy-power-bot).
