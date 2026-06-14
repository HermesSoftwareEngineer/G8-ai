from flask import Blueprint, request, jsonify
from app.models.database import get_db, db_insert, db_delete
from app.utils.auth import require_auth, require_permission

bp = Blueprint("schedules", __name__, url_prefix="/api/schedules")


@bp.route("/<barber_id>", methods=["GET"])
@require_auth
def get_schedule(barber_id):
    db = get_db()
    schedules = (
        db.table("schedules")
        .select("*")
        .eq("barber_id", barber_id)
        .order("day_of_week")
        .execute()
        .data or []
    )
    exceptions = (
        db.table("schedule_exceptions")
        .select("*")
        .eq("barber_id", barber_id)
        .order("date")
        .execute()
        .data or []
    )
    return jsonify({"schedules": schedules, "exceptions": exceptions})


@bp.route("/<barber_id>", methods=["PUT"])
@require_permission("manage_schedules")
def update_schedule(barber_id):
    """Replace the entire weekly schedule for a barber."""
    body = request.get_json() or {}
    slots = body.get("schedules", [])

    db = get_db()
    # Delete existing
    db.table("schedules").delete().eq("barber_id", barber_id).execute()

    created = []
    for slot in slots:
        required = ["day_of_week", "start_time", "end_time"]
        if not all(slot.get(f) is not None for f in required):
            continue
        row = db_insert("schedules", {
            "barber_id": barber_id,
            "day_of_week": slot["day_of_week"],
            "start_time": slot["start_time"],
            "end_time": slot["end_time"],
            "is_active": slot.get("is_active", True),
        })
        created.append(row)

    return jsonify({"schedules": created})


@bp.route("/<barber_id>/exceptions", methods=["POST"])
@require_permission("manage_schedules")
def create_exception(barber_id):
    body = request.get_json() or {}
    required = ["date", "type"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({"error": f"Campos obrigatórios: {missing}"}), 400

    exc_type = body["type"]
    if exc_type not in ("block", "extra"):
        return jsonify({"error": "type deve ser 'block' ou 'extra'"}), 400

    exc = db_insert("schedule_exceptions", {
        "barber_id": barber_id,
        "date": body["date"],
        "start_time": body.get("start_time"),
        "end_time": body.get("end_time"),
        "reason": body.get("reason"),
        "type": exc_type,
    })
    return jsonify(exc), 201


@bp.route("/<barber_id>/exceptions/<exception_id>", methods=["DELETE"])
@require_permission("manage_schedules")
def delete_exception(barber_id, exception_id):
    db = get_db()
    existing = (
        db.table("schedule_exceptions")
        .select("id")
        .eq("id", exception_id)
        .eq("barber_id", barber_id)
        .execute()
    )
    if not existing.data:
        return jsonify({"error": "Exceção não encontrada"}), 404
    db_delete("schedule_exceptions", exception_id)
    return jsonify({"message": "Exceção removida"})
