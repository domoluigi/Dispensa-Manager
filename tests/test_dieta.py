"""Dieta e profilo nutrizionale (2.5.0): python -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dispensa_manager"))

from dieta import valuta_dieta, profilo_nutrizionale, estrai_off  # noqa: E402


def v(ingredienti="", **kw):
    return valuta_dieta(ingredienti, **kw)


class Ingredienti(unittest.TestCase):
    def test_latte_non_e_vegano_ma_e_vegetariano(self):
        d = v("Zucchero, latte intero in polvere, cacao")
        self.assertEqual((d["vegano"], d["vegetariano"]), ("no", "probabile"))
        self.assertIn("latte", d["motivi"])

    def test_carne_e_pesce_non_sono_ne_vegani_ne_vegetariani(self):
        for t in ("Carne di manzo 60%, sale", "Pasta, tonno, olio", "Zucchero, gelatina, acqua", "Acqua, colorante E120"):
            d = v(t)
            self.assertEqual((d["vegano"], d["vegetariano"]), ("no", "no"), t)

    def test_miele_e_uova_non_sono_vegani(self):
        for t in ("Farina, zucchero, miele", "Farina, uova fresche", "Semola, uovo"):
            d = v(t)
            self.assertEqual((d["vegano"], d["vegetariano"]), ("no", "probabile"), t)

    def test_parole_che_sembrano_animali_ma_non_lo_sono(self):
        for t in ("Acqua, farina, lievito di birra, sale", "Latte di soia, acqua", "Burro di cacao, zucchero, pasta di cacao",
                  "Latte di noce di cocco in polvere, zucchero", "Olio di cocco, SENZA LATTICINI, aromi", "Burro di arachidi, sale",
                  "Acqua, amido, MOZZARELLA AROMA, sale", "Acido lattico, cremor tartaro, acqua", "Panna di soia, zucchero",
                  "Water, coconut cream, sugar", "Peanut butter, salt"):
            d = v(t)
            self.assertEqual(d["vegano"], "probabile", t + " -> " + str(d["motivi"]))

    def test_tracce_non_contano_come_ingredienti(self):
        d = v("Farina di grano, acqua, sale. Può contenere tracce di latte e uova.")
        self.assertEqual(d["vegano"], "probabile")
        self.assertEqual(sorted(d["tracce"]), ["latte", "uova"])

    def test_ingredienti_dubbi(self):
        for t in ("Farina, E471, sale", "Acqua, vitamina D3, olio", "Malto, birra, acqua"):
            self.assertEqual(v(t)["vegano"], "verifica", t)

    def test_senza_elenco_non_si_dice_nulla(self):
        d = v("")
        self.assertEqual((d["vegano"], d["vegetariano"]), ("ignoto", "ignoto"))
        self.assertFalse(d["ha_ingredienti"])

    def test_lingua_che_non_sappiamo_leggere(self):
        self.assertEqual(v("woda cukier sol maka pszenna")["vegano"], "ignoto")


class Fonti(unittest.TestCase):
    def test_etichetta_e_analisi_di_off(self):
        self.assertEqual(v("Acqua, olio di cocco, sale", etichette=["en:vegan"])["vegano"], "si")
        self.assertEqual(v("", analisi=["en:vegan", "en:vegetarian"])["vegano"], "si")
        self.assertEqual(v("", analisi=["en:non-vegan"])["vegano"], "no")
        self.assertEqual(v("", analisi=["en:non-vegetarian"])["vegetariano"], "no")

    def test_off_dice_forse_ma_il_testo_e_pulito(self):
        self.assertEqual(v("Pasta di semola di grano duro, acqua", analisi=["en:maybe-vegan"])["vegano"], "probabile")

    def test_contraddizione_tra_etichetta_e_ingredienti(self):
        d = v("Acqua, latte, sale", etichette=["en:vegan"])
        self.assertEqual(d["vegano"], "verifica")
        self.assertEqual(d["fonte"], "contraddizione")

    def test_etichetta_non_vegan_non_vale(self):
        self.assertNotEqual(v("Acqua, sale", etichette=["en:non-vegan"])["fonte"], "etichetta")

    def test_categorie_e_nome_quando_mancano_gli_ingredienti(self):
        self.assertEqual(v("", categorie_tag=["en:meats", "en:cured-meats"])["vegetariano"], "no")
        self.assertEqual(v("", categorie_tag=["en:plant-based-foods", "en:meat-substitutes"])["vegano"], "ignoto")
        self.assertEqual(v("", nome="Tofu naturale")["vegano"], "probabile")
        self.assertEqual(v("", nome="Prosciutto cotto")["vegano"], "verifica")

    def test_nome_non_da_mai_certezza(self):
        self.assertNotEqual(v("", nome="Burger vegetale")["vegano"], "si")

    def test_override_dell_utente(self):
        self.assertEqual(v("Acqua, latte", override="si")["vegano"], "si")
        self.assertEqual(v("Acqua, sale", override="no")["vegano"], "no")

    def test_tracce_da_off(self):
        self.assertEqual(v("Acqua, sale", tracce=["en:milk", "en:soybeans"])["tracce"], ["latte"])


class Profilo(unittest.TestCase):
    def test_proteico_e_sale(self):
        p = profilo_nutrizionale({"energia_kcal": 120, "proteine": 12, "fibre": 2, "sale": 2.0}, "A", None)
        ids = {x["id"]: x["tono"] for x in p["punti"]}
        self.assertEqual(ids["proteine"], "ok")
        self.assertEqual(ids["sale"], "attenzione")
        self.assertEqual(p["salute"]["livello"], "buono")

    def test_soglie_proteine(self):
        self.assertEqual([x["testo"][:10] for x in profilo_nutrizionale({"energia_kcal": 300, "proteine": 10}, "", None)["punti"]], ["Fonte di p"])
        self.assertEqual(profilo_nutrizionale({"energia_kcal": 100, "proteine": 14}, "", None)["punti"][0]["testo"][:10], "Alto conte")
        self.assertEqual(profilo_nutrizionale({"energia_kcal": 400, "proteine": 8}, "", None)["punti"], [])     # 8%: ne' fonte ne' alto

    def test_eccessi_senza_nutriscore(self):
        p = profilo_nutrizionale({"energia_kcal": 520, "zuccheri": 40, "grassi_saturi": 9}, "", None)
        self.assertEqual(p["salute"]["livello"], "scarso")

    def test_nessun_dato(self):
        p = profilo_nutrizionale({}, "", None)
        self.assertEqual((p["punti"], p["salute"], p["ha_dati"]), ([], None, False))

    def test_valori_non_numerici(self):
        self.assertEqual(profilo_nutrizionale({"proteine": "boh", "energia_kcal": None}, "x", "abc")["punti"], [])

    def test_nova(self):
        self.assertEqual(profilo_nutrizionale({}, "", 4)["punti"][0]["id"], "nova")


class DatiOff(unittest.TestCase):
    def test_estrazione(self):
        d = estrai_off({"ingredients_text": "Acqua, sale", "nova_group": "3", "ingredients_analysis_tags": ["en:vegan"],
                        "labels_tags": ["en:bio"], "traces_tags": ["en:milk"], "categories_tags": ["en:waters"]})
        self.assertEqual((d["ingredienti"], d["nova"]), ("Acqua, sale", 3))
        self.assertEqual(d["off_dati"]["analisi"], ["en:vegan"])
        self.assertEqual(estrai_off(None)["ingredienti"], "")


if __name__ == "__main__":
    unittest.main()
