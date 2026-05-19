import os
import re
import logging
from datetime import timedelta
from flask import Flask, jsonify, make_response, send_from_directory, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from database import APP_VERSION

WWW_DIR = os.path.join(os.path.dirname(__file__), "www")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

OPTIONS_PATH = "/data/options.json"
_JWT_SECRET_CACHE = None

def _load_jwt_secret() -> str:
    global _JWT_SECRET_CACHE
    if _JWT_SECRET_CACHE:
        return _JWT_SECRET_CACHE
    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        try:
            import json
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


def create_app():
    app = Flask(__name__)

    jwt_secret = _load_jwt_secret()
    app.config["JWT_SECRET_KEY"] = jwt_secret
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=1)
    app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(days=30)
    app.config["HA_URL"] = os.environ.get("HA_URL", "http://supervisor/core")
    app.config["HA_TOKEN"] = os.environ.get("SUPERVISOR_TOKEN", "")

    CORS(app, resources={r"/api/*": {
        "origins": "*",
        "allow_headers": ["Content-Type", "Authorization"],
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
        from database import get_db, get_setting
        conn = get_db()
        cf_url = get_setting(conn, "cloudflare_url").rstrip("/")
        conn.close()
        try:
            with open(os.path.join(WWW_DIR, "index.html"), "r", encoding="utf-8-sig") as fh:
                html = fh.read()
            html = html.replace('<meta name="cf-url" content="">', f'<meta name="cf-url" content="{cf_url}">')
            html = re.sub(r'<meta name="app-version" content="[^"]*">', f'<meta name="app-version" content="{APP_VERSION}">', html)
            html = re.sub(r"Dispensa Manager v\d+\.\d+\.\d+", f"Dispensa Manager v{APP_VERSION}", html)
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

    @app.route("/<path:filename>")
    def static_files(filename):
        resp = send_from_directory(WWW_DIR, filename)
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    @app.route("/api/health")
    def health():
        from datetime import datetime
        return jsonify({"status": "ok", "version": APP_VERSION, "timestamp": datetime.now().isoformat()})

    return app


if __name__ == "__main__":
    from database import init_db
    init_db()
    logger.info("Dispensa Manager v%s avviato su porta 5000", APP_VERSION)
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=False)
