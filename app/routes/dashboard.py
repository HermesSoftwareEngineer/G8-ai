from datetime import timezone
from flask import Blueprint, jsonify
from app.models.database import get_db
from app.utils.auth import require_auth
from app.utils.datetime_utils import now_fortaleza

bp_dashboard = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


@bp_dashboard.route("/summary", methods=["GET"])
@require_auth
def summary():
    db = get_db()
    now = now_fortaleza()

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
    today_end   = now.replace(hour=23, minute=59, second=59, microsecond=0).astimezone(timezone.utc).isoformat()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()

    # Agendamentos de hoje
    today_appts = (
        db.table("appointments")
        .select("id, status")
        .gte("start_datetime", today_start)
        .lte("start_datetime", today_end)
        .execute()
        .data or []
    )

    # Agendamentos do mês
    month_appts = (
        db.table("appointments")
        .select("id, status")
        .gte("start_datetime", month_start)
        .execute()
        .data or []
    )

    # Totais
    total_customers = db.table("customers").select("id", count="exact").eq("is_active", True).execute()
    total_barbers   = db.table("barbers").select("id", count="exact").eq("is_active", True).execute()

    def count_by_status(appts, status):
        return sum(1 for a in appts if a["status"] == status)

    return jsonify({
        "today": {
            "total":     len(today_appts),
            "confirmed": count_by_status(today_appts, "confirmed"),
            "completed": count_by_status(today_appts, "completed"),
            "cancelled": count_by_status(today_appts, "cancelled"),
            "pending":   count_by_status(today_appts, "pending"),
        },
        "month": {
            "total":     len(month_appts),
            "completed": count_by_status(month_appts, "completed"),
            "cancelled": count_by_status(month_appts, "cancelled"),
        },
        "totals": {
            "customers": total_customers.count or 0,
            "barbers":   total_barbers.count or 0,
        },
    })
