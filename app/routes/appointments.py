from flask import Blueprint, request, jsonify
from app.models.database import get_db, db_insert, db_update, db_delete
from app.utils.auth import require_auth, require_permission
from app.services.notifications import send_confirmation, send_cancellation

bp = Blueprint("appointments", __name__, url_prefix="/api/appointments")


@bp.route("", methods=["GET"])
@require_auth
def list_appointments():
    db = get_db()
    query = db.table("appointments").select(
        "*, customers(name, phone_whatsapp), barbers(name), services(name, price)"
    )

    barber_id = request.args.get("barber_id")
    status = request.args.get("status")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    if barber_id:
        query = query.eq("barber_id", barber_id)
    if status:
        query = query.eq("status", status)
    if date_from:
        query = query.gte("start_datetime", date_from)
    if date_to:
        query = query.lte("start_datetime", date_to)

    result = query.order("start_datetime").execute()
    return jsonify(result.data or [])


@bp.route("/<appointment_id>", methods=["GET"])
@require_auth
def get_appointment(appointment_id):
    db = get_db()
    result = (
        db.table("appointments")
        .select("*, customers(*), barbers(name, phone_whatsapp), services(*)")
        .eq("id", appointment_id)
        .execute()
    )
    if not result.data:
        return jsonify({"error": "Agendamento não encontrado"}), 404
    return jsonify(result.data[0])


@bp.route("", methods=["POST"])
@require_permission("manage_appointments")
def create_appointment():
    body = request.get_json() or {}
    required = ["customer_id", "barber_id", "service_id", "start_datetime", "end_datetime"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({"error": f"Campos obrigatórios: {missing}"}), 400

    appt = db_insert("appointments", {
        "customer_id": body["customer_id"],
        "barber_id": body["barber_id"],
        "service_id": body["service_id"],
        "start_datetime": body["start_datetime"],
        "end_datetime": body["end_datetime"],
        "status": body.get("status", "confirmed"),
        "notes": body.get("notes"),
    })

    if body.get("send_notification", True):
        try:
            send_confirmation(appt["id"])
        except Exception:
            pass

    return jsonify(appt), 201


@bp.route("/<appointment_id>/status", methods=["PATCH"])
@require_permission("manage_appointments")
def update_status(appointment_id):
    body = request.get_json() or {}
    new_status = body.get("status")
    valid = {"pending", "confirmed", "cancelled", "completed", "no_show"}
    if new_status not in valid:
        return jsonify({"error": f"Status inválido. Opções: {valid}"}), 400

    db = get_db()
    existing = db.table("appointments").select("id, status").eq("id", appointment_id).execute()
    if not existing.data:
        return jsonify({"error": "Agendamento não encontrado"}), 404

    updated = db_update("appointments", appointment_id, {"status": new_status})

    if new_status == "cancelled":
        try:
            send_cancellation(appointment_id)
        except Exception:
            pass

    return jsonify(updated)


@bp.route("/<appointment_id>", methods=["DELETE"])
@require_permission("manage_appointments")
def delete_appointment(appointment_id):
    db_delete("appointments", appointment_id)
    return jsonify({"message": "Agendamento removido"}), 200
