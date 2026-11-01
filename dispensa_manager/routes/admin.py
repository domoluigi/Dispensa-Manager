import base64
import binascii
import glob
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import get_jwt_identity
from database import get_db, set_setting, get_api_key, regenerate_api_key, BACKUPS_DIR, IMAGES_DIR
from auth import admin_required, hash_password

logger = logging.getLogger(__name__)

bp = Blueprint("admin", __name__, url_prefix="/api/admin")

# Chiavi gestite via UI HA addon (NON editabili da admin panel)
HA_MANAGED_KEYS = ("telegram_token", "telegram_chat_id", "cloudflare_url")
# Chiavi interne (non esposte mai)
INTERNAL_KEYS = ("schema_version", "jwt_secret_key", "api_key")


def _altri_admin_attivi(conn, escluso_id) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM users WHERE is_admin=1 AND is_active=1 AND id!=?", (escluso_id,)
    ).fetchone()["n"]


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

        toglie_admin = bool(user["is_admin"] and user["is_active"]) and (
            fields.get("is_admin", 1) == 0 or fields.get("is_active", 1) == 0)
        if toglie_admin and _altri_admin_attivi(conn, user_id) == 0:
            return jsonify({"error": "Deve restare almeno un amministratore attivo"}), 400

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
        user = conn.execute("SELECT is_admin, is_active FROM users WHERE id=?", (user_id,)).fetchone()
        if user and user["is_admin"] and user["is_active"] and _altri_admin_attivi(conn, user_id) == 0:
            return jsonify({"error": "Deve restare almeno un amministratore attivo"}), 400
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
        "ban_durata_minuti",
    }
    invalid = set(data.keys()) - ALLOWED_KEYS
    if invalid:
        return jsonify({"error": f"Chiavi non ammesse: {invalid}"}), 400
    if "ban_durata_minuti" in data:
        try:
            if not 0 <= int(data["ban_durata_minuti"]) <= 525600:
                raise ValueError
        except (ValueError, TypeError):
            return jsonify({"error": "ban_durata_minuti: intero da 0 (permanente) a 525600"}), 400

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
        ora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with conn:   # i ban scaduti non si mostrano e si tolgono
            conn.execute("DELETE FROM ip_bans WHERE scade_il IS NOT NULL AND scade_il <= ?", (ora,))
        rows = conn.execute("""
            SELECT b.ip, b.banned_at, b.reason, b.scade_il,
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
    scade = None   # un ban manuale e' permanente, salvo "minuti" nella richiesta
    if data.get("minuti") not in (None, "", 0):
        try:
            minuti = int(data["minuti"])
            if not 1 <= minuti <= 525600:
                raise ValueError
        except (ValueError, TypeError):
            return jsonify({"error": "minuti: intero da 1 a 525600"}), 400
        scade = (datetime.now(timezone.utc) + timedelta(minutes=minuti)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO ip_bans (ip, reason, scade_il) VALUES (?, ?, ?)",
                (ip, reason, scade),
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

# Immagini prodotto (/dispensa-images/<id>.<ext>): salvate nel JSON in base64 e ripristinate con i dati
RE_IMMAGINE = re.compile(r"^\d+\.(jpg|png|webp)$")
MAX_IMMAGINE_BYTES = 5 * 1024 * 1024
_MAGIC = {"jpg": (b"\xff\xd8\xff",), "png": (b"\x89PNG\r\n\x1a\n",), "webp": (b"RIFF",)}


def _immagini_per_backup(prodotti) -> dict:
    """{nome_file: base64} delle immagini referenziate dai prodotti e presenti su disco."""
    out = {}
    for p in prodotti:
        url = p.get("immagine_url") or ""
        if not url.startswith("/dispensa-images/"):
            continue
        nome = url[len("/dispensa-images/"):]
        if nome in out or not RE_IMMAGINE.match(nome):
            continue
        try:
            with open(os.path.join(IMAGES_DIR, nome), "rb") as f:
                out[nome] = base64.b64encode(f.read()).decode("ascii")
        except OSError:
            logger.warning("Immagine %s referenziata ma assente su disco: non inclusa nel backup", nome)
    return out


def _ripristina_immagini(immagini) -> dict:
    """Scrive su disco le immagini del backup. Controlla nome, firma del file e dimensione:
    il contenuto arriva da un file caricato. Ritorna {"scritte": n, "scartate": n}."""
    esito = {"scritte": 0, "scartate": 0}
    if not isinstance(immagini, dict) or not immagini:
        return esito
    os.makedirs(IMAGES_DIR, exist_ok=True)
    for nome, b64 in immagini.items():
        ok = False
        if isinstance(nome, str) and isinstance(b64, str) and RE_IMMAGINE.match(nome):
            try:
                dati = base64.b64decode(b64, validate=True)
            except (binascii.Error, ValueError):
                dati = b""
            estensione = nome.rsplit(".", 1)[1]
            if 0 < len(dati) <= MAX_IMMAGINE_BYTES and dati.startswith(_MAGIC[estensione]):
                percorso = os.path.join(IMAGES_DIR, nome)
                try:
                    with open(percorso + ".tmp", "wb") as f:
                        f.write(dati)
                    os.replace(percorso + ".tmp", percorso)
                    ok = True
                except OSError as e:
                    logger.warning("Immagine %s non scritta: %s", nome, e)
        esito["scritte" if ok else "scartate"] += 1
    return esito


def _build_backup() -> dict:
    """Costruisce dizionario con TUTTO il contenuto utile del DB (no password hash, no api_key)."""
    conn = get_db()
    try:
        prodotti = [dict(r) for r in conn.execute("SELECT * FROM prodotti ORDER BY id").fetchall()]
        immagini = _immagini_per_backup(prodotti)
        backup = {
            "_meta": {
                "version": "dispensa-manager-backup-v1",
                "created_at": datetime.utcnow().isoformat() + "Z",
                "schema_version": int(conn.execute("SELECT value FROM app_settings WHERE key='schema_version'").fetchone()["value"]),
                "immagini": len(immagini),
            },
            "prodotti": prodotti,
            "immagini": immagini,
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
                colonne = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
                rows = backup.get(table, [])
                counts[table] = len(rows)
                for row in rows:
                    if not row:
                        continue
                    keys = [k for k in row.keys() if k in colonne]   # i nomi colonna arrivano dal file caricato
                    if not keys:
                        continue
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
    finally:
        conn.close()

    # le immagini si scrivono dopo il commit dei dati: se il ripristino fallisce non si tocca il disco
    esito = _ripristina_immagini(backup.get("immagini"))
    if esito["scritte"] or esito["scartate"]:
        counts["immagini"] = esito["scritte"]
        if esito["scartate"]:
            counts["immagini scartate"] = esito["scartate"]
    return counts


BACKUP_AUTO_COPIE = 4


def scrivi_backup_auto() -> str:
    """Scrive auto_backup.json (l'ultimo) e una copia datata; tiene le ultime BACKUP_AUTO_COPIE copie,
    cosi' un dato rovinato non sovrascrive subito l'unico backup buono."""
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    contenuto = json.dumps(_build_backup(), indent=2, default=str, ensure_ascii=False)
    auto_path = os.path.join(BACKUPS_DIR, "auto_backup.json")
    copia = os.path.join(BACKUPS_DIR, f"auto_backup_{datetime.now().strftime('%Y%m%d')}.json")
    for percorso in (auto_path, copia):
        with open(percorso, "w", encoding="utf-8") as f:
            f.write(contenuto)
    for vecchia in sorted(glob.glob(os.path.join(BACKUPS_DIR, "auto_backup_*.json")))[:-BACKUP_AUTO_COPIE]:
        try:
            os.remove(vecchia)
        except OSError as e:
            logger.warning("Impossibile rimuovere il backup vecchio %s: %s", vecchia, e)
    return auto_path


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
        auto_path = scrivi_backup_auto()
        return jsonify({"ok": True, "path": auto_path, "size_bytes": os.path.getsize(auto_path)})
    except Exception as e:
        logger.error("Errore backup manuale auto: %s", e)
        return jsonify({"error": str(e)}), 500
