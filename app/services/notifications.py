import logging
from app.models.database import get_db, db_insert, db_update
from app.services.whatsapp import send_text
from app.utils.datetime_utils import format_datetime_br, format_date_br, format_time_br, parse_iso

logger = logging.getLogger(__name__)


def _fetch_appointment_details(appointment_id: str) -> dict | None:
    db = get_db()
    result = (
        db.table("appointments")
        .select(
            "*, "
            "customers(name, phone_whatsapp), "
            "barbers(name, phone_whatsapp), "
            "services(name)"
        )
        .eq("id", appointment_id)
        .execute()
    )
    return result.data[0] if result.data else None


def _get_template(template_key: str) -> str | None:
    db = get_db()
    result = (
        db.table("notification_templates")
        .select("body")
        .eq("template_key", template_key)
        .execute()
        .data or []
    )
    return result[0]["body"] if result else None


def _format_msg(template_key: str, fallback: str, **kwargs) -> str:
    template = _get_template(template_key)
    return (template or fallback).format(**kwargs)


def send_confirmation(appointment_id: str) -> None:
    appt = _fetch_appointment_details(appointment_id)
    if not appt:
        logger.warning("Agendamento %s não encontrado para notificação", appointment_id)
        return

    start = parse_iso(appt["start_datetime"])
    data_br = format_date_br(start)
    hora_br = format_time_br(start)
    servico = appt["services"]["name"]
    barbeiro = appt["barbers"]["name"]
    cliente_nome = appt["customers"]["name"]
    cliente_phone = appt["customers"]["phone_whatsapp"]
    barbeiro_phone = appt["barbers"]["phone_whatsapp"]

    msg_cliente = _format_msg("confirmation_client",
        "✅ Agendamento confirmado!\n\n"
        "📅 Data: {data}\n⏰ Horário: {hora}\n"
        "💈 Serviço: {servico}\n👤 Barbeiro: {barbeiro}\n\n"
        "Até lá! 🤙",
        data=data_br, hora=hora_br, servico=servico, barbeiro=barbeiro)

    msg_barbeiro = _format_msg("confirmation_barber",
        "🔔 Novo agendamento!\n\n"
        "👤 Cliente: {cliente}\n📱 WhatsApp: {cliente_phone}\n"
        "📅 Data: {data}\n⏰ Horário: {hora}\n"
        "💈 Serviço: {servico}",
        cliente=cliente_nome, cliente_phone=cliente_phone,
        data=data_br, hora=hora_br, servico=servico)

    _send_and_record(appointment_id, "confirmation", cliente_phone, msg_cliente)
    _send_and_record(appointment_id, "barber_alert", barbeiro_phone, msg_barbeiro)


def send_reminder(appointment_id: str) -> None:
    appt = _fetch_appointment_details(appointment_id)
    if not appt:
        return

    start = parse_iso(appt["start_datetime"])
    hora_br = format_time_br(start)
    servico = appt["services"]["name"]
    barbeiro = appt["barbers"]["name"]
    cliente_nome = appt["customers"]["name"]
    cliente_phone = appt["customers"]["phone_whatsapp"]
    barbeiro_phone = appt["barbers"]["phone_whatsapp"]

    msg_cliente = _format_msg("reminder_1h_client",
        "⏰ Lembrete: seu horário na Barbershop G8 é em 1 hora!\n\n"
        "🕐 {hora} com {barbeiro}\n💈 {servico}\n\n"
        "Qualquer dúvida, é só chamar aqui. 👊",
        hora=hora_br, barbeiro=barbeiro, servico=servico)

    msg_barbeiro = _format_msg("reminder_1h_barber",
        "⏰ Lembrete: você tem um cliente em 1 hora!\n\n"
        "👤 {cliente}\n🕐 {hora}\n💈 {servico}",
        cliente=cliente_nome, hora=hora_br, servico=servico)

    _send_and_record(appointment_id, "reminder_1h", cliente_phone, msg_cliente)
    _send_and_record(appointment_id, "barber_reminder_1h", barbeiro_phone, msg_barbeiro)


def send_cancellation(appointment_id: str) -> None:
    appt = _fetch_appointment_details(appointment_id)
    if not appt:
        return

    start = parse_iso(appt["start_datetime"])
    data_br = format_date_br(start)
    hora_br = format_time_br(start)
    barbeiro_phone = appt["barbers"]["phone_whatsapp"]
    cliente_nome = appt["customers"]["name"]

    msg_barbeiro = _format_msg("cancellation_barber",
        "❌ Agendamento cancelado!\n\n"
        "👤 Cliente: {cliente}\n📅 Data: {data}\n⏰ Horário: {hora}",
        cliente=cliente_nome, data=data_br, hora=hora_br)

    send_text(barbeiro_phone, msg_barbeiro)


def _send_and_record(appointment_id: str, notif_type: str, phone: str, text: str) -> None:
    db = get_db()
    existing = (
        db.table("appointment_notifications")
        .select("id, status")
        .eq("appointment_id", appointment_id)
        .eq("type", notif_type)
        .execute()
        .data or []
    )
    if existing and existing[0]["status"] == "sent":
        return

    success = send_text(phone, text)
    status = "sent" if success else "failed"

    if existing:
        db_update("appointment_notifications", existing[0]["id"], {"status": status, "sent_at": "now()"})
    else:
        db_insert("appointment_notifications", {
            "appointment_id": appointment_id,
            "type": notif_type,
            "status": status,
            "sent_at": "now()" if success else None,
        })
