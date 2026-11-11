"""Finto Home Assistant per provare la sincronizzazione senza HA: liste to-do in memoria dietro le stesse
chiamate REST dei servizi `todo.*` e di `/api/states/<entita>` (come le vede l'add-on dal Supervisor).

    python tests/finto_ha.py [porta]          # default 8124

Poi l'add-on con:  HA_URL=http://127.0.0.1:8124 SUPERVISOR_TOKEN=prova DISPENSA_SYNC_SECONDI=3 python app.py

Due liste: quella del widget (todo.lista_della_spesa) e quella di Alexa (todo.luigisss92_gmail_com_shopping_list),
che puo' diventare «non disponibile» come quando Amazon limita le richieste.

Estra per le prove a mano (`?lista=<entita>`, di default la lista del widget):
GET /finto/stato, POST /finto/aggiungi {"summary": "...", "status": "..."}, POST /finto/spunta {"uid": "..."},
POST /finto/cancella {"uid": "..."}, POST /finto/rotto {"si": true}, POST /finto/disponibile {"si": false}.
"""
import sys
import uuid

from flask import Flask, jsonify, request

app = Flask(__name__)
ENTITA = "todo.lista_della_spesa"
ALEXA = "todo.luigisss92_gmail_com_shopping_list"
liste = {ENTITA: {}, ALEXA: {}}        # entita -> {uid: {"summary", "status"}}
stato = {"rotto": False, "disponibile": {ENTITA: True, ALEXA: True}}
scritture = []                         # (servizio, entita) delle chiamate di scrittura: serve per provare che un giro a vuoto non scrive


def _lista(entita=None):
    return liste[entita or request.args.get("lista") or ENTITA]


def _items(voci):
    return [{"summary": v["summary"], "uid": u, "status": v["status"]} for u, v in voci.items()]


def _trova(voci, riferimento):
    if riferimento in voci:
        return riferimento
    return next((u for u, v in voci.items() if v["summary"] == riferimento), None)


@app.get("/api/states/<entita>")
def stato_entita(entita):
    if entita not in liste:
        return jsonify({"message": "Entity not found."}), 404
    if not stato["disponibile"][entita]:
        return jsonify({"entity_id": entita, "state": "unavailable", "attributes": {}})
    aperte = sum(1 for v in liste[entita].values() if v["status"] == "needs_action")
    return jsonify({"entity_id": entita, "state": str(aperte), "attributes": {}})


@app.post("/api/services/todo/<servizio>")
def servizio(servizio):
    if stato["rotto"]:
        return jsonify({"message": "simulazione di errore"}), 500
    dati = request.get_json(silent=True) or {}
    entita = dati.get("entity_id")
    if entita not in liste:
        return jsonify({"message": f"Entity {entita} not found"}), 400
    if not stato["disponibile"][entita]:
        return jsonify({"message": f"Entity {entita} is unavailable"}), 400
    voci = liste[entita]
    if servizio == "get_items":
        richiesti = dati.get("status") or ["needs_action"]
        elenco = [i for i in _items(voci) if i["status"] in richiesti]
        return jsonify({"changed_states": [], "service_response": {entita: {"items": elenco}}})
    if servizio == "add_item":
        scritture.append((servizio, entita))
        voci[uuid.uuid4().hex] = {"summary": dati["item"], "status": "needs_action"}
        return jsonify([])
    if servizio == "update_item":
        scritture.append((servizio, entita))
        u = _trova(voci, dati["item"])
        if u is None:
            return jsonify({"message": "item not found"}), 400
        if "rename" in dati:
            voci[u]["summary"] = dati["rename"]
        if "status" in dati:
            voci[u]["status"] = dati["status"]
        return jsonify([])
    if servizio == "remove_item":
        scritture.append((servizio, entita))
        for rif in dati["item"] if isinstance(dati["item"], list) else [dati["item"]]:
            u = _trova(voci, rif)
            if u is None:
                return jsonify({"message": "item not found"}), 400
            del voci[u]
        return jsonify([])
    return jsonify({"message": "servizio sconosciuto"}), 400


@app.get("/finto/stato")
def finto_stato():
    return jsonify(_items(_lista()))


@app.get("/finto/scritture")
def finto_scritture():
    return jsonify(scritture)


@app.post("/finto/aggiungi")
def finto_aggiungi():
    d = request.get_json()
    _lista()[uuid.uuid4().hex] = {"summary": d["summary"], "status": d.get("status", "needs_action")}
    return jsonify({"ok": True})


@app.post("/finto/spunta")
def finto_spunta():
    _lista()[request.get_json()["uid"]]["status"] = "completed"
    return jsonify({"ok": True})


@app.post("/finto/cancella")
def finto_cancella():
    _lista().pop(request.get_json()["uid"], None)
    return jsonify({"ok": True})


@app.post("/finto/rotto")
def finto_rotto():
    stato["rotto"] = bool(request.get_json().get("si"))
    return jsonify({"rotto": stato["rotto"]})


@app.post("/finto/disponibile")
def finto_disponibile():
    stato["disponibile"][request.args.get("lista") or ENTITA] = bool(request.get_json().get("si"))
    return jsonify(stato["disponibile"])


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8124)
