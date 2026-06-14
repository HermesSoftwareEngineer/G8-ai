import logging
from flask import Blueprint, request, jsonify
from app.services.whatsapp import extract_message
from app.services.ai_agent import process_message
from app.services.whatsapp import send_text

logger = logging.getLogger(__name__)
bp = Blueprint("webhook", __name__)


@bp.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_webhook():
    payload = request.get_json(silent=True) or {}
    event = payload.get("event", "")

    # Only process incoming text messages
    if event not in ("messages.upsert", "MESSAGES_UPSERT"):
        return jsonify({"status": "ignored"}), 200

    phone, text = extract_message(payload)
    if not phone or not text:
        return jsonify({"status": "ignored"}), 200

    logger.info("Mensagem recebida de %s: %s", phone, text[:80])

    try:
        reply = process_message(phone, text)
        send_text(phone, reply)
        logger.info("Resposta enviada para %s: %s", phone, reply[:80])
    except Exception as e:
        logger.error("Erro ao processar mensagem de %s: %s", phone, e, exc_info=True)
        send_text(phone, "Eita, deu um erro aqui. Tenta de novo em instantes! 🙏")

    return jsonify({"status": "ok"}), 200
