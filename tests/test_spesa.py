"""Lista della spesa 2.2.0: python -m unittest discover -s tests"""
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

TMP = tempfile.mkdtemp(prefix="dispensa_test_spesa_")
os.environ["DB_PATH"] = os.path.join(TMP, "dispensa.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dispensa_manager"))

import database  # noqa: E402
import spesa as sp  # noqa: E402
from routes import products, shopping, admin  # noqa: E402

database.init_db()
from app import create_app  # noqa: E402

APP = create_app()


def db():
    return database.get_db()


def pulisci():
    c = db()
    with c:
        for t in ("lista_spesa", "prodotti", "suggerimenti_ignorati", "spesa_storico", "storico_movimenti"):
            c.execute(f"DELETE FROM {t}")
    c.close()


def prodotto(nome, quantita, ean="", marca="", posizione="Dispensa", categoria=""):
    c = db()
    with c:
        cur = c.execute("INSERT INTO prodotti (ean, nome, marca, categoria, quantita, posizione) VALUES (?,?,?,?,?,?)",
                        (ean, nome, marca, categoria, quantita, posizione))
    c.close()
    return cur.lastrowid


def imposta_quantita(pid, q):
    c = db()
    with c:
        c.execute("UPDATE prodotti SET quantita=? WHERE id=?", (q, pid))
    c.close()


def nomi_suggeriti():
    c = db()
    try:
        return sorted(s["nome"] for s in sp.suggeriti(c))
    finally:
        c.close()


class Voci(unittest.TestCase):
    def setUp(self):
        pulisci()
        self.c = db()

    def tearDown(self):
        self.c.close()

    def test_aggiunta_e_reparto(self):
        r = sp.aggiungi_voce(self.c, "dentifricio")
        self.assertEqual(r["nome"], "Dentifricio")
        riga = self.c.execute("SELECT * FROM lista_spesa WHERE id=?", (r["id"],)).fetchone()
        self.assertEqual((riga["reparto"], riga["origine"], riga["quantita"]), ("igiene", "manuale", 1))
        self.assertTrue(riga["uid"])

    def test_doppione_non_crea_una_seconda_voce(self):
        sp.aggiungi_voce(self.c, "dentifricio")
        r = sp.aggiungi_voce(self.c, "Dentifrici")           # plurale e maiuscola
        self.assertTrue(r["unita"])
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM lista_spesa").fetchone()[0], 1)
        self.assertEqual(self.c.execute("SELECT quantita FROM lista_spesa").fetchone()[0], 1)   # nessuna quantita' chiesta

    def test_quantita_dal_testo_si_somma(self):
        sp.aggiungi_voce(self.c, "dentifricio")
        sp.aggiungi_voce(self.c, "2 dentifricio")
        self.assertEqual(self.c.execute("SELECT quantita FROM lista_spesa").fetchone()[0], 3)
        r = sp.aggiungi_voce(self.c, "latte x3")
        self.assertEqual(self.c.execute("SELECT quantita FROM lista_spesa WHERE id=?", (r["id"],)).fetchone()[0], 3)

    def test_voce_nel_carrello_torna_da_comprare(self):
        r = sp.aggiungi_voce(self.c, "latte")
        with self.c:
            self.c.execute("UPDATE lista_spesa SET completato=1 WHERE id=?", (r["id"],))
        r2 = sp.aggiungi_voce(self.c, "latte")
        self.assertTrue(r2["riattivata"])
        self.assertEqual(self.c.execute("SELECT completato FROM lista_spesa WHERE id=?", (r["id"],)).fetchone()[0], 0)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM lista_spesa").fetchone()[0], 1)

    def test_avviso_se_gia_in_dispensa(self):
        prodotto("Latte intero", 2, posizione="Frigo")
        prodotto("Latte vuoto", 0)
        r = sp.aggiungi_voce(self.c, "latte")
        self.assertEqual(r["in_dispensa"], [{"nome": "Latte intero", "quantita": 2, "posizione": "Frigo"}])
        self.assertEqual(sp.aggiungi_voce(self.c, "dentifricio")["in_dispensa"], [])

    def test_l_avviso_tiene_conto_del_reparto(self):
        # parole in comune ma prodotti diversi: nessun avviso
        prodotto("Cioccolato al latte di cocco", 2)
        prodotto("Tisana strudel di mele", 1)
        self.assertEqual(sp.aggiungi_voce(self.c, "latte")["in_dispensa"], [])
        self.assertEqual(sp.aggiungi_voce(self.c, "mele")["in_dispensa"], [])
        # stesso reparto: avviso
        prodotto("La morbida carta igienica", 1)
        self.assertEqual(sp.aggiungi_voce(self.c, "carta igienica")["in_dispensa"][0]["nome"], "La morbida carta igienica")

    def test_voce_generica_non_copre_un_prodotto_di_un_altro_reparto(self):
        prodotto("Cioccolato al latte di cocco", 0)
        sp.aggiungi_voce(self.c, "latte")
        self.assertEqual(nomi_suggeriti(), ["Cioccolato al latte di cocco"])

    def test_voce_gia_in_lista_mostra_il_nome_in_lista(self):
        sp.aggiungi_voce(self.c, "Dentifricio")
        r = sp.aggiungi_voce(self.c, "dentifrici")
        self.assertEqual((r["unita"], r["nome"]), (True, "Dentifricio"))

    def test_nome_vuoto_o_senza_parole_utili(self):
        for brutto in ("", "   ", "il la lo", "2"):
            with self.assertRaises(ValueError, msg=brutto):
                sp.aggiungi_voce(self.c, brutto)

    def test_ordine_per_reparto(self):
        for n in ("dentifricio", "mele", "latte", "pasta"):
            sp.aggiungi_voce(self.c, n)
        da_comprare, carrello = sp.lista(self.c)
        self.assertEqual([v["nome"] for v in da_comprare], ["Mele", "Latte", "Pasta", "Dentifricio"])
        self.assertEqual(carrello, [])

    def test_cerca_voci_frequenti_e_prodotti(self):
        prodotto("Dentifricio Mentadent", 1)
        for _ in range(3):
            r = sp.aggiungi_voce(self.c, "detersivo piatti")
            with self.c:
                self.c.execute("DELETE FROM lista_spesa WHERE id=?", (r["id"],))
        sp.aggiungi_voce(self.c, "dentifricio bianco")
        out = sp.cerca(self.c, "de")
        nomi = [o["nome"] for o in out]
        self.assertIn("Detersivo piatti", nomi)
        self.assertEqual(out[0]["fonte"], "frequente")
        self.assertIn("Dentifricio Mentadent", nomi)
        self.assertNotIn("Dentifricio bianco", nomi)         # gia' in lista
        self.assertEqual(sp.cerca(self.c, "d"), [])           # troppo corto


class Suggeriti(unittest.TestCase):
    def setUp(self):
        pulisci()
        self.c = db()

    def tearDown(self):
        self.c.close()

    def test_solo_gli_esauriti_e_senza_doppioni(self):
        prodotto("Pasta penne", 0, ean="8000000000001")
        prodotto("Pasta penne", 0, ean="8000000000001")           # stessa cosa scansionata due volte
        prodotto("Biscotti", 0)
        prodotto("Riso", 3)
        self.assertEqual(nomi_suggeriti(), ["Biscotti", "Pasta penne"])

    def test_non_si_suggerisce_cio_che_ha_ancora_una_scorta(self):
        prodotto("Yogurt greco", 0, ean="8000000000002")
        prodotto("Yogurt greco", 2, ean="8000000000002")           # riacquistato in una riga nuova
        prodotto("Succo di mela", 0)
        prodotto("Succo di mela", 1)                               # stesso nome, senza EAN
        self.assertEqual(nomi_suggeriti(), [])

    def test_voce_in_lista_o_nel_carrello_copre_il_suggerimento(self):
        prodotto("Latte intero parzialmente scremato", 0)
        prodotto("Biscotti", 0)
        sp.aggiungi_voce(self.c, "latte")                          # voce generica
        r = sp.aggiungi_voce(self.c, "biscotti")
        with self.c:
            self.c.execute("UPDATE lista_spesa SET completato=1 WHERE id=?", (r["id"],))
        self.assertEqual(nomi_suggeriti(), [])

    def test_non_serve_nasconde_fino_al_ritorno_in_dispensa(self):
        pid = prodotto("Caffe", 0, ean="8000000000003")
        prodotto("Caffe", 0, ean="8000000000003")
        self.assertEqual(nomi_suggeriti(), ["Caffe"])
        self.assertEqual(sp.ignora_suggerito(self.c, pid), 2)       # nasconde anche il doppione
        self.assertEqual(nomi_suggeriti(), [])
        imposta_quantita(pid, 1)                                    # lo ricompro
        self.assertEqual(nomi_suggeriti(), [])
        imposta_quantita(pid, 0)                                    # e lo finisco di nuovo
        self.assertEqual(nomi_suggeriti(), ["Caffe"])

    def test_aggiungi_suggerito_lo_porta_in_lista(self):
        pid = prodotto("Pasta penne", 0, ean="8000000000004", marca="Barilla")
        r = sp.aggiungi_suggerito(self.c, pid, "luigi")
        riga = self.c.execute("SELECT * FROM lista_spesa WHERE id=?", (r["id"],)).fetchone()
        self.assertEqual((riga["origine"], riga["ean"], riga["marca"], riga["aggiunto_da"]), ("suggerimento", "8000000000004", "Barilla", "luigi"))
        self.assertEqual(nomi_suggeriti(), [])                     # non e' piu' un suggerimento
        self.assertIsNone(sp.aggiungi_suggerito(self.c, 99999))

    def test_manual_ean_non_conta_come_ean(self):
        prodotto("Torta della nonna", 0, ean="MANUAL-1")
        prodotto("Torta della nonna", 2, ean="MANUAL-2")
        self.assertEqual(nomi_suggeriti(), [])                     # stesso nome in scorta

    def test_giorni_dall_ultimo_consumo(self):
        prodotto("Olio", 0, ean="8000000000005")
        with self.c:
            self.c.execute("INSERT INTO storico_movimenti (ean, nome, tipo, data) VALUES ('8000000000005','Olio','consumo', datetime('now','-10 day'))")
        self.assertEqual(sp.suggeriti(self.c)[0]["giorni"], 10)


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = APP.test_client()
        r = cls.c.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        cls.h = {"Authorization": "Bearer " + r.get_json()["access_token"]}

    def setUp(self):
        pulisci()

    def test_vista_completa(self):
        prodotto("Pasta penne", 0, ean="8000000000006")
        r = self.c.post("/api/lista-spesa", json={"nome": "2 dentifricio"}, headers=self.h)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["nome"], "Dentifricio")
        v = self.c.get("/api/spesa", headers=self.h).get_json()
        self.assertEqual([x["nome"] for x in v["da_comprare"]], ["Dentifricio"])
        self.assertEqual(v["da_comprare"][0]["quantita"], 2)
        self.assertEqual(v["da_comprare"][0]["aggiunto_da"], "admin")
        self.assertEqual([x["nome"] for x in v["suggeriti"]], ["Pasta penne"])
        self.assertEqual(v["conteggi"], {"da_comprare": 1, "carrello": 0, "suggeriti": 1})
        self.assertEqual(self.c.get("/api/spesa/conteggi", headers=self.h).get_json()["suggeriti"], 1)
        self.assertGreaterEqual(len(v["reparti"]), 10)

    def test_aggiungi_e_ignora_suggeriti_via_api(self):
        a = prodotto("Pasta penne", 0)
        b = prodotto("Biscotti", 0)
        r = self.c.post(f"/api/spesa/suggeriti/{a}/aggiungi", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.c.post(f"/api/spesa/suggeriti/{b}/ignora", headers=self.h).status_code, 200)
        v = self.c.get("/api/spesa", headers=self.h).get_json()
        self.assertEqual([x["nome"] for x in v["da_comprare"]], ["Pasta penne"])
        self.assertEqual(v["suggeriti"], [])
        self.assertEqual(self.c.post("/api/spesa/suggeriti/99999/aggiungi", headers=self.h).status_code, 404)
        self.assertEqual(self.c.post("/api/spesa/suggeriti/99999/ignora", headers=self.h).status_code, 404)

    def test_nascondi_i_suggeriti_vecchi(self):
        vecchio = prodotto("Olio", 0, ean="8000000000010")
        recente = prodotto("Pasta penne", 0, ean="8000000000011")
        c = db()
        with c:
            c.execute("INSERT INTO storico_movimenti (ean, nome, tipo, data) VALUES ('8000000000010','Olio','consumo', datetime('now','-120 day'))")
            c.execute("INSERT INTO storico_movimenti (ean, nome, tipo, data) VALUES ('8000000000011','Pasta penne','consumo', datetime('now','-5 day'))")
        c.close()
        r = self.c.post("/api/spesa/suggeriti/ignora-vecchi", headers=self.h).get_json()
        self.assertEqual(r["nascosti"], 1)
        v = self.c.get("/api/spesa", headers=self.h).get_json()
        self.assertEqual([x["prodotto_id"] for x in v["suggeriti"]], [recente])
        self.assertEqual(self.c.post("/api/spesa/suggeriti/ignora-vecchi?giorni=x", headers=self.h).status_code, 400)
        del vecchio

    def test_aggiungi_tutti(self):
        for n in ("Pasta penne", "Biscotti", "Riso"):
            prodotto(n, 0)
        r = self.c.post("/api/spesa/suggeriti/aggiungi-tutti", headers=self.h).get_json()
        self.assertEqual(r["aggiunti"], 3)
        self.assertEqual(self.c.get("/api/spesa", headers=self.h).get_json()["suggeriti"], [])

    def test_aggiornamento_voce(self):
        vid = self.c.post("/api/lista-spesa", json={"nome": "latte"}, headers=self.h).get_json()["id"]
        self.assertEqual(self.c.put(f"/api/lista-spesa/{vid}", json={"quantita": 0}, headers=self.h).status_code, 400)
        self.assertEqual(self.c.put(f"/api/lista-spesa/{vid}", json={"quantita": "x"}, headers=self.h).status_code, 400)
        self.assertEqual(self.c.put("/api/lista-spesa/99999", json={"quantita": 2}, headers=self.h).status_code, 404)
        self.assertEqual(self.c.put(f"/api/lista-spesa/{vid}", json={"quantita": 4}, headers=self.h).status_code, 200)
        self.c.put(f"/api/lista-spesa/{vid}", json={"completato": 1}, headers=self.h)       # non azzera la quantita'
        v = self.c.get("/api/spesa", headers=self.h).get_json()
        self.assertEqual(v["carrello"][0]["quantita"], 4)
        self.c.put(f"/api/lista-spesa/{vid}", json={"nome": "pane"}, headers=self.h)
        self.assertEqual(self.c.get("/api/spesa", headers=self.h).get_json()["carrello"][0]["reparto"], "pane")
        self.assertEqual(self.c.put(f"/api/lista-spesa/{vid}", json={"nome": "il"}, headers=self.h).status_code, 400)

    def test_nome_vuoto_rifiutato_e_svuota(self):
        self.assertEqual(self.c.post("/api/lista-spesa", json={"nome": "  "}, headers=self.h).status_code, 400)
        vid = self.c.post("/api/lista-spesa", json={"nome": "latte"}, headers=self.h).get_json()["id"]
        self.c.put(f"/api/lista-spesa/{vid}", json={"completato": 1}, headers=self.h)
        self.assertEqual(self.c.delete("/api/lista-spesa/svuota-completati", headers=self.h).get_json()["rimossi"], 1)
        self.assertEqual(self.c.get("/api/lista-spesa", headers=self.h).get_json(), [])

    def test_senza_login_401(self):
        for url in ("/api/spesa", "/api/spesa/conteggi", "/api/spesa/cerca?q=ab"):
            self.assertEqual(self.c.get(url).status_code, 401, url)

    def test_cerca(self):
        prodotto("Dentifricio Mentadent", 1)
        r = self.c.get("/api/spesa/cerca?q=denti", headers=self.h).get_json()
        self.assertEqual(r, [{"nome": "Dentifricio Mentadent", "fonte": "prodotto"}])


class Sensori(unittest.TestCase):
    def setUp(self):
        pulisci()

    def test_gli_esauriti_non_entrano_piu_da_soli_in_lista(self):
        prodotto("Pasta penne", 0)
        prodotto("Biscotti", 0)
        inviati = []
        env = {"SUPERVISOR_TOKEN": "token-finto", "HA_URL": "http://ha.finto"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(products.http_requests, "post", lambda url, **kw: inviati.append((url, kw["json"]))):
            products.aggiorna_sensori_ha()
            products.aggiorna_sensori_ha()
        c = db()
        self.assertEqual(c.execute("SELECT COUNT(*) FROM lista_spesa").fetchone()[0], 0)
        c.close()
        stati = {u.rsplit("/", 1)[1]: j for u, j in inviati[-6:]}
        self.assertEqual(stati["sensor.dispensa_suggeriti"]["state"], 2)
        self.assertEqual(sorted(stati["sensor.dispensa_suggeriti"]["attributes"]["prodotti"]), ["Biscotti", "Pasta penne"])
        self.assertEqual(stati["sensor.dispensa_lista_spesa"]["state"], 0)
        self.assertEqual(stati["sensor.dispensa_esauriti"]["state"], 2)

    def test_sensore_lista(self):
        c = db()
        sp.aggiungi_voce(c, "2 dentifricio")
        c.close()
        inviati = []
        with mock.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "t", "HA_URL": "http://ha.finto"}), \
                mock.patch.object(products.http_requests, "post", lambda url, **kw: inviati.append((url, kw["json"]))):
            products.aggiorna_sensori_ha()
        stato = {u.rsplit("/", 1)[1]: j for u, j in inviati}["sensor.dispensa_lista_spesa"]
        self.assertEqual(stato["state"], 1)
        self.assertEqual(stato["attributes"]["voci"], [{"nome": "Dentifricio", "quantita": 2, "reparto": "igiene"}])


class Telegram(unittest.TestCase):
    def setUp(self):
        pulisci()

    def test_testo(self):
        c = db()
        try:
            self.assertIsNone(shopping.testo_telegram(c))
            sp.aggiungi_voce(c, "mele")
            sp.aggiungi_voce(c, "dentifricio_bianco")
            prodotto("Pasta *penne*", 0)
            t = shopping.testo_telegram(c)
        finally:
            c.close()
        self.assertIn("Frutta e verdura", t)
        self.assertLess(t.index("Mele"), t.index("Dentifricio"))        # ordine dei reparti
        self.assertIn("Finiti in dispensa", t)
        self.assertIn("Pasta \\*penne\\*", t)                            # Markdown protetto
        self.assertIn("dentifricio\\_bianco".capitalize(), t)

    def test_solo_suggerimenti(self):
        prodotto("Biscotti", 0)
        c = db()
        try:
            t = shopping.testo_telegram(c)
        finally:
            c.close()
        self.assertIn("Nessuna voce in lista", t)
        self.assertIn("Biscotti", t)


class Migrazione(unittest.TestCase):
    """Un database della 2.1.x con 66 voci automatiche, una manuale e una nel carrello."""

    def costruisci(self, percorso):
        c = sqlite3.connect(percorso)
        c.executescript("""
            CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, description TEXT, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO app_settings (key, value) VALUES ('schema_version', '7');
            CREATE TABLE prodotti (id INTEGER PRIMARY KEY AUTOINCREMENT, ean TEXT, nome TEXT NOT NULL, marca TEXT, categoria TEXT,
                immagine_url TEXT, quantita INTEGER DEFAULT 1, scadenza TEXT, data_inserimento TEXT DEFAULT (datetime('now')),
                note TEXT, nutriments TEXT, nutriscore TEXT, posizione TEXT DEFAULT 'Dispensa', prezzo REAL);
            CREATE TABLE lista_spesa (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, quantita INTEGER DEFAULT 1,
                ean TEXT, marca TEXT, completato INTEGER DEFAULT 0, data_aggiunta TEXT DEFAULT (datetime('now')));
        """)
        for i in range(66):
            c.execute("INSERT INTO prodotti (ean, nome, quantita) VALUES (?, ?, 0)", (f"80000{i:08d}", f"Prodotto {i}"))
            c.execute("INSERT INTO lista_spesa (nome, ean) VALUES (?, ?)", (f"Prodotto {i}", f"80000{i:08d}"))
        c.execute("INSERT INTO lista_spesa (nome, ean) VALUES ('Vegan Salad Cream', '8999999999999')")           # manuale
        c.execute("INSERT INTO lista_spesa (nome, completato) VALUES ('Prodotto 3', 1)")                          # nel carrello
        c.commit()
        c.close()

    def test_migra_senza_perdere_nulla(self):
        p = os.path.join(TMP, "v7.db")
        self.costruisci(p)
        vecchio = database.DB_PATH
        database.DB_PATH = p
        try:
            database.init_db()
            c = database.get_db()
            versione = c.execute("SELECT value FROM app_settings WHERE key='schema_version'").fetchone()[0]
            righe = c.execute("SELECT * FROM lista_spesa ORDER BY id").fetchall()
            legacy = c.execute("SELECT COUNT(*) FROM lista_spesa_legacy").fetchone()[0]
            sugg = sp.suggeriti(c)
            colonne = {r[1] for r in c.execute("PRAGMA table_info(lista_spesa)")}
            c.close()
        finally:
            database.DB_PATH = vecchio
        self.assertEqual(versione, str(database.SCHEMA_VERSION))     # arriva all'ultima versione
        self.assertEqual(sorted(r["nome"] for r in righe), ["Prodotto 3", "Vegan Salad Cream"])
        self.assertEqual(legacy, 66)                                    # copia di sicurezza delle voci tolte
        self.assertTrue(all(r["uid"] and r["nome_norm"] and r["reparto"] for r in righe))
        self.assertEqual({"uid", "origine", "nome_norm", "reparto", "aggiunto_da", "aggiornato_il", "completato_il"} - colonne, set())
        # gli esauriti non spariscono: sono suggerimenti (tranne quello coperto dalla voce nel carrello)
        self.assertEqual(len(sugg), 65)

    def test_seconda_esecuzione_non_cambia_nulla(self):
        p = os.path.join(TMP, "v7b.db")
        self.costruisci(p)
        vecchio = database.DB_PATH
        database.DB_PATH = p
        try:
            database.init_db()
            database.init_db()
            c = database.get_db()
            n = c.execute("SELECT COUNT(*) FROM lista_spesa").fetchone()[0]
            legacy = c.execute("SELECT COUNT(*) FROM lista_spesa_legacy").fetchone()[0]
            c.close()
        finally:
            database.DB_PATH = vecchio
        self.assertEqual((n, legacy), (2, 66))


class Backup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = APP.test_client()
        r = cls.c.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        cls.h = {"Authorization": "Bearer " + r.get_json()["access_token"]}

    def setUp(self):
        pulisci()

    def test_il_backup_include_la_lista_e_un_backup_vecchio_si_ripristina(self):
        self.c.post("/api/lista-spesa", json={"nome": "latte"}, headers=self.h)
        b = self.c.get("/api/admin/backup", headers=self.h).get_json()
        self.assertEqual(b["lista_spesa"][0]["nome"], "Latte")
        self.assertIn("uid", b["lista_spesa"][0])
        # backup di una versione precedente: righe senza le colonne nuove
        b["lista_spesa"] = [{"id": 1, "nome": "Pane", "quantita": 1, "ean": "", "marca": "", "completato": 0, "data_aggiunta": "2026-01-01 10:00:00"}]
        r = self.c.post("/api/admin/restore", json={"backup": b, "confirm": "RIPRISTINA"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.get_json())
        v = self.c.get("/api/spesa", headers=self.h).get_json()
        self.assertEqual(v["da_comprare"][0]["nome"], "Pane")
        self.assertTrue(v["da_comprare"][0]["uid"])
        self.assertEqual(v["da_comprare"][0]["reparto"], "pane")


if __name__ == "__main__":
    unittest.main()
