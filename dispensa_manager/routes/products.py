import csv
import io
import json
import logging
import os
import threading
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, make_response
from flask_jwt_extended import jwt_required
import requests as http_requests

from database import (
    get_db, get_setting, get_ha_option, APP_VERSION,
    save_image_to_fs, delete_image_from_fs,
)
from auth import api_key_or_jwt

logger = logging.getLogger(__name__)

bp = Blueprint("products", __name__)

# Telegram limita i messaggi a 4096 caratteri
TELEGRAM_MAX_LEN = 4000


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_days_threshold(conn):
    try:
        return int(get_setting(conn, "giorni_alert_scadenza", "3"))
    except ValueError:
        return 3


def log_movimento(nome, tipo, ean="", marca="", categoria="", quantita=1, prezzo=None):
    conn = get_db()
    try:
        with conn:
            conn.execute(
                "INSERT INTO storico_movimenti (ean, nome, marca, categoria, tipo, quantita, prezzo) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ean, nome, marca, categoria, tipo, quantita, prezzo),
            )
    except Exception as e:
        logger.error("Errore log movimento: %s", e)
    finally:
        conn.close()


def aggiorna_sensori_ha():
    ha_url = os.environ.get("HA_URL", "http://supervisor/core")
    ha_token = os.environ.get("SUPERVISOR_TOKEN", "")

    conn = get_db()
    try:
        tutti = conn.execute("SELECT * FROM prodotti ORDER BY scadenza ASC").fetchall()
        giorni_soglia = _get_days_threshold(conn)
    finally:
        conn.close()

    oggi = datetime.now().date()
    attivi = [p for p in tutti if p["quantita"] > 0]
    esauriti_list = [p for p in tutti if p["quantita"] <= 0]

    in_scadenza = []
    scaduti = []
    for p in attivi:
        if p["scadenza"]:
            try:
                scad = datetime.strptime(p["scadenza"], "%Y-%m-%d").date()
                giorni = (scad - oggi).days
                if giorni < 0:
                    scaduti.append({"nome": p["nome"], "scadenza": p["scadenza"], "giorni": giorni})
                elif giorni <= giorni_soglia:
                    in_scadenza.append({"nome": p["nome"], "scadenza": p["scadenza"], "giorni": giorni})
            except Exception:
                pass

    conn2 = get_db()
    try:
        with conn2:
            for p in esauriti_list:
                esistente = conn2.execute(
                    "SELECT id FROM lista_spesa WHERE ean=? AND completato=0", (p["ean"] or "",)
                ).fetchone()
                if not esistente:
                    conn2.execute(
                        "INSERT INTO lista_spesa (nome, ean, marca) VALUES (?, ?, ?)",
                        (p["nome"], p["ean"] or "", p["marca"] or ""),
                    )
    finally:
        conn2.close()

    if not ha_token:
        return

    headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
    stati = {
        "sensor.dispensa_totale_prodotti": {
            "state": len(attivi),
            "attributes": {"friendly_name": "Dispensa: prodotti totali", "icon": "mdi:package-variant", "unit_of_measurement": "prodotti"},
        },
        "sensor.dispensa_in_scadenza": {
            "state": len(in_scadenza),
            "attributes": {"friendly_name": "Dispensa: in scadenza", "prodotti": in_scadenza, "icon": "mdi:calendar-alert", "unit_of_measurement": "prodotti"},
        },
        "sensor.dispensa_scaduti": {
            "state": len(scaduti),
            "attributes": {"friendly_name": "Dispensa: scaduti", "prodotti": scaduti, "icon": "mdi:calendar-remove", "unit_of_measurement": "prodotti"},
        },
        "sensor.dispensa_esauriti": {
            "state": len(esauriti_list),
            "attributes": {"friendly_name": "Dispensa: esauriti", "prodotti": [p["nome"] for p in esauriti_list], "icon": "mdi:package-variant-remove", "unit_of_measurement": "prodotti"},
        },
    }
    for entity_id, payload in stati.items():
        try:
            http_requests.post(f"{ha_url}/api/states/{entity_id}", headers=headers, json=payload, timeout=5)
        except Exception as e:
            logger.error("Errore aggiornamento HA %s: %s", entity_id, e)


def _async(fn, *args, **kwargs):
    threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()


def invia_telegram(testo, categoria=None):
    """categoria opzionale ('acquisto', 'modifica', 'eliminazione') → check setting notif_telegram_<categoria>"""
    token = get_ha_option("telegram_token", "")
    chat_id_raw = get_ha_option("telegram_chat_id", "")
    if not token or not chat_id_raw:
        logger.warning("Telegram non configurato (token o chat_id mancanti nelle opzioni HA)")
        return
    if categoria:
        conn = get_db()
        try:
            enabled = get_setting(conn, f"notif_telegram_{categoria}", "1")
            if enabled != "1":
                logger.info("Notifica Telegram '%s' disabilitata da settings", categoria)
                return
        finally:
            conn.close()
    if len(testo) > TELEGRAM_MAX_LEN:
        logger.warning("Messaggio Telegram troppo lungo (%d char) — troncato a %d", len(testo), TELEGRAM_MAX_LEN)
        testo = testo[:TELEGRAM_MAX_LEN - 60] + "\n\n_…messaggio troncato, apri l'app per il dettaglio_"
    for cid in [c.strip() for c in str(chat_id_raw).split(",") if c.strip()]:
        try:
            r = http_requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": cid, "text": testo, "parse_mode": "Markdown"},
                timeout=10,
            )
            if r.status_code != 200:
                logger.error("Telegram chat %s respinto (HTTP %d): %s", cid, r.status_code, r.text[:300])
            else:
                logger.info("Telegram chat %s OK (%d char, cat=%s)", cid, len(testo), categoria or "default")
        except Exception as e:
            logger.error("Errore Telegram %s: %s", cid, e)


def _pos_icon(pos):
    return {"Frigo": "\U0001f9ca", "Freezer": "❄️", "Dispensa": "\U0001f5c4️"}.get(pos, "\U0001f4e6")


def _handle_immagine(immagine_url: str, prodotto_id: int) -> str:
    """Se immagine è data-URL base64 la sposta su filesystem.
    Se è URL esterna (http://...) o path /dispensa-images/... rimane invariata."""
    if not immagine_url:
        return ""
    if immagine_url.startswith("data:"):
        return save_image_to_fs(immagine_url, prodotto_id)
    return immagine_url


# ── Barcode ──────────────────────────────────────────────────────────────────

@bp.get("/api/barcode/<ean>")
@jwt_required()
def cerca_barcode(ean):
    headers = {"User-Agent": f"DispensaManager/{APP_VERSION}"}
    conn = get_db()
    try:
        cached = conn.execute("SELECT * FROM barcode_cache WHERE ean=?", (ean,)).fetchone()
    finally:
        conn.close()

    if cached:
        nutriments = None
        if cached["nutriments"]:
            try:
                nutriments = json.loads(cached["nutriments"])
            except Exception:
                pass
        return jsonify({
            "trovato": True, "fonte": "cache_locale", "ean": ean,
            "nome": cached["nome"], "marca": cached["marca"] or "",
            "categoria": cached["categoria"] or "", "immagine_url": cached["immagine_url"] or "",
            "nutriscore": cached["nutriscore"] or "", "nutriments": nutriments or {},
        })

    databases = [
        f"https://world.openfoodfacts.org/api/v2/product/{ean}.json",
        f"https://world.openproductsfacts.org/api/v2/product/{ean}.json",
        f"https://world.openbeautyfacts.org/api/v2/product/{ean}.json",
    ]
    for url in databases:
        try:
            r = http_requests.get(url, timeout=8, headers=headers)
            data = r.json()
            if data.get("status") == 1:
                p = data["product"]
                nutriments = p.get("nutriments", {})
                return jsonify({
                    "trovato": True, "fonte": "online", "ean": ean,
                    "nome": p.get("product_name_it") or p.get("product_name", "Prodotto sconosciuto"),
                    "marca": (p.get("brands", "").split(",")[0].strip()),
                    "categoria": (p.get("categories_tags", [""])[0].replace("en:", "").replace("-", " ")
                                  if p.get("categories_tags") else ""),
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
                    },
                })
        except Exception as e:
            logger.warning("Errore lookup barcode %s su %s: %s", ean, url, e)
            continue

    return jsonify({
        "trovato": False, "ean": ean, "nome": "", "marca": "",
        "categoria": "", "immagine_url": "", "nutriscore": "", "nutriments": {},
    }), 404


@bp.post("/api/barcode-cache")
@jwt_required()
def salva_barcode_cache():
    data = request.get_json(silent=True) or {}
    ean = data.get("ean", "")
    if not ean or ean.startswith("MANUAL-"):
        return jsonify({"ok": False, "errore": "EAN non valido"})
    conn = get_db()
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO barcode_cache (ean, nome, marca, categoria, immagine_url, nutriscore, nutriments) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ean, data.get("nome", ""), data.get("marca", ""), data.get("categoria", ""),
                 data.get("immagine_url", ""), data.get("nutriscore", ""),
                 json.dumps(data.get("nutriments")) if data.get("nutriments") else None),
            )
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.delete("/api/barcode-cache/<ean>")
@jwt_required()
def elimina_barcode_cache(ean):
    conn = get_db()
    try:
        with conn:
            conn.execute("DELETE FROM barcode_cache WHERE ean=?", (ean,))
        return jsonify({"ok": True})
    finally:
        conn.close()


# ── Prodotti ─────────────────────────────────────────────────────────────────

@bp.get("/api/prodotti")
@jwt_required()
def lista_prodotti():
    limit = request.args.get("limit", type=int)
    offset = request.args.get("offset", 0, type=int)
    conn = get_db()
    try:
        if limit:
            rows = conn.execute(
                "SELECT * FROM prodotti ORDER BY scadenza ASC NULLS LAST LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM prodotti ORDER BY scadenza ASC NULLS LAST").fetchall()
    finally:
        conn.close()

    oggi = datetime.now().date()
    result = []
    for p in rows:
        d = dict(p)
        if d["scadenza"]:
            try:
                scad = datetime.strptime(d["scadenza"], "%Y-%m-%d").date()
                d["giorni_alla_scadenza"] = (scad - oggi).days
            except Exception:
                d["giorni_alla_scadenza"] = None
        else:
            d["giorni_alla_scadenza"] = None
        if isinstance(d.get("nutriments"), str):
            try:
                d["nutriments"] = json.loads(d["nutriments"])
            except Exception:
                d["nutriments"] = None
        result.append(d)
    return jsonify(result)


@bp.get("/api/prodotti/by-ean/<ean>")
@jwt_required()
def prodotti_by_ean(ean):
    conn = get_db()
    try:
        items = conn.execute(
            "SELECT id, nome, marca, quantita, scadenza, posizione, prezzo FROM prodotti "
            "WHERE ean=? AND quantita>0 ORDER BY scadenza ASC",
            (ean,),
        ).fetchall()
        return jsonify([dict(i) for i in items])
    finally:
        conn.close()


@bp.get("/api/prodotti/esauriti")
@jwt_required()
def lista_esauriti():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM prodotti WHERE quantita<=0 ORDER BY nome ASC").fetchall()
        return jsonify([dict(p) for p in rows])
    finally:
        conn.close()


@bp.post("/api/prodotti")
@jwt_required()
def aggiungi_prodotto():
    data = request.get_json(silent=True) or {}
    immagine_url = data.get("immagine_url", "")
    # Salva prima senza immagine pesante (verrà spostata su FS post-insert)
    prezzo = data.get("prezzo")
    try:
        prezzo = float(prezzo) if prezzo not in (None, "") else None
    except (ValueError, TypeError):
        prezzo = None

    conn = get_db()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO prodotti (ean, nome, marca, categoria, immagine_url, quantita, scadenza, note, nutriments, nutriscore, posizione, prezzo) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    data.get("ean", ""), data.get("nome", "Prodotto"), data.get("marca", ""),
                    data.get("categoria", ""), "", data.get("quantita", 1),
                    data.get("scadenza"), data.get("note", ""),
                    json.dumps(data.get("nutriments")) if data.get("nutriments") else None,
                    data.get("nutriscore", ""), data.get("posizione", "Dispensa"),
                    prezzo,
                ),
            )
            new_id = cur.lastrowid
            # Gestione immagine: data-URL → filesystem, URL esterna → invariata
            final_url = _handle_immagine(immagine_url, new_id)
            if final_url:
                conn.execute("UPDATE prodotti SET immagine_url=? WHERE id=?", (final_url, new_id))
    finally:
        conn.close()

    log_movimento(
        nome=data.get("nome", "Prodotto"), tipo="acquisto",
        ean=data.get("ean", ""), marca=data.get("marca", ""),
        categoria=data.get("categoria", ""), quantita=data.get("quantita", 1),
        prezzo=prezzo,
    )
    _async(aggiorna_sensori_ha)

    nome = data.get("nome", "Prodotto")
    qty = data.get("quantita", 1)
    pos = data.get("posizione", "Dispensa")
    scad = data.get("scadenza")
    scad_str = (f"\n\U0001f4c5 Scade: {datetime.strptime(scad, '%Y-%m-%d').strftime('%d/%m/%Y')}" if scad else "")
    prezzo_str = f"\n💰 {prezzo:.2f}€" if prezzo else ""
    _async(invia_telegram, f"➕ *Aggiunto in dispensa*\n\n*{nome}* ×{qty}\n{_pos_icon(pos)} {pos}{scad_str}{prezzo_str}", "acquisto")

    return jsonify({"ok": True, "id": new_id}), 201


@bp.put("/api/prodotti/<int:id>")
@jwt_required()
def aggiorna_prodotto(id):
    data = request.get_json(silent=True) or {}
    skip_log = bool(data.get("_skip_log", False))

    p = None
    conn = get_db()
    try:
        p = conn.execute("SELECT * FROM prodotti WHERE id=?", (id,)).fetchone()
        if not p:
            return jsonify({"error": "Prodotto non trovato"}), 404

        # Gestione immagine se passata (data-URL → FS, URL esterna → invariata)
        if "immagine_url" in data:
            old_url = p["immagine_url"] or ""
            new_url_raw = data.get("immagine_url", "")
            if new_url_raw and new_url_raw.startswith("data:"):
                # Cancella vecchia se era su FS
                if old_url and old_url.startswith("/dispensa-images/"):
                    delete_image_from_fs(old_url)
                data["immagine_url"] = save_image_to_fs(new_url_raw, id)
            # Se new_url è URL normale, lascia stare data come è

        fields, values = [], []
        for campo in ["nome", "marca", "ean", "quantita", "scadenza", "note", "posizione", "immagine_url", "prezzo"]:
            if campo in data:
                fields.append(f"{campo}=?")
                val = data[campo]
                if campo == "prezzo":
                    try:
                        val = float(val) if val not in (None, "") else None
                    except (ValueError, TypeError):
                        val = None
                values.append(val)
        if fields:
            values.append(id)
            with conn:
                conn.execute(f"UPDATE prodotti SET {', '.join(fields)} WHERE id=?", values)
    finally:
        conn.close()

    if p and "quantita" in data and not skip_log:
        diff = data["quantita"] - p["quantita"]
        if diff < 0:
            log_movimento(
                nome=p["nome"], tipo="consumo", ean=p["ean"] or "",
                marca=p["marca"] or "", categoria=p["categoria"] or "",
                quantita=-diff, prezzo=p["prezzo"] if "prezzo" in p.keys() else None,
            )
        elif diff > 0:
            log_movimento(
                nome=p["nome"], tipo="acquisto", ean=p["ean"] or "",
                marca=p["marca"] or "", categoria=p["categoria"] or "",
                quantita=diff, prezzo=p["prezzo"] if "prezzo" in p.keys() else None,
            )
    _async(aggiorna_sensori_ha)

    if p and not skip_log:
        cambiamenti = []
        nome = data.get("nome", p["nome"])
        if "quantita" in data and data["quantita"] != p["quantita"]:
            cambiamenti.append(f"Quantità: {p['quantita']} → {data['quantita']}")
        if "scadenza" in data and data["scadenza"] != p["scadenza"]:
            def fmt(s): return datetime.strptime(s, "%Y-%m-%d").strftime("%d/%m/%Y") if s else "—"
            cambiamenti.append(f"Scadenza: {fmt(p['scadenza'])} → {fmt(data['scadenza'])}")
        if "posizione" in data and data["posizione"] != (p["posizione"] or "Dispensa"):
            cambiamenti.append(f"Posizione: {p['posizione'] or 'Dispensa'} → {data['posizione']}")
        if "nome" in data and data["nome"] != p["nome"]:
            cambiamenti.append(f"Nome: {p['nome']} → {data['nome']}")
        if "note" in data and data["note"] != (p["note"] or ""):
            cambiamenti.append("Note aggiornate")
        if cambiamenti:
            corpo = "\n".join(f"• {c}" for c in cambiamenti)
            _async(invia_telegram, f"✏️ *Modificato: {nome}*\n\n{corpo}", "modifica")

    return jsonify({"ok": True})


@bp.delete("/api/prodotti/<int:id>")
@jwt_required()
def elimina_prodotto(id):
    p = None
    conn = get_db()
    try:
        p = conn.execute("SELECT * FROM prodotti WHERE id=?", (id,)).fetchone()
        with conn:
            conn.execute("DELETE FROM prodotti WHERE id=?", (id,))
    finally:
        conn.close()

    if p:
        log_movimento(
            nome=p["nome"], tipo="eliminato", ean=p["ean"] or "",
            marca=p["marca"] or "", categoria=p["categoria"] or "", quantita=p["quantita"],
            prezzo=p["prezzo"] if "prezzo" in p.keys() else None,
        )
        # Rimuovi immagine da FS se presente
        if p["immagine_url"]:
            delete_image_from_fs(p["immagine_url"])
        pos = p["posizione"] or "Dispensa"
        _async(invia_telegram, f"\U0001f5d1️ *Eliminato*\n\n*{p['nome']}*\n{_pos_icon(pos)} {pos}", "eliminazione")
    _async(aggiorna_sensori_ha)
    return jsonify({"ok": True})


# ── Bulk operations (multi-select) ──────────────────────────────────────────

@bp.post("/api/prodotti/bulk")
@jwt_required()
def bulk_action():
    """Azione su multipli prodotti contemporaneamente.
    Body: {"ids": [1,2,3], "action": "delete"|"set_posizione"|"extend_scadenza", "value": <dipende>}
    """
    data = request.get_json(silent=True) or {}
    ids = data.get("ids", [])
    action = data.get("action")
    value = data.get("value")

    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "ids deve essere una lista non vuota"}), 400
    if action not in ("delete", "set_posizione", "extend_scadenza"):
        return jsonify({"error": f"Azione '{action}' non supportata"}), 400

    # Sanifica ids → solo interi
    ids = [int(i) for i in ids if isinstance(i, (int, str)) and str(i).isdigit()]
    if not ids:
        return jsonify({"error": "Nessun id valido"}), 400

    conn = get_db()
    affected = 0
    try:
        placeholders = ",".join("?" * len(ids))
        prodotti = conn.execute(f"SELECT * FROM prodotti WHERE id IN ({placeholders})", ids).fetchall()

        if action == "delete":
            with conn:
                conn.execute(f"DELETE FROM prodotti WHERE id IN ({placeholders})", ids)
            # Log + image cleanup
            for p in prodotti:
                log_movimento(
                    nome=p["nome"], tipo="eliminato", ean=p["ean"] or "",
                    marca=p["marca"] or "", categoria=p["categoria"] or "",
                    quantita=p["quantita"],
                )
                if p["immagine_url"]:
                    delete_image_from_fs(p["immagine_url"])
            affected = len(prodotti)
            _async(invia_telegram, f"🗑️ *Eliminazione massiva*\n\n{affected} prodotti rimossi dalla dispensa", "eliminazione")

        elif action == "set_posizione":
            if value not in ("Dispensa", "Frigo", "Freezer"):
                return jsonify({"error": "value deve essere Dispensa|Frigo|Freezer"}), 400
            with conn:
                cur = conn.execute(
                    f"UPDATE prodotti SET posizione=? WHERE id IN ({placeholders})",
                    [value] + ids,
                )
                affected = cur.rowcount
            _async(invia_telegram, f"📍 *Spostamento massivo*\n\n{affected} prodotti → {value}", "modifica")

        elif action == "extend_scadenza":
            # value = giorni da aggiungere alla scadenza esistente
            try:
                giorni = int(value)
            except (ValueError, TypeError):
                return jsonify({"error": "value deve essere intero (giorni da aggiungere)"}), 400
            with conn:
                # Solo per prodotti con scadenza
                cur = conn.execute(
                    f"UPDATE prodotti SET scadenza=date(scadenza, '+{giorni} days') "
                    f"WHERE id IN ({placeholders}) AND scadenza IS NOT NULL",
                    ids,
                )
                affected = cur.rowcount
            _async(invia_telegram, f"📅 *Modifica scadenze*\n\n{affected} prodotti: +{giorni} giorni", "modifica")
    finally:
        conn.close()

    _async(aggiorna_sensori_ha)
    return jsonify({"ok": True, "affected": affected, "action": action})


# ── Export / Statistiche ─────────────────────────────────────────────────────

@bp.get("/api/export-csv")
@jwt_required()
def export_csv():
    conn = get_db()
    try:
        prodotti = conn.execute("SELECT * FROM prodotti ORDER BY nome ASC").fetchall()
    finally:
        conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Nome", "Marca", "Categoria", "Quantità", "Scadenza", "Posizione", "EAN", "Note", "Prezzo", "Data inserimento"])
    for p in prodotti:
        writer.writerow([
            p["id"], p["nome"], p["marca"] or "", p["categoria"] or "",
            p["quantita"], p["scadenza"] or "", p["posizione"] or "",
            p["ean"] or "", p["note"] or "",
            p["prezzo"] if "prezzo" in p.keys() and p["prezzo"] else "",
            p["data_inserimento"] or "",
        ])

    output.seek(0)
    resp = make_response("﻿" + output.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = f'attachment; filename=dispensa_{datetime.now().strftime("%Y%m%d")}.csv'
    return resp


@bp.get("/api/statistiche")
@jwt_required()
def statistiche():
    """Statistiche aggregate con focus anti-spreco e trend temporali."""
    conn = get_db()
    try:
        oggi = datetime.now().date()
        mese_corrente = oggi.replace(day=1).strftime("%Y-%m-%d")
        sei_mesi_fa = (oggi - timedelta(days=180)).strftime("%Y-%m-%d")
        anno_fa = (oggi - timedelta(days=365)).strftime("%Y-%m-%d")

        # Totali assoluti
        acquisti = conn.execute("SELECT COUNT(*) as n FROM storico_movimenti WHERE tipo='acquisto'").fetchone()["n"]
        consumi = conn.execute("SELECT COUNT(*) as n FROM storico_movimenti WHERE tipo='consumo'").fetchone()["n"]
        eliminati = conn.execute("SELECT COUNT(*) as n FROM storico_movimenti WHERE tipo='eliminato'").fetchone()["n"]
        acquisti_mese = conn.execute(
            "SELECT COUNT(*) as n FROM storico_movimenti WHERE tipo='acquisto' AND data>=?", (mese_corrente,)
        ).fetchone()["n"]
        eliminati_mese = conn.execute(
            "SELECT COUNT(*) as n FROM storico_movimenti WHERE tipo='eliminato' AND data>=?", (mese_corrente,)
        ).fetchone()["n"]
        consumi_mese = conn.execute(
            "SELECT COUNT(*) as n FROM storico_movimenti WHERE tipo='consumo' AND data>=?", (mese_corrente,)
        ).fetchone()["n"]

        # Top 5
        top_acquistati = conn.execute(
            "SELECT nome, marca, SUM(quantita) as totale FROM storico_movimenti WHERE tipo='acquisto' "
            "GROUP BY ean, nome, marca ORDER BY totale DESC LIMIT 5"
        ).fetchall()
        top_consumati = conn.execute(
            "SELECT nome, marca, SUM(quantita) as totale FROM storico_movimenti WHERE tipo='consumo' "
            "GROUP BY ean, nome, marca ORDER BY totale DESC LIMIT 5"
        ).fetchall()
        top_sprecati = conn.execute(
            "SELECT nome, marca, SUM(quantita) as totale FROM storico_movimenti WHERE tipo='eliminato' "
            "GROUP BY ean, nome, marca ORDER BY totale DESC LIMIT 5"
        ).fetchall()
        per_posizione = conn.execute(
            "SELECT posizione, COUNT(*) as n FROM prodotti WHERE quantita>0 GROUP BY posizione"
        ).fetchall()

        # Trend mensile ultimi 6 mesi (per chart line)
        trend_rows = conn.execute(
            "SELECT strftime('%Y-%m', data) as mese, tipo, COUNT(*) as n "
            "FROM storico_movimenti WHERE data >= ? "
            "GROUP BY mese, tipo ORDER BY mese ASC",
            (sei_mesi_fa,),
        ).fetchall()
        trend = {}
        for r in trend_rows:
            mese = r["mese"]
            if mese not in trend:
                trend[mese] = {"acquisto": 0, "consumo": 0, "eliminato": 0}
            trend[mese][r["tipo"]] = r["n"]

        # Anti-spreco: % spreco vs consumi totali ultimi 6 mesi
        spreco_6m = conn.execute(
            "SELECT COUNT(*) as n FROM storico_movimenti WHERE tipo='eliminato' AND data>=?", (sei_mesi_fa,)
        ).fetchone()["n"]
        consumo_6m = conn.execute(
            "SELECT COUNT(*) as n FROM storico_movimenti WHERE tipo='consumo' AND data>=?", (sei_mesi_fa,)
        ).fetchone()["n"]
        totale_6m = spreco_6m + consumo_6m
        spreco_pct = round((spreco_6m / totale_6m * 100), 1) if totale_6m > 0 else 0

        # Categoria più sprecata (ultimi 6 mesi)
        top_categorie_sprecate = conn.execute(
            "SELECT categoria, COUNT(*) as n FROM storico_movimenti "
            "WHERE tipo='eliminato' AND data>=? AND categoria != '' "
            "GROUP BY categoria ORDER BY n DESC LIMIT 3",
            (sei_mesi_fa,),
        ).fetchall()

        # Spesa stimata mese corrente (solo se prezzi presenti)
        spesa_mese = conn.execute(
            "SELECT COALESCE(SUM(quantita * prezzo), 0) as totale FROM storico_movimenti "
            "WHERE tipo='acquisto' AND data>=? AND prezzo IS NOT NULL", (mese_corrente,)
        ).fetchone()["totale"]
        spreco_mese_eur = conn.execute(
            "SELECT COALESCE(SUM(quantita * prezzo), 0) as totale FROM storico_movimenti "
            "WHERE tipo='eliminato' AND data>=? AND prezzo IS NOT NULL", (mese_corrente,)
        ).fetchone()["totale"]

        return jsonify({
            "totali": {
                "acquisti": acquisti, "consumi": consumi, "eliminati": eliminati,
                "acquisti_mese": acquisti_mese, "eliminati_mese": eliminati_mese, "consumi_mese": consumi_mese,
            },
            "top_acquistati": [dict(r) for r in top_acquistati],
            "top_consumati": [dict(r) for r in top_consumati],
            "top_sprecati": [dict(r) for r in top_sprecati],
            "per_posizione": [dict(r) for r in per_posizione],
            "trend_6mesi": trend,
            "spreco": {
                "percentuale": spreco_pct,
                "eliminati_6m": spreco_6m,
                "consumati_6m": consumo_6m,
                "top_categorie": [dict(r) for r in top_categorie_sprecate],
            },
            "spesa_stimata": {
                "mese_corrente": round(spesa_mese, 2),
                "spreco_mese_corrente": round(spreco_mese_eur, 2),
            },
        })
    finally:
        conn.close()


# ── Alerts / Sync HA ─────────────────────────────────────────────────────────

@bp.get("/api/alerts")
@api_key_or_jwt
def invia_alerts():
    conn = get_db()
    try:
        prodotti = conn.execute("SELECT * FROM prodotti ORDER BY scadenza ASC").fetchall()
        giorni_soglia = _get_days_threshold(conn)
    finally:
        conn.close()

    oggi = datetime.now().date()
    in_scadenza, esauriti = [], []

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
            if p["giorni"] < 0: lbl = "già scaduto!"
            elif p["giorni"] == 0: lbl = "scade oggi!"
            elif p["giorni"] == 1: lbl = "scade domani"
            else: lbl = f"tra {p['giorni']} giorni"
            msg += f"  • {p['nome']} — _{lbl}_\n"
        msg += "\n"
    if esauriti:
        msg += "❌ *Esauriti:*\n"
        for nome in esauriti:
            msg += f"  • {nome}\n"

    _async(invia_telegram, msg)
    _async(aggiorna_sensori_ha)
    return jsonify({"ok": True, "notifica_inviata": True, "in_scadenza": len(in_scadenza), "esauriti": len(esauriti)})


@bp.get("/api/sync-ha")
@api_key_or_jwt
def sync_ha():
    try:
        aggiorna_sensori_ha()
        return jsonify({"ok": True, "message": "Sensori aggiornati"})
    except Exception as e:
        return jsonify({"ok": False, "errore": str(e)}), 500


@bp.get("/api/test-telegram")
@api_key_or_jwt
def test_telegram():
    token = get_ha_option("telegram_token", "")
    chat_id_raw = get_ha_option("telegram_chat_id", "")

    if not token or not chat_id_raw:
        return jsonify({"ok": False, "errore": "Token o chat_id non configurati nelle opzioni HA addon"})

    msg = "\U0001f9ea *Test Dispensa Manager*\n\nLe notifiche Telegram funzionano correttamente! ✅"
    risultati = []
    for cid in [c.strip() for c in str(chat_id_raw).split(",") if c.strip()]:
        try:
            r = http_requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"},
                timeout=10,
            )
            risultati.append({"chat_id": cid, "ok": r.status_code == 200, "http_status": r.status_code})
        except Exception as e:
            risultati.append({"chat_id": cid, "ok": False, "errore": str(e)})
    return jsonify({"risultati": risultati})


@bp.get("/api/report")
@api_key_or_jwt
def report_dispensa():
    """Report riassuntivo dispensa via Telegram (compatto, non elenca tutti i prodotti OK)."""
    token = get_ha_option("telegram_token", "")
    chat_id_raw = get_ha_option("telegram_chat_id", "")

    conn = get_db()
    try:
        prodotti = conn.execute("SELECT * FROM prodotti ORDER BY scadenza ASC NULLS LAST").fetchall()
        giorni_soglia = _get_days_threshold(conn)
    finally:
        conn.close()

    if not token or not chat_id_raw:
        return jsonify({"ok": False, "errore": "Telegram non configurato nelle opzioni HA addon"})

    oggi = datetime.now().date()
    in_scadenza, scaduti, esauriti = [], [], []
    totale_ok = 0

    for p in prodotti:
        if p["quantita"] <= 0:
            esauriti.append(p)
            continue
        if p["scadenza"]:
            try:
                scad = datetime.strptime(p["scadenza"], "%Y-%m-%d").date()
                giorni = (scad - oggi).days
                if giorni < 0:
                    scaduti.append({"nome": p["nome"], "giorni": giorni, "quantita": p["quantita"]})
                elif giorni <= giorni_soglia:
                    in_scadenza.append({"nome": p["nome"], "giorni": giorni, "quantita": p["quantita"]})
                else:
                    totale_ok += 1
            except Exception:
                totale_ok += 1
        else:
            totale_ok += 1

    attivi = len([p for p in prodotti if p["quantita"] > 0])

    msg = f"\U0001f4e6 *Report Dispensa*\n_{datetime.now().strftime('%d/%m/%Y %H:%M')}_\n\n"
    msg += f"📊 *Riepilogo*\n"
    msg += f"  • Totale: *{attivi}* prodotti\n"
    msg += f"  • OK: {totale_ok}\n"
    if scaduti:
        msg += f"  • 🔴 Scaduti: {len(scaduti)}\n"
    if in_scadenza:
        msg += f"  • ⚠️ In scadenza: {len(in_scadenza)}\n"
    if esauriti:
        msg += f"  • 🛒 Esauriti: {len(esauriti)}\n"
    msg += "\n"

    if scaduti:
        msg += "🔴 *Scaduti:*\n"
        for p in scaduti[:30]:
            gg = abs(p["giorni"])
            lbl = "ieri" if gg == 1 else f"{gg} giorni fa"
            msg += f"  • {p['nome']} ×{p['quantita']} — _scaduto {lbl}_\n"
        if len(scaduti) > 30:
            msg += f"  _…e altri {len(scaduti) - 30}_\n"
        msg += "\n"

    if in_scadenza:
        msg += "⚠️ *In scadenza:*\n"
        for p in in_scadenza[:30]:
            if p["giorni"] == 0: lbl = "scade oggi!"
            elif p["giorni"] == 1: lbl = "scade domani"
            else: lbl = f"tra {p['giorni']} giorni"
            msg += f"  • {p['nome']} ×{p['quantita']} — _{lbl}_\n"
        if len(in_scadenza) > 30:
            msg += f"  _…e altri {len(in_scadenza) - 30}_\n"
        msg += "\n"

    if esauriti:
        msg += "🛒 *Esauriti (lista spesa):*\n"
        for p in esauriti[:30]:
            msg += f"  • {p['nome']}\n"
        if len(esauriti) > 30:
            msg += f"  _…e altri {len(esauriti) - 30}_\n"

    _async(invia_telegram, msg)
    return jsonify({"ok": True, "totale": attivi, "scaduti": len(scaduti), "in_scadenza": len(in_scadenza), "esauriti": len(esauriti)})
