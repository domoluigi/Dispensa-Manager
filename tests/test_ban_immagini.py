"""Ban IP con scadenza e immagini nel backup: python -m unittest discover -s tests"""
import base64
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

TMP = tempfile.mkdtemp(prefix="dispensa_test_ban_")
os.environ["DB_PATH"] = os.path.join(TMP, "dispensa.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dispensa_manager"))

import database  # noqa: E402
from routes import admin  # noqa: E402

database.init_db()
from app import create_app  # noqa: E402

APP = create_app()
JPG = b"\xff\xd8\xff\xe0" + b"finto-jpeg" * 50


def accesso(c):
    r = c.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    return {"Authorization": "Bearer " + r.get_json()["access_token"]}


def login(c, ip, password):
    return c.post("/api/auth/login", json={"username": "admin", "password": password},
                  environ_overrides={"REMOTE_ADDR": ip})


class BanIp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = APP.test_client()
        cls.h = accesso(cls.c)

    def imposta(self, **kv):
        r = self.c.patch("/api/admin/settings", json=kv, headers=self.h)
        self.assertEqual(r.status_code, 200, r.get_json())

    def ban(self, ip):
        return [b for b in self.c.get("/api/admin/ip-bans", headers=self.h).get_json() if b["ip"] == ip]

    def tre_errori(self, ip):
        for _ in range(3):
            self.assertEqual(login(self.c, ip, "sbagliata").status_code, 401)

    def test_ban_automatico_ha_una_scadenza_e_finisce_da_solo(self):
        self.imposta(ban_durata_minuti="60", max_login_attempts="3")
        ip = "10.1.1.1"
        self.tre_errori(ip)
        self.assertEqual(login(self.c, ip, "admin").status_code, 429)       # bannato anche con la password giusta
        b = self.ban(ip)
        self.assertEqual(len(b), 1)
        self.assertIsNotNone(b[0]["scade_il"])
        # si simula il passare del tempo
        conn = database.get_db()
        with conn:
            conn.execute("UPDATE ip_bans SET scade_il='2000-01-01 00:00:00' WHERE ip=?", (ip,))
        conn.close()
        self.assertEqual(login(self.c, ip, "admin").status_code, 200)       # sbloccato da solo
        self.assertEqual(self.ban(ip), [])
        # e i vecchi fallimenti non lo ribaniscono al primo errore
        self.assertEqual(login(self.c, ip, "sbagliata").status_code, 401)
        self.assertEqual(login(self.c, ip, "admin").status_code, 200)

    def test_lista_non_mostra_i_ban_scaduti(self):
        ip = "10.1.1.2"
        conn = database.get_db()
        with conn:
            conn.execute("INSERT OR REPLACE INTO ip_bans (ip, scade_il) VALUES (?, '2000-01-01 00:00:00')", (ip,))
        conn.close()
        self.assertEqual(self.ban(ip), [])

    def test_durata_zero_e_ban_permanente(self):
        self.imposta(ban_durata_minuti="0", max_login_attempts="3")
        try:
            ip = "10.1.1.3"
            self.tre_errori(ip)
            self.assertIsNone(self.ban(ip)[0]["scade_il"])
            self.assertEqual(login(self.c, ip, "admin").status_code, 429)
        finally:
            self.imposta(ban_durata_minuti="60")

    def test_ban_manuale_permanente_o_a_tempo(self):
        self.assertEqual(self.c.post("/api/admin/ip-bans", json={"ip": "10.1.1.4"}, headers=self.h).status_code, 201)
        self.assertIsNone(self.ban("10.1.1.4")[0]["scade_il"])
        self.c.post("/api/admin/ip-bans", json={"ip": "10.1.1.5", "minuti": 30}, headers=self.h)
        self.assertIsNotNone(self.ban("10.1.1.5")[0]["scade_il"])
        self.assertEqual(self.c.post("/api/admin/ip-bans", json={"ip": "10.1.1.6", "minuti": "x"}, headers=self.h).status_code, 400)

    def test_durata_non_valida_rifiutata(self):
        for v in ("abc", -1, 99999999):
            self.assertEqual(self.c.patch("/api/admin/settings", json={"ban_durata_minuti": v}, headers=self.h).status_code, 400, v)

    def test_impostazione_presente_e_modificabile_dal_pannello(self):
        chiavi = [s["key"] for s in self.c.get("/api/admin/settings", headers=self.h).get_json()]
        self.assertIn("ban_durata_minuti", chiavi)

    def test_schema_7_migra_senza_perdere_i_ban_esistenti(self):
        # simula un database 2.1.0: tabella ip_bans senza scade_il, schema 6, ban gia' presente
        p = os.path.join(TMP, "vecchio.db")
        c = sqlite3.connect(p)
        c.executescript("""
            CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, description TEXT, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO app_settings (key, value) VALUES ('schema_version', '6');
            CREATE TABLE ip_bans (ip TEXT PRIMARY KEY, banned_at DATETIME DEFAULT CURRENT_TIMESTAMP, reason TEXT DEFAULT 'x');
            INSERT INTO ip_bans (ip) VALUES ('9.9.9.9');
        """)
        c.commit()
        c.close()
        vecchio = database.DB_PATH
        database.DB_PATH = p
        try:
            database.init_db()
            conn = database.get_db()
            riga = conn.execute("SELECT scade_il FROM ip_bans WHERE ip='9.9.9.9'").fetchone()
            durata = conn.execute("SELECT value FROM app_settings WHERE key='ban_durata_minuti'").fetchone()
            versione = conn.execute("SELECT value FROM app_settings WHERE key='schema_version'").fetchone()
            conn.close()
        finally:
            database.DB_PATH = vecchio
        self.assertIsNone(riga["scade_il"])          # i ban esistenti restano permanenti
        self.assertEqual(durata["value"], "60")
        self.assertEqual(versione["value"], "7")


class ImmaginiNelBackup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = APP.test_client()
        cls.h = accesso(cls.c)

    def prodotto_con_immagine(self, contenuto=JPG, estensione="jpg"):
        pid = self.c.post("/api/prodotti", json={"nome": "Con foto", "quantita": 1}, headers=self.h).get_json()["id"]
        os.makedirs(database.IMAGES_DIR, exist_ok=True)
        nome = f"{pid}.{estensione}"
        with open(os.path.join(database.IMAGES_DIR, nome), "wb") as f:
            f.write(contenuto)
        conn = database.get_db()
        with conn:
            conn.execute("UPDATE prodotti SET immagine_url=? WHERE id=?", (f"/dispensa-images/{nome}", pid))
        conn.close()
        return pid, nome

    def test_backup_contiene_le_immagini_e_il_ripristino_le_riscrive(self):
        pid, nome = self.prodotto_con_immagine()
        backup = self.c.get("/api/admin/backup", headers=self.h).get_json()
        self.assertEqual(base64.b64decode(backup["immagini"][nome]), JPG)
        self.assertGreaterEqual(backup["_meta"]["immagini"], 1)
        percorso = os.path.join(database.IMAGES_DIR, nome)
        os.remove(percorso)                                              # disastro: file perso
        r = self.c.post("/api/admin/restore", json={"backup": backup, "confirm": "RIPRISTINA"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertGreaterEqual(r.get_json()["ripristinati"]["immagini"], 1)
        with open(percorso, "rb") as f:
            self.assertEqual(f.read(), JPG)
        self.assertEqual(self.c.get("/dispensa-images/" + nome).status_code, 200)

    def test_immagine_assente_su_disco_non_rompe_il_backup(self):
        pid, nome = self.prodotto_con_immagine()
        os.remove(os.path.join(database.IMAGES_DIR, nome))
        r = self.c.get("/api/admin/backup", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(nome, r.get_json()["immagini"])

    def test_url_esterne_e_nomi_strani_non_finiscono_nel_backup(self):
        conn = database.get_db()
        with conn:
            conn.execute("INSERT INTO prodotti (nome, immagine_url) VALUES ('Esterna', 'https://x/y.jpg')")
            conn.execute("INSERT INTO prodotti (nome, immagine_url) VALUES ('Strana', '/dispensa-images/../../etc/passwd')")
        conn.close()
        backup = self.c.get("/api/admin/backup", headers=self.h).get_json()
        self.assertTrue(all(admin.RE_IMMAGINE.match(n) for n in backup["immagini"]))

    def test_ripristino_scarta_le_immagini_pericolose(self):
        backup = self.c.get("/api/admin/backup", headers=self.h).get_json()
        buona = base64.b64encode(JPG).decode()
        backup["immagini"] = {
            "../fuori.jpg": buona,                                             # percorso fuori cartella
            "sub/dir.jpg": buona,
            "77.php": buona,                                                   # estensione non ammessa
            "78.jpg": base64.b64encode(b"non un jpeg").decode(),               # firma sbagliata
            "79.png": buona,                                                   # firma JPEG con estensione png
            "80.jpg": "!!!non base64!!!",
            "81.jpg": base64.b64encode(b"\xff\xd8\xff" + b"0" * (admin.MAX_IMMAGINE_BYTES + 1)).decode(),   # troppo grande
            "82.jpg": buona,                                                   # questa e' valida
        }
        r = self.c.post("/api/admin/restore", json={"backup": backup, "confirm": "RIPRISTINA"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.get_json())
        conteggi = r.get_json()["ripristinati"]
        self.assertEqual(conteggi["immagini"], 1)
        self.assertEqual(conteggi["immagini scartate"], 7)
        self.assertTrue(os.path.exists(os.path.join(database.IMAGES_DIR, "82.jpg")))
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(database.IMAGES_DIR), "fuori.jpg")))
        self.assertFalse(os.path.exists(os.path.join(database.IMAGES_DIR, "78.jpg")))

    def test_backup_vecchio_senza_immagini_si_ripristina(self):
        backup = self.c.get("/api/admin/backup", headers=self.h).get_json()
        backup.pop("immagini")
        backup["_meta"].pop("immagini")
        r = self.c.post("/api/admin/restore", json={"backup": backup, "confirm": "RIPRISTINA"}, headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("immagini", r.get_json()["ripristinati"])

    def test_backup_automatico_include_le_immagini(self):
        pid, nome = self.prodotto_con_immagine()
        cartella = os.path.join(TMP, "bk")
        os.makedirs(cartella, exist_ok=True)
        with mock.patch.object(admin, "BACKUPS_DIR", cartella):
            percorso = admin.scrivi_backup_auto()
        with open(percorso, encoding="utf-8") as f:
            self.assertIn(nome, json.load(f)["immagini"])


if __name__ == "__main__":
    unittest.main()
