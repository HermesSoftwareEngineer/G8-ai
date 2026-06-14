from flask import Blueprint, request, jsonify
from app.models.database import get_db, db_insert, db_update, db_delete
from app.utils.auth import require_auth, require_permission

bp = Blueprint("services", __name__, url_prefix="/api/services")


@bp.route("", methods=["GET"])
@require_auth
def list_services():
    db = get_db()
    active_only = request.args.get("active", "true").lower() == "true"
    query = db.table("services").select("*")
    if active_only:
        query = query.eq("is_active", True)
    result = query.order("name").execute()
    return jsonify(result.data or [])


@bp.route("/<service_id>", methods=["GET"])
@require_auth
def get_service(service_id):
    db = get_db()
    result = db.table("services").select("*").eq("id", service_id).execute()
    if not result.data:
        return jsonify({"error": "Serviço não encontrado"}), 404
    return jsonify(result.data[0])


@bp.route("", methods=["POST"])
@require_permission("manage_services")
def create_service():
    body = request.get_json() or {}
    required = ["name", "price"]
    missing = [f for f in required if body.get(f) is None]
    if missing:
        return jsonify({"error": f"Campos obrigatórios: {missing}"}), 400

    service = db_insert("services", {
        "name": body["name"],
        "description": body.get("description"),
        "duration_minutes": body.get("duration_minutes", 30),
        "price": body["price"],
    })
    return jsonify(service), 201


@bp.route("/<service_id>", methods=["PUT"])
@require_permission("manage_services")
def update_service(service_id):
    body = request.get_json() or {}
    fields = {k: v for k, v in body.items() if k in ("name", "description", "duration_minutes", "price", "is_active")}
    updated = db_update("services", service_id, fields)
    return jsonify(updated)


@bp.route("/<service_id>", methods=["DELETE"])
@require_permission("manage_services")
def delete_service(service_id):
    db_update("services", service_id, {"is_active": False})
    return jsonify({"message": "Serviço desativado"})
