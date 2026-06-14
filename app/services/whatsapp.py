import logging
import requests
from app.config import Config

logger = logging.getLogger(__name__)


def _headers() -> dict:
    return {
        "apikey": Config.EVOLUTION_API_KEY,
        "Content-Type": "application/json",
    }


def _send_url(instance: str) -> str:
    return f"{Config.EVOLUTION_API_URL}/message/sendText/{instance}"


def send_text(to: str, text: str, instance: str | None = None) -> bool:
    """Send a WhatsApp text message via Evolution API.

    Args:
        to: Destination phone number.
        text: Message content.
        instance: Evolution API instance name. Defaults to EVOLUTION_INSTANCE_NAME.
    """
    phone = "".join(c for c in to if c.isdigit())
    if not phone.startswith("55"):
        phone = "55" + phone

    used_instance = instance or Config.EVOLUTION_INSTANCE_NAME
    payload = {"number": phone, "text": text}

    try:
        resp = requests.post(_send_url(used_instance), json=payload, headers=_headers(), timeout=15)
        resp.raise_for_status()
        logger.info("Mensagem enviada para %s via instância '%s'", phone, used_instance)
        return True
    except requests.RequestException as e:
        logger.error("Erro ao enviar mensagem para %s: %s", phone, e)
        return False


def setup_webhook(webhook_url: str | None = None) -> bool:
    """
    Configure the Evolution API webhook and verify WhatsApp connection.
    Called once on app startup.

    Args:
        webhook_url: Override URL (e.g. from ngrok). Falls back to WEBHOOK_URL env var.
    """
    base = Config.EVOLUTION_API_URL
    instance = Config.EVOLUTION_INSTANCE_NAME
    webhook_url = webhook_url or Config.WEBHOOK_URL

    if not webhook_url:
        logger.warning("WEBHOOK_URL não definida — pulando configuração automática do webhook")
        return False

    # 1. Set webhook
    try:
        resp = requests.post(
            f"{base}/webhook/set/{instance}",
            json={
                "webhook": {
                    "enabled": True,
                    "url": webhook_url,
                    "events": ["MESSAGES_UPSERT"],
                    "webhookByEvents": False,
                    "webhookBase64": False,
                }
            },
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("✅ Webhook configurado: %s", webhook_url)
    except requests.RequestException as e:
        logger.error("❌ Falha ao configurar webhook: %s", e)
        return False

    # 2. Check WhatsApp connection state
    try:
        resp = requests.get(
            f"{base}/instance/connectionState/{instance}",
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        state = data.get("instance", {}).get("state") or data.get("state", "unknown")
        if state == "open":
            logger.info("✅ WhatsApp conectado (instância: %s)", instance)
        else:
            logger.warning("⚠️  WhatsApp não conectado — estado: %s | escaneie o QR Code", state)
    except requests.RequestException as e:
        logger.warning("⚠️  Não foi possível verificar conexão WhatsApp: %s", e)

    return True


def extract_message(payload: dict) -> tuple[str, str, str] | tuple[None, None, None]:
    """
    Extract (phone, text, instance) from an Evolution API webhook payload.
    Returns (None, None, None) if the event is not a text message.
    """
    try:
        data = payload.get("data", {})
        key = data.get("key", {})
        if key.get("fromMe"):
            return None, None, None

        msg_type = data.get("messageType", "")
        if msg_type not in ("conversation", "extendedTextMessage"):
            return None, None, None

        message = data.get("message", {})
        text = message.get("conversation") or message.get("extendedTextMessage", {}).get("text", "")
        remote_jid = key.get("remoteJid", "")
        phone = remote_jid.split("@")[0]
        # Evolution API sends the source instance in the top-level payload
        instance = payload.get("instance") or Config.EVOLUTION_INSTANCE_NAME
        return phone, text.strip(), instance
    except Exception as e:
        logger.warning("Falha ao extrair mensagem do payload: %s", e)
        return None, None, None
