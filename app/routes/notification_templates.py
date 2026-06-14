from flask import Blueprint, request, jsonify
from app.models.database import get_db
from app.utils.auth import require_auth, require_permission

bp = Blueprint("notification_templates", __name__, url_prefix="/api/notification-templates")


@bp.route("", methods=["GET"])
@require_auth
def list_templates():
    db = get_db()
    rows = db.table("notification_templates").select("template_key, subject, body").execute().data or []
    return jsonify({r["template_key"]: {"subject": r["subject"], "body": r["body"]} for r in rows})


@bp.route("", methods=["PUT"])
@require_permission("edit_ai_config")
def update_templates():
    body = request.get_json() or {}
    if not body:
        return jsonify({"error": "Body vazio"}), 400

    db = get_db()
    for template_key, data in body.items():
        if not isinstance(data, dict) or "body" not in data:
            continue
        db.table("notification_templates").upsert({
            "template_key": template_key,
            "subject": data.get("subject", template_key),
            "body": data["body"],
        }, on_conflict="template_key").execute()

    rows = db.table("notification_templates").select("template_key, subject, body").execute().data or []
    return jsonify({r["template_key"]: {"subject": r["subject"], "body": r["body"]} for r in rows})
