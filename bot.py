#!/usr/bin/env python3
"""
Roxy Power Bot — Telegram bot mínimo para encender (WoL) y apagar (SSH) un PC.

Debe correr en un host SIEMPRE encendido (VPS, otra PC, Raspberry Pi, NAS…),
NO en el PC objetivo: si está apagado el bot no podría recibir /on.

Secretos (TELEGRAM_TOKEN, claves SSH, .env) NUNCA van en el repositorio.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Config (env vars o archivo .env local — no versionado)
# ---------------------------------------------------------------------------

def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
# IDs de Telegram permitidos, separados por coma (ej: 123456789,987654321)
ALLOWED_USER_IDS = {
    int(x.strip())
    for x in os.environ.get("ALLOWED_USER_IDS", "").split(",")
    if x.strip().isdigit()
}

# Nombre amigable en los mensajes del bot
TARGET_NAME = os.environ.get("TARGET_NAME", "Roxy").strip() or "Roxy"

# PC objetivo — sin defaults de red/usuario reales; se exigen al arrancar
ROXY_MAC = os.environ.get("ROXY_MAC", "").strip().lower()
ROXY_BROADCAST = os.environ.get("ROXY_BROADCAST", "255.255.255.255").strip()
ROXY_WOL_PORT = int(os.environ.get("ROXY_WOL_PORT", "9"))
ROXY_HOST = os.environ.get("ROXY_HOST", "").strip()
ROXY_SSH_USER = os.environ.get("ROXY_SSH_USER", "").strip()
ROXY_SSH_PORT = int(os.environ.get("ROXY_SSH_PORT", "22"))
# Ruta a la clave privada en el host del bot (vacío = default de ssh)
ROXY_SSH_KEY = os.environ.get("ROXY_SSH_KEY", "").strip()
ROXY_SSH_POWEROFF_CMD = os.environ.get(
    "ROXY_SSH_POWEROFF_CMD",
    "sudo /sbin/poweroff",
).strip()

POLL_TIMEOUT = int(os.environ.get("POLL_TIMEOUT", "50"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("roxy-power-bot")


def _api_url(method: str) -> str:
    """Construye URL de la API. El token no se loguea en claro."""
    return f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"


# ---------------------------------------------------------------------------
# Telegram helpers
# ---------------------------------------------------------------------------

def api_call(method: str, payload: dict | None = None, timeout: int = 60) -> dict:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        _api_url(method),
        data=data,
        headers=headers,
        method="POST" if data else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # No incluir e.url (lleva el token). Solo código + cuerpo de error.
        err = e.read().decode("utf-8", errors="replace")
        log.error("Telegram HTTP %s en %s: %s", e.code, method, err)
        raise
    except urllib.error.URLError as e:
        log.error("Telegram red en %s: %s", method, e.reason)
        raise
    if not body.get("ok"):
        raise RuntimeError(f"Telegram API error en {method}: {body}")
    return body["result"]


def send_message(chat_id: int, text: str, reply_to: int | None = None) -> None:
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_to is not None:
        payload["reply_to_message_id"] = reply_to
    try:
        api_call("sendMessage", payload, timeout=30)
    except Exception:
        log.exception("No se pudo enviar mensaje a chat_id=%s", chat_id)


# ---------------------------------------------------------------------------
# Power actions
# ---------------------------------------------------------------------------

def normalize_mac(mac: str) -> bytes:
    mac = mac.replace("-", ":").replace(".", ":").lower()
    parts = mac.split(":")
    if len(parts) != 6:
        raise ValueError(f"MAC inválida: {mac}")
    return bytes(int(p, 16) for p in parts)


def wake_on_lan(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    """Envía magic packet (Wake-on-LAN)."""
    mac_bytes = normalize_mac(mac)
    packet = b"\xff" * 6 + mac_bytes * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, port))
        if broadcast != "255.255.255.255":
            try:
                sock.sendto(packet, ("255.255.255.255", port))
            except OSError:
                pass


def ssh_base_cmd() -> list[str]:
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-p",
        str(ROXY_SSH_PORT),
    ]
    if ROXY_SSH_KEY:
        cmd += ["-i", ROXY_SSH_KEY]
    cmd.append(f"{ROXY_SSH_USER}@{ROXY_HOST}")
    return cmd


def is_roxy_up() -> bool:
    """Comprueba si el puerto SSH responde."""
    try:
        with socket.create_connection((ROXY_HOST, ROXY_SSH_PORT), timeout=3):
            return True
    except OSError:
        return False


def power_off_roxy() -> tuple[bool, str]:
    if not is_roxy_up():
        return False, f"{TARGET_NAME} no responde en SSH (¿ya está apagada?)."
    cmd = ssh_base_cmd() + [ROXY_SSH_POWEROFF_CMD]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        return True, "Comando enviado (timeout al cerrar SSH; suele ser normal)."
    except FileNotFoundError:
        return False, "No está instalado `ssh` en el host del bot."
    if proc.returncode == 0:
        return True, "Apagado solicitado."
    err = (proc.stderr or proc.stdout or "").strip()
    if "closed" in err.lower() or proc.returncode in (255, -1):
        return True, f"Apagado solicitado (ssh rc={proc.returncode})."
    return False, f"Error SSH (rc={proc.returncode}): {err or 'sin detalle'}"


def power_on_roxy() -> tuple[bool, str]:
    if is_roxy_up():
        return True, f"{TARGET_NAME} ya está encendida (SSH responde)."
    try:
        wake_on_lan(ROXY_MAC, ROXY_BROADCAST, ROXY_WOL_PORT)
    except Exception as e:
        return False, f"Error enviando WoL: {e}"
    return True, (
        f"Magic packet enviado a <code>{ROXY_MAC}</code>\n"
        f"broadcast <code>{ROXY_BROADCAST}:{ROXY_WOL_PORT}</code>\n"
        "Espera 30–90 s y prueba SSH / <code>/status</code>."
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def help_text() -> str:
    return (
        f"<b>{TARGET_NAME} Power Bot</b>\n"
        "Comandos:\n"
        "• /on — encender (Wake-on-LAN)\n"
        "• /off — apagar (SSH + poweroff)\n"
        "• /status — ¿responde SSH?\n"
        "• /help — esta ayuda"
    )


def handle_command(user_id: int, chat_id: int, text: str, message_id: int) -> None:
    if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
        log.warning("Usuario no autorizado: %s", user_id)
        send_message(chat_id, "⛔ No autorizado.", reply_to=message_id)
        return

    cmd = text.strip().split()[0].split("@")[0].lower()

    if cmd in ("/start", "/help"):
        send_message(chat_id, help_text(), reply_to=message_id)
        return

    if cmd == "/on":
        send_message(chat_id, "⚡ Enviando Wake-on-LAN…", reply_to=message_id)
        ok, msg = power_on_roxy()
        send_message(chat_id, ("✅ " if ok else "❌ ") + msg)
        return

    if cmd == "/off":
        send_message(chat_id, f"💤 Apagando {TARGET_NAME}…", reply_to=message_id)
        ok, msg = power_off_roxy()
        send_message(chat_id, ("✅ " if ok else "❌ ") + msg)
        return

    if cmd == "/status":
        up = is_roxy_up()
        send_message(
            chat_id,
            f"{'🟢 Encendida' if up else '🔴 Apagada / no responde'} "
            f"(<code>{ROXY_HOST}:{ROXY_SSH_PORT}</code>)",
            reply_to=message_id,
        )
        return

    send_message(chat_id, "Comando desconocido. Usa /help", reply_to=message_id)


def validate_config() -> None:
    missing = []
    if not TELEGRAM_TOKEN:
        missing.append("TELEGRAM_TOKEN")
    if not ALLOWED_USER_IDS:
        missing.append("ALLOWED_USER_IDS")
    if not ROXY_MAC:
        missing.append("ROXY_MAC")
    if not ROXY_HOST:
        missing.append("ROXY_HOST")
    if not ROXY_SSH_USER:
        missing.append("ROXY_SSH_USER")
    if missing:
        log.error(
            "Faltan variables: %s — copia .env.example a .env (local, no lo subas a git)",
            ", ".join(missing),
        )
        sys.exit(1)
    try:
        normalize_mac(ROXY_MAC)
    except ValueError as e:
        log.error("%s", e)
        sys.exit(1)
    # Nunca loguear TELEGRAM_TOKEN
    log.info(
        "Listo para %s | MAC=%s broadcast=%s ssh=%s@%s:%s allowlist=%d usuario(s)",
        TARGET_NAME,
        ROXY_MAC,
        ROXY_BROADCAST,
        ROXY_SSH_USER,
        ROXY_HOST,
        ROXY_SSH_PORT,
        len(ALLOWED_USER_IDS),
    )


def main() -> None:
    validate_config()
    me = api_call("getMe")
    log.info("Bot @%s listo. Ctrl+C para salir.", me.get("username"))

    offset = 0
    while True:
        try:
            updates = api_call(
                "getUpdates",
                {"offset": offset, "timeout": POLL_TIMEOUT, "allowed_updates": ["message"]},
                timeout=POLL_TIMEOUT + 10,
            )
        except Exception:
            log.exception("Error en getUpdates; reintento en 5s")
            time.sleep(5)
            continue

        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            text = msg.get("text") or ""
            if not text.startswith("/"):
                continue
            user = msg.get("from") or {}
            chat = msg.get("chat") or {}
            try:
                handle_command(
                    user_id=int(user["id"]),
                    chat_id=int(chat["id"]),
                    text=text,
                    message_id=int(msg["message_id"]),
                )
            except Exception:
                log.exception("Error manejando update %s", upd.get("update_id"))


if __name__ == "__main__":
    main()
