import logging
import requests
from app.config import Config

logger = logging.getLogger(__name__)


def _headers() -> dict:
    return {
        "apikey": Config.EVOLUTION_API_KEY,
        "Content-Type": "application/json",
    }


def _base_url() -> str:
    return f"{Config.EVOLUTION_API_URL}/message/sendText/{Config.EVOLUTION_INSTANCE_NAME}"


def send_text(to: str, text: str) -> bool:
    """Send a WhatsApp text message via Evolution API."""
    # Normalize phone: remove non-digits, ensure country code
    phone = "".join(c for c in to if c.isdigit())
    if not phone.startswith("55"):
        phone = "55" + phone

    payload = {
        "number": phone,
        "text": text,
    }

    try:
        resp = requests.post(_base_url(), json=payload, headers=_headers(), timeout=15)
        resp.raise_for_status()
        logger.info("Mensagem enviada para %s", phone)
        return True
    except requests.RequestException as e:
        logger.error("Erro ao enviar mensagem para %s: %s", phone, e)
        return False


def extract_message(payload: dict) -> tuple[str, str] | tuple[None, None]:
    """
    Extract (phone, text) from an Evolution API webhook payload.
    Returns (None, None) if the event is not a text message.
    """
    try:
        data = payload.get("data", {})
        key = data.get("key", {})
        # Ignore messages sent by the bot itself
        if key.get("fromMe"):
            return None, None

        msg_type = data.get("messageType", "")
        if msg_type not in ("conversation", "extendedTextMessage"):
            return None, None

        message = data.get("message", {})
        text = message.get("conversation") or message.get("extendedTextMessage", {}).get("text", "")
        remote_jid = key.get("remoteJid", "")
        # remoteJid format: 5585999999999@s.whatsapp.net
        phone = remote_jid.split("@")[0]
        return phone, text.strip()
    except Exception as e:
        logger.warning("Falha ao extrair mensagem do payload: %s", e)
        return None, None
