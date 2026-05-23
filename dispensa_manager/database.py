import sqlite3
import json
import os
import logging
import secrets
import bcrypt

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "/config/dispensa.db")
OPTIONS_PATH = "/data/options.json"

APP_VERSION = "2.0.10"
SCHEMA_VERSION = 4


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_ha_option(key: str, default: str = "") -> str:
    try:
        with open(OPTIONS_PATH) as f:
            opts = json.load(f)
        value = opts.get(key, default)
        if value is None:
            return default
        return str(value) if not isinstance(value, str) else value
    except Exception:
        return default


def get_api_key() -> str:
    """Restituisce la API key persistente per automazioni HA.
    Generata al primo accesso e salvata nel DB. Stabile tra restart."""
    conn = get_db()
    try:
        row = conn.execute("SELECT value FROM app_settings WHERE key='api_key'").fetchone()
        if row and row["value"]:
            return row["value"]
        key = "dk_" + secrets.token_urlsafe(32)
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO app_settings (key, value, description) VALUES (?, ?, ?)",
                ("api_key", key, "API key per automazioni HA (rest_command)"),
            )
        row = conn.execute("SELECT value FROM app_settings WHERE key='api_key'").fetchone()
        return row["value"] if row else key
    finally:
        conn.close()


def regenerate_api_key() -> str:
    """Genera una nuova API key sovrascrivendo la precedente.
    Invalida tutte le automazioni HA che usano la chiave vecchia."""
    key = "dk_" + secrets.token_urlsafe(32)
    conn = get_db()
    try:
        with conn:
            set_setting(conn, "api_key", key)
    finally:
        conn.close()
    logger.info("API key rigenerata da admin")
    return key


def _get_schema_version(conn):
    try:
        row = conn.execute("SELECT value FROM app_settings WHERE key='schema_version'").fetchone()
        return int(row["value"]) if row else 0
    except sqlite3.OperationalError:
        return 0


def _set_schema_version(conn, version):
    conn.execute(
        "INSERT OR REPLACE INTO app_settings (key, value, description) VALUES (?, ?, ?)",
        ("schema_version", str(version), "Versione schema DB interna"),
    )


def init_db():
    conn = get_db()

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS prodotti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ean TEXT,
            nome TEXT NOT NULL,
            marca TEXT,
            categoria TEXT,
            immagine_url TEXT,
            quantita INTEGER DEFAULT 1,
            scadenza TEXT,
            data_inserimento TEXT DEFAULT (datetime('now')),
            note TEXT,
            nutriments TEXT,
            nutriscore TEXT,
            posizione TEXT DEFAULT 'Dispensa'
        );

        CREATE TABLE IF NOT EXISTS barcode_cache (
            ean TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            marca TEXT,
            categoria TEXT,
            immagine_url TEXT,
            nutriscore TEXT,
            nutriments TEXT,
            data_inserimento TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS lista_spesa (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            quantita INTEGER DEFAULT 1,
            ean TEXT,
            marca TEXT,
            completato INTEGER DEFAULT 0,
            data_aggiunta TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS storico_movimenti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ean TEXT,
            nome TEXT NOT NULL,
            marca TEXT,
            categoria TEXT,
            tipo TEXT NOT NULL,
            quantita INTEGER DEFAULT 1,
            data TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_prodotti_scadenza ON prodotti(scadenza);
        CREATE INDEX IF NOT EXISTS idx_prodotti_ean ON prodotti(ean);
        CREATE INDEX IF NOT EXISTS idx_movimenti_data ON storico_movimenti(data);
    """)

    for alter in [
        "ALTER TABLE prodotti ADD COLUMN nutriments TEXT",
        "ALTER TABLE prodotti ADD COLUMN nutriscore TEXT",
        "ALTER TABLE prodotti ADD COLUMN posizione TEXT DEFAULT 'Dispensa'",
        "ALTER TABLE barcode_cache ADD COLUMN nutriscore TEXT",
        "ALTER TABLE barcode_cache ADD COLUMN nutriments TEXT",
    ]:
        try:
            conn.execute(alter)
        except Exception:
            pass

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            description TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_login DATETIME
        );
    """)

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            username TEXT,
            success INTEGER NOT NULL DEFAULT 0,
            attempted_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_login_attempts_ip ON login_attempts(ip, attempted_at);

        CREATE TABLE IF NOT EXISTS ip_bans (
            ip TEXT PRIMARY KEY,
            banned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            reason TEXT DEFAULT 'Tentativi di accesso eccessivi'
        );
    """)

    current = _get_schema_version(conn)

    if current < 2:
        logger.info("Migrazione schema DB: v%d → v2", current)
        with conn:
            _seed_defaults(conn)
            _set_schema_version(conn, 2)
        current = 2

    if current < 3:
        logger.info("Migrazione schema DB: v2 → v3 (IP ban tables)")
        with conn:
            _set_schema_version(conn, 3)
        current = 3

    if current < 4:
        logger.info("Migrazione schema DB: v3 → v4 (parametri IP ban configurabili)")
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO app_settings (key, value, description) VALUES (?, ?, ?)",
                ("max_login_attempts", "3", "Tentativi di login falliti max prima del ban IP"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO app_settings (key, value, description) VALUES (?, ?, ?)",
                ("ban_window_minutes", "15", "Finestra temporale (minuti) per contare i tentativi falliti"),
            )
            _set_schema_version(conn, 4)
        current = 4

    conn.close()

    # API key auto-generata al primo avvio (idempotente)
    get_api_key()


def _seed_defaults(conn):
    ha_opts = {}
    try:
        with open(OPTIONS_PATH) as f:
            ha_opts = json.load(f)
    except Exception:
        pass

    defaults = [
        ("giorni_alert_scadenza", str(ha_opts.get("giorni_alert_scadenza", 3)),
         "Giorni prima della scadenza per inviare alert"),
        ("soglia_scorte_minime", str(ha_opts.get("soglia_scorte_minime", 1)),
         "Quantità minima prima di avvisare scorta esaurita"),
        ("max_login_attempts", "3",
         "Tentativi di login falliti max prima del ban IP"),
        ("ban_window_minutes", "15",
         "Finestra temporale (minuti) per contare i tentativi falliti"),
    ]
    for key, value, desc in defaults:
        conn.execute(
            "INSERT OR IGNORE INTO app_settings (key, value, description) VALUES (?, ?, ?)",
            (key, value, desc),
        )

    row = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()
    if row["cnt"] == 0:
        pw_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode()
        conn.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
            ("admin", pw_hash),
        )
        logger.warning("SICUREZZA: utente admin creato con password 'admin' — cambiala subito dal pannello Admin!")


def get_settings(conn) -> dict:
    rows = conn.execute(
        "SELECT key, value FROM app_settings WHERE key != 'schema_version'"
    ).fetchall()
    return {r["key"]: r["value"] for r in rows}


def get_setting(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key: str, value: str):
    conn.execute(
        "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
        (key, value),
    )
