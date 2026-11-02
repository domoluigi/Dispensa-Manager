"""Sincronizzazione con la lista to-do di Home Assistant: python -m unittest discover -s tests

La lista di Home Assistant e' simulata in memoria (FakeLista): si controlla cosa arriva da una parte
e dall'altra, che un giro a vuoto non scriva niente e che gli errori non rovinino i dati.
"""
import copy
import os
import sys
import tempfile
import unittest
from unittest import mock

TMP = tempfile.mkdtemp(prefix="dispensa_test_sync_")
os.environ["DB_PATH"] = os.path.join(TMP, "dispensa.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dispensa_manager"))

import database  # noqa: E402
import spesa as sp  # noqa: E402
import sync_todo as st  # noqa: E402
from routes import shopping  # noqa: E402

database.init_db()
from app import create_app  # noqa: E402

APP = create_app()
ENT = "todo.lista_della_spesa"


class FakeLista:
    """Una lista to-do di Home Assistant in memoria."""

    def __init__(self):
        self.items = {}
        self.n = 0
        self.chiamate = []
        self.rotta = False

    def leggi(self, entity):
        if self.rotta:
            raise st.ErroreHA("Home Assistant non raggiungibile (finto)")
        self.chiamate.append(("get",))
        return copy.deepcopy(self.items)

    def aggiungi(self, entity, summary):
        self.n += 1
        self.items[f"u{self.n}"] = {"summary": summary, "status": "needs_action"}
        self.chiamate.append(("add", summary))

    def aggiorna(self, entity, uid, summary=None, status=None):
        if summary is not None:
            self.items[uid]["summary"] = summary
        if status is not None:
            self.items[uid]["status"] = status
        self.chiamate.append(("update", uid, summary, status))

    def rimuovi(self, entity, uid):
        del self.items[uid]
        self.chiamate.append(("remove", uid))

    def scritture(self):
        return [c for c in self.chiamate if c[0] != "get"]

    def azzera_chiamate(self):
        self.chiamate = []

    # lato telefono
    def telefono_aggiunge(self, summary, status="needs_action"):
        self.n += 1
        self.items[f"u{self.n}"] = {"summary": summary, "status": status}
        return f"u{self.n}"


def pulisci():
    c = database.get_db()
    with c:
        for t in ("lista_spesa", "spesa_sync_map", "prodotti", "suggerimenti_ignorati", "spesa_storico"):
            c.execute(f"DELETE FROM {t}")
    c.close()


def voci():
    """Elenco (nome, quantita, completato) della lista locale."""
    c = database.get_db()
    try:
        return sorted((r["nome"], r["quantita"], r["completato"]) for r in c.execute("SELECT * FROM lista_spesa"))
    finally:
        c.close()


def aggiungi_locale(nome, quantita=None):
    c = database.get_db()
    try:
        return sp.aggiungi_voce(c, nome, quantita)["id"]
    finally:
        c.close()


def locale(sql, *args):
    c = database.get_db()
    try:
        with c:
            c.execute(sql, args)
    finally:
        c.close()


class Motore(unittest.TestCase):
    def setUp(self):
        pulisci()
        self.f = FakeLista()
        self.patch = [
            mock.patch.object(st, "leggi_remoti", self.f.leggi),
            mock.patch.object(st, "aggiungi_remoto", self.f.aggiungi),
            mock.patch.object(st, "aggiorna_remoto", self.f.aggiorna),
            mock.patch.object(st, "rimuovi_remoto", self.f.rimuovi),
        ]
        for p in self.patch:
            p.start()

    def tearDown(self):
        for p in self.patch:
            p.stop()

    def giro(self, n=1):
        ris = None
        for _ in range(n):
            ris = st.sincronizza("widget", ENT)
        return ris

    def remoto(self):
        return sorted((x["summary"], x["status"]) for x in self.f.items.values())

    # ── dal locale al telefono ──
    def test_voce_locale_va_sul_telefono_e_il_giro_dopo_e_a_vuoto(self):
        aggiungi_locale("dentifricio")
        aggiungi_locale("2 latte")
        ris = self.giro()
        self.assertEqual(ris["remote_aggiunte"], 2)
        self.assertEqual(self.remoto(), [("Dentifricio", "needs_action"), ("Latte ×2", "needs_action")])
        self.f.azzera_chiamate()
        ris = self.giro()
        self.assertEqual(self.f.scritture(), [])                       # nessun rimbalzo
        self.assertEqual(sum(ris.values()), 0)
        self.assertEqual(len(self.f.items), 2)

    def test_voce_gia_spuntata_arriva_come_completata(self):
        vid = aggiungi_locale("pane")
        locale("UPDATE lista_spesa SET completato=1 WHERE id=?", vid)
        self.giro()
        self.assertEqual(self.remoto(), [("Pane", "completed")])
        self.f.azzera_chiamate()
        self.giro()
        self.assertEqual(self.f.scritture(), [])

    def test_modifiche_locali_arrivano_sul_telefono(self):
        vid = aggiungi_locale("latte")
        self.giro()
        locale("UPDATE lista_spesa SET quantita=3 WHERE id=?", vid)
        self.giro()
        self.assertEqual(self.remoto(), [("Latte ×3", "needs_action")])
        locale("UPDATE lista_spesa SET completato=1 WHERE id=?", vid)
        self.giro()
        self.assertEqual(self.remoto(), [("Latte ×3", "completed")])
        self.f.azzera_chiamate()
        self.giro()
        self.assertEqual(self.f.scritture(), [])

    def test_cancellazione_locale_toglie_dal_telefono(self):
        vid = aggiungi_locale("latte")
        aggiungi_locale("pane")
        self.giro()
        locale("DELETE FROM lista_spesa WHERE id=?", vid)
        ris = self.giro()
        self.assertEqual(ris["remote_rimosse"], 1)
        self.assertEqual(self.remoto(), [("Pane", "needs_action")])

    def test_svuota_carrello_toglie_dal_telefono(self):
        a = aggiungi_locale("latte")
        aggiungi_locale("pane")
        locale("UPDATE lista_spesa SET completato=1 WHERE id=?", a)
        self.giro()
        locale("DELETE FROM lista_spesa WHERE completato=1")
        self.giro()
        self.assertEqual(self.remoto(), [("Pane", "needs_action")])

    # ── dal telefono al locale ──
    def test_voce_aggiunta_dal_telefono_arriva_in_locale(self):
        self.f.telefono_aggiunge("dentifricio")
        self.f.telefono_aggiunge("2 mele")
        ris = self.giro()
        self.assertEqual(ris["locali_aggiunte"], 2)
        self.assertEqual(voci(), [("Dentifricio", 1, 0), ("Mele", 2, 0)])
        c = database.get_db()
        self.assertEqual({r["origine"] for r in c.execute("SELECT origine FROM lista_spesa")}, {"widget"})
        c.close()
        # il telefono riceve il nome "bello" e poi non ci sono piu' scritture
        self.assertEqual(self.remoto(), [("Dentifricio", "needs_action"), ("Mele ×2", "needs_action")])
        self.f.azzera_chiamate()
        self.giro()
        self.assertEqual(self.f.scritture(), [])

    def test_spunta_dal_telefono(self):
        aggiungi_locale("latte")
        self.giro()
        uid = next(iter(self.f.items))
        self.f.items[uid]["status"] = "completed"
        ris = self.giro()
        self.assertEqual(ris["locali_aggiornate"], 1)
        self.assertEqual(voci(), [("Latte", 1, 1)])
        self.f.azzera_chiamate()
        self.giro()
        self.assertEqual(self.f.scritture(), [])

    def test_rinomina_dal_telefono_con_quantita(self):
        aggiungi_locale("latte")
        self.giro()
        uid = next(iter(self.f.items))
        self.f.items[uid]["summary"] = "latte intero x3"
        self.giro()
        self.assertEqual(voci(), [("Latte intero", 3, 0)])
        self.assertEqual(self.remoto(), [("Latte intero ×3", "needs_action")])
        c = database.get_db()
        self.assertEqual(c.execute("SELECT reparto FROM lista_spesa").fetchone()[0], "latticini")
        c.close()

    def test_nome_non_valido_dal_telefono_si_ignora(self):
        self.f.telefono_aggiunge("2")
        self.f.telefono_aggiunge("   ")
        ris = self.giro()
        self.assertEqual(ris["ignorate"], 2)
        self.assertEqual(voci(), [])
        self.f.azzera_chiamate()
        self.giro()
        self.assertEqual(self.f.scritture(), [])                       # non riprova all'infinito a scrivere

    def test_cancellazione_dal_telefono_vale_dopo_due_giri(self):
        aggiungi_locale("latte")
        aggiungi_locale("pane")
        self.giro()
        uid = next(u for u, x in self.f.items.items() if x["summary"] == "Latte")
        del self.f.items[uid]
        self.giro()
        self.assertEqual(voci(), [("Latte", 1, 0), ("Pane", 1, 0)])    # primo giro: ancora li'
        ris = self.giro()
        self.assertEqual(ris["locali_rimosse"], 1)
        self.assertEqual(voci(), [("Pane", 1, 0)])

    def test_se_l_elemento_ricompare_non_si_cancella(self):
        aggiungi_locale("latte")
        self.giro()
        uid = next(iter(self.f.items))
        salvato = self.f.items.pop(uid)
        self.giro()
        self.f.items[uid] = salvato                                    # lettura incompleta, poi torna
        self.giro(3)
        self.assertEqual(voci(), [("Latte", 1, 0)])

    def test_lettura_vuota_non_svuota_la_lista(self):
        for n in ("latte", "pane", "pasta", "mele", "uova"):
            aggiungi_locale(n)
        self.giro()
        self.f.items.clear()                                           # HA restituisce una lista vuota (ricarica dell'integrazione)
        self.giro(4)
        self.assertEqual(len(voci()), 5)

    # ── unioni e conflitti ──
    def test_prima_attivazione_unisce_senza_cancellare(self):
        aggiungi_locale("pane")
        aggiungi_locale("dentifricio")
        self.f.telefono_aggiunge("Pane")                               # gia' presente da entrambe le parti
        self.f.telefono_aggiunge("detersivo")
        self.giro()
        self.assertEqual(voci(), [("Dentifricio", 1, 0), ("Detersivo", 1, 0), ("Pane", 1, 0)])
        self.assertEqual(self.remoto(), [("Dentifricio", "needs_action"), ("Detersivo", "needs_action"), ("Pane", "needs_action")])
        self.f.azzera_chiamate()
        self.giro()
        self.assertEqual(self.f.scritture(), [])

    def test_unione_prende_lo_stato_piu_avanzato(self):
        vid = aggiungi_locale("latte", 2)
        self.f.telefono_aggiunge("Latte ×4", "completed")
        self.giro()
        self.assertEqual(voci(), [("Latte", 4, 1)])
        self.assertEqual(self.remoto(), [("Latte ×4", "completed")])
        del vid

    def test_doppione_dal_telefono_si_toglie(self):
        aggiungi_locale("latte")
        self.giro()
        self.f.telefono_aggiunge("latte")                              # scritto due volte nel widget
        self.giro()
        self.assertEqual(voci(), [("Latte", 1, 0)])
        self.assertEqual(self.remoto(), [("Latte", "needs_action")])

    def test_conflitto_stato_fatto_vince_e_il_nome_resta_quello_locale(self):
        vid = aggiungi_locale("latte")
        self.giro()
        uid = next(iter(self.f.items))
        locale("UPDATE lista_spesa SET quantita=2 WHERE id=?", vid)    # in app
        self.f.items[uid]["status"] = "completed"                      # sul telefono, nello stesso intervallo
        self.giro()
        self.assertEqual(voci(), [("Latte", 2, 1)])
        self.assertEqual(self.remoto(), [("Latte ×2", "completed")])

    def test_rinomina_che_coincide_con_un_altra_voce_si_ignora(self):
        aggiungi_locale("latte")
        aggiungi_locale("pane")
        self.giro()
        uid = next(u for u, x in self.f.items.items() if x["summary"] == "Pane")
        self.f.items[uid]["summary"] = "Latte"
        self.giro()
        self.assertEqual(voci(), [("Latte", 1, 0), ("Pane", 1, 0)])
        self.assertEqual(self.remoto(), [("Latte", "needs_action"), ("Pane", "needs_action")])   # il telefono torna com'era

    # ── errori ──
    def test_errore_di_home_assistant_non_cambia_nulla(self):
        aggiungi_locale("latte")
        self.giro()
        prima = (voci(), self.remoto())
        self.f.rotta = True
        with self.assertRaises(st.ErroreHA):
            st.sincronizza("widget", ENT)
        self.assertEqual((voci(), self.remoto()), prima)

    def test_esegui_registra_stato_ed_errore(self):
        aggiungi_locale("latte")
        r = st.esegui("widget", ENT)
        self.assertTrue(r["ok"])
        self.assertEqual(r["risultato"]["remote_aggiunte"], 1)
        self.f.rotta = True
        r = st.esegui("widget", ENT)
        self.assertFalse(r["ok"])
        self.assertIn("non raggiungibile", r["errore"])
        self.f.rotta = False
        self.assertTrue(st.esegui("widget", ENT)["ok"])


class Chiamate(unittest.TestCase):
    """Il livello che parla con Home Assistant."""

    def risposta(self, stato=200, corpo=None):
        m = mock.Mock()
        m.status_code = stato
        m.json.return_value = corpo if corpo is not None else {}
        m.text = str(corpo)
        return m

    def test_leggi_remoti(self):
        corpo = {"changed_states": [], "service_response": {ENT: {"items": [
            {"summary": "Latte", "uid": "a", "status": "needs_action"}, {"summary": "Pane", "uid": "b", "status": "completed"}]}}}
        with mock.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "t"}), \
                mock.patch.object(st.http_requests, "post", return_value=self.risposta(200, corpo)) as p:
            r = st.leggi_remoti(ENT)
        self.assertEqual(r, {"a": {"summary": "Latte", "status": "needs_action"}, "b": {"summary": "Pane", "status": "completed"}})
        url = p.call_args[0][0]
        self.assertTrue(url.endswith("/api/services/todo/get_items?return_response"))
        self.assertEqual(p.call_args[1]["json"]["entity_id"], ENT)

    def test_errori(self):
        with mock.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "t"}):
            with mock.patch.object(st.http_requests, "post", return_value=self.risposta(400, "entity not found")):
                with self.assertRaises(st.ErroreHA) as c:
                    st.leggi_remoti(ENT)
                self.assertIn("400", str(c.exception))
            with mock.patch.object(st.http_requests, "post", side_effect=st.http_requests.ConnectionError("giu")):
                with self.assertRaises(st.ErroreHA):
                    st.leggi_remoti(ENT)
            with mock.patch.object(st.http_requests, "post", return_value=self.risposta(200, {"service_response": {}})):
                with self.assertRaises(st.ErroreHA):
                    st.leggi_remoti(ENT)
        with mock.patch.dict(os.environ, {"SUPERVISOR_TOKEN": ""}):
            with self.assertRaises(st.ErroreHA):
                st.leggi_remoti(ENT)

    def test_il_token_non_finisce_nei_messaggi(self):
        with mock.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "segretissimo"}), \
                mock.patch.object(st.http_requests, "post", side_effect=st.http_requests.ConnectionError("url con segretissimo")):
            with self.assertRaises(st.ErroreHA) as c:
                st.leggi_remoti(ENT)
        self.assertNotIn("segretissimo", str(c.exception))

    def test_scritture(self):
        with mock.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "t"}), \
                mock.patch.object(st.http_requests, "post", return_value=self.risposta(200, [])) as p:
            st.aggiungi_remoto(ENT, "Latte")
            st.aggiorna_remoto(ENT, "u1", summary="Latte ×2", status="completed")
            st.rimuovi_remoto(ENT, "u1")
        chiamate = [(c[0][0].rsplit("/", 1)[1], c[1]["json"]) for c in p.call_args_list]
        self.assertEqual(chiamate, [
            ("add_item", {"entity_id": ENT, "item": "Latte"}),
            ("update_item", {"entity_id": ENT, "item": "u1", "rename": "Latte ×2", "status": "completed"}),
            ("remove_item", {"entity_id": ENT, "item": ["u1"]}),
        ])


class AdminEApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = APP.test_client()
        r = cls.c.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        cls.h = {"Authorization": "Bearer " + r.get_json()["access_token"]}

    def setUp(self):
        pulisci()

    def test_impostazioni_di_default_e_validazione(self):
        s = {x["key"]: x["value"] for x in self.c.get("/api/admin/settings", headers=self.h).get_json()}
        self.assertEqual(s["todo_widget_entity"], "todo.lista_della_spesa")
        self.assertEqual(s["todo_sync_attivo"], "1")
        for brutto in ("lista della spesa", "light.cucina", "todo.", "todo.Lista-Spesa"):
            r = self.c.patch("/api/admin/settings", json={"todo_widget_entity": brutto}, headers=self.h)
            self.assertEqual(r.status_code, 400, brutto)
        self.assertEqual(self.c.patch("/api/admin/settings", json={"todo_sync_attivo": "2"}, headers=self.h).status_code, 400)
        self.assertEqual(self.c.patch("/api/admin/settings", json={"todo_widget_entity": " TODO.Altra_Lista "}, headers=self.h).status_code, 200)
        c = database.get_db()
        self.assertEqual(st.impostazioni(c)["widget"], "todo.altra_lista")        # normalizzata
        c.close()
        self.assertEqual(self.c.patch("/api/admin/settings", json={"todo_widget_entity": ""}, headers=self.h).status_code, 200)
        self.c.patch("/api/admin/settings", json={"todo_widget_entity": "todo.lista_della_spesa"}, headers=self.h)

    def test_stato_e_giro_manuale(self):
        f = FakeLista()
        aggiungi_locale("latte")
        with mock.patch.object(st, "leggi_remoti", f.leggi), mock.patch.object(st, "aggiungi_remoto", f.aggiungi), \
                mock.patch.object(st, "aggiorna_remoto", f.aggiorna), mock.patch.object(st, "rimuovi_remoto", f.rimuovi):
            r = self.c.post("/api/admin/spesa-sync/ora", headers=self.h)
            self.assertEqual(r.status_code, 200, r.get_json())
            w = r.get_json()["widget"]
            self.assertTrue(w["ok"])
            self.assertEqual((w["entity"], w["attivo"], w["voci_collegate"]), (ENT, True, 1))
            stato = self.c.get("/api/admin/spesa-sync", headers=self.h).get_json()["widget"]
            self.assertEqual(stato["voci_collegate"], 1)
        self.assertEqual(self.c.get("/api/admin/spesa-sync").status_code, 401)

    def test_giro_manuale_senza_lista_indicata(self):
        self.c.patch("/api/admin/settings", json={"todo_widget_entity": ""}, headers=self.h)
        try:
            self.assertEqual(self.c.post("/api/admin/spesa-sync/ora", headers=self.h).status_code, 400)
        finally:
            self.c.patch("/api/admin/settings", json={"todo_widget_entity": "todo.lista_della_spesa"}, headers=self.h)

    def test_ogni_modifica_della_lista_chiede_un_giro(self):
        with mock.patch.object(shopping, "richiedi_sync") as r:
            vid = self.c.post("/api/lista-spesa", json={"nome": "latte"}, headers=self.h).get_json()["id"]
            self.c.put(f"/api/lista-spesa/{vid}", json={"quantita": 2}, headers=self.h)
            self.c.put(f"/api/lista-spesa/{vid}", json={"completato": 1}, headers=self.h)
            self.c.delete("/api/lista-spesa/svuota-completati", headers=self.h)
            vid2 = self.c.post("/api/lista-spesa", json={"nome": "pane"}, headers=self.h).get_json()["id"]
            self.c.delete(f"/api/lista-spesa/{vid2}", headers=self.h)
            c = database.get_db()
            with c:
                pid = c.execute("INSERT INTO prodotti (nome, quantita) VALUES ('Riso', 0)").lastrowid
            c.close()
            self.c.post(f"/api/spesa/suggeriti/{pid}/aggiungi", headers=self.h)
        self.assertEqual(r.call_count, 7)

    def test_il_sync_non_parte_senza_thread_nei_test(self):
        self.assertEqual([t.name for t in __import__("threading").enumerate() if t.name == "sync-todo"], [])


if __name__ == "__main__":
    unittest.main()
