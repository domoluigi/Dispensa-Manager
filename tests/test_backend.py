"""Test del backend: python -m unittest discover -s tests   (dalla cartella del repository)

Usano un database temporaneo e mettono dei finti al posto di Open Food Facts e di Telegram.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

TMP = tempfile.mkdtemp(prefix="dispensa_test_")
os.environ["DB_PATH"] = os.path.join(TMP, "dispensa.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dispensa_manager"))

import database  # noqa: E402
import notifiche  # noqa: E402
import suggerimenti  # noqa: E402
from routes import products  # noqa: E402

database.init_db()
from app import create_app  # noqa: E402

APP = create_app()


class Suggerimenti(unittest.TestCase):
    def test_sugo_guarda_il_tag_piu_specifico(self):
        # la catena contiene anche "vegetables based foods": non deve vincere sul sugo
        tag = ["plant based foods and beverages", "vegetables based foods", "sauces", "pasta sauces", "tomato sauces"]
        s = suggerimenti.suggerisci_da_categoria(tag)
        self.assertEqual((s["posizione"], s["scadenza_giorni"]), ("Dispensa", 540))

    def test_mozzarella_in_frigo(self):
        s = suggerimenti.suggerisci_da_categoria(["dairies", "cheeses", "mozzarella"])
        self.assertEqual((s["posizione"], s["scadenza_giorni"]), ("Frigo", 8))

    def test_surgelato(self):
        s = suggerimenti.suggerisci_da_categoria(["frozen foods", "frozen pizzas"])
        self.assertEqual(s["posizione"], "Freezer")

    def test_latte_generico_non_inventa_la_data(self):
        s = suggerimenti.suggerisci_da_categoria(["beverages", "milks"])
        self.assertIsNone(s["scadenza_giorni"])
        self.assertIsNone(s["fonte"])

    def test_sconosciuto_nessuna_data(self):
        s = suggerimenti.suggerisci_da_categoria(["qualcosa di strano"], "Xyz")
        self.assertIsNone(s["scadenza_giorni"])

    def test_storico_mediana_ed_esclusione_aperti(self):
        conn = database.get_db()
        try:
            with conn:
                for ins, scad, note in [("2026-01-01 10:00:00", "2026-01-11", ""), ("2026-02-01 10:00:00", "2026-02-21", ""),
                                        ("2026-03-01 10:00:00", "2026-03-31", ""), ("2026-04-01 10:00:00", "2026-04-02", "Aperto il 01/04")]:
                    conn.execute("INSERT INTO prodotti (ean, nome, quantita, scadenza, data_inserimento, note, posizione) VALUES (?,?,?,?,?,?,?)",
                                 ("8000000000001", "Prova", 1, scad, ins, note, "Frigo"))
            s = suggerimenti.costruisci_suggerimento(conn, "8000000000001", ["pasta"], "")
        finally:
            conn.close()
        self.assertEqual(s["fonte"], "storico")
        self.assertEqual(s["campioni"], 3)           # il prodotto «Aperto il…» non conta
        self.assertEqual(s["scadenza_giorni"], 20)   # mediana di 10, 20, 30


class Notifiche(unittest.TestCase):
    def test_md_esc(self):
        self.assertEqual(notifiche.md_esc("a_b*c[d`e"), r"a\_b\*c\[d\`e")
        self.assertEqual(notifiche.md_esc(None), "")

    def test_token_non_resta_nel_log(self):
        token = "123456:ABC-def_GHI"
        msg = f"HTTPSConnectionPool: Max retries exceeded with url: /bot{token}/sendMessage"
        self.assertNotIn(token, notifiche.redact(msg, token))
        self.assertNotIn("ABC-def", notifiche.redact(msg))      # anche senza conoscere il token


def accesso(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.get_json()
    return {"Authorization": "Bearer " + r.get_json()["access_token"]}


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = APP.test_client()
        cls.h = accesso(cls.c)

    def setUp(self):
        self.patches = [mock.patch.object(products, "_async", lambda fn, *a, **k: fn(*a, **k))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def nuovo(self, **extra):
        dati = {"nome": "Test", "quantita": 2, "ean": "8076809513388"}
        dati.update(extra)
        r = self.c.post("/api/prodotti", json=dati, headers=self.h)
        self.assertEqual(r.status_code, 201)
        return r.get_json()["id"]

    def test_quantita_non_valida_viene_corretta_o_rifiutata(self):
        pid = self.nuovo(quantita="abc")
        r = self.c.get("/api/prodotti", headers=self.h).get_json()
        self.assertEqual(next(p for p in r if p["id"] == pid)["quantita"], 1)
        self.assertEqual(self.c.put(f"/api/prodotti/{pid}", json={"quantita": "x"}, headers=self.h).status_code, 400)
        self.assertEqual(self.c.put(f"/api/prodotti/{pid}", json={"quantita": -3}, headers=self.h).status_code, 400)

    def test_consuma_e_butta(self):
        pid = self.nuovo(quantita=2)
        r = self.c.post(f"/api/prodotti/{pid}/consuma", headers=self.h).get_json()
        self.assertEqual(r["quantita"], 1)
        r = self.c.post(f"/api/prodotti/{pid}/consuma", json={"quantita": 5}, headers=self.h).get_json()
        self.assertEqual(r["quantita"], 0)                         # mai sotto zero
        self.assertEqual(self.c.post(f"/api/prodotti/{pid}/butta", headers=self.h).status_code, 200)
        self.assertEqual(self.c.post(f"/api/prodotti/{pid}/butta", headers=self.h).status_code, 404)
        conn = database.get_db()
        try:
            tipi = [r["tipo"] for r in conn.execute("SELECT tipo FROM storico_movimenti WHERE ean='8076809513388' ORDER BY id").fetchall()]
        finally:
            conn.close()
        self.assertIn("consumo", tipi)
        self.assertIn("eliminato", tipi)

    def test_azioni_ha_con_api_key_e_senza_credenziali(self):
        pid = self.nuovo(quantita=3)
        self.assertEqual(self.c.post(f"/api/prodotti/{pid}/consuma").status_code, 401)
        chiave = self.c.get("/api/admin/api-key", headers=self.h).get_json()["api_key"]
        r = self.c.post(f"/api/prodotti/{pid}/consuma", headers={"x-api-key": chiave})
        self.assertEqual(r.get_json()["quantita"], 2)

    def test_bulk_extend_negativo_non_cancella_le_date(self):
        pid = self.nuovo(scadenza="2027-05-10")
        r = self.c.post("/api/prodotti/bulk", json={"ids": [pid], "action": "extend_scadenza", "value": -5}, headers=self.h)
        self.assertEqual(r.status_code, 200)
        p = next(x for x in self.c.get("/api/prodotti", headers=self.h).get_json() if x["id"] == pid)
        self.assertEqual(p["scadenza"], "2027-05-05")
        r = self.c.post("/api/prodotti/bulk", json={"ids": [pid], "action": "extend_scadenza", "value": 99999}, headers=self.h)
        self.assertEqual(r.status_code, 400)

    def test_barcode_online_miss_cache_e_suggerimento(self):
        prodotto = {"product_name": "Arrabbiata", "brands": "Barilla, altro", "image_front_small_url": "https://x/y.jpg",
                    "categories_tags": ["en:plant-based-foods", "en:sauces", "en:pasta-sauces", "en:arrabbiata-sauces"],
                    "nutriscore_grade": "b", "nutriments": {"energy-kcal_100g": 50}}
        chiamate = []

        def finto(url, headers):
            chiamate.append(url)
            return prodotto if ("openfoodfacts" in url and "8076809513388" in url) else None

        with mock.patch.object(products, "_scarica_prodotto", finto):
            d = self.c.get("/api/barcode/8076809513388", headers=self.h).get_json()
            self.assertTrue(d["trovato"])
            self.assertEqual(d["marca"], "Barilla")
            self.assertEqual(d["categoria"], "arrabbiata sauces")          # la piu' specifica
            self.assertEqual(d["suggerimento"]["scadenza_giorni"], 540)
            self.assertEqual(d["nutriscore"], "B")
            self.assertEqual(len(chiamate), 3)                              # i tre database interrogati insieme

            chiamate.clear()
            r1 = self.c.get("/api/barcode/1234567890123", headers=self.h)
            self.assertEqual(r1.status_code, 404)
            n1 = len(chiamate)
            self.c.get("/api/barcode/1234567890123", headers=self.h)
            self.assertEqual(len(chiamate), n1)                             # secondo giro: dalla cache dei non trovati
            self.c.get("/api/barcode/1234567890123?refresh=1", headers=self.h)
            self.assertEqual(len(chiamate), 2 * n1)

    def test_barcode_errore_di_rete_non_viene_ricordato(self):
        def guasto(url, headers):
            raise RuntimeError("rete giu'")

        with mock.patch.object(products, "_scarica_prodotto", guasto):
            self.assertEqual(self.c.get("/api/barcode/5555555555555", headers=self.h).status_code, 404)
        self.assertNotIn("5555555555555", products._miss)

    def test_barcode_ean_non_numerico_non_esce_in_rete(self):
        with mock.patch.object(products, "_scarica_prodotto", side_effect=AssertionError("non deve chiamare")):
            self.assertEqual(self.c.get("/api/barcode/..%2Fx", headers=self.h).status_code, 404)
            self.assertEqual(self.c.get("/api/barcode/MANUAL-123", headers=self.h).status_code, 404)

    def test_ultimo_admin_non_si_toglie(self):
        utenti = self.c.get("/api/admin/users", headers=self.h).get_json()
        admin_id = next(u["id"] for u in utenti if u["username"] == "admin")
        self.assertEqual(self.c.patch(f"/api/admin/users/{admin_id}", json={"is_admin": False}, headers=self.h).status_code, 400)
        self.assertEqual(self.c.patch(f"/api/admin/users/{admin_id}", json={"is_active": False}, headers=self.h).status_code, 400)

    def test_restore_ignora_colonne_sconosciute(self):
        backup = self.c.get("/api/admin/backup", headers=self.h).get_json()
        backup["prodotti"].append({"id": 9999, "nome": "Ripristinato", "colonna_inventata": "x); DROP TABLE users;--"})
        r = self.c.post("/api/admin/restore", json={"backup": backup, "confirm": "RIPRISTINA"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.get_json())
        nomi = [p["nome"] for p in self.c.get("/api/prodotti", headers=self.h).get_json()]
        self.assertIn("Ripristinato", nomi)
        self.assertEqual(self.c.get("/api/admin/users", headers=self.h).status_code, 200)   # users intatta

    def test_backup_automatico_ruota_le_copie(self):
        from routes import admin
        cartella = os.path.join(TMP, "backups")
        os.makedirs(cartella, exist_ok=True)
        for g in range(1, 8):
            open(os.path.join(cartella, f"auto_backup_2026010{g}.json"), "w").close()
        with mock.patch.object(admin, "BACKUPS_DIR", cartella):
            admin.scrivi_backup_auto()
        copie = sorted(f for f in os.listdir(cartella) if f.startswith("auto_backup_"))
        self.assertEqual(len(copie), admin.BACKUP_AUTO_COPIE)
        self.assertTrue(os.path.exists(os.path.join(cartella, "auto_backup.json")))

    def test_csp_senza_cdn_e_file_locali(self):
        r = self.c.get("/api/health")
        csp = r.headers["Content-Security-Policy"]
        self.assertNotIn("unpkg", csp)
        self.assertNotIn("jsdelivr", csp)
        for f in ("vendor/zxing.min.js", "vendor/chart.umd.min.js", "vendor/tesseract/tesseract.min.js",
                  "vendor/tesseract/worker.min.js", "vendor/tesseract/tesseract-core-simd-lstm.wasm.js",
                  "vendor/tesseract/tesseract-core-lstm.wasm.js", "scadenza.js", "scanner.js"):
            self.assertEqual(self.c.get("/" + f).status_code, 200, f)
        lingua = self.c.get("/vendor/tesseract/lang/eng.traineddata.gz")
        self.assertEqual(lingua.status_code, 200)
        self.assertGreater(len(lingua.data), 1_000_000)


if __name__ == "__main__":
    unittest.main()
