import sqlite3
import json
import os
import logging
import secrets
import base64
import bcrypt

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "/config/dispensa.db")
OPTIONS_PATH = "/data/options.json"

# Cartella per immagini salvate su filesystem (non più nel DB)
IMAGES_DIR = os.path.join(os.path.dirname(DB_PATH), "dispensa", "images")
BACKUPS_DIR = os.path.join(os.path.dirname(DB_PATH), "dispensa", "backups")

APP_VERSION = "2.0.19"
SCHEMA_VERSION = 6


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
    """Restituisce la API key persistente per automazioni HA."""
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
    key = "dk_" + secrets.token_urlsafe(32)
    conn = get_db()
    try:
        with conn:
            set_setting(conn, "api_key", key)
    finally:
        conn.close()
    logger.info("API key rigenerata da admin")
    return key


def save_image_to_fs(data_url: str, prodotto_id: int) -> str:
    """Decodifica una data-URL base64 e salva l'immagine su filesystem.
    Ritorna il path relativo /dispensa-images/<id>.<ext> da salvare nel DB.
    Se non è una data-URL, ritorna il valore originale immutato."""
    if not data_url or not data_url.startswith("data:image/"):
        return data_url
    try:
        os.makedirs(IMAGES_DIR, exist_ok=True)
        header, b64data = data_url.split(",", 1)
        ext = "jpg"
        if "png" in header.lower():
            ext = "png"
        elif "webp" in header.lower():
            ext = "webp"
        filepath = os.path.join(IMAGES_DIR, f"{prodotto_id}.{ext}")
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(b64data))
        rel = f"/dispensa-images/{prodotto_id}.{ext}"
        logger.info("Immagine prodotto %d salvata su FS (%d bytes)", prodotto_id, len(b64data))
        return rel
    except Exception as e:
        logger.error("Errore salvataggio immagine prodotto %d: %s", prodotto_id, e)
        return ""  # fallback: rimuove immagine corrotta


def delete_image_from_fs(image_path: str):
    """Elimina file immagine da FS se path inizia con /dispensa-images/."""
    if not image_path or not image_path.startswith("/dispensa-images/"):
        return
    try:
        filename = image_path.replace("/dispensa-images/", "")
        filepath = os.path.join(IMAGES_DIR, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception as e:
        logger.warning("Impossibile rimuovere immagine %s: %s", image_path, e)


def _migra_immagini_su_fs(conn):
    """Migrazione one-shot: sposta tutte le immagini base64 dal DB al filesystem."""
    rows = conn.execute(
        "SELECT id, immagine_url FROM prodotti WHERE immagine_url LIKE 'data:image/%'"
    ).fetchall()
    if not rows:
        return 0
    count = 0
    for r in rows:
        new_path = save_image_to_fs(r["immagine_url"], r["id"])
        if new_path != r["immagine_url"]:
            conn.execute("UPDATE prodotti SET immagine_url=? WHERE id=?", (new_path, r["id"]))
            count += 1
    return count


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
            posizione TEXT DEFAULT 'Dispensa',
            prezzo REAL
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
            prezzo REAL,
            data TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_prodotti_scadenza ON prodotti(scadenza);
        CREATE INDEX IF NOT EXISTS idx_prodotti_ean ON prodotti(ean);
        CREATE INDEX IF NOT EXISTS idx_prodotti_categoria ON prodotti(categoria);
        CREATE INDEX IF NOT EXISTS idx_movimenti_data ON storico_movimenti(data);
        CREATE INDEX IF NOT EXISTS idx_movimenti_tipo_data ON storico_movimenti(tipo, data);
    """)

    for alter in [
        "ALTER TABLE prodotti ADD COLUMN nutriments TEXT",
        "ALTER TABLE prodotti ADD COLUMN nutriscore TEXT",
        "ALTER TABLE prodotti ADD COLUMN posizione TEXT DEFAULT 'Dispensa'",
        "ALTER TABLE prodotti ADD COLUMN prezzo REAL",
        "ALTER TABLE barcode_cache ADD COLUMN nutriscore TEXT",
        "ALTER TABLE barcode_cache ADD COLUMN nutriments TEXT",
        "ALTER TABLE storico_movimenti ADD COLUMN prezzo REAL",
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
        logger.info("Migrazione schema DB: v3 → v4 (IP ban configurabili)")
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

    if current < 5:
        logger.info("Migrazione schema DB: v4 → v5 (notifiche Telegram granulari)")
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO app_settings (key, value, description) VALUES (?, ?, ?)",
                ("notif_telegram_acquisto", "1", "Notifica Telegram quando aggiungi un prodotto"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO app_settings (key, value, description) VALUES (?, ?, ?)",
                ("notif_telegram_modifica", "1", "Notifica Telegram quando modifichi un prodotto"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO app_settings (key, value, description) VALUES (?, ?, ?)",
                ("notif_telegram_eliminazione", "1", "Notifica Telegram quando elimini un prodotto"),
            )
            _set_schema_version(conn, 5)
        current = 5

    if current < 6:
        logger.info("Migrazione schema DB: v5 → v6 (immagini su FS, prezzo opzionale, indici)")
        # Migra immagini base64 → filesystem
        try:
            n = _migra_immagini_su_fs(conn)
            conn.commit()
            if n > 0:
                logger.info("Migrate %d immagini base64 → filesystem", n)
        except Exception as e:
            logger.error("Errore migrazione immagini: %s", e)
        with conn:
            _set_schema_version(conn, 6)
        current = 6

    conn.close()

    # API key auto-generata al primo avvio (idempotente)
    get_api_key()

    # Crea cartelle se mancanti
    try:
        os.makedirs(IMAGES_DIR, exist_ok=True)
        os.makedirs(BACKUPS_DIR, exist_ok=True)
    except Exception as e:
        logger.warning("Impossibile creare cartelle dispensa: %s", e)


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
        ("notif_telegram_acquisto", "1",
         "Notifica Telegram quando aggiungi un prodotto"),
        ("notif_telegram_modifica", "1",
         "Notifica Telegram quando modifichi un prodotto"),
        ("notif_telegram_eliminazione", "1",
         "Notifica Telegram quando elimini un prodotto"),
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
        logger.warning("SICUREZZA: utente admin creato con password 'admin' — cambiala subito!")


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
