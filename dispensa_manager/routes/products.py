import csv
import io
import json
import logging
import os
import threading
from datetime import datetime
from flask import Blueprint, request, jsonify, make_response
from flask_jwt_extended import jwt_required
import requests as http_requests

from database import get_db, get_setting, APP_VERSION

logger = logging.getLogger(__name__)

bp = Blueprint("products", __name__)


# ── Helpers ────────────────────────────────────────────

def _get_days_threshold(conn):
    try:
        return int(get_setting(conn, "giorni_alert_scadenza", "3"))
    except ValueError:
        return 3


def log_movimento(nome, tipo, ean="", marca="", categoria="", quantita=1):
    conn = get_db()
    try:
        with conn:
            conn.execute(
                "INSERT INTO storico_movimenti (ean, nome, marca, categoria, tipo, quantita) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ean, nome, marca, categoria, tipo, quantita),
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
    for p in attivi:
        if p["scadenza"]:
            try:
                scad = datetime.strptime(p["scadenza"], "%Y-%m-%d").date()
                if (scad - oggi).days <= giorni_soglia:
                    in_scadenza.append({"nome": p["nome"], "scadenza": p["scadenza"], "giorni": (scad - oggi).days})
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
            "attributes": {"friendly_name": "Dispensa: prodotti totali", "icon": "mdi:package-variant"},
        },
        "sensor.dispensa_in_scadenza": {
            "state": len(in_scadenza),
            "attributes": {"friendly_name": "Dispensa: in scadenza", "prodotti": in_scadenza, "icon": "mdi:calendar-alert"},
        },
        "sensor.dispensa_esauriti": {
            "state": len(esauriti_list),
            "attributes": {"friendly_name": "Dispensa: esauriti", "prodotti": [p["nome"] for p in esauriti_list], "icon": "mdi:package-variant-remove"},
        },
    }
    for entity_id, payload in stati.items():
        try:
            http_requests.post(f"{ha_url}/api/states/{entity_id}", headers=headers, json=payload, timeout=5)
        except Exception as e:
            logger.error("Errore aggiornamento HA %s: %s", entity_id, e)


def _async(fn, *args, **kwargs):
    threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()


def invia_telegram(testo):
    conn = get_db()
    try:
        token = get_setting(conn, "telegram_token")
        chat_id_raw = get_setting(conn, "telegram_chat_id")
    finally:
        conn.close()
    if not token or not chat_id_raw:
        return
    for cid in [c.strip() for c in str(chat_id_raw).split(",") if c.strip()]:
        try:
            http_requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": cid, "text": testo, "parse_mode": "Markdown"},
                timeout=10,
            )
        except Exception as e:
            logger.error("Errore Telegram %s: %s", cid, e)


def _pos_icon(pos):
    return {"Frigo": "\U0001f9ca", "Freezer": "❄️", "Dispensa": "\U0001f5c4️"}.get(pos, "\U0001f4e6")


# ── Barcode ────────────────────────────────────────────

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
        except Exception:
            continue

    return jsonify({
        "trovato": False, "ean": ean, "nome": "", "marca": "",
        "categoria": "", "immagine_url": "", "nutriscore": "", "nutriments": {},
    })


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


# ── Prodotti ─────────────────────────────────────────────

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
            "SELECT id, nome, marca, quantita, scadenza, posizione FROM prodotti "
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
    if immagine_url and immagine_url.startswith("data:") and len(immagine_url) > 600000:
        immagine_url = ""

    conn = get_db()
    try:
        with conn:
            conn.execute(
                "INSERT INTO prodotti (ean, nome, marca, categoria, immagine_url, quantita, scadenza, note, nutriments, nutriscore, posizione) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    data.get("ean", ""), data.get("nome", "Prodotto"), data.get("marca", ""),
                    data.get("categoria", ""), immagine_url, data.get("quantita", 1),
                    data.get("scadenza"), data.get("note", ""),
                    json.dumps(data.get("nutriments")) if data.get("nutriments") else None,
                    data.get("nutriscore", ""), data.get("posizione", "Dispensa"),
                ),
            )
    finally:
        conn.close()

    log_movimento(
        nome=data.get("nome", "Prodotto"), tipo="acquisto",
        ean=data.get("ean", ""), marca=data.get("marca", ""),
        categoria=data.get("categoria", ""), quantita=data.get("quantita", 1),
    )
    _async(aggiorna_sensori_ha)

    nome = data.get("nome", "Prodotto")
    qty = data.get("quantita", 1)
    pos = data.get("posizione", "Dispensa")
    scad = data.get("scadenza")
    scad_str = (
        f"\n\U0001f4c5 Scade: {datetime.strptime(scad, '%Y-%m-%d').strftime('%d/%m/%Y')}"
        if scad else ""
    )
    _async(invia_telegram, f"➕ *Aggiunto in dispensa*\n\n*{nome}* ×{qty}\n{_pos_icon(pos)} {pos}{scad_str}")

    return jsonify({"ok": True}), 201


@bp.put("/api/prodotti/<int:id>")
@jwt_required()
def aggiorna_prodotto(id):
    data = request.get_json(silent=True) or {}
    p = None
    conn = get_db()
    try:
        p = conn.execute("SELECT * FROM prodotti WHERE id=?", (id,)).fetchone()
        if not p:
            return jsonify({"error": "Prodotto non trovato"}), 404
        fields, values = [], []
        for campo in ["nome", "marca", "quantita", "scadenza", "note", "posizione"]:
            if campo in data:
                fields.append(f"{campo}=?")
                values.append(data[campo])
        if fields:
            values.append(id)
            with conn:
                conn.execute(f"UPDATE prodotti SET {', '.join(fields)} WHERE id=?", values)
    finally:
        conn.close()

    if p and "quantita" in data and data["quantita"] < p["quantita"]:
        log_movimento(
            nome=p["nome"], tipo="consumo", ean=p["ean"] or "",
            marca=p["marca"] or "", categoria=p["categoria"] or "",
            quantita=p["quantita"] - data["quantita"],
        )
    _async(aggiorna_sensori_ha)

    if p:
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
            _async(invia_telegram, f"✏️ *Modificato: {nome}*\n\n{corpo}")

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
        )
        pos = p["posizione"] or "Dispensa"
        _async(invia_telegram, f"\U0001f5d1️ *Eliminato*\n\n*{p['nome']}*\n{_pos_icon(pos)} {pos}")
    _async(aggiorna_sensori_ha)
    return jsonify({"ok": True})


# ── Export / Statistiche ─────────────────────────────────────────

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
    writer.writerow(["ID", "Nome", "Marca", "Categoria", "Quantità", "Scadenza", "Posizione", "EAN", "Note", "Data inserimento"])
    for p in prodotti:
        writer.writerow([
            p["id"], p["nome"], p["marca"] or "", p["categoria"] or "",
            p["quantita"], p["scadenza"] or "", p["posizione"] or "",
            p["ean"] or "", p["note"] or "", p["data_inserimento"] or "",
        ])

    output.seek(0)
    resp = make_response("﻿" + output.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = f'attachment; filename=dispensa_{datetime.now().strftime("%Y%m%d")}.csv'
    return resp


@bp.get("/api/statistiche")
@jwt_required()
def statistiche():
    conn = get_db()
    try:
        oggi = datetime.now().date()
        mese_fa = oggi.replace(day=1).strftime("%Y-%m-%d")

        acquisti = conn.execute("SELECT COUNT(*) as n FROM storico_movimenti WHERE tipo='acquisto'").fetchone()["n"]
        consumi = conn.execute("SELECT COUNT(*) as n FROM storico_movimenti WHERE tipo='consumo'").fetchone()["n"]
        eliminati = conn.execute("SELECT COUNT(*) as n FROM storico_movimenti WHERE tipo='eliminato'").fetchone()["n"]
        acquisti_mese = conn.execute(
            "SELECT COUNT(*) as n FROM storico_movimenti WHERE tipo='acquisto' AND data>=?", (mese_fa,)
        ).fetchone()["n"]
        top_acquistati = conn.execute(
            "SELECT nome, marca, SUM(quantita) as totale FROM storico_movimenti WHERE tipo='acquisto' "
            "GROUP BY ean, nome, marca ORDER BY totale DESC LIMIT 5"
        ).fetchall()
        top_consumati = conn.execute(
            "SELECT nome, marca, SUM(quantita) as totale FROM storico_movimenti WHERE tipo='consumo' "
            "GROUP BY ean, nome, marca ORDER BY totale DESC LIMIT 5"
        ).fetchall()
        per_posizione = conn.execute(
            "SELECT posizione, COUNT(*) as n FROM prodotti WHERE quantita>0 GROUP BY posizione"
        ).fetchall()

        return jsonify({
            "totali": {"acquisti": acquisti, "consumi": consumi, "eliminati": eliminati, "acquisti_mese": acquisti_mese},
            "top_acquistati": [dict(r) for r in top_acquistati],
            "top_consumati": [dict(r) for r in top_consumati],
            "per_posizione": [dict(r) for r in per_posizione],
        })
    finally:
        conn.close()


# ── Alerts / Sync HA ─────────────────────────────────────────────

@bp.get("/api/alerts")
@jwt_required()
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
@jwt_required()
def sync_ha():
    try:
        aggiorna_sensori_ha()
        return jsonify({"ok": True, "message": "Sensori aggiornati"})
    except Exception as e:
        return jsonify({"ok": False, "errore": str(e)}), 500


@bp.get("/api/test-telegram")
@jwt_required()
def test_telegram():
    conn = get_db()
    try:
        token = get_setting(conn, "telegram_token")
        chat_id_raw = get_setting(conn, "telegram_chat_id")
    finally:
        conn.close()

    if not token or not chat_id_raw:
        return jsonify({"ok": False, "errore": "Token o chat_id non configurati"})

    msg = "\U0001f9ea *Test Dispensa Manager*\n\nLe notifiche Telegram funzionano correttamente! ✅"
    risultati = []
    for cid in [c.strip() for c in str(chat_id_raw).split(",") if c.strip()]:
        try:
            r = http_requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"},
                timeout=10,
            )
            risultati.append({"chat_id": cid, "ok": r.status_code == 200})
        except Exception as e:
            risultati.append({"chat_id": cid, "ok": False, "errore": str(e)})
    return jsonify({"risultati": risultati})


@bp.get("/api/report")
@jwt_required()
def report_dispensa():
    conn = get_db()
    try:
        prodotti = conn.execute("SELECT * FROM prodotti ORDER BY scadenza ASC NULLS LAST").fetchall()
        giorni_soglia = _get_days_threshold(conn)
        token = get_setting(conn, "telegram_token")
        chat_id_raw = get_setting(conn, "telegram_chat_id")
    finally:
        conn.close()

    if not token or not chat_id_raw:
        return jsonify({"ok": False, "errore": "Telegram non configurato"})

    oggi = datetime.now().date()
    in_scadenza, esauriti, ok_list = [], [], []

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
            if p["giorni"] < 0: lbl = "scaduto!"
            elif p["giorni"] == 0: lbl = "scade oggi!"
            elif p["giorni"] == 1: lbl = "scade domani"
            else: lbl = f"tra {p['giorni']} giorni"
            msg += f"  • {p['nome']} ×{p['quantita']} — _{lbl}_\n"
        msg += "\n"
    if esauriti:
        msg += "❌ *Esauriti:*\n"
        for p in esauriti:
            msg += f"  • {p['nome']}\n"
        msg += "\n"
    if ok_list:
        msg += "✅ *In dispensa:*\n"
        for p in ok_list:
            msg += f"  • {p['nome']} ×{p['quantita']}\n"

    _async(invia_telegram, msg)
    return jsonify({"ok": True, "totale": attivi})
