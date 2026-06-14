from flask import Blueprint, jsonify, request
from app.utils.auth import require_auth, require_permission
from app.models.database import get_db
from app.services.ai_agent import reset_session, clear_thread
from app.services.whatsapp import send_text

bp = Blueprint("sessions", __name__, url_prefix="/api/sessions")


@bp.route("", methods=["GET"])
@require_auth
def list_sessions():
    """List all conversation sessions with mode, handoff info and last activity."""
    db = get_db()
    query = (
        db.table("conversation_sessions")
        .select("phone_whatsapp, mode, handoff_reason, handoff_at, last_activity, customers(name)")
        .order("last_activity", desc=True)
    )

    search = (request.args.get("search") or "").strip()
    if search:
        query = query.ilike("phone_whatsapp", f"%{search}%")

    result = query.execute()
    rows = []
    for s in (result.data or []):
        customer = s.pop("customers", None)
        rows.append({
            **s,
            "customer_name": customer["name"] if customer else None,
        })
    return jsonify(rows)


@bp.route("/<phone>/mode", methods=["PUT"])
@require_permission("manage_sessions")
def update_mode(phone: str):
    """Toggle a contact between 'ai' and 'human' mode."""
    data = request.get_json() or {}
    mode = data.get("mode")
    if mode not in ("ai", "human"):
        return jsonify({"error": "mode deve ser 'ai' ou 'human'"}), 400

    db = get_db()
    result = db.table("conversation_sessions").select("id").eq("phone_whatsapp", phone).execute()
    if not result.data:
        return jsonify({"error": "Sessão não encontrada"}), 404

    update = {"mode": mode, "last_activity": "now()"}
    if mode == "ai":
        update.update({"handoff_reason": None, "handoff_at": None})
        clear_thread(phone)

    db.table("conversation_sessions").update(update).eq("phone_whatsapp", phone).execute()
    return jsonify({"status": "ok", "phone": phone, "mode": mode})


@bp.route("/<phone>", methods=["DELETE"])
@require_permission("manage_sessions")
def delete_session(phone: str):
    """Reset a conversation thread (clears LangGraph checkpoints + resets mode to ai)."""
    reset_session(phone)
    return jsonify({"status": "reset", "phone": phone})


@bp.route("/<phone>/message", methods=["POST"])
@require_permission("manage_sessions")
def send_operator_message(phone: str):
    """Send a WhatsApp message on behalf of a human operator."""
    data = request.get_json() or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Campo 'text' é obrigatório"}), 400

    send_text(phone, text)
    return jsonify({"status": "sent", "phone": phone})
