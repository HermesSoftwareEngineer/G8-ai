import logging
from datetime import timezone, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from app.utils.datetime_utils import now_fortaleza

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def check_reminders() -> None:
    """Find appointments starting in 45–75 min and send reminders if not already sent."""
    from app.models.database import get_db
    from app.services.notifications import send_reminder

    db = get_db()
    now_utc = now_fortaleza().astimezone(timezone.utc)
    window_start = (now_utc + timedelta(minutes=45)).isoformat()
    window_end = (now_utc + timedelta(minutes=75)).isoformat()

    logger.debug("Verificando lembretes entre %s e %s", window_start, window_end)

    # Appointments in the window with status confirmed or pending
    appointments = (
        db.table("appointments")
        .select("id")
        .in_("status", ["confirmed", "pending"])
        .gte("start_datetime", window_start)
        .lte("start_datetime", window_end)
        .execute()
        .data or []
    )

    for appt in appointments:
        appt_id = appt["id"]
        # Check if reminder was already sent
        existing = (
            db.table("appointment_notifications")
            .select("status")
            .eq("appointment_id", appt_id)
            .eq("type", "reminder_1h")
            .execute()
            .data or []
        )
        if existing and existing[0]["status"] == "sent":
            continue
        logger.info("Enviando lembrete para agendamento %s", appt_id)
        send_reminder(appt_id)


def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(timezone="America/Fortaleza")
    _scheduler.add_job(check_reminders, "interval", minutes=15, id="reminder_job")
    _scheduler.start()
    logger.info("APScheduler iniciado — verificando lembretes a cada 15 minutos")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
        logger.info("APScheduler encerrado")
