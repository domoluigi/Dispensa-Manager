"""Posizioni 2.4.0 (Dispensa, Frigo, Congelatore, Saponi, Altro): python -m unittest discover -s tests"""
import os
import sys
import tempfile
import unittest
from unittest import mock

TMP = tempfile.mkdtemp(prefix="dispensa_test_pos_")
os.environ["DB_PATH"] = os.path.join(TMP, "dispensa.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dispensa_manager"))

import database  # noqa: E402
import riclassifica as rc  # noqa: E402
from posizioni import classifica, POSIZIONI  # noqa: E402
from routes import products  # noqa: E402

database.init_db()
from app import create_app  # noqa: E402

APP = create_app()


class Classificatore(unittest.TestCase):
    def pos(self, nome, marca="", **kw):
        return classifica(nome, marca, **kw)["posizione"]

    def test_saponi(self):
        for n in ("Dentifricio Mentadent", "Shampoo delicato", "Detersivo piatti limone", "Bagnoschiuma", "Ammorbidente"):
            self.assertEqual(self.pos(n), "Saponi", n)

    def test_altro(self):
        for n in ("Sacchetti per freezer", "Pellicola trasparente", "Pile stilo AA", "Lampadina LED"):
            self.assertEqual(self.pos(n), "Altro", n)

    def test_congelatore(self):
        for n in ("Piselli surgelati", "Gelato alla vaniglia", "Bastoncini di pesce congelati"):
            self.assertEqual(self.pos(n), "Freezer", n)

    def test_cavolo_non_e_un_cavo(self):
        self.assertNotEqual(self.pos("Cavolo cappuccio"), "Altro")

    def test_cibo_comune(self):
        self.assertEqual(self.pos("Mozzarella di bufala"), "Frigo")
        self.assertEqual(self.pos("Spaghetti n.5"), "Dispensa")

    def test_i_non_cibo_sono_sicuri_il_resto_no(self):
        self.assertTrue(classifica("Shampoo")["sicuro"])
        self.assertEqual(classifica("xyzzy qwerty")["livello"], "basso")
        self.assertFalse(classifica("xyzzy qwerty")["sicuro"])

    def test_posizioni_valide(self):
        self.assertEqual(POSIZIONI, ("Dispensa", "Frigo", "Freezer", "Saponi", "Altro"))


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = APP.test_client()
        r = cls.c.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        cls.h = {"Authorization": "Bearer " + r.get_json()["access_token"]}

    def setUp(self):
        self.patch = mock.patch.object(products, "_async", lambda fn, *a, **k: fn(*a, **k))
        self.patch.start()
        conn = database.get_db()
        with conn:
            for t in ("prodotti", "posizioni_log", "riclassifica_ignorati", "storico_movimenti"):
                conn.execute(f"DELETE FROM {t}")
        conn.close()

    def tearDown(self):
        self.patch.stop()

    def inserisci(self, nome, posizione="Dispensa", **extra):
        r = self.c.post("/api/prodotti", json={"nome": nome, "quantita": 1, "ean": "", "posizione": posizione, **extra}, headers=self.h)
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()["id"]

    def posizione_di(self, pid):
        conn = database.get_db()
        try:
            return conn.execute("SELECT posizione FROM prodotti WHERE id=?", (pid,)).fetchone()["posizione"]
        finally:
            conn.close()

    def test_prodotto_nuovo_senza_posizione_viene_classificato(self):
        r = self.c.post("/api/prodotti", json={"nome": "Dentifricio", "quantita": 1, "ean": ""}, headers=self.h)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.posizione_di(r.get_json()["id"]), "Saponi")

    def test_posizione_scelta_a_mano_non_si_tocca(self):
        pid = self.inserisci("Dentifricio", "Dispensa")
        self.assertEqual(self.posizione_di(pid), "Dispensa")

    def test_posizione_sconosciuta_rifiutata(self):
        pid = self.inserisci("Latte")
        r = self.c.put(f"/api/prodotti/{pid}", json={"posizione": "Cantina"}, headers=self.h)
        self.assertEqual(r.status_code, 400)
        r = self.c.post("/api/prodotti/bulk", json={"ids": [pid], "action": "set_posizione", "value": "Cantina"}, headers=self.h)
        self.assertEqual(r.status_code, 400)

    def test_bulk_verso_le_nuove_posizioni(self):
        pid = self.inserisci("Roba")
        r = self.c.post("/api/prodotti/bulk", json={"ids": [pid], "action": "set_posizione", "value": "Altro"}, headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.posizione_di(pid), "Altro")

    def test_endpoint_classifica(self):
        d = self.c.get("/api/classifica?nome=Shampoo", headers=self.h).get_json()
        self.assertEqual((d["posizione"], d["etichetta"], d["suggerita"]), ("Saponi", "Saponi", True))
        self.assertEqual(self.c.get("/api/classifica?nome=Gelato", headers=self.h).get_json()["etichetta"], "Congelatore")
        self.assertIsNone(self.c.get("/api/classifica?nome=a", headers=self.h).get_json()["posizione"])
        self.assertEqual(self.c.get("/api/classifica?nome=Shampoo").status_code, 401)

    def test_riclassifica_proposta_applica_e_annulla(self):
        sapone = self.inserisci("Shampoo", "Dispensa")
        gelato = self.inserisci("Gelato alla crema", "Frigo")
        giusto = self.inserisci("Spaghetti", "Dispensa")
        d = self.c.get("/api/prodotti/riclassifica", headers=self.h).get_json()
        proposti = {x["id"]: x for x in d["proposte"]}
        self.assertEqual(set(proposti), {sapone, gelato})
        self.assertEqual((proposti[sapone]["a"], proposti[gelato]["a"]), ("Saponi", "Freezer"))
        self.assertEqual(d["conteggi"]["alto"], 2)
        # il giusto non si muove, e niente cambia finche' non si conferma
        self.assertEqual(self.posizione_di(sapone), "Dispensa")

        r = self.c.post("/api/prodotti/riclassifica", json={"ids": [sapone, gelato]}, headers=self.h).get_json()
        self.assertEqual(r["cambiati"], 2)
        self.assertEqual((self.posizione_di(sapone), self.posizione_di(gelato), self.posizione_di(giusto)), ("Saponi", "Freezer", "Dispensa"))
        self.assertEqual(self.c.get("/api/prodotti/riclassifica/conteggio", headers=self.h).get_json(), {"alto": 0, "medio": 0})

        a = self.c.post("/api/prodotti/riclassifica/annulla", json={"lotto": r["lotto"]}, headers=self.h).get_json()
        self.assertEqual(a["ripristinati"], 2)
        self.assertEqual((self.posizione_di(sapone), self.posizione_di(gelato)), ("Dispensa", "Frigo"))

    def test_annulla_rispetta_lo_spostamento_fatto_nel_frattempo(self):
        sapone = self.inserisci("Shampoo", "Dispensa")
        r = self.c.post("/api/prodotti/riclassifica", json={"ids": [sapone]}, headers=self.h).get_json()
        self.c.put(f"/api/prodotti/{sapone}", json={"posizione": "Altro"}, headers=self.h)
        a = self.c.post("/api/prodotti/riclassifica/annulla", json={"lotto": r["lotto"]}, headers=self.h).get_json()
        self.assertEqual(a["ripristinati"], 0)
        self.assertEqual(self.posizione_di(sapone), "Altro")

    def test_ignorati_non_tornano_e_il_client_non_decide_la_destinazione(self):
        sapone = self.inserisci("Shampoo", "Dispensa")
        self.c.post("/api/prodotti/riclassifica", json={"ids": [], "ignora": [sapone]}, headers=self.h)
        self.assertEqual(self.c.get("/api/prodotti/riclassifica", headers=self.h).get_json()["proposte"], [])
        # un id che non e' una proposta non viene spostato
        giusto = self.inserisci("Spaghetti", "Dispensa")
        r = self.c.post("/api/prodotti/riclassifica", json={"ids": [giusto]}, headers=self.h).get_json()
        self.assertEqual(r["cambiati"], 0)
        self.assertEqual(self.posizione_di(giusto), "Dispensa")

    def test_ids_non_numerici(self):
        r = self.c.post("/api/prodotti/riclassifica", json={"ids": ["x"]}, headers=self.h)
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
