"""Nuovo inventario, riscansione e dati dieta (2.5.0): python -m unittest discover -s tests"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

TMP = tempfile.mkdtemp(prefix="dispensa_test_inv_")
os.environ["DB_PATH"] = os.path.join(TMP, "dispensa.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dispensa_manager"))

import database  # noqa: E402
import notifiche  # noqa: E402
import spesa  # noqa: E402
import inventario as inv  # noqa: E402
from routes import products, admin  # noqa: E402
from routes import inventario as rinv  # noqa: E402

database.init_db()
from app import create_app  # noqa: E402

APP = create_app()
AVVIA_VERO = rinv.avvia_arricchimento       # nei test della modalita' si sostituisce con un finto: questo e' l'originale

OFF_LATTE = {"product_name": "Budino", "brands": "Acme", "categories_tags": ["en:desserts"], "nutriscore_grade": "c",
             "ingredients_text_it": "Latte, zucchero, amido", "ingredients_analysis_tags": ["en:non-vegan", "en:vegetarian"],
             "labels_tags": [], "traces_tags": ["en:eggs"], "nova_group": 4,
             "nutriments": {"energy-kcal_100g": 120, "proteins_100g": 3.5, "sugars_100g": 14}}


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = APP.test_client()
        r = cls.c.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        cls.h = {"Authorization": "Bearer " + r.get_json()["access_token"]}

    def setUp(self):
        self.patches = [
            mock.patch.object(products, "_async", lambda fn, *a, **k: fn(*a, **k)),
            mock.patch.object(rinv, "avvia_arricchimento", lambda: {}),
        ]
        for p in self.patches:
            p.start()
        conn = database.get_db()
        with conn:
            for t in ("prodotti", "storico_movimenti", "barcode_cache", "azzeramento_log", "lista_spesa"):
                conn.execute(f"DELETE FROM {t}")
            conn.execute("UPDATE app_settings SET value='0' WHERE key='riscansione_attiva'")
            conn.execute("UPDATE app_settings SET value='' WHERE key='riscansione_lotto'")
        conn.close()
        for f in os.listdir(database.BACKUPS_DIR):
            if f.startswith("dispensa_pre_azzeramento_"):
                os.remove(os.path.join(database.BACKUPS_DIR, f))

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def aggiungi(self, nome, ean="", q=1, **extra):
        r = self.c.post("/api/prodotti", json={"nome": nome, "ean": ean, "quantita": q, "posizione": "Dispensa", **extra}, headers=self.h)
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()

    def riga(self, pid):
        conn = database.get_db()
        try:
            return dict(conn.execute("SELECT * FROM prodotti WHERE id=?", (pid,)).fetchone())
        finally:
            conn.close()

    def conta(self, where="1=1"):
        conn = database.get_db()
        try:
            return conn.execute(f"SELECT COUNT(*) FROM prodotti WHERE {where}").fetchone()[0]
        finally:
            conn.close()

    def azzera(self):
        r = self.c.post("/api/inventario/azzera", json={"conferma": "AZZERA"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.get_json())
        return r.get_json()


class Azzeramento(Base):
    def test_serve_la_conferma(self):
        self.aggiungi("Pasta", "8000000000001")
        self.assertEqual(self.c.post("/api/inventario/azzera", json={}, headers=self.h).status_code, 400)
        self.assertEqual(self.c.post("/api/inventario/azzera", json={"conferma": "si"}, headers=self.h).status_code, 400)
        self.assertEqual(self.conta("quantita>0"), 1)

    def test_azzera_tutto_e_conta_giusto(self):
        for i in range(5):
            self.aggiungi("Prodotto %d" % i, "800000000010%d" % i, q=i + 1)
        self.aggiungi("Finito", "8000000000999", q=1)
        conn = database.get_db()
        with conn:
            conn.execute("UPDATE prodotti SET quantita=0 WHERE nome='Finito'")
        conn.close()
        d = self.azzera()
        self.assertEqual((d["azzerati"], d["pezzi"]), (5, 15))            # atteso esatto: 5 righe attive, 1+2+3+4+5 pezzi
        self.assertEqual(self.conta("quantita>0"), 0)
        self.assertEqual(self.conta(), 6)                                   # le righe restano
        self.assertTrue(os.path.getsize(os.path.join(database.BACKUPS_DIR, d["copia"])) > 0)
        # la copia ha davvero le righe di prima: si apre e si contano
        cp = sqlite3.connect(os.path.join(database.BACKUPS_DIR, d["copia"]))
        self.assertEqual(cp.execute("SELECT COUNT(*), SUM(quantita) FROM prodotti WHERE quantita>0").fetchone(), (5, 15))
        cp.close()

    def test_solo_admin(self):
        self.c.post("/api/admin/users", json={"username": "laura", "password": "segreta123"}, headers=self.h)
        r = self.c.post("/api/auth/login", json={"username": "laura", "password": "segreta123"})
        h2 = {"Authorization": "Bearer " + r.get_json()["access_token"]}
        self.assertEqual(self.c.post("/api/inventario/azzera", json={"conferma": "AZZERA"}, headers=h2).status_code, 403)
        self.assertEqual(self.c.get("/api/inventario", headers=h2).status_code, 200)

    def test_senza_login(self):
        self.assertEqual(self.c.post("/api/inventario/azzera", json={"conferma": "AZZERA"}).status_code, 401)

    def test_annulla_rimette_le_quantita_e_rispetta_il_riscansionato(self):
        a = self.aggiungi("Pasta", "8000000000001", q=3)["id"]
        b = self.aggiungi("Riso", "8000000000002", q=2)["id"]
        d = self.azzera()
        self.aggiungi("Pasta", "8000000000001", q=7)                        # riscansionata: ricarica la riga di prima
        r = self.c.post("/api/inventario/annulla", json={"lotto": d["lotto"]}, headers=self.h).get_json()
        self.assertEqual((r["ripristinati"], r["gia_riscansionati"]), (1, 1))
        self.assertEqual((self.riga(a)["quantita"], self.riga(b)["quantita"]), (7, 2))
        st = self.c.get("/api/inventario", headers=self.h).get_json()
        self.assertFalse(st["attiva"])

    def test_dopo_un_secondo_azzeramento_si_conta_l_ultimo(self):
        self.aggiungi("Pasta", "8000000000001")
        self.azzera()
        self.aggiungi("Pasta", "8000000000001")
        d2 = self.azzera()
        st = self.c.get("/api/inventario", headers=self.h).get_json()
        self.assertEqual((st["lotto"], st["totale"], st["da_riscansionare"]), (d2["lotto"], 1, 1))


class Riscansione(Base):
    def test_la_scansione_ricarica_la_riga_senza_doppioni(self):
        a = self.aggiungi("Pasta", "8000000000001", q=2, ingredienti="Semola, acqua")["id"]
        self.azzera()
        r = self.aggiungi("Pasta", "8000000000001", q=1, scadenza="2027-01-01")
        self.assertTrue(r["ricaricato"])
        self.assertEqual(r["id"], a)
        self.assertEqual(self.conta(), 1)                                   # nessuna riga in piu'
        riga = self.riga(a)
        self.assertEqual((riga["quantita"], riga["scadenza"]), (1, "2027-01-01"))
        self.assertEqual(riga["ingredienti"], "Semola, acqua")              # i dati gia' raccolti restano
        st = self.c.get("/api/inventario", headers=self.h).get_json()
        self.assertEqual((st["totale"], st["riscansionati"], st["da_riscansionare"], st["nuovi"]), (1, 1, 0, 0))

    def test_prodotto_nuovo_durante_la_riscansione(self):
        self.aggiungi("Pasta", "8000000000001")
        self.azzera()
        r = self.aggiungi("Biscotti", "8000000000002")
        self.assertFalse(r["ricaricato"])
        st = self.c.get("/api/inventario", headers=self.h).get_json()
        self.assertEqual((st["riscansionati"], st["da_riscansionare"], st["nuovi"]), (0, 1, 1))

    def test_fuori_dalla_riscansione_si_ricarica_comunque_una_riga_esaurita(self):
        a = self.aggiungi("Latte", "8000000000003", q=1)["id"]
        self.c.put(f"/api/prodotti/{a}", json={"quantita": 0, "_skip_log": True}, headers=self.h)
        r = self.aggiungi("Latte", "8000000000003", q=2)
        self.assertEqual((r["id"], r["ricaricato"]), (a, True))
        self.assertEqual(self.conta(), 1)

    def test_una_riga_attiva_non_si_tocca(self):
        a = self.aggiungi("Latte", "8000000000003", q=1)["id"]
        r = self.aggiungi("Latte", "8000000000003", q=2)
        self.assertNotEqual(r["id"], a)                                      # c'e' gia' un pezzo in casa: altra riga (scadenza diversa)
        self.assertEqual(self.conta(), 2)

    def test_i_suggeriti_tacciono_finche_si_riscansiona(self):
        self.aggiungi("Pasta di Gragnano", "8000000000001")
        conn = database.get_db()
        with conn:
            conn.execute("UPDATE prodotti SET quantita=0")
        self.assertEqual(len(spesa.suggeriti(conn)), 1)
        conn.close()
        self.azzera()
        conn = database.get_db()
        self.assertEqual(spesa.suggeriti(conn), [])
        conn.close()
        self.c.post("/api/inventario/riscansione", json={"attiva": False}, headers=self.h)
        conn = database.get_db()
        self.assertEqual(len(spesa.suggeriti(conn)), 1)
        conn.close()

    def test_riscansione_chiede_un_booleano(self):
        self.assertEqual(self.c.post("/api/inventario/riscansione", json={"attiva": "si"}, headers=self.h).status_code, 400)

    def test_telegram_sospeso_durante_la_riscansione(self):
        invii = []
        with mock.patch.object(notifiche, "get_ha_option", lambda k, d="": {"telegram_token": "t", "telegram_chat_id": "1"}.get(k, d)), \
                mock.patch.object(notifiche, "invia_a_chat", lambda t, c, m: invii.append(m) or {"ok": True, "http_status": 200, "errore": None}):
            notifiche.invia_telegram("a", "acquisto")
            self.assertEqual(len(invii), 1)                                  # normale: parte
            self.aggiungi("Pasta", "8000000000001")                          # anche questa manda il suo «Aggiunto in dispensa»
            self.azzera()
            prima = len(invii)
            notifiche.invia_telegram("b", "acquisto")
            notifiche.invia_telegram("c", "modifica")
            self.assertEqual(len(invii), prima)                              # in riscansione: sospese
            notifiche.invia_telegram("d", "eliminazione")
            self.assertEqual(len(invii), prima + 1)                          # l'eliminazione no


class Dati(Base):
    def test_barcode_online_porta_ingredienti_e_dieta(self):
        with mock.patch.object(products, "_cerca_online", return_value=(OFF_LATTE, True)):
            d = self.c.get("/api/barcode/8000000000777", headers=self.h).get_json()
        self.assertEqual(d["ingredienti"], "Latte, zucchero, amido")
        self.assertEqual((d["dieta"]["vegano"], d["dieta"]["vegetariano"]), ("no", "si"))
        self.assertEqual(d["dieta"]["tracce"], ["uova"])
        self.assertEqual(d["nova"], 4)
        self.assertEqual({x["id"] for x in d["profilo"]["punti"]}, {"nova"})
        self.assertEqual(d["off_dati"]["analisi"], ["en:non-vegan", "en:vegetarian"])

    def test_cache_vecchia_si_aggiorna_una_volta_sola(self):
        conn = database.get_db()
        with conn:
            conn.execute("INSERT INTO barcode_cache (ean, nome, marca, categoria, nutriscore, nutriments) VALUES ('8000000000777', 'Budino', 'Acme', 'desserts', 'C', NULL)")
        conn.close()
        with mock.patch.object(products, "_cerca_online", return_value=(OFF_LATTE, True)) as m:
            d1 = self.c.get("/api/barcode/8000000000777", headers=self.h).get_json()
            d2 = self.c.get("/api/barcode/8000000000777", headers=self.h).get_json()
        self.assertEqual(m.call_count, 1)                                    # la seconda volta basta la cache
        self.assertEqual(d1["fonte"], "cache_locale")
        self.assertEqual((d1["dieta"]["vegano"], d2["dieta"]["vegano"]), ("no", "no"))
        self.assertEqual(d2["ingredienti"], "Latte, zucchero, amido")

    def test_cache_vecchia_con_database_che_non_risponde_non_si_segna_controllata(self):
        conn = database.get_db()
        with conn:
            conn.execute("INSERT INTO barcode_cache (ean, nome) VALUES ('8000000000778', 'Qualcosa')")
        conn.close()
        with mock.patch.object(products, "_cerca_online", return_value=(None, False)):
            d = self.c.get("/api/barcode/8000000000778", headers=self.h).get_json()
        self.assertEqual(d["dieta"]["vegano"], "ignoto")
        conn = database.get_db()
        self.assertIsNone(conn.execute("SELECT off_dati FROM barcode_cache WHERE ean='8000000000778'").fetchone()[0])
        conn.close()

    def test_salvataggio_di_un_prodotto_con_i_dati(self):
        off = {"analisi": ["en:vegan"], "etichette": [], "tracce": [], "categorie": [], "allergeni": []}
        pid = self.aggiungi("Tofu", "8000000000555", ingredienti="Soia, acqua", nova=3, off_dati=off)["id"]
        riga = self.riga(pid)
        self.assertEqual((riga["ingredienti"], riga["nova"]), ("Soia, acqua", 3))
        self.assertEqual(json.loads(riga["off_dati"])["analisi"], ["en:vegan"])
        elenco = {p["id"]: p for p in self.c.get("/api/prodotti", headers=self.h).get_json()}
        self.assertEqual(elenco[pid]["dieta"]["vegano"], "si")
        self.assertNotIn("off_dati", elenco[pid])

    def test_cio_che_non_e_cibo_non_ha_una_dieta_anche_se_e_ancora_in_dispensa(self):
        det = self.aggiungi("Detersivo piatti limone", "8000000000901")["id"]          # posizione «Dispensa», da riclassificare
        pasta = self.aggiungi("Spaghetti n.5", "8000000000902")["id"]
        elenco = {p["id"]: p for p in self.c.get("/api/prodotti", headers=self.h).get_json()}
        self.assertTrue(elenco[det]["non_cibo"])
        self.assertFalse(elenco[pasta]["non_cibo"])

    def test_ingredienti_e_giudizio_manuale_valgono_per_tutte_le_righe_dello_stesso_prodotto(self):
        a = self.aggiungi("Crema", "8000000000444")["id"]
        b = self.aggiungi("Crema", "8000000000444")["id"]
        r = self.c.put(f"/api/prodotti/{a}", json={"ingredienti": "Nocciole, zucchero, latte"}, headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.riga(b)["ingredienti"], "Nocciole, zucchero, latte")
        self.c.put(f"/api/prodotti/{a}", json={"dieta_override": "si"}, headers=self.h)
        elenco = {p["id"]: p for p in self.c.get("/api/prodotti", headers=self.h).get_json()}
        self.assertEqual((elenco[a]["dieta"]["vegano"], elenco[b]["dieta"]["vegano"]), ("si", "si"))
        self.assertEqual(elenco[a]["dieta"]["fonte"], "manuale")
        self.c.put(f"/api/prodotti/{a}", json={"dieta_override": "boh"}, headers=self.h)                 # valore non valido: si toglie
        self.assertIsNone(self.riga(b)["dieta_override"])

    def test_backup_e_ripristino_portano_i_campi_nuovi(self):
        pid = self.aggiungi("Tofu", "8000000000555", ingredienti="Soia, acqua", nova=3, off_dati={"analisi": ["en:vegan"]})["id"]
        bk = admin._build_backup()
        self.assertEqual(bk["prodotti"][0]["ingredienti"], "Soia, acqua")
        conn = database.get_db()
        with conn:
            conn.execute("DELETE FROM prodotti")
        conn.close()
        admin._restore_backup(json.loads(json.dumps(bk, default=str)))
        riga = self.riga(pid)
        self.assertEqual((riga["ingredienti"], riga["nova"]), ("Soia, acqua", 3))


class Raccolta(Base):
    """La raccolta dei dati dei prodotti gia' in casa, con Open Food Facts finto."""

    def test_raccolta(self):
        a = self.aggiungi("Budino", "8000000000001")["id"]
        b = self.aggiungi("Sconosciuto", "8000000000002")["id"]
        c = self.aggiungi("Muto", "8000000000003")["id"]
        d = self.aggiungi("Fatto a mano", "MANUAL-xyz")["id"]

        def finto(base, ean):
            if ean == "8000000000001":
                return OFF_LATTE, "ok"
            if ean == "8000000000002":
                return None, "assente"
            return None, "errore"

        with mock.patch.object(rinv, "_chiedi", finto), mock.patch.object(rinv.time, "sleep", lambda s: None):
            rinv._arr.update(in_corso=True, totale=3, fatti=0, trovati=0, non_trovati=0, errori=0)
            conn = database.get_db()
            eans = [r["ean"] for r in conn.execute(
                "SELECT DISTINCT ean FROM prodotti WHERE ean<>'' AND ean NOT LIKE 'MANUAL-%' AND off_dati IS NULL ORDER BY ean")]
            conn.close()
            self.assertEqual(eans, ["8000000000001", "8000000000002", "8000000000003"])     # il «MANUAL-» non si cerca
            rinv._lavora(eans)
        self.assertEqual({k: rinv._arr[k] for k in ("fatti", "trovati", "non_trovati", "errori")},
                         {"fatti": 3, "trovati": 1, "non_trovati": 1, "errori": 1})
        ra, rb, rc, rd = self.riga(a), self.riga(b), self.riga(c), self.riga(d)
        self.assertEqual(ra["ingredienti"], "Latte, zucchero, amido")
        self.assertEqual(ra["nutriscore"], "C")
        self.assertEqual(json.loads(ra["nutriments"])["proteine"], 3.5)
        self.assertEqual(rb["off_dati"], "{}")                 # controllato: non c'e'
        self.assertIsNone(rc["off_dati"])                       # errore: si riprovera'
        self.assertIsNone(rd["off_dati"])
        conn = database.get_db()
        cache = conn.execute("SELECT nome, ingredienti, off_dati FROM barcode_cache WHERE ean='8000000000001'").fetchone()
        conn.close()
        self.assertEqual((cache["nome"], cache["ingredienti"]), ("Budino", "Latte, zucchero, amido"))     # la riscansione sara' immediata
        # la raccolta non cancella quello che l'utente ha scritto
        self.c.put(f"/api/prodotti/{a}", json={"ingredienti": "Scritto da me"}, headers=self.h)
        with mock.patch.object(rinv, "_chiedi", finto), mock.patch.object(rinv.time, "sleep", lambda s: None):
            conn = database.get_db()
            with conn:
                conn.execute("UPDATE prodotti SET off_dati=NULL WHERE id=?", (a,))
            conn.close()
            rinv._arr.update(in_corso=True)
            rinv._lavora(["8000000000001"])
        self.assertEqual(self.riga(a)["ingredienti"], "Scritto da me")

    def test_il_server_limita_le_richieste_si_rallenta_e_si_riprova(self):
        class R:
            def __init__(self, codice, corpo=None):
                self.status_code, self._c = codice, corpo

            def json(self):
                return self._c

        risposte = [R(429), R(429), R(200, {"status": 1, "product": OFF_LATTE})]
        pause = []
        rinv._pausa = rinv.PAUSA_OFF
        with mock.patch.object(rinv.http_requests, "get", lambda *a, **k: risposte.pop(0)), \
                mock.patch.object(rinv.time, "sleep", lambda s: pause.append(s)):
            prodotto, esito = rinv._chiedi("world.openfoodfacts.org", "8000000000001")
        self.assertEqual((esito, prodotto["product_name"]), ("ok", "Budino"))
        self.assertEqual(len(pause), 2)                                        # due attese, una per ogni 429
        self.assertTrue(pause[1] > pause[0] >= 1.5)                           # ogni volta piu' lunga
        self.assertTrue(rinv._pausa < pause[1])                               # dopo un successo si accorcia di nuovo
        rinv._pausa = rinv.PAUSA_OFF

    def test_troppi_429_di_fila_e_un_errore_da_riprovare(self):
        rinv._pausa = rinv.PAUSA_OFF

        class R:
            status_code = 429

        with mock.patch.object(rinv.http_requests, "get", lambda *a, **k: R()), mock.patch.object(rinv.time, "sleep", lambda s: None):
            self.assertEqual(rinv._chiedi("world.openfoodfacts.org", "8000000000001"), (None, "errore"))
        self.assertTrue(rinv._pausa <= 12)
        rinv._pausa = rinv.PAUSA_OFF

    def test_non_parte_due_volte(self):
        self.aggiungi("Pasta", "8000000000001")
        with rinv._arr_lock:
            rinv._arr["in_corso"] = True
        try:
            with mock.patch.object(rinv.threading, "Thread") as t:
                esito = AVVIA_VERO()
            t.assert_not_called()
            self.assertTrue(esito["in_corso"])
        finally:
            with rinv._arr_lock:
                rinv._arr["in_corso"] = False

    def test_senza_prodotti_da_cercare_non_parte_niente(self):
        self.aggiungi("Fatto a mano", "MANUAL-abc")
        with mock.patch.object(rinv.threading, "Thread") as t:
            esito = AVVIA_VERO()
        t.assert_not_called()
        self.assertEqual((esito["in_corso"], esito["totale"]), (False, 0))


class Report(Base):
    def test_report_e_alert_senza_esauriti_in_riscansione(self):
        self.aggiungi("Pasta", "8000000000001")
        self.aggiungi("Riso", "8000000000002")
        inviati = []
        with mock.patch.object(products, "invia_telegram", lambda m, c=None: inviati.append(m)), \
                mock.patch.object(products, "get_ha_option", lambda k, d="": "x"):
            self.assertEqual(self.c.get("/api/report", headers=self.h).get_json()["esauriti"], 0)       # nessun esaurito: base di confronto
            conn = database.get_db()
            with conn:
                conn.execute("UPDATE prodotti SET quantita=0 WHERE nome='Riso'")
            conn.close()
            self.assertEqual(self.c.get("/api/report", headers=self.h).get_json()["esauriti"], 1)       # fuori riscansione si elencano
            self.azzera()
            self.assertEqual(self.c.get("/api/report", headers=self.h).get_json()["esauriti"], 0)       # in riscansione no
            self.assertFalse(self.c.get("/api/alerts", headers=self.h).get_json()["notifica_inviata"])   # solo esauriti: niente da dire
        self.assertEqual(sum("Esauriti" in m for m in inviati), 1)           # un solo messaggio li elenca: quello fuori riscansione


if __name__ == "__main__":
    unittest.main()
