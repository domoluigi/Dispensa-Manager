import bcrypt
import ipaddress
import logging
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import request, jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt
from database import get_db, get_setting, get_api_key

logger = logging.getLogger(__name__)

DEFAULT_BAN_WINDOW_MINUTES = 15
DEFAULT_MAX_ATTEMPTS = 3


def _get_ban_window_minutes(conn) -> int:
    try:
        return int(get_setting(conn, "ban_window_minutes", str(DEFAULT_BAN_WINDOW_MINUTES)))
    except ValueError:
        return DEFAULT_BAN_WINDOW_MINUTES


def _get_max_attempts(conn) -> int:
    try:
        return int(get_setting(conn, "max_login_attempts", str(DEFAULT_MAX_ATTEMPTS)))
    except ValueError:
        return DEFAULT_MAX_ATTEMPTS


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def check_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# Rete interna degli add-on HA (hassio): da qui arrivano cloudflared e Ingress.
# Solo questi proxy possono dichiarare l'IP del client via header; un client
# in LAN sulla porta 5000 non puo' falsificare CF-Connecting-IP/X-Forwarded-For
# per aggirare il ban (v2.0.19).
TRUSTED_PROXIES = [ipaddress.ip_network("172.30.32.0/23")]


def _from_trusted_proxy(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in TRUSTED_PROXIES)


def get_client_ip() -> str:
    remote = request.remote_addr or "0.0.0.0"
    if not _from_trusted_proxy(remote):
        return remote
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return remote


def is_ip_banned(conn, ip: str) -> bool:
    row = conn.execute("SELECT ip FROM ip_bans WHERE ip=?", (ip,)).fetchone()
    return row is not None


def record_attempt(conn, ip: str, username: str, success: bool):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        conn.execute(
            "INSERT INTO login_attempts (ip, username, success) VALUES (?, ?, ?)",
            (ip, username, int(success)),
        )
        conn.execute("DELETE FROM login_attempts WHERE attempted_at < ?", (cutoff,))
    if not success:
        _maybe_ban(conn, ip)


def _maybe_ban(conn, ip: str):
    window_minutes = _get_ban_window_minutes(conn)
    max_attempts = _get_max_attempts(conn)
    window_start = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    row = conn.execute(
        "SELECT COUNT(*) as n FROM login_attempts "
        "WHERE ip=? AND success=0 AND attempted_at>=?",
        (ip, window_start),
    ).fetchone()
    if row["n"] >= max_attempts:
        with conn:
            conn.execute("INSERT OR IGNORE INTO ip_bans (ip) VALUES (?)", (ip,))
        logger.warning("IP bannato dopo %d tentativi falliti: %s", max_attempts, ip)


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        claims = get_jwt()
        if not claims.get("is_admin"):
            return jsonify({"error": "Accesso riservato agli amministratori"}), 403
        return fn(*args, **kwargs)
    return wrapper


def api_key_or_jwt(fn):
    """Decoratore che accetta autenticazione via API key (x-api-key header)
    OPPURE JWT (Authorization: Bearer ...). Usato per endpoint automation-friendly
    chiamati da HA rest_command."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        api_key_header = request.headers.get("x-api-key", "").strip()
        if api_key_header:
            stored = get_api_key()
            if stored and api_key_header == stored:
                return fn(*args, **kwargs)
            logger.warning("Tentativo API call con x-api-key non valida da %s", get_client_ip())
            return jsonify({"error": "API key non valida"}), 401
        # Fallback su JWT
        try:
            verify_jwt_in_request()
        except Exception:
            return jsonify({"error": "Autenticazione richiesta (JWT o x-api-key)"}), 401
        return fn(*args, **kwargs)
    return wrapper
