import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
import requests as http_requests

from database import get_db, get_setting

logger = logging.getLogger(__name__)

bp = Blueprint("shopping", __name__)


@bp.get("/api/lista-spesa")
@jwt_required()
def get_lista_spesa():
    conn = get_db()
    try:
        items = conn.execute(
            "SELECT * FROM lista_spesa ORDER BY completato ASC, data_aggiunta DESC"
        ).fetchall()
        return jsonify([dict(i) for i in items])
    finally:
        conn.close()


@bp.post("/api/lista-spesa")
@jwt_required()
def aggiungi_lista_spesa():
    data = request.get_json(silent=True) or {}
    conn = get_db()
    try:
        with conn:
            conn.execute(
                "INSERT INTO lista_spesa (nome, quantita, ean, marca) VALUES (?, ?, ?, ?)",
                (data.get("nome", ""), data.get("quantita", 1), data.get("ean", ""), data.get("marca", "")),
            )
        return jsonify({"ok": True}), 201
    finally:
        conn.close()


@bp.put("/api/lista-spesa/<int:id>")
@jwt_required()
def aggiorna_lista_spesa(id):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    try:
        with conn:
            conn.execute(
                "UPDATE lista_spesa SET completato=?, quantita=? WHERE id=?",
                (data.get("completato", 0), data.get("quantita", 1), id),
            )
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
            conn.execute("DELETE FROM lista_spesa WHERE completato=1")
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.get("/api/lista-spesa/invia-telegram")
@jwt_required()
def invia_lista_spesa_telegram():
    conn = get_db()
    try:
        token = get_setting(conn, "telegram_token")
        chat_id_raw = get_setting(conn, "telegram_chat_id")
        items = conn.execute(
            "SELECT * FROM lista_spesa WHERE completato=0 ORDER BY data_aggiunta DESC"
        ).fetchall()
    finally:
        conn.close()

    if not token or not chat_id_raw:
        return jsonify({"ok": False, "errore": "Telegram non configurato"})
    if not items:
        return jsonify({"ok": False, "errore": "Lista spesa vuota"})

    msg = f"\U0001f6d2 *Lista della Spesa*\n_{datetime.now().strftime('%d/%m/%Y %H:%M')}_\n\n"
    for item in items:
        msg += f"  ☐ {item['nome']}"
        if item["quantita"] > 1:
            msg += f" \xd7{item['quantita']}"
        if item["marca"]:
            msg += f" _{item['marca']}_"
        msg += "\n"

    for cid in [c.strip() for c in str(chat_id_raw).split(",") if c.strip()]:
        try:
            http_requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"},
                timeout=10,
            )
        except Exception as e:
            logger.error("Errore Telegram lista spesa %s: %s", cid, e)

    return jsonify({"ok": True, "totale": len(items)})
