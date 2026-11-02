"""Finto Home Assistant per provare la sincronizzazione senza HA: una lista to-do in memoria dietro le stesse
chiamate REST dei servizi `todo.*` (come le vede l'add-on dal Supervisor).

    python tests/finto_ha.py [porta]          # default 8124

Poi l'add-on con:  HA_URL=http://localhost:8124 SUPERVISOR_TOKEN=prova DISPENSA_SYNC_SECONDI=3 python app.py

Estra per le prove a mano: GET /finto/stato (elenco), POST /finto/aggiungi {"summary": "..."},
POST /finto/spunta {"uid": "..."}, POST /finto/cancella {"uid": "..."}, POST /finto/rotto {"si": true}.
"""
import sys
import uuid

from flask import Flask, jsonify, request

app = Flask(__name__)
ENTITA = "todo.lista_della_spesa"
voci = {}        # uid -> {"summary", "status"}
stato = {"rotto": False}


def _items():
    return [{"summary": v["summary"], "uid": u, "status": v["status"]} for u, v in voci.items()]


def _trova(riferimento):
    if riferimento in voci:
        return riferimento
    return next((u for u, v in voci.items() if v["summary"] == riferimento), None)


@app.post("/api/services/todo/<servizio>")
def servizio(servizio):
    if stato["rotto"]:
        return jsonify({"message": "simulazione di errore"}), 500
    dati = request.get_json(silent=True) or {}
    if dati.get("entity_id") != ENTITA:
        return jsonify({"message": f"Entity {dati.get('entity_id')} not found"}), 400
    if servizio == "get_items":
        richiesti = dati.get("status") or ["needs_action"]
        elenco = [i for i in _items() if i["status"] in richiesti]
        return jsonify({"changed_states": [], "service_response": {ENTITA: {"items": elenco}}})
    if servizio == "add_item":
        voci[uuid.uuid4().hex] = {"summary": dati["item"], "status": "needs_action"}
        return jsonify([])
    if servizio == "update_item":
        u = _trova(dati["item"])
        if u is None:
            return jsonify({"message": "item not found"}), 400
        if "rename" in dati:
            voci[u]["summary"] = dati["rename"]
        if "status" in dati:
            voci[u]["status"] = dati["status"]
        return jsonify([])
    if servizio == "remove_item":
        for rif in dati["item"] if isinstance(dati["item"], list) else [dati["item"]]:
            u = _trova(rif)
            if u is None:
                return jsonify({"message": "item not found"}), 400
            del voci[u]
        return jsonify([])
    return jsonify({"message": "servizio sconosciuto"}), 400


@app.get("/finto/stato")
def finto_stato():
    return jsonify(_items())


@app.post("/finto/aggiungi")
def finto_aggiungi():
    d = request.get_json()
    voci[uuid.uuid4().hex] = {"summary": d["summary"], "status": d.get("status", "needs_action")}
    return jsonify({"ok": True})


@app.post("/finto/spunta")
def finto_spunta():
    voci[request.get_json()["uid"]]["status"] = "completed"
    return jsonify({"ok": True})


@app.post("/finto/cancella")
def finto_cancella():
    voci.pop(request.get_json()["uid"], None)
    return jsonify({"ok": True})


@app.post("/finto/rotto")
def finto_rotto():
    stato["rotto"] = bool(request.get_json().get("si"))
    return jsonify(stato)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8124)
