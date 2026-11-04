"""Nuovo inventario e raccolta dei dati dei prodotti gia' in casa (v2.5.0)."""
import json
import logging
import threading
import time
from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
import requests as http_requests

from auth import admin_required
from database import get_db, get_setting, APP_VERSION
from dieta import valuta_dieta
import inventario as inv
from routes.products import OFF_CAMPI, _dati_da_off, _async, aggiorna_sensori_ha

logger = logging.getLogger(__name__)

bp = Blueprint("inventario", __name__)

PAUSA_OFF = 1.5          # misurato: a una richiesta ogni 1,5 s (circa 40 al minuto) Open Food Facts risponde sempre; a 0,7 s dava 429
BASI_OFF = ("world.openfoodfacts.org", "world.openproductsfacts.org", "world.openbeautyfacts.org")


@bp.get("/api/inventario")
@jwt_required()
def get_inventario():
    conn = get_db()
    try:
        return jsonify({**inv.stato(conn), "anteprima": inv.anteprima(conn),
                        "dieta_profilo": get_setting(conn, "dieta_profilo", "vegana")})
    finally:
        conn.close()


@bp.post("/api/dieta/valuta")
@jwt_required()
def valuta():
    """Giudizio vegano/vegetariano su un elenco ingredienti scritto o incollato (anteprima mentre lo si inserisce)."""
    d = request.get_json(silent=True) or {}
    return jsonify(valuta_dieta(str(d.get("ingredienti") or "")[:4000], nome=str(d.get("nome") or "")))


@bp.post("/api/inventario/azzera")
@admin_required
def azzera_inventario():
    if str((request.get_json(silent=True) or {}).get("conferma") or "") != "AZZERA":
        return jsonify({"error": "Serve la conferma: scrivi AZZERA"}), 400
    conn = get_db()
    try:
        esito = inv.azzera(conn)
    except Exception as e:
        logger.error("Azzeramento inventario fallito: %s", e)
        return jsonify({"error": "Azzeramento non eseguito: %s" % e}), 500
    finally:
        conn.close()
    _async(aggiorna_sensori_ha)
    avvia_arricchimento()       # i dati nutrizionali e di dieta dei prodotti noti si raccolgono mentre si riscansiona
    return jsonify({"ok": True, **esito})


@bp.post("/api/inventario/annulla")
@admin_required
def annulla_azzeramento():
    lotto = str((request.get_json(silent=True) or {}).get("lotto") or "")
    if not lotto:
        return jsonify({"error": "lotto mancante"}), 400
    conn = get_db()
    try:
        esito = inv.annulla(conn, lotto)
    finally:
        conn.close()
    _async(aggiorna_sensori_ha)
    return jsonify({"ok": True, **esito})


@bp.post("/api/inventario/riscansione")
@admin_required
def imposta_riscansione():
    dati = request.get_json(silent=True) or {}
    if not isinstance(dati.get("attiva"), bool):
        return jsonify({"error": "attiva: true o false"}), 400
    conn = get_db()
    try:
        inv.imposta_riscansione(conn, dati["attiva"])
        return jsonify({"ok": True, **inv.stato(conn)})
    finally:
        conn.close()


# ── Raccolta dei dati dei prodotti gia' presenti ─────────────────────────────

_arr = {"in_corso": False, "totale": 0, "fatti": 0, "trovati": 0, "non_trovati": 0, "errori": 0, "inizio": None, "fine": None}
_arr_lock = threading.Lock()


_pausa = PAUSA_OFF       # pausa tra una richiesta e l'altra: si allunga quando il server dice «troppe richieste» e si accorcia piano piano


def _chiedi(base, ean):
    """(prodotto|None, esito) con esito 'ok', 'assente' o 'errore'. Se il server limita le richieste (429) rallenta e riprova:
    Open Food Facts non dice quanto aspettare, quindi la pausa si adatta da sola al ritmo che accetta."""
    global _pausa
    headers = {"User-Agent": "DispensaManager/%s (https://github.com/domoluigi/Dispensa-Manager)" % APP_VERSION}
    for tentativo in range(5):
        try:
            r = http_requests.get("https://%s/api/v2/product/%s.json" % (base, ean), params={"fields": OFF_CAMPI}, headers=headers, timeout=15)
        except Exception as e:
            logger.warning("Raccolta dati %s su %s: %s", ean, base, type(e).__name__)
            time.sleep(3)
            continue
        if r.status_code == 200:
            _pausa = max(PAUSA_OFF, _pausa * 0.9)
            d = r.json()
            return (d["product"], "ok") if d.get("status") == 1 else (None, "assente")
        if r.status_code == 404:
            return None, "assente"
        _pausa = min(max(_pausa * 2, 1.5), 12)          # 429 o errore del server: si rallenta
        time.sleep(_pausa)
    return None, "errore"


def _salva_dati(conn, ean, dati):
    off_json = json.dumps(dati["off_dati"], ensure_ascii=False)
    nutr = json.dumps(dati["nutriments"])
    with conn:
        conn.execute(
            "UPDATE prodotti SET ingredienti=COALESCE(NULLIF(ingredienti, ''), NULLIF(?, '')), off_dati=?, nova=COALESCE(nova, ?), "
            "nutriscore=COALESCE(NULLIF(nutriscore, ''), ?), nutriments=COALESCE(nutriments, ?) WHERE ean=?",
            (dati["ingredienti"], off_json, dati["nova"], dati["nutriscore"], nutr, ean))
        cache = conn.execute("SELECT 1 FROM barcode_cache WHERE ean=?", (ean,)).fetchone()
        if cache:
            conn.execute(
                "UPDATE barcode_cache SET ingredienti=?, off_dati=?, nova=?, nutriscore=COALESCE(NULLIF(nutriscore, ''), ?), "
                "nutriments=COALESCE(nutriments, ?) WHERE ean=?",
                (dati["ingredienti"] or None, off_json, dati["nova"], dati["nutriscore"], nutr, ean))
        else:       # con la cache la riscansione e' immediata e non chiede niente a Open Food Facts
            p = conn.execute("SELECT nome, marca, categoria, immagine_url FROM prodotti WHERE ean=? ORDER BY id DESC LIMIT 1", (ean,)).fetchone()
            if p:
                conn.execute(
                    "INSERT OR IGNORE INTO barcode_cache (ean, nome, marca, categoria, immagine_url, nutriscore, nutriments, ingredienti, off_dati, nova) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (ean, p["nome"], p["marca"], p["categoria"], p["immagine_url"], dati["nutriscore"], nutr,
                     dati["ingredienti"] or None, off_json, dati["nova"]))


def _segna_controllato(conn, ean):
    with conn:
        conn.execute("UPDATE prodotti SET off_dati='{}' WHERE ean=? AND off_dati IS NULL", (ean,))


def _lavora(eans):
    conn = get_db()
    try:
        for ean in eans:
            prodotto, esito = None, "assente"
            for base in BASI_OFF:
                prodotto, esito = _chiedi(base, ean)
                time.sleep(_pausa)
                if prodotto or esito == "errore":
                    break
            try:
                if prodotto:
                    _salva_dati(conn, ean, _dati_da_off(prodotto))
                    chiave = "trovati"
                elif esito == "assente":
                    _segna_controllato(conn, ean)
                    chiave = "non_trovati"
                else:
                    chiave = "errori"       # resta da fare: alla prossima raccolta
            except Exception as e:
                logger.error("Raccolta dati %s: %s", ean, e)
                chiave = "errori"
            with _arr_lock:
                _arr["fatti"] += 1
                _arr[chiave] += 1
    finally:
        conn.close()
        with _arr_lock:
            _arr["in_corso"] = False
            _arr["fine"] = datetime.now().isoformat(timespec="seconds")
        logger.info("Raccolta dati prodotti finita: %s", {k: v for k, v in _arr.items() if k in ("fatti", "trovati", "non_trovati", "errori")})
        _async(aggiorna_sensori_ha)


def avvia_arricchimento() -> dict:
    """Parte in background: chiede a Open Food Facts ingredienti, valori e analisi per i prodotti con EAN che non li hanno ancora."""
    with _arr_lock:
        if _arr["in_corso"]:
            return dict(_arr)
        conn = get_db()
        try:
            eans = [r["ean"] for r in conn.execute(
                "SELECT DISTINCT ean FROM prodotti WHERE ean IS NOT NULL AND ean<>'' AND ean NOT LIKE 'MANUAL-%' AND off_dati IS NULL ORDER BY ean").fetchall()]
        finally:
            conn.close()
        _arr.update(in_corso=bool(eans), totale=len(eans), fatti=0, trovati=0, non_trovati=0, errori=0,
                    inizio=datetime.now().isoformat(timespec="seconds"), fine=None)
        if eans:
            threading.Thread(target=_lavora, args=(eans,), daemon=True).start()
        return dict(_arr)


@bp.post("/api/inventario/arricchisci")
@jwt_required()
def post_arricchisci():
    return jsonify(avvia_arricchimento())


@bp.get("/api/inventario/arricchimento")
@jwt_required()
def get_arricchimento():
    with _arr_lock:
        return jsonify(dict(_arr))
