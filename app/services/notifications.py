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

    # Mensagem para o cliente
    msg_cliente = (
        f"✅ Agendamento confirmado!\n\n"
        f"📅 Data: {data_br}\n"
        f"⏰ Horário: {hora_br}\n"
        f"💈 Serviço: {servico}\n"
        f"👤 Barbeiro: {barbeiro}\n\n"
        f"Até lá! 🤙"
    )

    # Mensagem para o barbeiro
    msg_barbeiro = (
        f"🔔 Novo agendamento!\n\n"
        f"👤 Cliente: {cliente_nome}\n"
        f"📱 WhatsApp: {cliente_phone}\n"
        f"📅 Data: {data_br}\n"
        f"⏰ Horário: {hora_br}\n"
        f"💈 Serviço: {servico}"
    )

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

    msg_cliente = (
        f"⏰ Lembrete: seu horário na Barbershop G8 é em 1 hora!\n\n"
        f"🕐 {hora_br} com {barbeiro}\n"
        f"💈 {servico}\n\n"
        f"Qualquer dúvida, é só chamar aqui. 👊"
    )

    msg_barbeiro = (
        f"⏰ Lembrete: você tem um cliente em 1 hora!\n\n"
        f"👤 {cliente_nome}\n"
        f"🕐 {hora_br}\n"
        f"💈 {servico}"
    )

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

    msg_barbeiro = (
        f"❌ Agendamento cancelado!\n\n"
        f"👤 Cliente: {cliente_nome}\n"
        f"📅 Data: {data_br}\n"
        f"⏰ Horário: {hora_br}"
    )
    send_text(barbeiro_phone, msg_barbeiro)


def _send_and_record(appointment_id: str, notif_type: str, phone: str, text: str) -> None:
    db = get_db()
    # Check if already sent
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
