import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, verify_jwt_in_request, get_jwt_identity

from database import get_db, get_ha_option
from auth import api_key_or_jwt
from notifiche import chat_ids, invia_a_chat, md_esc, TELEGRAM_MAX_LEN
import spesa as sp
from normalizza import bella, token_chiave
from reparti import reparto_di, ETICHETTA

logger = logging.getLogger(__name__)

bp = Blueprint("shopping", __name__)


def _utente(conn) -> str:
    """Nome di chi sta facendo la richiesta (vuoto per le chiamate con x-api-key)."""
    try:
        verify_jwt_in_request(optional=True)
        ident = get_jwt_identity()
    except Exception:
        ident = None
    if not ident:
        return ""
    r = conn.execute("SELECT username FROM users WHERE id=?", (ident,)).fetchone()
    return r["username"] if r else ""


# ── Vista della schermata: da comprare, carrello, suggeriti ──────────────────

@bp.get("/api/spesa")
@jwt_required()
def get_spesa():
    conn = get_db()
    try:
        da_comprare, carrello = sp.lista(conn)
        sugg = sp.suggeriti(conn)
        return jsonify({
            "da_comprare": da_comprare, "carrello": carrello, "suggeriti": sugg,
            "reparti": sp.elenco_reparti(),
            "conteggi": {"da_comprare": len(da_comprare), "carrello": len(carrello), "suggeriti": len(sugg)},
        })
    finally:
        conn.close()


@bp.get("/api/spesa/conteggi")
@jwt_required()
def get_conteggi():
    conn = get_db()
    try:
        return jsonify(sp.conteggi(conn))
    finally:
        conn.close()


@bp.get("/api/spesa/cerca")
@jwt_required()
def cerca_spesa():
    conn = get_db()
    try:
        return jsonify(sp.cerca(conn, request.args.get("q", "")))
    finally:
        conn.close()


@bp.post("/api/spesa/suggeriti/<int:prodotto_id>/aggiungi")
@jwt_required()
def aggiungi_suggerito(prodotto_id):
    conn = get_db()
    try:
        ris = sp.aggiungi_suggerito(conn, prodotto_id, _utente(conn))
        if ris is None:
            return jsonify({"error": "Prodotto non trovato"}), 404
        return jsonify({"ok": True, **ris})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@bp.post("/api/spesa/suggeriti/<int:prodotto_id>/ignora")
@jwt_required()
def ignora_suggerito(prodotto_id):
    conn = get_db()
    try:
        n = sp.ignora_suggerito(conn, prodotto_id)
        if not n:
            return jsonify({"error": "Suggerimento non trovato"}), 404
        return jsonify({"ok": True, "nascosti": n})
    finally:
        conn.close()


@bp.post("/api/spesa/suggeriti/ignora-vecchi")
@jwt_required()
def ignora_suggeriti_vecchi():
    try:
        giorni = int(request.args.get("giorni", 90))
    except ValueError:
        return jsonify({"error": "giorni deve essere un intero"}), 400
    conn = get_db()
    try:
        return jsonify({"ok": True, "nascosti": sp.ignora_vecchi(conn, max(1, giorni))})
    finally:
        conn.close()


@bp.post("/api/spesa/suggeriti/aggiungi-tutti")
@jwt_required()
def aggiungi_tutti_suggeriti():
    conn = get_db()
    try:
        utente = _utente(conn)
        aggiunti = 0
        for s in sp.suggeriti(conn)[:100]:
            ris = sp.aggiungi_suggerito(conn, s["prodotto_id"], utente)
            if ris and not ris.get("unita"):
                aggiunti += 1
        return jsonify({"ok": True, "aggiunti": aggiunti})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


# ── Voci della lista (compatibili con le versioni precedenti) ────────────────

@bp.get("/api/lista-spesa")
@jwt_required()
def get_lista_spesa():
    conn = get_db()
    try:
        sp.assicura_righe(conn)
        items = conn.execute("SELECT * FROM lista_spesa ORDER BY completato ASC, data_aggiunta DESC").fetchall()
        return jsonify([dict(i) for i in items])
    finally:
        conn.close()


@bp.post("/api/lista-spesa")
@jwt_required()
def aggiungi_lista_spesa():
    data = request.get_json(silent=True) or {}
    conn = get_db()
    try:
        ris = sp.aggiungi_voce(
            conn, data.get("nome", ""), data.get("quantita"), data.get("ean", ""), data.get("marca", ""),
            "manuale", _utente(conn),
        )
        return jsonify({"ok": True, **ris}), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@bp.put("/api/lista-spesa/<int:id>")
@jwt_required()
def aggiorna_lista_spesa(id):
    data = request.get_json(silent=True) or {}
    campi, valori = [], []
    adesso = sp.ora_utc()
    if "completato" in data:
        fatto = 1 if data["completato"] in (1, True, "1", "true") else 0
        campi += ["completato=?", "completato_il=?"]
        valori += [fatto, adesso if fatto else None]
    if "quantita" in data:
        try:
            q = int(data["quantita"])
        except (TypeError, ValueError):
            return jsonify({"error": "quantita deve essere un intero"}), 400
        if not 1 <= q <= 99:
            return jsonify({"error": "quantita da 1 a 99"}), 400
        campi.append("quantita=?")
        valori.append(q)
    conn = get_db()
    try:
        riga = conn.execute("SELECT * FROM lista_spesa WHERE id=?", (id,)).fetchone()
        if not riga:
            return jsonify({"error": "Voce non trovata"}), 404
        if "nome" in data:
            nome = bella(str(data["nome"]))
            tok = token_chiave(nome)
            if not nome or not tok:
                return jsonify({"error": "Scrivi il nome del prodotto"}), 400
            campi += ["nome=?", "nome_norm=?", "reparto=?"]
            valori += [nome, " ".join(sorted(tok)), reparto_di(nome, riga["marca"])]
        if campi:
            campi.append("aggiornato_il=?")
            valori.append(adesso)
            with conn:
                conn.execute(f"UPDATE lista_spesa SET {', '.join(campi)} WHERE id=?", valori + [id])
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.delete("/api/lista-spesa/<int:id>")
@jwt_required()
def elimina_lista_spesa(id):
    conn = get_db()
    try:
        with conn:
            conn.execute("DELETE FROM lista_spesa WHERE id=?", (id,))
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.delete("/api/lista-spesa/svuota-completati")
@jwt_required()
def svuota_completati():
    conn = get_db()
    try:
        with conn:
            cur = conn.execute("DELETE FROM lista_spesa WHERE completato=1")
        return jsonify({"ok": True, "rimossi": cur.rowcount})
    finally:
        conn.close()


# ── Telegram ──────────────────────────────────────────────────────────────────

def testo_telegram(conn):
    """Messaggio con la lista per reparto e, a parte, i prodotti finiti non ancora in lista. None se non c'e' nulla."""
    da_comprare, _ = sp.lista(conn)
    sugg = sp.suggeriti(conn)
    if not da_comprare and not sugg:
        return None
    msg = f"\U0001f6d2 *Lista della Spesa*\n_{datetime.now().strftime('%d/%m/%Y %H:%M')}_\n"
    if da_comprare:
        reparto_corrente = None
        for v in da_comprare:
            if v["reparto"] != reparto_corrente:
                reparto_corrente = v["reparto"]
                msg += f"\n*{md_esc(ETICHETTA.get(reparto_corrente, ETICHETTA['altro']))}*\n"
            msg += f"  ☐ {md_esc(v['nome'])}"
            if v["quantita"] > 1:
                msg += f" \xd7{v['quantita']}"
            if v["marca"]:
                msg += f" _{md_esc(v['marca'])}_"
            msg += "\n"
    else:
        msg += "\n_Nessuna voce in lista._\n"
    if sugg:
        msg += f"\n\U0001f4a1 *Finiti in dispensa* ({len(sugg)}, non ancora in lista):\n"
        for s in sugg[:10]:
            msg += f"  • {md_esc(s['nome'])}\n"
        if len(sugg) > 10:
            msg += f"  _…e altri {len(sugg) - 10}_\n"
    return msg


@bp.get("/api/lista-spesa/invia-telegram")
@api_key_or_jwt
def invia_lista_spesa_telegram():
    # Auth: x-api-key (HA automation) o JWT (frontend)
    token = get_ha_option("telegram_token", "")
    ids = chat_ids()

    conn = get_db()
    try:
        msg = testo_telegram(conn)
        n_voci = len(sp.lista(conn)[0])
    finally:
        conn.close()

    if not token or not ids:
        return jsonify({"ok": False, "errore": "Telegram non configurato nelle opzioni HA addon"})
    if msg is None:
        return jsonify({"ok": False, "errore": "Lista spesa vuota"})
    if len(msg) > TELEGRAM_MAX_LEN:
        msg = msg[:TELEGRAM_MAX_LEN - 60] + "\n\n_…messaggio troncato, apri l'app per il dettaglio_"

    for cid in ids:
        invia_a_chat(token, cid, msg)

    return jsonify({"ok": True, "totale": n_voci})
