from flask import Blueprint, request, jsonify
from app.models.database import get_db, db_insert, db_update
from app.utils.auth import require_auth, require_permission

bp = Blueprint("customers", __name__, url_prefix="/api/customers")


@bp.route("", methods=["GET"])
@require_permission("view_customers")
def list_customers():
    db = get_db()
    query = db.table("customers").select("*")

    search = request.args.get("search")
    if search:
        query = query.or_(f"name.ilike.%{search}%,phone_whatsapp.ilike.%{search}%")

    active_only = request.args.get("active", "true").lower() == "true"
    if active_only:
        query = query.eq("is_active", True)

    result = query.order("name").execute()
    return jsonify(result.data or [])


@bp.route("/<customer_id>", methods=["GET"])
@require_permission("view_customers")
def get_customer(customer_id):
    db = get_db()
    result = db.table("customers").select("*").eq("id", customer_id).execute()
    if not result.data:
        return jsonify({"error": "Cliente não encontrado"}), 404

    # Fetch appointment history
    appts = (
        db.table("appointments")
        .select("id, start_datetime, status, barbers(name), services(name)")
        .eq("customer_id", customer_id)
        .order("start_datetime", desc=True)
        .limit(10)
        .execute()
        .data or []
    )

    customer = result.data[0]
    customer["recent_appointments"] = appts
    return jsonify(customer)


@bp.route("", methods=["POST"])
@require_permission("manage_customers")
def create_customer():
    body = request.get_json() or {}
    required = ["name", "phone_whatsapp"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({"error": f"Campos obrigatórios: {missing}"}), 400

    customer = db_insert("customers", {
        "name": body["name"],
        "phone_whatsapp": body["phone_whatsapp"],
        "email": body.get("email"),
        "birth_date": body.get("birth_date"),
        "gender": body.get("gender"),
        "how_found_us": body.get("how_found_us"),
        "notes": body.get("notes"),
    })
    return jsonify(customer), 201


@bp.route("/<customer_id>", methods=["PUT"])
@require_permission("manage_customers")
def update_customer(customer_id):
    body = request.get_json() or {}
    allowed = ("name", "phone_whatsapp", "email", "birth_date", "gender", "avatar_url", "how_found_us", "notes", "is_active")
    fields = {k: v for k, v in body.items() if k in allowed}
    updated = db_update("customers", customer_id, fields)
    return jsonify(updated)
