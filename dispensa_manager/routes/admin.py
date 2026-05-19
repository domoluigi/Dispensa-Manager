from flask import Blueprint, request, jsonify
from database import get_db, set_setting
from auth import admin_required, hash_password

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


@bp.get("/users")
@admin_required
def list_users():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, username, is_admin, is_active, created_at, last_login FROM users ORDER BY id"
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@bp.post("/users")
@admin_required
def create_user():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    is_admin = bool(data.get("is_admin", False))

    if not username or len(password) < 6:
        return jsonify({"error": "Username richiesto e password di almeno 6 caratteri"}), 400

    conn = get_db()
    try:
        existing = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if existing:
            return jsonify({"error": "Username già in uso"}), 409

        with conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
                (username, hash_password(password), int(is_admin)),
            )
        return jsonify({"id": cur.lastrowid, "username": username, "is_admin": is_admin}), 201
    finally:
        conn.close()


@bp.patch("/users/<int:user_id>")
@admin_required
def update_user(user_id):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    try:
        user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            return jsonify({"error": "Utente non trovato"}), 404

        fields = {}
        if "is_admin" in data:
            fields["is_admin"] = int(bool(data["is_admin"]))
        if "is_active" in data:
            fields["is_active"] = int(bool(data["is_active"]))
        if "password" in data:
            if len(data["password"]) < 6:
                return jsonify({"error": "Password di almeno 6 caratteri"}), 400
            fields["password_hash"] = hash_password(data["password"])

        if not fields:
            return jsonify({"error": "Nessun campo da aggiornare"}), 400

        set_clause = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [user_id]
        with conn:
            conn.execute(f"UPDATE users SET {set_clause} WHERE id=?", values)

        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.delete("/users/<int:user_id>")
@admin_required
def delete_user(user_id):
    from flask_jwt_extended import get_jwt_identity
    identity = get_jwt_identity()
    if str(user_id) == str(identity):
        return jsonify({"error": "Non puoi eliminare te stesso"}), 400

    conn = get_db()
    try:
        with conn:
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.get("/settings")
@admin_required
def get_all_settings():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT key, value, description, updated_at FROM app_settings WHERE key != 'schema_version' ORDER BY key"
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@bp.patch("/settings")
@admin_required
def update_settings():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "JSON object richiesto"}), 400

    ALLOWED_KEYS = {
        "giorni_alert_scadenza", "soglia_scorte_minime",
        "telegram_token", "telegram_chat_id",
        "cloudflare_url", "cloudflare_token",
    }
    invalid = set(data.keys()) - ALLOWED_KEYS
    if invalid:
        return jsonify({"error": f"Chiavi non ammesse: {invalid}"}), 400

    conn = get_db()
    try:
        with conn:
            for key, value in data.items():
                set_setting(conn, key, str(value))
        return jsonify({"ok": True, "updated": list(data.keys())})
    finally:
        conn.close()
