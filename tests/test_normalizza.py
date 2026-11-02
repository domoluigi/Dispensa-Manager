"""Nomi, quantita' e reparti della lista della spesa: python -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dispensa_manager"))

import normalizza as n  # noqa: E402
import reparti  # noqa: E402


class Quantita(unittest.TestCase):
    def test_casi(self):
        casi = [
            ("2 dentifricio", ("dentifricio", 2)),
            ("dentifricio x2", ("dentifricio", 2)),
            ("dentifricio x 2", ("dentifricio", 2)),
            ("3x latte", ("latte", 3)),
            ("3 x latte", ("latte", 3)),
            ("2 confezioni di pasta", ("pasta", 2)),
            ("6 bottiglie acqua", ("acqua", 6)),
            ("due dentifrici", ("dentifrici", 2)),
            ("una mela", ("mela", 1)),
            ("latte", ("latte", 1)),
            ("  latte  ", ("latte", 1)),
            # misure: il numero fa parte del nome, la quantita' resta 1
            ("500 g pasta", ("500 g pasta", 1)),
            ("1 l latte", ("1 l latte", 1)),
            ("2 kg di patate", ("2 kg di patate", 1)),
            # numeri che non sono quantita'
            ("00 farina", ("00 farina", 1)),
            ("Farina 00", ("Farina 00", 1)),
            ("", ("", 1)),
        ]
        for testo, atteso in casi:
            self.assertEqual(n.estrai_quantita(testo), atteso, testo)


class Chiavi(unittest.TestCase):
    def test_stessa_voce(self):
        gruppi = [
            ["Dentifricio", "dentifrici", "2 dentifricio", "Il dentifricio", "DENTIFRICIO!"],
            ["latte intero", "intero latte", "Latte  Intero"],
            ["mela", "mele", "una mela"],
            ["uova", "uovo"],
            ["pomodori", "pomodoro"],
            ["spaghetti", "spaghetto"],
            ["caffè", "caffe"],
            ["lattuga", "lattughe"],
            ["amico", "amici"],
        ]
        for g in gruppi:
            chiavi = {n.chiave(x) for x in g}
            self.assertEqual(len(chiavi), 1, f"{g} → {chiavi}")
            self.assertNotEqual(chiavi.pop(), "")

    def test_voci_diverse(self):
        for a, b in [("pane", "pasta"), ("latte", "latte intero"), ("sale", "salame"), ("acqua", "aceto")]:
            self.assertFalse(n.stessa_voce(n.token_chiave(a), n.token_chiave(b)), (a, b))

    def test_articoli_e_punteggiatura_non_contano(self):
        self.assertEqual(n.chiave("olio d'oliva"), n.chiave("olio oliva"))
        self.assertEqual(n.chiave("Pasta, di semola"), n.chiave("pasta semola"))
        self.assertEqual(n.chiave("il, la, lo"), "")           # nessuna parola utile

    def test_copre(self):
        voce = n.token_chiave("latte")
        self.assertTrue(n.copre(voce, n.token_chiave("Latte intero parzialmente scremato")))
        self.assertTrue(n.copre(voce, n.token_chiave("latte")))
        self.assertFalse(n.copre(n.token_chiave("latte intero"), n.token_chiave("latte")))   # voce piu' specifica
        self.assertFalse(n.copre(n.token_chiave("pane"), n.token_chiave("pasta penne")))
        self.assertFalse(n.copre(frozenset(), n.token_chiave("qualcosa")))

    def test_bella(self):
        self.assertEqual(n.bella("  dentifricio   mentadent "), "Dentifricio mentadent")
        self.assertEqual(n.bella("Latte"), "Latte")
        self.assertEqual(n.bella(""), "")


class Reparti(unittest.TestCase):
    def test_casi(self):
        casi = {
            "dentifricio": "igiene", "spazzolino": "igiene", "shampoo": "igiene", "carta igienica": "igiene",
            "crema viso": "igiene", "carta forno": "casa", "detersivo piatti": "casa", "sacchetti spazzatura": "casa",
            "ammorbidente": "casa", "pizza surgelata": "surgelati", "gelato": "surgelati",
            "Latte intero": "latticini", "yogurt greco": "latticini", "uova": "latticini", "mozzarella": "latticini",
            "latte di avena": "bevande", "acqua frizzante": "bevande", "coca cola": "bevande", "birra": "bevande",
            "olio per friggere": "dispensa", "crema spalmabile": "dispensa", "pasta": "dispensa", "tonno in scatola": "dispensa",
            "passata di pomodoro": "dispensa", "caffe": "dispensa", "mele": "frutta_verdura", "banane": "frutta_verdura",
            "insalata": "frutta_verdura", "pane": "pane", "pancarre": "pane", "focaccia": "pane",
            "prosciutto cotto": "carne_pesce", "salmone": "carne_pesce", "pollo": "carne_pesce",
            "crocchette gatto": "animali", "cibo per cani": "animali", "lettiera": "animali",
            "xyz sconosciuto": "altro", "": "altro",
        }
        for testo, atteso in casi.items():
            self.assertEqual(reparti.reparto_di(testo), atteso, testo)

    def test_piu_testi_e_accenti(self):
        self.assertEqual(reparti.reparto_di("Sugo", "pasta sauces"), "dispensa")
        self.assertEqual(reparti.reparto_di("Té"), "dispensa")

    def test_ordine_coerente(self):
        codici = [c for c, _ in reparti.REPARTI]
        self.assertEqual(codici[-1], "altro")
        self.assertEqual(len(codici), len(set(codici)))
        self.assertEqual(reparti.ORDINE["frutta_verdura"], 0)


if __name__ == "__main__":
    unittest.main()
