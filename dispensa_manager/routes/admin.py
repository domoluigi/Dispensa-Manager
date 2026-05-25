import json
import logging
import os
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import get_jwt_identity
from database import get_db, set_setting, get_api_key, regenerate_api_key, BACKUPS_DIR
from auth import admin_required, hash_password

logger = logging.getLogger(__name__)

bp = Blueprint("admin", __name__, url_prefix="/api/admin")

# Chiavi gestite via UI HA addon (NON editabili da admin panel)
HA_MANAGED_KEYS = ("telegram_token", "telegram_chat_id", "cloudflare_url")
# Chiavi interne (non esposte mai)
INTERNAL_KEYS = ("schema_version", "jwt_secret_key", "api_key")


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


# ── Impostazioni ───────────────────────────────────────────────────────────────────────────

@bp.get("/settings")
@admin_required
def get_all_settings():
    excluded = INTERNAL_KEYS + HA_MANAGED_KEYS
    placeholders = ",".join("?" * len(excluded))
    conn = get_db()
    try:
        rows = conn.execute(
            f"SELECT key, value, description, updated_at FROM app_settings "
            f"WHERE key NOT IN ({placeholders}) ORDER BY key",
            excluded,
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
        "max_login_attempts", "ban_window_minutes",
        "notif_telegram_acquisto", "notif_telegram_modifica", "notif_telegram_eliminazione",
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


# ── API Key ───────────────────────────────────────────────────────────────────

@bp.get("/api-key")
@admin_required
def get_api_key_endpoint():
    return jsonify({"api_key": get_api_key()})


@bp.post("/api-key/regenerate")
@admin_required
def regenerate_api_key_endpoint():
    new_key = regenerate_api_key()
    return jsonify({"api_key": new_key, "ok": True})


# ── IP Ban ─────────────────────────────────────────────────────────────────────────────

@bp.get("/ip-bans")
@admin_required
def list_ip_bans():
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT b.ip, b.banned_at, b.reason,
                   (SELECT COUNT(*) FROM login_attempts WHERE ip=b.ip AND success=0) AS failed_attempts,
                   (SELECT MAX(attempted_at) FROM login_attempts WHERE ip=b.ip AND success=0) AS last_attempt
            FROM ip_bans b ORDER BY b.banned_at DESC
        """).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@bp.post("/ip-bans")
@admin_required
def ban_ip():
    data = request.get_json(silent=True) or {}
    ip = (data.get("ip") or "").strip()
    reason = (data.get("reason") or "Ban manuale da admin").strip()
    if not ip:
        return jsonify({"error": "IP richiesto"}), 400
    conn = get_db()
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO ip_bans (ip, reason) VALUES (?, ?)",
                (ip, reason),
            )
        return jsonify({"ok": True}), 201
    finally:
        conn.close()


@bp.delete("/ip-bans/<path:ip>")
@admin_required
def unban_ip(ip):
    conn = get_db()
    try:
        with conn:
            conn.execute("DELETE FROM ip_bans WHERE ip=?", (ip,))
            conn.execute("DELETE FROM login_attempts WHERE ip=?", (ip,))
        return jsonify({"ok": True})
    finally:
        conn.close()


# ── Backup / Restore ──────────────────────────────────────────────────────────

def _build_backup() -> dict:
    """Costruisce dizionario con TUTTO il contenuto utile del DB (no password hash, no api_key)."""
    conn = get_db()
    try:
        backup = {
            "_meta": {
                "version": "dispensa-manager-backup-v1",
                "created_at": datetime.utcnow().isoformat() + "Z",
                "schema_version": int(conn.execute("SELECT value FROM app_settings WHERE key='schema_version'").fetchone()["value"]),
            },
            "prodotti": [dict(r) for r in conn.execute("SELECT * FROM prodotti ORDER BY id").fetchall()],
            "lista_spesa": [dict(r) for r in conn.execute("SELECT * FROM lista_spesa ORDER BY id").fetchall()],
            "storico_movimenti": [dict(r) for r in conn.execute("SELECT * FROM storico_movimenti ORDER BY id").fetchall()],
            "barcode_cache": [dict(r) for r in conn.execute("SELECT * FROM barcode_cache ORDER BY ean").fetchall()],
            "app_settings": [
                dict(r) for r in conn.execute(
                    "SELECT key, value, description FROM app_settings WHERE key NOT IN ('jwt_secret_key', 'api_key', 'schema_version')"
                ).fetchall()
            ],
            "users": [
                dict(r) for r in conn.execute(
                    "SELECT id, username, is_admin, is_active, created_at, last_login FROM users"
                ).fetchall()
            ],
        }
        return backup
    finally:
        conn.close()


def _restore_backup(backup: dict) -> dict:
    """Sovrascrive le tabelle con i dati del backup. ATTENZIONE: distruttivo!
    Non tocca: users password_hash, jwt_secret_key, api_key."""
    if backup.get("_meta", {}).get("version") != "dispensa-manager-backup-v1":
        raise ValueError("Formato backup non valido o versione non supportata")

    conn = get_db()
    counts = {}
    try:
        with conn:
            # Backup tabelle dati (NON utenti, NON segreti)
            for table in ("prodotti", "lista_spesa", "storico_movimenti", "barcode_cache"):
                conn.execute(f"DELETE FROM {table}")
                rows = backup.get(table, [])
                counts[table] = len(rows)
                for row in rows:
                    if not row:
                        continue
                    keys = list(row.keys())
                    placeholders = ",".join("?" * len(keys))
                    cols = ",".join(keys)
                    conn.execute(
                        f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
                        [row[k] for k in keys],
                    )
            # Restore settings (no internal)
            settings = backup.get("app_settings", [])
            for s in settings:
                if s.get("key") in ("schema_version", "jwt_secret_key", "api_key"):
                    continue
                set_setting(conn, s["key"], s["value"])
            counts["app_settings"] = len(settings)
        return counts
    finally:
        conn.close()


@bp.get("/backup")
@admin_required
def download_backup():
    """Ritorna backup JSON come file scaricabile."""
    backup = _build_backup()
    from io import BytesIO
    buf = BytesIO()
    buf.write(json.dumps(backup, indent=2, default=str, ensure_ascii=False).encode("utf-8"))
    buf.seek(0)
    filename = f"dispensa_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    return send_file(buf, mimetype="application/json", as_attachment=True, download_name=filename)


@bp.post("/restore")
@admin_required
def upload_restore():
    """Riceve backup JSON e lo applica. Distruttivo!
    Body: {"backup": {...}, "confirm": "RIPRISTINA"}"""
    data = request.get_json(silent=True) or {}
    if data.get("confirm") != "RIPRISTINA":
        return jsonify({"error": "Conferma mancante o errata (richiesto: 'RIPRISTINA')"}), 400
    backup = data.get("backup")
    if not backup or not isinstance(backup, dict):
        return jsonify({"error": "Backup mancante o malformato"}), 400
    try:
        counts = _restore_backup(backup)
        # Trigger aggiornamento sensori HA dopo ripristino
        try:
            from routes.products import aggiorna_sensori_ha
            import threading
            threading.Thread(target=aggiorna_sensori_ha, daemon=True).start()
        except Exception:
            pass
        return jsonify({"ok": True, "ripristinati": counts})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error("Errore ripristino backup: %s", e)
        return jsonify({"error": "Errore durante il ripristino"}), 500


@bp.get("/backup/auto-status")
@admin_required
def auto_backup_status():
    """Stato del backup automatico (data ultimo, dimensione)."""
    auto_path = os.path.join(BACKUPS_DIR, "auto_backup.json")
    if not os.path.exists(auto_path):
        return jsonify({"exists": False, "path": auto_path})
    try:
        stat = os.stat(auto_path)
        return jsonify({
            "exists": True,
            "path": auto_path,
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "age_days": round((datetime.now().timestamp() - stat.st_mtime) / 86400, 1),
        })
    except Exception as e:
        return jsonify({"exists": False, "error": str(e)})


@bp.post("/backup/auto-now")
@admin_required
def trigger_auto_backup_now():
    """Forza un backup automatico immediato."""
    try:
        auto_path = os.path.join(BACKUPS_DIR, "auto_backup.json")
        os.makedirs(BACKUPS_DIR, exist_ok=True)
        backup = _build_backup()
        with open(auto_path, "w", encoding="utf-8") as f:
            json.dump(backup, f, indent=2, default=str, ensure_ascii=False)
        return jsonify({"ok": True, "path": auto_path, "size_bytes": os.path.getsize(auto_path)})
    except Exception as e:
        logger.error("Errore backup manuale auto: %s", e)
        return jsonify({"error": str(e)}), 500
