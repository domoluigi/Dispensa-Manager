import os
import re
import time
import logging
import threading
import json
from datetime import timedelta, datetime
from flask import Flask, jsonify, make_response, send_from_directory, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from database import APP_VERSION, get_ha_option, IMAGES_DIR, BACKUPS_DIR

WWW_DIR = os.path.join(os.path.dirname(__file__), "www")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

OPTIONS_PATH = "/data/options.json"
_JWT_SECRET_CACHE = None

# Backup automatico ogni 7 giorni (controllato ogni ora, sovrascrive auto_backup.json)
AUTO_BACKUP_INTERVAL_DAYS = 7
AUTO_BACKUP_CHECK_INTERVAL_SECONDS = 3600  # 1h


def _load_jwt_secret() -> str:
    global _JWT_SECRET_CACHE
    if _JWT_SECRET_CACHE:
        return _JWT_SECRET_CACHE
    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        try:
            with open(OPTIONS_PATH) as f:
                opts = json.load(f)
            secret = opts.get("jwt_secret_key", "")
        except Exception:
            pass
    if not secret:
        secret = _get_or_create_secret_in_db()
    _JWT_SECRET_CACHE = secret
    return secret


def _get_or_create_secret_in_db() -> str:
    import sqlite3, os as _os
    db_path = _os.environ.get("DB_PATH", "/config/dispensa.db")
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, description TEXT, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        row = conn.execute("SELECT value FROM app_settings WHERE key='jwt_secret_key'").fetchone()
        if row:
            conn.close()
            return row[0]
        secret = _os.urandom(32).hex()
        conn.execute("INSERT INTO app_settings (key, value, description) VALUES (?, ?, ?)",
                     ("jwt_secret_key", secret, "Chiave segreta JWT — generata automaticamente"))
        conn.commit()
        conn.close()
        return secret
    except Exception:
        return _os.urandom(32).hex()


def _sync_ha_on_startup():
    """Aggiorna i sensori HA all'avvio dell'addon (dopo 5s per dare tempo a Flask)."""
    time.sleep(5)
    try:
        from routes.products import aggiorna_sensori_ha
        aggiorna_sensori_ha()
        logger.info("Sync sensori HA all'avvio completato")
    except Exception as e:
        logger.warning("Sync sensori HA all'avvio fallito: %s", e)


def _auto_backup_loop():
    """Thread daemon: ogni ora verifica se il backup automatico è invecchiato (>7gg)
    e in tal caso lo rigenera sovrascrivendo auto_backup.json."""
    time.sleep(60)  # Attendi avvio completo
    auto_path = os.path.join(BACKUPS_DIR, "auto_backup.json")
    while True:
        try:
            os.makedirs(BACKUPS_DIR, exist_ok=True)
            should_backup = True
            if os.path.exists(auto_path):
                age_seconds = time.time() - os.path.getmtime(auto_path)
                should_backup = age_seconds > (AUTO_BACKUP_INTERVAL_DAYS * 24 * 3600)
            if should_backup:
                from routes.admin import _build_backup
                backup = _build_backup()
                with open(auto_path, "w", encoding="utf-8") as f:
                    json.dump(backup, f, indent=2, default=str, ensure_ascii=False)
                size_kb = os.path.getsize(auto_path) / 1024
                logger.info("Backup automatico settimanale completato: %s (%.1f KB)", auto_path, size_kb)
        except Exception as e:
            logger.error("Errore loop backup automatico: %s", e)
        time.sleep(AUTO_BACKUP_CHECK_INTERVAL_SECONDS)


def create_app():
    app = Flask(__name__)

    jwt_secret = _load_jwt_secret()
    app.config["JWT_SECRET_KEY"] = jwt_secret
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=1)
    app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(days=30)
    app.config["HA_URL"] = os.environ.get("HA_URL", "http://supervisor/core")
    app.config["HA_TOKEN"] = os.environ.get("SUPERVISOR_TOKEN", "")
    # Limite upload (per restore backup): 64 MB
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024

    CORS(app, resources={r"/api/*": {
        "origins": "*",
        "allow_headers": ["Content-Type", "Authorization", "x-jarvis-token", "x-api-key"],
        "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    }})

    JWTManager(app)

    from flask_jwt_extended import exceptions as jwt_exc

    @app.errorhandler(jwt_exc.NoAuthorizationError)
    @app.errorhandler(jwt_exc.InvalidHeaderError)
    def handle_jwt_error(e):
        return jsonify({"error": "Token mancante o non valido"}), 401

    from routes.auth_routes import bp as auth_bp
    from routes.products import bp as products_bp
    from routes.shopping import bp as shopping_bp
    from routes.admin import bp as admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(shopping_bp)
    app.register_blueprint(admin_bp)

    @app.route("/")
    def index():
        cf_url = get_ha_option("cloudflare_url", "").rstrip("/")
        try:
            with open(os.path.join(WWW_DIR, "index.html"), "r", encoding="utf-8-sig") as fh:
                html = fh.read()
            html = html.replace('<meta name="cf-url" content="">', f'<meta name="cf-url" content="{cf_url}">')
            html = re.sub(r'<meta name="app-version" content="[^"]*">', f'<meta name="app-version" content="{APP_VERSION}">', html)
            html = re.sub(r"Dispensa Manager v\d+\.\d+\.\d+", f"Dispensa Manager v{APP_VERSION}", html)
            html = html.replace('?v=__VER__', f'?v={APP_VERSION}')
            resp = make_response(html)
            resp.headers["Content-Type"] = "text/html; charset=utf-8"
            resp.headers["Cache-Control"] = "no-cache"
            return resp
        except Exception as e:
            logger.error("Errore index: %s", e)
            return send_from_directory(WWW_DIR, "index.html")

    @app.route("/sw.js")
    def service_worker():
        resp = send_from_directory(WWW_DIR, "sw.js")
        resp.headers["Service-Worker-Allowed"] = "/"
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    # ── Serve immagini prodotti salvate su filesystem ────────────────────────
    @app.route("/dispensa-images/<filename>")
    def serve_dispensa_image(filename):
        """Serve immagini prodotti da /config/dispensa/images/.
        Cache lunga (1 anno, immutable) perché filename include ID prodotto e
        quando si modifica il prodotto si genera un nuovo file."""
        # Path traversal protection: filename deve essere semplice
        if "/" in filename or "\\" in filename or filename.startswith("."):
            return "", 400
        try:
            resp = send_from_directory(IMAGES_DIR, filename)
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return resp
        except Exception:
            return "", 404

    @app.route("/<path:filename>")
    def static_files(filename):
        resp = send_from_directory(WWW_DIR, filename)
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok", "version": APP_VERSION, "timestamp": datetime.now().isoformat()})

    return app


if __name__ == "__main__":
    from database import init_db
    init_db()
    logger.info("Dispensa Manager v%s avviato su porta 5000", APP_VERSION)
    # Sync sensori HA in background (best-effort, non blocca lo startup)
    threading.Thread(target=_sync_ha_on_startup, daemon=True).start()
    # Backup automatico ogni 7 giorni
    threading.Thread(target=_auto_backup_loop, daemon=True).start()
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=False)
