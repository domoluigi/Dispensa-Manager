"""Il DB non usa piu' il WAL (2.6.1): il backup di HA archivia /config file per file e il -wal che sparisce lo faceva fallire.
python -m unittest discover -s tests"""
import os
import sqlite3
import sys
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix="dispensa_test_journal_")
os.environ["DB_PATH"] = os.path.join(TMP, "dispensa.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dispensa_manager"))

import database  # noqa: E402


class TestJournal(unittest.TestCase):
    def test_modalita_delete(self):
        conn = database.get_db()
        try:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        finally:
            conn.close()

    def test_nessun_wal_su_disco(self):
        database.init_db()
        conn = database.get_db()
        with conn:
            conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('prova_journal', '1')")
        conn.close()
        for suffisso in ("-wal", "-shm", "-journal"):
            self.assertFalse(os.path.exists(database.DB_PATH + suffisso), suffisso)

    def test_db_gia_in_wal_viene_convertito(self):
        percorso = os.path.join(TMP, "vecchio.db")
        vecchio = sqlite3.connect(percorso)
        self.assertEqual(vecchio.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        vecchio.execute("CREATE TABLE t (x)")
        vecchio.commit()
        vecchio.close()
        precedente, database.DB_PATH = database.DB_PATH, percorso
        try:
            conn = database.get_db()
            try:
                self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            finally:
                conn.close()
        finally:
            database.DB_PATH = precedente
        self.assertFalse(os.path.exists(percorso + "-wal"))


if __name__ == "__main__":
    unittest.main()
