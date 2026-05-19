import bcrypt
import logging
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt
from database import get_db

logger = logging.getLogger(__name__)

BAN_WINDOW_MINUTES = 15
MAX_ATTEMPTS = 3


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def check_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def get_client_ip() -> str:
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.remote_addr or "0.0.0.0"


def is_ip_banned(conn, ip: str) -> bool:
    row = conn.execute("SELECT ip FROM ip_bans WHERE ip=?", (ip,)).fetchone()
    return row is not None


def record_attempt(conn, ip: str, username: str, success: bool):
    cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    with conn:
        conn.execute(
            "INSERT INTO login_attempts (ip, username, success) VALUES (?, ?, ?)",
            (ip, username, int(success)),
        )
        conn.execute("DELETE FROM login_attempts WHERE attempted_at < ?", (cutoff,))
    if not success:
        _maybe_ban(conn, ip)


def _maybe_ban(conn, ip: str):
    window_start = (datetime.utcnow() - timedelta(minutes=BAN_WINDOW_MINUTES)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) as n FROM login_attempts "
        "WHERE ip=? AND success=0 AND attempted_at>=?",
        (ip, window_start),
    ).fetchone()
    if row["n"] >= MAX_ATTEMPTS:
        with conn:
            conn.execute("INSERT OR IGNORE INTO ip_bans (ip) VALUES (?)", (ip,))
        logger.warning("IP bannato dopo %d tentativi falliti: %s", MAX_ATTEMPTS, ip)


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        claims = get_jwt()
        if not claims.get("is_admin"):
            return jsonify({"error": "Accesso riservato agli amministratori"}), 403
        return fn(*args, **kwargs)
    return wrapper
