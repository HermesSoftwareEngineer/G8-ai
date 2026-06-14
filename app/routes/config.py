from flask import Blueprint, request, jsonify
from app.models.database import get_db, db_upsert
from app.utils.auth import require_auth, require_permission
from app.utils.md_reader import read_shop_info, write_shop_info, read_prompt, write_prompt

bp = Blueprint("config", __name__, url_prefix="/api/config")


# ---------------------------------------------------------------------------
# AI Config
# ---------------------------------------------------------------------------

@bp.route("/ai", methods=["GET"])
@require_auth
def get_ai_config():
    db = get_db()
    rows = db.table("ai_config").select("*").execute().data or []
    return jsonify({r["key"]: {"value": r["value"], "description": r.get("description")} for r in rows})


@bp.route("/ai", methods=["PUT"])
@require_permission("edit_ai_config")
def update_ai_config():
    body = request.get_json() or {}
    db = get_db()
    for key, value in body.items():
        db.table("ai_config").upsert({"key": key, "value": str(value)}, on_conflict="key").execute()
    rows = db.table("ai_config").select("*").execute().data or []
    return jsonify({r["key"]: r["value"] for r in rows})


# ---------------------------------------------------------------------------
# Shop Info (database)
# ---------------------------------------------------------------------------

@bp.route("/shop", methods=["GET"])
@require_auth
def get_shop_config():
    db = get_db()
    rows = db.table("shop_info").select("*").execute().data or []
    return jsonify({r["key"]: r["value"] for r in rows})


@bp.route("/shop", methods=["PUT"])
@require_permission("edit_shop_info")
def update_shop_config():
    body = request.get_json() or {}
    db = get_db()
    for key, value in body.items():
        db.table("shop_info").upsert({"key": key, "value": str(value)}, on_conflict="key").execute()
    rows = db.table("shop_info").select("*").execute().data or []
    return jsonify({r["key"]: r["value"] for r in rows})


# ---------------------------------------------------------------------------
# Shop Info (Markdown file)
# ---------------------------------------------------------------------------

@bp.route("/shop/md", methods=["GET"])
@require_auth
def get_shop_md():
    content = read_shop_info()
    return jsonify({"content": content})


@bp.route("/shop/md", methods=["PUT"])
@require_permission("edit_shop_info")
def update_shop_md():
    body = request.get_json() or {}
    content = body.get("content", "")
    if not content:
        return jsonify({"error": "Campo 'content' é obrigatório"}), 400
    write_shop_info(content)
    return jsonify({"message": "shop_info.md atualizado com sucesso"})


# ---------------------------------------------------------------------------
# AI Prompt (Markdown file)
# ---------------------------------------------------------------------------

@bp.route("/ai/prompt", methods=["GET"])
@require_auth
def get_ai_prompt():
    return jsonify({"content": read_prompt()})


@bp.route("/ai/prompt", methods=["PUT"])
@require_permission("edit_ai_config")
def update_ai_prompt():
    body = request.get_json() or {}
    content = body.get("content", "")
    if not content:
        return jsonify({"error": "Campo 'content' é obrigatório"}), 400

    # Garante que as variáveis obrigatórias ainda estão no template
    required = ["{bot_name}", "{customer_info}", "{state}"]
    missing = [v for v in required if v not in content]
    if missing:
        return jsonify({
            "error": "O prompt deve conter todas as variáveis obrigatórias",
            "missing": missing,
        }), 400

    write_prompt(content)
    return jsonify({"message": "prompt.md atualizado com sucesso"})
