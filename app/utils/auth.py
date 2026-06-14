import logging
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import request, jsonify, g
from jose import jwt, JWTError
from werkzeug.security import generate_password_hash, check_password_hash
from app.config import Config
from app.models.database import get_db

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return check_password_hash(hashed, plain)


def create_token(user_id: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=Config.JWT_EXPIRY_HOURS)
    payload = {"sub": user_id, "role": role, "exp": expire}
    return jwt.encode(payload, Config.SECRET_KEY, algorithm=Config.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, Config.SECRET_KEY, algorithms=[Config.JWT_ALGORITHM])


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Token não informado"}), 401
        token = auth_header.split(" ", 1)[1]
        try:
            payload = decode_token(token)
        except JWTError:
            return jsonify({"error": "Token inválido ou expirado"}), 401

        db = get_db()
        user = db.table("users").select("*").eq("id", payload["sub"]).eq("is_active", True).execute()
        if not user.data:
            return jsonify({"error": "Usuário não encontrado"}), 401

        g.current_user = user.data[0]
        g.current_role = payload.get("role")
        return f(*args, **kwargs)
    return decorated


def require_permission(action: str):
    def decorator(f):
        @wraps(f)
        @require_auth
        def decorated(*args, **kwargs):
            db = get_db()
            user = g.current_user
            perms = db.table("permissions").select("action").eq("role_id", user["role_id"]).execute()
            allowed = [p["action"] for p in (perms.data or [])]
            if action not in allowed:
                return jsonify({"error": "Permissão insuficiente"}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator
