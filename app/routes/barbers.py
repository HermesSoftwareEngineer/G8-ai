from datetime import date
from flask import Blueprint, request, jsonify
from app.models.database import get_db, db_insert, db_update, db_delete
from app.utils.auth import require_auth, require_permission
from app.services.scheduler import get_available_slots

bp = Blueprint("barbers", __name__, url_prefix="/api/barbers")


@bp.route("", methods=["GET"])
@require_auth
def list_barbers():
    db = get_db()
    active_only = request.args.get("active", "true").lower() == "true"
    query = db.table("barbers").select("*, barber_services(service_id, services(name, duration_minutes, price))")
    if active_only:
        query = query.eq("is_active", True)
    result = query.order("name").execute()
    return jsonify(result.data or [])


@bp.route("/<barber_id>", methods=["GET"])
@require_auth
def get_barber(barber_id):
    db = get_db()
    result = db.table("barbers").select("*, barber_services(service_id, services(*))").eq("id", barber_id).execute()
    if not result.data:
        return jsonify({"error": "Barbeiro não encontrado"}), 404
    return jsonify(result.data[0])


@bp.route("", methods=["POST"])
@require_permission("manage_barbers")
def create_barber():
    body = request.get_json() or {}
    required = ["name", "phone_whatsapp"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({"error": f"Campos obrigatórios: {missing}"}), 400

    barber = db_insert("barbers", {
        "name": body["name"],
        "phone_whatsapp": body["phone_whatsapp"],
        "bio": body.get("bio"),
        "avatar_url": body.get("avatar_url"),
        "user_id": body.get("user_id"),
    })

    # Associate services
    service_ids = body.get("service_ids", [])
    if service_ids:
        db = get_db()
        for sid in service_ids:
            db.table("barber_services").insert({"barber_id": barber["id"], "service_id": sid}).execute()

    return jsonify(barber), 201


@bp.route("/<barber_id>", methods=["PUT"])
@require_permission("manage_barbers")
def update_barber(barber_id):
    body = request.get_json() or {}
    fields = {k: v for k, v in body.items() if k in ("name", "phone_whatsapp", "bio", "avatar_url", "is_active", "user_id")}
    updated = db_update("barbers", barber_id, fields)

    # Update service associations if provided
    service_ids = body.get("service_ids")
    if service_ids is not None:
        db = get_db()
        db.table("barber_services").delete().eq("barber_id", barber_id).execute()
        for sid in service_ids:
            db.table("barber_services").insert({"barber_id": barber_id, "service_id": sid}).execute()

    return jsonify(updated)


@bp.route("/<barber_id>", methods=["DELETE"])
@require_permission("manage_barbers")
def delete_barber(barber_id):
    db_update("barbers", barber_id, {"is_active": False})
    return jsonify({"message": "Barbeiro desativado"})


@bp.route("/<barber_id>/availability", methods=["GET"])
@require_auth
def get_availability(barber_id):
    date_str = request.args.get("date")
    service_id = request.args.get("service_id")

    if not date_str or not service_id:
        return jsonify({"error": "Parâmetros 'date' e 'service_id' são obrigatórios"}), 400

    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"error": "Formato de data inválido. Use YYYY-MM-DD"}), 400

    db = get_db()
    svc = db.table("services").select("duration_minutes").eq("id", service_id).execute()
    if not svc.data:
        return jsonify({"error": "Serviço não encontrado"}), 404

    duration = svc.data[0]["duration_minutes"]
    slots = get_available_slots(barber_id, target_date, duration)
    return jsonify({"date": date_str, "available_slots": slots})
