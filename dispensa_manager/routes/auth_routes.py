from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity,
    get_jwt,
)
from datetime import datetime
from database import get_db
from auth import check_password

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "Username e password richiesti"}), 400

    conn = get_db()
    try:
        user = conn.execute(
            "SELECT * FROM users WHERE username=? AND is_active=1", (username,)
        ).fetchone()

        if not user or not check_password(password, user["password_hash"]):
            return jsonify({"error": "Credenziali non valide"}), 401

        additional_claims = {"is_admin": bool(user["is_admin"])}
        access_token = create_access_token(identity=str(user["id"]), additional_claims=additional_claims)
        refresh_token = create_refresh_token(identity=str(user["id"]), additional_claims=additional_claims)

        with conn:
            conn.execute(
                "UPDATE users SET last_login=? WHERE id=?",
                (datetime.utcnow().isoformat(), user["id"]),
            )

        return jsonify({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "username": user["username"],
            "is_admin": bool(user["is_admin"]),
        })
    finally:
        conn.close()


@bp.post("/refresh")
@jwt_required(refresh=True)
def refresh():
    identity = get_jwt_identity()
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT is_admin, is_active FROM users WHERE id=?", (identity,)
        ).fetchone()
        if not user or not user["is_active"]:
            return jsonify({"error": "Utente non trovato o disabilitato"}), 401
        additional_claims = {"is_admin": bool(user["is_admin"])}
        new_token = create_access_token(identity=identity, additional_claims=additional_claims)
        return jsonify({"access_token": new_token})
    finally:
        conn.close()


@bp.get("/me")
@jwt_required()
def me():
    identity = get_jwt_identity()
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT id, username, is_admin, is_active, created_at, last_login FROM users WHERE id=?",
            (identity,),
        ).fetchone()
        if not user:
            return jsonify({"error": "Utente non trovato"}), 404
        return jsonify(dict(user))
    finally:
        conn.close()
