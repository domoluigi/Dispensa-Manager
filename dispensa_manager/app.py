import csv
import io
import json
import os
import sqlite3
import threading
import requests
from datetime import datetime
from flask import Flask, request, jsonify, make_response, send_from_directory
from flask_cors import CORS

APP_VERSION = "1.5.2"
DB_PATH = "/config/dispensa.db"
OPTIONS_PATH = "/data/options.json"
HA_URL = os.environ.get("HA_URL", "http://supervisor/core")
HA_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
WWW_DIR = os.path.join(os.path.dirname(__file__), 'www')

print(f"SUPERVISOR_TOKEN presente: {bool(os.environ.get('SUPERVISOR_TOKEN'))}", flush=True)

# ---------------------------------------------------------------------------
# Options cache — rilettura dal disco solo se il file è cambiato
# ---------------------------------------------------------------------------
_options_cache = None
_options_mtime = 0

def get_options():
    global _options_cache, _options_mtime
    try:
        mtime = os.path.getmtime(OPTIONS_PATH)
        if mtime != _options_mtime:
            with open(OPTIONS_PATH) as f:
                _options_cache = json.load(f)
            _options_mtime = mtime
    except Exception:
        pass
    return _options_cache or {
        "telegram_token": "",
        "telegram_chat_id": "",
        "giorni_alert_scadenza": 3,
        "soglia_scorte_minime": 1,
    }

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*", "allow_headers": ["Content-Type"], "methods": ["GET","POST","PUT","DELETE","OPTIONS"]}})

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,PUT,DELETE,OPTIONS')
    return response

# ---------------------------------------------------------------------------
# Frontend statico servito da Flask
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    resp = send_from_directory(WWW_DIR, 'index.html')
    resp.headers['Cache-Control'] = 'no-cache'
    return resp

@app.route('/sw.js')
def service_worker():
    resp = send_from_directory(WWW_DIR, 'sw.js')
    resp.headers['Service-Worker-Allowed'] = '/'
    resp.headers['Cache-Control'] = 'no-cache'
    return resp

@app.route('/<path:filename>')
def static_files(filename):
    resp = send_from_directory(WWW_DIR, filename)
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS prodotti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ean TEXT NOT NULL,
            nome TEXT NOT NULL,
            marca TEXT,
            categoria TEXT,
            immagine_url TEXT,
            quantita INTEGER DEFAULT 1,
            scadenza TEXT,
            data_inserimento TEXT DEFAULT (datetime('now')),
            note TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS barcode_cache (
            ean TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            marca TEXT,
            categoria TEXT,
            immagine_url TEXT,
            nutriscore TEXT,
            nutriments TEXT,
            data_inserimento TEXT DEFAULT (datetime('now'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS lista_spesa (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            quantita INTEGER DEFAULT 1,
            ean TEXT,
            marca TEXT,
            completato INTEGER DEFAULT 0,
            data_aggiunta TEXT DEFAULT (datetime('now'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS storico_movimenti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ean TEXT,
            nome TEXT NOT NULL,
            marca TEXT,
            categoria TEXT,
            tipo TEXT NOT NULL,
            quantita INTEGER DEFAULT 1,
            data TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    for alter in [
        "ALTER TABLE prodotti ADD COLUMN nutriments TEXT",
        "ALTER TABLE prodotti ADD COLUMN nutriscore TEXT",
        "ALTER TABLE prodotti ADD COLUMN posizione TEXT DEFAULT 'Dispensa'",
        "ALTER TABLE barcode_cache ADD COLUMN nutriscore TEXT",
        "ALTER TABLE barcode_cache ADD COLUMN nutriments TEXT",
    ]:
        try:
            c.execute(alter)
        except Exception:
            pass
    c.execute("CREATE INDEX IF NOT EXISTS idx_prodotti_scadenza ON prodotti(scadenza)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_prodotti_ean ON prodotti(ean)")
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def aggiungi_a_lista_spesa(nome, ean="", marca=""):
    conn = get_db()
    esistente = conn.execute(
        "SELECT id FROM lista_spesa WHERE ean = ? AND completato = 0", (ean,)
    ).fetchone()
    if not esistente:
        conn.execute("INSERT INTO lista_spesa (nome, ean, marca) VALUES (?, ?, ?)", (nome, ean, marca))
        conn.commit()
    conn.close()

def log_movimento(nome, tipo, ean="", marca="", categoria="", quantita=1):
    try:
        conn = get_db()
        conn.execute("""
            INSERT INTO storico_movimenti (ean, nome, marca, categoria, tipo, quantita)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (ean, nome, marca, categoria, tipo, quantita))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Errore log movimento: {e}")

def aggiorna_sensori_ha():
    conn = get_db()
    tutti = conn.execute("SELECT * FROM prodotti ORDER BY scadenza ASC").fetchall()
    conn.close()

    oggi = datetime.now().date()
    opts = get_options()
    giorni_soglia = opts.get("giorni_alert_scadenza", 3)

    attivi = [p for p in tutti if p["quantita"] > 0]
    esauriti_list = [p for p in tutti if p["quantita"] <= 0]

    in_scadenza = []
    for p in attivi:
        if p["scadenza"]:
            try:
                scad = datetime.strptime(p["scadenza"], "%Y-%m-%d").date()
                if (scad - oggi).days <= giorni_soglia:
                    in_scadenza.append({"nome": p["nome"], "scadenza": p["scadenza"], "giorni": (scad - oggi).days})
            except Exception:
                pass

    for p in esauriti_list:
        aggiungi_a_lista_spesa(p["nome"], p["ean"], p["marca"] or "")

    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json"
    }
    stati = {
        "sensor.dispensa_totale_prodotti": {
            "state": len(attivi),
            "attributes": {"friendly_name": "Dispensa: prodotti totali", "icon": "mdi:package-variant"}
        },
        "sensor.dispensa_in_scadenza": {
            "state": len(in_scadenza),
            "attributes": {"friendly_name": "Dispensa: in scadenza", "prodotti": in_scadenza, "icon": "mdi:calendar-alert"}
        },
        "sensor.dispensa_esauriti": {
            "state": len(esauriti_list),
            "attributes": {"friendly_name": "Dispensa: esauriti", "prodotti": [p["nome"] for p in esauriti_list], "icon": "mdi:package-variant-remove"}
        }
    }
    for entity_id, payload in stati.items():
        try:
            requests.post(f"{HA_URL}/api/states/{entity_id}", headers=headers, json=payload, timeout=5)
        except Exception as e:
            print(f"Errore aggiornamento HA {entity_id}: {e}")

def _aggiorna_sensori_async():
    threading.Thread(target=aggiorna_sensori_ha, daemon=True).start()

def _invia_notifica_async(testo):
    threading.Thread(target=invia_notifica_azione, args=(testo,), daemon=True).start()

def invia_notifica_azione(testo):
    opts = get_options()
    token = opts.get("telegram_token", "")
    chat_id_raw = opts.get("telegram_chat_id", "")
    if not token or not chat_id_raw:
        return
    chat_ids = [c.strip() for c in str(chat_id_raw).split(",") if c.strip()]
    for chat_id in chat_ids:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": testo, "parse_mode": "Markdown"},
                timeout=10
            )
        except Exception as e:
            print(f"Errore Telegram {chat_id}: {e}")

@app.route("/api/barcode/<ean>", methods=["GET"])
def cerca_barcode(ean):
    headers = {"User-Agent": f"DispensaManager/{APP_VERSION}"}
    conn = get_db()
    cached = conn.execute("SELECT * FROM barcode_cache WHERE ean = ?", (ean,)).fetchone()
    conn.close()
    if cached:
        nutriments_cached = None
        if cached["nutriments"]:
            try:
                nutriments_cached = json.loads(cached["nutriments"])
            except Exception:
                nutriments_cached = None
        return jsonify({
            "trovato": True, "fonte": "cache_locale", "ean": ean,
            "nome": cached["nome"], "marca": cached["marca"] or "",
            "categoria": cached["categoria"] or "", "immagine_url": cached["immagine_url"] or "",
            "nutriscore": cached["nutriscore"] or "", "nutriments": nutriments_cached or {}
        })

    databases = [
        f"https://world.openfoodfacts.org/api/v2/product/{ean}.json",
        f"https://world.openproductsfacts.org/api/v2/product/{ean}.json",
        f"https://world.openbeautyfacts.org/api/v2/product/{ean}.json",
    ]
    for url in databases:
        try:
            r = requests.get(url, timeout=8, headers=headers)
            data = r.json()
            if data.get("status") == 1:
                p = data["product"]
                nutriments = p.get("nutriments", {})
                return jsonify({
                    "trovato": True, "fonte": "online", "ean": ean,
                    "nome": p.get("product_name_it") or p.get("product_name", "Prodotto sconosciuto"),
                    "marca": (p.get("brands", "").split(",")[0].strip()),
                    "categoria": p.get("categories_tags", [""])[0].replace("en:", "").replace("-", " ") if p.get("categories_tags") else "",
                    "immagine_url": p.get("image_front_small_url", ""),
                    "nutriscore": p.get("nutriscore_grade", "").upper(),
                    "nutriments": {
                        "energia_kcal": nutriments.get("energy-kcal_100g"),
                        "grassi": nutriments.get("fat_100g"),
                        "grassi_saturi": nutriments.get("saturated-fat_100g"),
                        "carboidrati": nutriments.get("carbohydrates_100g"),
                        "zuccheri": nutriments.get("sugars_100g"),
                        "fibre": nutriments.get("fiber_100g"),
                        "proteine": nutriments.get("proteins_100g"),
                        "sale": nutriments.get("salt_100g"),
                    }
                })
        except Exception:
            continue

    return jsonify({"trovato": False, "ean": ean, "nome": "", "marca": "", "categoria": "", "immagine_url": "", "nutriscore": "", "nutriments": {}})

@app.route("/api/prodotti/by-ean/<ean>", methods=["GET"])
def prodotti_by_ean(ean):
    conn = get_db()
    items = conn.execute(
        "SELECT id, nome, marca, quantita, scadenza, posizione FROM prodotti WHERE ean = ? AND quantita > 0 ORDER BY scadenza ASC",
        (ean,)
    ).fetchall()
    conn.close()
    return jsonify([dict(i) for i in items])

@app.route("/api/prodotti/esauriti", methods=["GET"])
def lista_esauriti():
    conn = get_db()
    prodotti = conn.execute(
        "SELECT * FROM prodotti WHERE quantita <= 0 ORDER BY nome ASC"
    ).fetchall()
    conn.close()
    return jsonify([dict(p) for p in prodotti])

@app.route("/api/lista-spesa", methods=["GET"])
def get_lista_spesa():
    conn = get_db()
    items = conn.execute("SELECT * FROM lista_spesa ORDER BY completato ASC, data_aggiunta DESC").fetchall()
    conn.close()
    return jsonify([dict(i) for i in items])

@app.route("/api/lista-spesa", methods=["POST"])
def aggiungi_lista_spesa():
    data = request.json
    conn = get_db()
    conn.execute("INSERT INTO lista_spesa (nome, quantita, ean, marca) VALUES (?, ?, ?, ?)",
        (data.get("nome", ""), data.get("quantita", 1), data.get("ean", ""), data.get("marca", "")))
    conn.commit()
    conn.close()
    return jsonify({"ok": True}), 201

@app.route("/api/lista-spesa/<int:id>", methods=["PUT"])
def aggiorna_lista_spesa(id):
    data = request.json
    conn = get_db()
    conn.execute("UPDATE lista_spesa SET completato = ?, quantita = ? WHERE id = ?",
        (data.get("completato", 0), data.get("quantita", 1), id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/lista-spesa/<int:id>", methods=["DELETE"])
def elimina_lista_spesa(id):
    conn = get_db()
    conn.execute("DELETE FROM lista_spesa WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/lista-spesa/svuota-completati", methods=["DELETE"])
def svuota_completati():
    conn = get_db()
    conn.execute("DELETE FROM lista_spesa WHERE completato = 1")
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/lista-spesa/invia-telegram", methods=["GET"])
def invia_lista_spesa_telegram():
    opts = get_options()
    token = opts.get("telegram_token", "")
    chat_id_raw = opts.get("telegram_chat_id", "")
    if not token or not chat_id_raw:
        return jsonify({"ok": False, "errore": "Telegram non configurato"})

    conn = get_db()
    items = conn.execute("SELECT * FROM lista_spesa WHERE completato = 0 ORDER BY data_aggiunta DESC").fetchall()
    conn.close()
    if not items:
        return jsonify({"ok": False, "errore": "Lista spesa vuota"})

    msg = f"\U0001f6d2 *Lista della Spesa*\n_{datetime.now().strftime('%d/%m/%Y %H:%M')}_\n\n"
    for item in items:
        msg += f"  ☐ {item['nome']}"
        if item['quantita'] > 1:
            msg += f" \xd7{item['quantita']}"
        if item['marca']:
            msg += f" _{item['marca']}_"
        msg += "\n"

    chat_ids = [c.strip() for c in str(chat_id_raw).split(",") if c.strip()]
    for cid in chat_ids:
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        except Exception as e:
            print(f"Errore Telegram lista spesa {cid}: {e}")
    return jsonify({"ok": True, "totale": len(items)})

@app.route("/api/barcode-cache", methods=["POST"])
def salva_barcode_cache():
    data = request.json
    ean = data.get("ean", "")
    if not ean or ean.startswith("MANUAL-"):
        return jsonify({"ok": False, "errore": "EAN non valido"})
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO barcode_cache (ean, nome, marca, categoria, immagine_url, nutriscore, nutriments)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (ean, data.get("nome", ""), data.get("marca", ""), data.get("categoria", ""),
          data.get("immagine_url", ""), data.get("nutriscore", ""),
          json.dumps(data.get("nutriments")) if data.get("nutriments") else None))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/prodotti", methods=["GET"])
def lista_prodotti():
    limit = request.args.get('limit', type=int)
    offset = request.args.get('offset', 0, type=int)
    conn = get_db()
    if limit:
        prodotti = conn.execute(
            "SELECT * FROM prodotti ORDER BY scadenza ASC NULLS LAST LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
    else:
        prodotti = conn.execute("SELECT * FROM prodotti ORDER BY scadenza ASC NULLS LAST").fetchall()
    conn.close()
    oggi = datetime.now().date()
    result = []
    for p in prodotti:
        d = dict(p)
        if d["scadenza"]:
            try:
                scad = datetime.strptime(d["scadenza"], "%Y-%m-%d").date()
                d["giorni_alla_scadenza"] = (scad - oggi).days
            except Exception:
                d["giorni_alla_scadenza"] = None
        else:
            d["giorni_alla_scadenza"] = None
        if d.get("nutriments") and isinstance(d["nutriments"], str):
            try:
                d["nutriments"] = json.loads(d["nutriments"])
            except Exception:
                d["nutriments"] = None
        result.append(d)
    return jsonify(result)

@app.route("/api/prodotti", methods=["POST"])
def aggiungi_prodotto():
    data = request.json
    conn = get_db()

    immagine_url = data.get("immagine_url", "")
    if immagine_url and immagine_url.startswith("data:") and len(immagine_url) > 600000:
        immagine_url = ""

    conn.execute("""
        INSERT INTO prodotti (ean, nome, marca, categoria, immagine_url, quantita, scadenza, note, nutriments, nutriscore, posizione)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("ean", ""), data.get("nome", "Prodotto"), data.get("marca", ""),
        data.get("categoria", ""), immagine_url, data.get("quantita", 1),
        data.get("scadenza"), data.get("note", ""),
        json.dumps(data.get("nutriments")) if data.get("nutriments") else None,
        data.get("nutriscore", ""), data.get("posizione", "Dispensa")
    ))
    conn.commit()
    conn.close()
    log_movimento(nome=data.get("nome", "Prodotto"), tipo="acquisto", ean=data.get("ean", ""),
        marca=data.get("marca", ""), categoria=data.get("categoria", ""), quantita=data.get("quantita", 1))
    _aggiorna_sensori_async()

    nome = data.get("nome", "Prodotto")
    qty = data.get("quantita", 1)
    pos = data.get("posizione", "Dispensa")
    pos_icon = {"Frigo": "\U0001f9ca", "Freezer": "❄️", "Dispensa": "\U0001f5c4️"}.get(pos, "\U0001f4e6")
    scad = data.get("scadenza")
    scad_str = f"\n\U0001f4c5 Scade: {datetime.strptime(scad, '%Y-%m-%d').strftime('%d/%m/%Y')}" if scad else ""
    _invia_notifica_async(f"➕ *Aggiunto in dispensa*\n\n*{nome}* \xd7{qty}\n{pos_icon} {pos}{scad_str}")

    return jsonify({"ok": True}), 201

@app.route("/api/prodotti/<int:id>", methods=["PUT"])
def aggiorna_prodotto(id):
    data = request.json
    conn = get_db()
    p = conn.execute("SELECT * FROM prodotti WHERE id = ?", (id,)).fetchone()
    fields = []
    values = []
    for campo in ["nome", "marca", "quantita", "scadenza", "note", "posizione"]:
        if campo in data:
            fields.append(f"{campo} = ?")
            values.append(data[campo])
    if fields:
        values.append(id)
        conn.execute(f"UPDATE prodotti SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    conn.close()

    if p and "quantita" in data and data["quantita"] < p["quantita"]:
        log_movimento(nome=p["nome"], tipo="consumo", ean=p["ean"] or "",
            marca=p["marca"] or "", categoria=p["categoria"] or "",
            quantita=p["quantita"] - data["quantita"])
    _aggiorna_sensori_async()

    if p:
        nome = data.get("nome", p["nome"])
        cambiamenti = []
        if "quantita" in data and data["quantita"] != p["quantita"]:
            cambiamenti.append(f"Quantit\xe0: {p['quantita']} → {data['quantita']}")
        if "scadenza" in data and data["scadenza"] != p["scadenza"]:
            def fmt(s): return datetime.strptime(s, "%Y-%m-%d").strftime("%d/%m/%Y") if s else "—"
            cambiamenti.append(f"Scadenza: {fmt(p['scadenza'])} → {fmt(data['scadenza'])}")
        if "posizione" in data and data["posizione"] != (p["posizione"] or "Dispensa"):
            cambiamenti.append(f"Posizione: {p['posizione'] or 'Dispensa'} → {data['posizione']}")
        if "nome" in data and data["nome"] != p["nome"]:
            cambiamenti.append(f"Nome: {p['nome']} → {data['nome']}")
        if "marca" in data and data["marca"] != (p["marca"] or ""):
            cambiamenti.append(f"Marca: {p['marca'] or '—'} → {data['marca']}")
        if "note" in data and data["note"] != (p["note"] or ""):
            cambiamenti.append("Note aggiornate")
        if cambiamenti:
            corpo = "\n".join(f"• {c}" for c in cambiamenti)
            _invia_notifica_async(f"✏️ *Modificato: {nome}*\n\n{corpo}")

    return jsonify({"ok": True})

@app.route("/api/prodotti/<int:id>", methods=["DELETE"])
def elimina_prodotto(id):
    conn = get_db()
    p = conn.execute("SELECT * FROM prodotti WHERE id = ?", (id,)).fetchone()
    conn.execute("DELETE FROM prodotti WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    if p:
        log_movimento(nome=p["nome"], tipo="eliminato", ean=p["ean"] or "",
            marca=p["marca"] or "", categoria=p["categoria"] or "", quantita=p["quantita"])
        pos = p["posizione"] or "Dispensa"
        pos_icon = {"Frigo": "\U0001f9ca", "Freezer": "❄️", "Dispensa": "\U0001f5c4️"}.get(pos, "\U0001f4e6")
        _invia_notifica_async(f"\U0001f5d1️ *Eliminato dalla dispensa*\n\n*{p['nome']}*\n{pos_icon} {pos}")
    _aggiorna_sensori_async()
    return jsonify({"ok": True})

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": APP_VERSION, "timestamp": datetime.now().isoformat()})

@app.route("/api/test-telegram", methods=["GET"])
def test_telegram():
    opts = get_options()
    token = opts.get("telegram_token", "")
    chat_id_raw = opts.get("telegram_chat_id", "")
    if not token or not chat_id_raw:
        return jsonify({"ok": False, "errore": "Token o chat_id non configurati"})
    chat_ids = [c.strip() for c in str(chat_id_raw).split(",") if c.strip()]
    msg = "\U0001f9ea *Test Dispensa Manager*\n\nLe notifiche Telegram funzionano correttamente! ✅"
    risultati = []
    for cid in chat_ids:
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"}, timeout=10)
            risultati.append({"chat_id": cid, "ok": r.status_code == 200})
        except Exception as e:
            risultati.append({"chat_id": cid, "ok": False, "errore": str(e)})
    return jsonify({"risultati": risultati})

@app.route("/api/alerts", methods=["GET"])
def invia_alerts():
    conn = get_db()
    prodotti = conn.execute("SELECT * FROM prodotti ORDER BY scadenza ASC").fetchall()
    conn.close()

    oggi = datetime.now().date()
    opts = get_options()
    giorni_soglia = opts.get("giorni_alert_scadenza", 3)

    in_scadenza = []
    esauriti = []

    for p in prodotti:
        if p["quantita"] <= 0:
            esauriti.append(p["nome"])
        if p["quantita"] > 0 and p["scadenza"]:
            try:
                scad = datetime.strptime(p["scadenza"], "%Y-%m-%d").date()
                giorni = (scad - oggi).days
                if giorni <= giorni_soglia:
                    in_scadenza.append({"nome": p["nome"], "giorni": giorni})
            except Exception:
                pass

    if not in_scadenza and not esauriti:
        return jsonify({"ok": True, "notifica_inviata": False, "motivo": "Nessun alert da inviare"})

    msg = f"\U0001f514 *Alert Dispensa*\n_{datetime.now().strftime('%d/%m/%Y')}_\n\n"
    if in_scadenza:
        msg += "⚠️ *In scadenza:*\n"
        for p in in_scadenza:
            if p["giorni"] < 0: label = "gi\xe0 scaduto!"
            elif p["giorni"] == 0: label = "scade oggi!"
            elif p["giorni"] == 1: label = "scade domani"
            else: label = f"tra {p['giorni']} giorni"
            msg += f"  • {p['nome']} — _{label}_\n"
        msg += "\n"
    if esauriti:
        msg += "❌ *Esauriti:*\n"
        for nome in esauriti:
            msg += f"  • {nome}\n"

    _invia_notifica_async(msg)
    _aggiorna_sensori_async()
    return jsonify({"ok": True, "notifica_inviata": True, "in_scadenza": len(in_scadenza), "esauriti": len(esauriti)})

@app.route("/api/export-csv", methods=["GET"])
def export_csv():
    conn = get_db()
    prodotti = conn.execute("SELECT * FROM prodotti ORDER BY nome ASC").fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Nome', 'Marca', 'Categoria', 'Quantit\xe0', 'Scadenza', 'Posizione', 'EAN', 'Note', 'Data inserimento'])
    for p in prodotti:
        writer.writerow([
            p['id'], p['nome'], p['marca'] or '', p['categoria'] or '',
            p['quantita'], p['scadenza'] or '', p['posizione'] or '',
            p['ean'] or '', p['note'] or '', p['data_inserimento'] or ''
        ])

    output.seek(0)
    response = make_response('﻿' + output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename=dispensa_{datetime.now().strftime("%Y%m%d")}.csv'
    return response

@app.route("/api/report", methods=["GET"])
def report_dispensa():
    conn = get_db()
    prodotti = conn.execute("SELECT * FROM prodotti ORDER BY scadenza ASC NULLS LAST").fetchall()
    conn.close()

    oggi = datetime.now().date()
    opts = get_options()
    giorni_soglia = opts.get("giorni_alert_scadenza", 3)
    token = opts.get("telegram_token", "")
    chat_id_raw = opts.get("telegram_chat_id", "")
    if not token or not chat_id_raw:
        return jsonify({"ok": False, "errore": "Telegram non configurato"})

    chat_ids = [c.strip() for c in str(chat_id_raw).split(",") if c.strip()]
    in_scadenza = []
    esauriti = []
    ok_list = []

    for p in prodotti:
        if p["quantita"] <= 0:
            esauriti.append(p)
            continue
        if p["scadenza"]:
            try:
                scad = datetime.strptime(p["scadenza"], "%Y-%m-%d").date()
                giorni = (scad - oggi).days
                if giorni <= giorni_soglia:
                    in_scadenza.append({"nome": p["nome"], "giorni": giorni, "quantita": p["quantita"]})
                else:
                    ok_list.append(p)
            except Exception:
                ok_list.append(p)
        else:
            ok_list.append(p)

    attivi = len([p for p in prodotti if p["quantita"] > 0])
    msg = f"\U0001f4e6 *Report Dispensa*\n_{datetime.now().strftime('%d/%m/%Y %H:%M')}_\n\n"
    msg += f"*Prodotti in dispensa: {attivi}*"
    if esauriti:
        msg += f" _(+ {len(esauriti)} esauriti)_"
    msg += "\n\n"
    if in_scadenza:
        msg += "⚠️ *In scadenza:*\n"
        for p in in_scadenza:
            if p["giorni"] < 0: label = "scaduto!"
            elif p["giorni"] == 0: label = "scade oggi!"
            elif p["giorni"] == 1: label = "scade domani"
            else: label = f"tra {p['giorni']} giorni"
            msg += f"  • {p['nome']} \xd7{p['quantita']} — _{label}_\n"
        msg += "\n"
    if esauriti:
        msg += "❌ *Esauriti:*\n"
        for p in esauriti:
            msg += f"  • {p['nome']}\n"
        msg += "\n"
    if ok_list:
        msg += "✅ *In dispensa:*\n"
        for p in ok_list:
            msg += f"  • {p['nome']} \xd7{p['quantita']}\n"

    for cid in chat_ids:
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        except Exception as e:
            print(f"Errore Telegram report {cid}: {e}")
    return jsonify({"ok": True, "totale": attivi})

@app.route("/api/barcode-cache/<ean>", methods=["DELETE"])
def elimina_barcode_cache(ean):
    conn = get_db()
    conn.execute("DELETE FROM barcode_cache WHERE ean = ?", (ean,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/statistiche", methods=["GET"])
def statistiche():
    conn = get_db()
    oggi = datetime.now().date()
    mese_fa = (oggi.replace(day=1)).strftime("%Y-%m-%d")

    acquisti = conn.execute("SELECT COUNT(*) as n FROM storico_movimenti WHERE tipo='acquisto'").fetchone()["n"]
    consumi = conn.execute("SELECT COUNT(*) as n FROM storico_movimenti WHERE tipo='consumo'").fetchone()["n"]
    eliminati = conn.execute("SELECT COUNT(*) as n FROM storico_movimenti WHERE tipo='eliminato'").fetchone()["n"]
    top_acquistati = conn.execute("""
        SELECT nome, marca, SUM(quantita) as totale FROM storico_movimenti WHERE tipo='acquisto'
        GROUP BY ean ORDER BY totale DESC LIMIT 5
    """).fetchall()
    top_consumati = conn.execute("""
        SELECT nome, marca, SUM(quantita) as totale FROM storico_movimenti WHERE tipo='consumo'
        GROUP BY ean ORDER BY totale DESC LIMIT 5
    """).fetchall()
    acquisti_mese = conn.execute("""
        SELECT COUNT(*) as n FROM storico_movimenti WHERE tipo='acquisto' AND data >= ?
    """, (mese_fa,)).fetchone()["n"]
    per_posizione = conn.execute("""
        SELECT posizione, COUNT(*) as n FROM prodotti WHERE quantita > 0 GROUP BY posizione
    """).fetchall()
    conn.close()

    return jsonify({
        "totali": {"acquisti": acquisti, "consumi": consumi, "eliminati": eliminati, "acquisti_mese": acquisti_mese},
        "top_acquistati": [dict(r) for r in top_acquistati],
        "top_consumati": [dict(r) for r in top_consumati],
        "per_posizione": [dict(r) for r in per_posizione]
    })

@app.route("/api/sync-ha", methods=["GET"])
def sync_ha():
    try:
        aggiorna_sensori_ha()
        return jsonify({"ok": True, "message": "Sensori aggiornati"})
    except Exception as e:
        return jsonify({"ok": False, "errore": str(e)}), 500

if __name__ == "__main__":
    init_db()
    print(f"Dispensa Manager v{APP_VERSION} avviato su porta 5000", flush=True)
    app.run(host="0.0.0.0", port=5000, debug=False)

