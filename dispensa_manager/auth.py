import bcrypt
from functools import wraps
from flask import request, jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt
from database import get_db


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def check_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        claims = get_jwt()
        if not claims.get("is_admin"):
            return jsonify({"error": "Accesso riservato agli amministratori"}), 403
        return fn(*args, **kwargs)
    return wrapper


def verify_cf_token(f):
    """Middleware opzionale: valida x-jarvis-token se cloudflare_token è configurato."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        conn = get_db()
        try:
            row = conn.execute("SELECT value FROM app_settings WHERE key='cloudflare_token'").fetchone()
            expected = row["value"] if row else ""
        finally:
            conn.close()
        if expected:
            received = request.headers.get("x-jarvis-token", "")
            if received != expected:
                return jsonify({"error": "Token non valido"}), 401
        return f(*args, **kwargs)
    return wrapper
