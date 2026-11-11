"""Collegamento con la lista della spesa di Alexa (2.6.0): python -m unittest discover -s tests

La lista Alexa e' simulata come quella del widget (FakeLista di test_sync_todo), con in piu' i suoi tratti:
storico di voci spuntate, lista «non disponibile» quando Amazon limita le richieste, poche scritture per giro.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import test_sync_todo as base  # noqa: E402  (prepara il database di prova e l'app)

st = base.st
database = base.database
FakeLista, pulisci, voci, aggiungi_locale, locale = base.FakeLista, base.pulisci, base.voci, base.aggiungi_locale, base.locale

ALEXA = "todo.luigisss92_gmail_com_shopping_list"
NOMI = ["pane", "latte", "riso", "pasta", "tonno", "uova", "sale", "olio", "aceto", "farina", "burro", "miele"]


def origini():
    c = database.get_db()
    try:
        return {r["nome"]: r["origine"] for r in c.execute("SELECT nome, origine FROM lista_spesa")}
    finally:
        c.close()


class MotoreAlexa(unittest.TestCase):
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
            ris = st.sincronizza("alexa", ALEXA)
        return ris

    def remoto(self):
        return sorted((x["summary"], x["status"]) for x in self.f.items.values())

    # ── prima unione ──
    def test_prima_unione_importa_le_aperte_e_non_lo_storico(self):
        self.f.telefono_aggiunge("Cipolle")
        self.f.telefono_aggiunge("Biscotti per il cane")
        self.f.telefono_aggiunge("Pangrattato", "completed")
        self.f.telefono_aggiunge("Sale lavastoviglie", "completed")
        aggiungi_locale("latte")
        ris = self.giro()
        self.assertEqual([v[0] for v in voci()], ["Biscotti per il cane", "Cipolle", "Latte"])     # lo storico non entra
        self.assertEqual((ris["locali_aggiunte"], ris["remote_aggiunte"], ris["ignorate"]), (2, 1, 2))
        self.assertEqual(origini()["Cipolle"], "alexa")                                            # nell'app si vede «🎤 Alexa»
        self.assertEqual(origini()["Latte"], "manuale")
        self.assertIn(("Latte", "needs_action"), self.remoto())
        self.f.azzera_chiamate()
        self.giro()
        self.assertEqual(self.f.scritture(), [])                                                   # il giro dopo e' a vuoto

    def test_le_voci_spuntate_in_locale_non_vanno_su_alexa(self):
        vid = aggiungi_locale("pane")
        locale("UPDATE lista_spesa SET completato=1 WHERE id=?", vid)
        aggiungi_locale("latte")
        self.giro()
        self.assertEqual(self.remoto(), [("Latte", "needs_action")])                                # il carrello non intasa Alexa

    def test_maiuscole_diverse_non_fanno_scrivere_su_amazon(self):
        self.f.telefono_aggiunge("cipolle")
        self.f.telefono_aggiunge("biscotti per il cane")
        self.giro()
        self.giro(2)
        self.assertEqual(self.f.scritture(), [])                                                   # nessun «Cipolle» riscritto ogni giro
        self.assertEqual(self.remoto(), [("biscotti per il cane", "needs_action"), ("cipolle", "needs_action")])

    # ── spunte e cancellazioni ──
    def test_spuntata_su_alexa_diventa_nel_carrello(self):
        uid = self.f.telefono_aggiunge("Cipolle")
        self.giro()
        self.f.items[uid]["status"] = "completed"
        self.f.azzera_chiamate()
        self.giro()
        self.assertEqual(voci(), [("Cipolle", 1, 1)])
        self.assertEqual(self.f.scritture(), [])

    def test_spuntata_in_dispensa_si_spunta_su_alexa(self):
        vid = aggiungi_locale("latte")
        self.giro()
        locale("UPDATE lista_spesa SET completato=1 WHERE id=?", vid)
        self.giro()
        self.assertEqual(self.remoto(), [("Latte", "completed")])

    def test_cancellata_su_alexa_si_toglie_dopo_due_giri(self):
        uid = self.f.telefono_aggiunge("Cipolle")
        aggiungi_locale("latte")
        self.giro()
        del self.f.items[uid]
        self.giro()
        self.assertEqual([v[0] for v in voci()], ["Cipolle", "Latte"])                              # un giro solo non basta
        self.giro()
        self.assertEqual([v[0] for v in voci()], ["Latte"])

    def test_lo_storico_che_scorre_non_cancella_le_voci_spuntate(self):
        uid = self.f.telefono_aggiunge("Cipolle")
        self.giro()
        self.f.items[uid]["status"] = "completed"
        self.giro()
        del self.f.items[uid]                                  # Alexa dimentica la voce vecchia (tetto di 100)
        self.giro(3)
        self.assertEqual(voci(), [("Cipolle", 1, 1)])                                               # in Dispensa resta nel carrello
        self.assertEqual(self.f.items, {})                                                         # e non viene rimandata su Alexa
        c = database.get_db()
        self.assertEqual(c.execute("SELECT COUNT(*) FROM spesa_sync_map WHERE connettore='alexa'").fetchone()[0], 0)
        c.close()

    def test_rimessa_tra_le_da_comprare_torna_su_alexa(self):
        uid = self.f.telefono_aggiunge("Cipolle")
        self.giro()
        self.f.items[uid]["status"] = "completed"
        self.giro()
        del self.f.items[uid]
        self.giro(2)
        locale("UPDATE lista_spesa SET completato=0")
        self.giro()
        self.assertEqual(self.remoto(), [("Cipolle", "needs_action")])

    # ── Amazon limita le richieste ──
    def test_poche_scritture_per_giro(self):
        for nome in NOMI:
            aggiungi_locale(nome)
        self.assertEqual(len(voci()), 12)                                                          # 12 voci distinte, non fuse dal normalizzatore
        ris = self.giro()
        self.assertEqual((ris["remote_aggiunte"], len(self.f.items)), (8, 8))
        self.giro()
        self.assertEqual(len(self.f.items), 12)                                                    # il resto al giro dopo

    def test_il_widget_non_ha_il_limite_basso(self):
        for nome in NOMI:
            aggiungi_locale(nome)
        ris = st.sincronizza("widget", base.ENT)
        self.assertEqual(ris["remote_aggiunte"], 12)

    # ── lista non disponibile ──
    def test_esegui_salta_il_giro_se_la_lista_non_e_disponibile(self):
        self.f.telefono_aggiunge("Cipolle")
        with mock.patch.object(st, "_stato_entita", return_value="unavailable"):
            r = st.esegui("alexa", ALEXA)
        self.assertIsNone(r["ok"])
        self.assertTrue(r["non_disponibile"])
        self.assertIsNone(r["errore"])
        self.assertEqual(self.f.chiamate, [])                                                      # non si e' toccato niente
        self.assertEqual(voci(), [])
        with mock.patch.object(st, "_stato_entita", return_value="20"):
            r = st.esegui("alexa", ALEXA)
        self.assertTrue(r["ok"])
        self.assertFalse(r["non_disponibile"])
        self.assertEqual(voci(), [("Cipolle", 1, 0)])

    def test_lista_inesistente_e_un_errore_vero(self):
        with mock.patch.object(st, "_stato_entita", return_value=None):
            r = st.esegui("alexa", ALEXA)
        self.assertFalse(r["ok"])
        self.assertIn("non esiste", r["errore"])

    def test_il_widget_non_controlla_la_disponibilita(self):
        with mock.patch.object(st, "_stato_entita", side_effect=AssertionError("non va chiamata")):
            self.assertTrue(st.esegui("widget", base.ENT)["ok"])

    # ── anteprima ──
    def test_anteprima_non_scrive_niente(self):
        self.f.telefono_aggiunge("Cipolle")
        self.f.telefono_aggiunge("Latte")
        self.f.telefono_aggiunge("Pangrattato", "completed")
        self.f.telefono_aggiunge("???")
        aggiungi_locale("2 latte")
        aggiungi_locale("dentifricio")
        vid = aggiungi_locale("pane")
        locale("UPDATE lista_spesa SET completato=1 WHERE id=?", vid)
        with mock.patch.object(st, "_stato_entita", return_value="4"):
            a = st.anteprima(ALEXA)
        self.assertTrue(a["disponibile"])
        self.assertEqual(a["importa"], ["Cipolle"])
        self.assertEqual(a["presenti"], ["Latte"])
        self.assertEqual(a["invia"], ["Dentifricio"])             # il pane e' nel carrello: non parte; «2 latte» c'e' gia' su Alexa
        self.assertEqual(a["storico_ignorato"], 1)
        self.assertEqual(self.f.scritture(), [])
        self.assertEqual(len(voci()), 3)

    def test_anteprima_con_lista_non_disponibile_o_inesistente(self):
        with mock.patch.object(st, "_stato_entita", return_value="unavailable"):
            self.assertEqual(st.anteprima(ALEXA), {"entity": ALEXA, "disponibile": False})
        with mock.patch.object(st, "_stato_entita", return_value=None):
            with self.assertRaises(st.ErroreHA):
                st.anteprima(ALEXA)

    def test_anteprima_avvisa_se_si_arriva_al_tetto_delle_100_voci(self):
        for i in range(100):
            self.f.telefono_aggiunge("voce %d" % i, "completed")
        with mock.patch.object(st, "_stato_entita", return_value="0"):
            a = st.anteprima(ALEXA)
        self.assertTrue(a["tetto_raggiunto"])


class Pianificazione(unittest.TestCase):
    def test_alexa_gira_ogni_90_secondi_il_widget_ogni_giro(self):
        self.assertTrue(st.deve_girare("alexa", {}, 1000.0, False))                        # mai girato: parte
        self.assertFalse(st.deve_girare("alexa", {"alexa": 1000.0}, 1030.0, False))
        self.assertTrue(st.deve_girare("alexa", {"alexa": 1000.0}, 1091.0, False))
        self.assertTrue(st.deve_girare("alexa", {"alexa": 1000.0}, 1010.0, True))          # dopo una modifica della lista: subito
        self.assertTrue(st.deve_girare("widget", {"widget": 1000.0}, 1000.5, False))

    def test_alexa_parte_solo_dopo_la_conferma(self):
        imp = {"_attivo": True, "widget": base.ENT, "alexa": ALEXA, "_alexa_confermato": False}
        self.assertFalse(st.connettore_attivo(imp, "alexa"))
        self.assertTrue(st.connettore_attivo(imp, "widget"))
        self.assertTrue(st.connettore_attivo(dict(imp, _alexa_confermato=True), "alexa"))
        self.assertFalse(st.connettore_attivo(dict(imp, _alexa_confermato=True, alexa=""), "alexa"))
        self.assertFalse(st.connettore_attivo(dict(imp, _alexa_confermato=True, _attivo=False), "alexa"))


class StatoEntita(unittest.TestCase):
    def risposta(self, stato=200, corpo=None):
        m = mock.Mock()
        m.status_code = stato
        m.json.return_value = corpo if corpo is not None else {}
        m.text = str(corpo)
        return m

    def test_letture(self):
        with mock.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "t"}):
            with mock.patch.object(st.http_requests, "get", return_value=self.risposta(200, {"state": "unavailable"})) as g:
                self.assertEqual(st._stato_entita(ALEXA), "unavailable")
            self.assertTrue(g.call_args[0][0].endswith("/api/states/" + ALEXA))
            with mock.patch.object(st.http_requests, "get", return_value=self.risposta(200, {"state": "20"})):
                self.assertEqual(st._stato_entita(ALEXA), "20")
            with mock.patch.object(st.http_requests, "get", return_value=self.risposta(404, {"message": "Entity not found"})):
                self.assertIsNone(st._stato_entita(ALEXA))

    def test_errori_e_token(self):
        with mock.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "segretissimo"}):
            with mock.patch.object(st.http_requests, "get", side_effect=st.http_requests.ConnectionError("url con segretissimo")):
                with self.assertRaises(st.ErroreHA) as c:
                    st._stato_entita(ALEXA)
            self.assertNotIn("segretissimo", str(c.exception))
            with mock.patch.object(st.http_requests, "get", return_value=self.risposta(500, "boom")):
                with self.assertRaises(st.ErroreHA):
                    st._stato_entita(ALEXA)
        with mock.patch.dict(os.environ, {"SUPERVISOR_TOKEN": ""}):
            with self.assertRaises(st.ErroreHA):
                st._stato_entita(ALEXA)


class AdminAlexa(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = base.APP.test_client()
        r = cls.c.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        cls.h = {"Authorization": "Bearer " + r.get_json()["access_token"]}

    def setUp(self):
        pulisci()
        c = database.get_db()
        with c:
            for k, v in (("todo_alexa_entity", ""), (st.ALEXA_CONFERMA, "0")):
                database.set_setting(c, k, v)
        c.close()
        self.f = FakeLista()
        self.patch = [mock.patch.object(st, "leggi_remoti", self.f.leggi), mock.patch.object(st, "aggiungi_remoto", self.f.aggiungi),
                      mock.patch.object(st, "aggiorna_remoto", self.f.aggiorna), mock.patch.object(st, "rimuovi_remoto", self.f.rimuovi)]
        for p in self.patch:
            p.start()

    def tearDown(self):
        for p in self.patch:
            p.stop()

    def stato_alexa(self):
        return self.c.get("/api/admin/spesa-sync", headers=self.h).get_json()["alexa"]

    def test_all_inizio_non_e_attiva_e_non_gira(self):
        s = self.stato_alexa()
        self.assertEqual((s["entity"], s["attivo"], s["confermato"]), ("", False, False))
        aggiungi_locale("latte")
        with mock.patch.object(st, "_stato_entita", return_value="1"):
            r = self.c.post("/api/admin/spesa-sync/ora", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.f.items and len(self.f.items), 1)                         # ha girato il widget (stessa FakeLista), non Alexa
        c = database.get_db()
        self.assertEqual(c.execute("SELECT COUNT(*) FROM spesa_sync_map WHERE connettore='alexa'").fetchone()[0], 0)
        c.close()

    def test_anteprima(self):
        self.f.telefono_aggiunge("Cipolle")
        with mock.patch.object(st, "_stato_entita", return_value="1"):
            r = self.c.get("/api/admin/spesa-sync/alexa/anteprima?entity=" + ALEXA, headers=self.h)
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()["importa"], ["Cipolle"])
        self.assertEqual(self.f.scritture(), [])
        self.assertEqual(self.stato_alexa()["confermato"], False)                       # guardare non attiva
        self.assertEqual(self.c.get("/api/admin/spesa-sync/alexa/anteprima", headers=self.h).status_code, 400)   # nessuna lista indicata
        self.assertEqual(self.c.get("/api/admin/spesa-sync/alexa/anteprima?entity=light.cucina", headers=self.h).status_code, 400)

    def test_anteprima_con_home_assistant_giu(self):
        with mock.patch.object(st, "_stato_entita", side_effect=st.ErroreHA("Home Assistant non raggiungibile")):
            r = self.c.get("/api/admin/spesa-sync/alexa/anteprima?entity=" + ALEXA, headers=self.h)
        self.assertEqual(r.status_code, 502)

    def test_attiva_solo_dopo_la_conferma_e_se_la_lista_e_disponibile(self):
        self.f.telefono_aggiunge("Cipolle")
        with mock.patch.object(st, "_stato_entita", return_value="1"):
            self.assertEqual(self.c.post("/api/admin/spesa-sync/alexa/attiva", json={"entity": ALEXA}, headers=self.h).status_code, 400)
            self.assertEqual(self.c.post("/api/admin/spesa-sync/alexa/attiva", json={"entity": ALEXA, "conferma": "si"}, headers=self.h).status_code, 400)
            self.assertEqual(self.c.post("/api/admin/spesa-sync/alexa/attiva", json={"entity": "brutto", "conferma": True}, headers=self.h).status_code, 400)
        with mock.patch.object(st, "_stato_entita", return_value="unavailable"):
            r = self.c.post("/api/admin/spesa-sync/alexa/attiva", json={"entity": ALEXA, "conferma": True}, headers=self.h)
        self.assertEqual(r.status_code, 409)
        self.assertFalse(self.stato_alexa()["confermato"])
        with mock.patch.object(st, "_stato_entita", return_value="1"), mock.patch.object(st, "richiedi_sync") as ric:
            r = self.c.post("/api/admin/spesa-sync/alexa/attiva", json={"entity": " TODO.Luigisss92_Gmail_Com_Shopping_List ", "conferma": True}, headers=self.h)
            self.assertEqual(r.status_code, 200, r.get_json())
            ric.assert_called_once()
        s = self.stato_alexa()
        self.assertEqual((s["entity"], s["confermato"], s["attivo"]), (ALEXA, True, True))

    def test_attivata_si_sincronizza_e_la_pausa_la_ferma(self):
        self.f.telefono_aggiunge("Cipolle")
        with mock.patch.object(st, "_stato_entita", return_value="1"):
            self.c.post("/api/admin/spesa-sync/alexa/attiva", json={"entity": ALEXA, "conferma": True}, headers=self.h)
            r = self.c.post("/api/admin/spesa-sync/ora", headers=self.h)
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual([v[0] for v in voci()], ["Cipolle"])
        self.assertTrue(self.stato_alexa()["ok"])
        r = self.c.post("/api/admin/spesa-sync/alexa/disattiva", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(self.stato_alexa()["attivo"])
        self.assertEqual(self.stato_alexa()["entity"], ALEXA)                         # la lista resta indicata: si riattiva con un tocco

    def test_le_chiavi_alexa_non_sono_nel_modulo_delle_impostazioni_generiche(self):
        chiavi = {x["key"] for x in self.c.get("/api/admin/settings", headers=self.h).get_json()}
        self.assertNotIn("todo_alexa_entity", chiavi)
        self.assertNotIn(st.ALEXA_CONFERMA, chiavi)
        r = self.c.patch("/api/admin/settings", json={"todo_alexa_confermato": "1"}, headers=self.h)
        self.assertEqual(r.status_code, 400)                                           # si attiva solo con anteprima + conferma

    def test_solo_admin(self):
        self.assertEqual(self.c.post("/api/admin/spesa-sync/alexa/attiva", json={"entity": ALEXA, "conferma": True}).status_code, 401)
        self.assertEqual(self.c.get("/api/admin/spesa-sync/alexa/anteprima").status_code, 401)


if __name__ == "__main__":
    unittest.main()
