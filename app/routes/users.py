from flask import Blueprint, request, jsonify, g
from app.models.database import get_db, db_insert, db_update, db_delete
from app.utils.auth import require_auth, require_permission, hash_password, verify_password, create_token

bp = Blueprint("users", __name__)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@bp.route("/api/auth/login", methods=["POST"])
def login():
    body = request.get_json() or {}
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email e senha são obrigatórios"}), 400

    db = get_db()
    result = db.table("users").select("*, roles(name)").eq("email", email).eq("is_active", True).execute()
    if not result.data:
        return jsonify({"error": "Credenciais inválidas"}), 401

    user = result.data[0]
    if not verify_password(password, user["password_hash"]):
        return jsonify({"error": "Credenciais inválidas"}), 401

    token = create_token(user["id"], user["roles"]["name"] if user.get("roles") else "")
    user.pop("password_hash", None)
    return jsonify({
        "token": token,
        "access_token": token,
        "token_type": "bearer",
        "user": user,
    })


@bp.route("/api/auth/refresh", methods=["POST"])
@require_auth
def refresh():
    """Re-issue a fresh token for the currently authenticated user."""
    user = g.current_user
    db = get_db()
    role_res = db.table("roles").select("name").eq("id", user["role_id"]).execute()
    role_name = role_res.data[0]["name"] if role_res.data else ""
    token = create_token(user["id"], role_name)
    user.pop("password_hash", None)
    return jsonify({
        "token": token,
        "access_token": token,
        "token_type": "bearer",
        "user": user,
    })


@bp.route("/api/auth/logout", methods=["POST"])
@require_auth
def logout():
    return jsonify({"message": "Logout realizado com sucesso"})


# ---------------------------------------------------------------------------
# Users CRUD
# ---------------------------------------------------------------------------

@bp.route("/api/users", methods=["GET"])
@require_permission("manage_users")
def list_users():
    db = get_db()
    result = db.table("users").select("id, name, email, phone, role_id, is_active, created_at, roles(name)").execute()
    return jsonify(result.data or [])


@bp.route("/api/users", methods=["POST"])
@require_permission("manage_users")
def create_user():
    body = request.get_json() or {}
    required = ["name", "email", "password", "role_id"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({"error": f"Campos obrigatórios: {missing}"}), 400

    user = db_insert("users", {
        "name": body["name"],
        "email": body["email"].strip().lower(),
        "phone": body.get("phone"),
        "password_hash": hash_password(body["password"]),
        "role_id": body["role_id"],
    })
    user.pop("password_hash", None)
    return jsonify(user), 201


@bp.route("/api/users/<user_id>", methods=["PUT"])
@require_permission("manage_users")
def update_user(user_id):
    body = request.get_json() or {}
    fields = {}
    for k in ("name", "email", "phone", "role_id", "is_active"):
        if k in body:
            fields[k] = body[k]
    if "password" in body:
        fields["password_hash"] = hash_password(body["password"])

    updated = db_update("users", user_id, fields)
    updated.pop("password_hash", None)
    return jsonify(updated)


@bp.route("/api/users/<user_id>", methods=["DELETE"])
@require_permission("manage_users")
def delete_user(user_id):
    if g.current_user["id"] == user_id:
        return jsonify({"error": "Você não pode excluir sua própria conta"}), 400
    db_update("users", user_id, {"is_active": False})
    return jsonify({"message": "Usuário desativado"})


# ---------------------------------------------------------------------------
# Roles & Permissions
# ---------------------------------------------------------------------------

@bp.route("/api/roles", methods=["GET"])
@require_auth
def list_roles():
    db = get_db()
    roles = db.table("roles").select("*, permissions(action)").execute()
    return jsonify(roles.data or [])


@bp.route("/api/roles/<role_id>/permissions", methods=["PUT"])
@require_permission("manage_users")
def update_role_permissions(role_id):
    body = request.get_json() or {}
    actions = body.get("actions", [])

    db = get_db()
    # Replace all permissions for this role
    db.table("permissions").delete().eq("role_id", role_id).execute()
    for action in actions:
        db.table("permissions").insert({"role_id": role_id, "action": action}).execute()

    updated = db.table("permissions").select("action").eq("role_id", role_id).execute()
    return jsonify({"role_id": role_id, "actions": [p["action"] for p in (updated.data or [])]})
