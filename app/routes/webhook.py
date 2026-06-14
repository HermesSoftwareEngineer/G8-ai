import logging
from flask import Blueprint, request, jsonify
from app.services.whatsapp import extract_message, send_text
from app.services.ai_agent import process_message, reset_session, get_session_mode, RESET_COMMANDS

logger = logging.getLogger(__name__)
bp = Blueprint("webhook", __name__)

RESET_REPLY = "Conversa reiniciada! 👋 Como posso te ajudar?"


@bp.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_webhook():
    payload = request.get_json(silent=True) or {}
    event = payload.get("event", "")

    if event not in ("messages.upsert", "MESSAGES_UPSERT"):
        return jsonify({"status": "ignored"}), 200

    phone, text, instance = extract_message(payload)

    # Debug: log raw payload keys to diagnose instance routing issues
    logger.debug("Webhook payload keys: event=%s instance=%s data_keys=%s",
                 payload.get("event"), payload.get("instance"), list((payload.get("data") or {}).keys()))

    if not phone or not text:
        return jsonify({"status": "ignored"}), 200

    logger.info("Mensagem recebida de %s via instância '%s': %s", phone, instance, text[:80])

    # /reset command
    if text.strip().lower() in RESET_COMMANDS:
        reset_session(phone)
        send_text(phone, RESET_REPLY, instance=instance)
        logger.info("Sessão resetada para %s", phone)
        return jsonify({"status": "reset"}), 200

    # Human mode — AI stays silent
    if get_session_mode(phone) == "human":
        logger.info("Contato %s em modo humano — IA silenciada", phone)
        return jsonify({"status": "human_mode"}), 200

    try:
        reply = process_message(phone, text)
        send_text(phone, reply, instance=instance)
        logger.info("Resposta enviada para %s via '%s': %s", phone, instance, reply[:80])
    except Exception as e:
        logger.error("Erro ao processar mensagem de %s: %s", phone, e, exc_info=True)
        send_text(phone, "Eita, deu um erro aqui. Tenta de novo em instantes! 🙏", instance=instance)

    return jsonify({"status": "ok"}), 200
