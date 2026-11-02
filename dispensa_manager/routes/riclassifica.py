from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from database import get_db
import riclassifica as rc
from posizioni import classifica, ETICHETTE

bp = Blueprint("riclassifica", __name__)


@bp.get("/api/classifica")
@jwt_required()
def classifica_prodotto():
    """Posizione suggerita per un nome (usata alla conferma di un prodotto inserito a mano)."""
    nome = (request.args.get("nome") or "").strip()
    if len(nome) < 2:
        return jsonify({"posizione": None})
    k = classifica(nome, request.args.get("marca", ""), request.args.get("categoria", ""))
    return jsonify({**k, "etichetta": ETICHETTE[k["posizione"]], "suggerita": k["livello"] != "basso"})


@bp.get("/api/prodotti/riclassifica")
@jwt_required()
def get_proposte():
    conn = get_db()
    try:
        pr = rc.proposte(conn)
        return jsonify({
            "proposte": pr,
            "conteggi": {"alto": sum(1 for x in pr if x["livello"] == "alto"), "medio": sum(1 for x in pr if x["livello"] == "medio")},
        })
    finally:
        conn.close()


@bp.get("/api/prodotti/riclassifica/conteggio")
@jwt_required()
def get_conteggio():
    conn = get_db()
    try:
        return jsonify(rc.conteggi(conn))
    finally:
        conn.close()


@bp.post("/api/prodotti/riclassifica")
@jwt_required()
def applica_proposte():
    dati = request.get_json(silent=True) or {}
    try:
        ids = [int(i) for i in (dati.get("ids") or [])]
        ignora = [int(i) for i in (dati.get("ignora") or [])]
    except (TypeError, ValueError):
        return jsonify({"error": "ids e ignora devono essere liste di numeri"}), 400
    conn = get_db()
    try:
        return jsonify({"ok": True, **rc.applica(conn, ids, ignora)})
    finally:
        conn.close()


@bp.post("/api/prodotti/riclassifica/annulla")
@jwt_required()
def annulla_lotto():
    lotto = str((request.get_json(silent=True) or {}).get("lotto") or "")
    if not lotto:
        return jsonify({"error": "lotto mancante"}), 400
    conn = get_db()
    try:
        return jsonify({"ok": True, "ripristinati": rc.annulla(conn, lotto)})
    finally:
        conn.close()
