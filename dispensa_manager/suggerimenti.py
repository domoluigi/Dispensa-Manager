"""Suggerimenti di posizione e scadenza per un prodotto appena scansionato (v2.1.0).

Ordine di affidabilita':
1. lo storico di QUESTO prodotto (stesso EAN): mediana dei giorni tra inserimento e
   scadenza degli acquisti passati;
2. la categoria (tabella qui sotto, con termini italiani e inglesi: Open Food Facts
   restituisce le categorie in inglese);
3. niente: il campo scadenza resta vuoto, meglio di una data inventata.
"""
import re
import statistics
from datetime import datetime

# (espressione, giorni dalla data d'acquisto, posizione). Le regole piu' specifiche vanno prima.
_REGOLE = [(re.compile(p), g, pos) for p, g, pos in [
    (r"surgelat|frozen|ice.?cream|gelat|sorbett", 150, "Freezer"),
    # alternative vegetali e affettati: freschi, da frigo
    (r"tofu|tempeh|seitan|affettat|\bburger|\bburgher|cotolett|nugget|salsicc|sausage|wurstel|bresaola|prosciutt|"
     r"\bspeck|salame|giambon|mopur|beyond|yogurt|yoghurt|yosoi|skyr|fette (?:per|vegan|di veg|mediterran)|rucola|lattugh|"
     r"insalata\b(?!\s+di\s+riso)|insalatina|spinacin|pasta fresca|gnocch|chicche|cheesecake|apple pie|margarina", 15, "Frigo"),
    # prodotti a lunga conservazione che contengono parole «fresche» (latte, uova, mele…): prima delle regole del fresco
    (r"tisan|infus|camomill|\bcaff|cioccolat|biscott|cracker|spalmabil|coconut cream|cream.*(?:cocco|coconut)|"
     r"latte di cocco|maionese|mayonnais|senape|ketchup|\bragu|\bsugo|pat[eèé]\b|pomodori secchi|pomodorini secchi|"
     r"sott.?olio|sottaceti|peperoncin|conserv|preparato per|in polvere|polvere|\bnoci\b|mandorle|frutta secca|pecan|"
     r"uvetta|corinto|semi\b", 365, "Dispensa"),
    # ortaggi e frutta che si tengono fuori dal frigo
    (r"patat|cipoll|\baglio|zucca|pomodor|banan|\bmel[ae]\b|aranc|limon|agrum|castagn", 14, "Dispensa"),
    (r"\buht\b|a lunga conservazione|long.?life", 120, "Dispensa"),
    (r"latte fresco|fresh.?milk|pasteurized.?milk", 6, "Frigo"),
    (r"\blatte\b|\bmilks?\b", None, "Frigo"),   # fresco o UHT: dalla categoria non si capisce, data non suggerita
    (r"yogurt|yoghurt|kefir", 21, "Frigo"),
    (r"mozzarella|burrata|ricotta|stracchino|crescenza|mascarpone|fresh.?chees", 8, "Frigo"),
    (r"parmigiano|grana|pecorino|stagionat|aged.?chees|hard.?chees", 60, "Frigo"),
    (r"formagg|chees", 25, "Frigo"),
    (r"burro|butter", 45, "Frigo"),
    (r"panna|cream|besciamella", 20, "Frigo"),
    (r"\buova\b|\buovo\b|\beggs?\b", 28, "Frigo"),
    (r"affettat|salum|prosciutt|\bham\b|cold.?cuts|mortadella|salami|bresaola|wurstel|sausage", 15, "Frigo"),
    (r"pesce|\bfish\b|seafood|salmon|\bsalmone\b", 3, "Frigo"),
    (r"\bcarne\b|\bmeats?\b|chicken|\bpollo\b|\bmanzo\b|beef|pork|\bmaiale\b|hamburger|tacchino|turkey", 4, "Frigo"),
    (r"insalata|\bsalads?\b|lettuce|rucola|spinaci|spinach", 5, "Frigo"),
    (r"pasta fresca|fresh.?pasta|gnocchi|ravioli|tortellini", 12, "Frigo"),
    (r"\bpane\b|\bbread\b|baguette|focaccia|piadina", 4, "Dispensa"),
    (r"verdur|vegetables|ortaggi|\bfruits?\b|\bfrutta\b|\bmele\b|apples?|banan|arance|oranges", 8, "Frigo"),
    (r"tonno|tuna|sardin|mackerel|sgombro|canned|scatolam|conserv|legumi in scatola|pelati|passata|polpa", 730, "Dispensa"),
    (r"sugo|sauces?|salsa|pesto|ketchup|maionese|mayonnaise|senape|mustard", 540, "Dispensa"),
    (r"olio|\boils?\b|aceto|vinegar", 540, "Dispensa"),
    (r"biscott|biscuits?|cookies?|cracker|grissini|fette biscottate|wafer", 180, "Dispensa"),
    (r"snacks?|patatine|chips|crisps|popcorn|noccioline|nuts", 150, "Dispensa"),
    (r"cioccolat|chocolate|caramell|candy|sweets|confectionery", 365, "Dispensa"),
    (r"cereali|cereals|muesli|corn.?flakes|oat|avena", 365, "Dispensa"),
    (r"\bpasta\b|pastas|spaghetti|\bpenne\b|\brigatoni\b|\briso\b|\brice\b|couscous|farro|orzo|quinoa", 540, "Dispensa"),
    (r"farina|flours?|zucchero|sugars?|\bsale\b|\bsalt\b|lievito|yeast", 540, "Dispensa"),
    (r"legum|pulses|lenticchie|lentils|ceci|chickpeas|fagioli|beans", 540, "Dispensa"),
    (r"caff[eè]|coffee|\btea\b|\bt[eè]\b|infus|camomilla|tisane", 365, "Dispensa"),
    (r"miele|honey|marmellat|jams?|nutella|spreads?", 540, "Dispensa"),
    (r"acqua|\bwaters?\b|bevand|beverages?|drinks?|soda|cola|succh|juices?|birra|beers?|\bvino\b|\bwines?\b", 270, "Dispensa"),
]]


def _pulisci(tag: str) -> str:
    return re.sub(r"^[a-z]{2}:", "", str(tag or "").lower()).replace("-", " ").strip()


def suggerisci_da_categoria(categorie, nome: str = "") -> dict:
    """categorie: elenco di tag dal piu' generico al piu' specifico (come Open Food Facts).
    Si guarda dal piu' specifico: la catena di un sugo contiene anche 'vegetables based foods'."""
    def esito(giorni, pos, trovata=True):
        return {"posizione": pos, "scadenza_giorni": giorni, "fonte": "categoria" if giorni else None, "campioni": 0, "trovata": trovata}

    for tag in reversed([_pulisci(t) for t in (categorie or []) if t]):
        for regola, giorni, pos in _REGOLE:
            if regola.search(tag):
                return esito(giorni, pos)
    testo = _pulisci(nome)
    if testo:
        for regola, giorni, pos in _REGOLE:
            if regola.search(testo):
                return esito(giorni, pos)
    return esito(None, "Dispensa", False)


def _data(s):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def suggerisci_da_storico(conn, ean: str):
    """Mediana dei giorni inserimento→scadenza degli ultimi acquisti dello stesso EAN.
    Si escludono i prodotti segnati «Aperto il…» (scadenza gia' accorciata a mano)."""
    if not ean or ean.startswith("MANUAL-"):
        return None
    righe = conn.execute(
        "SELECT data_inserimento, scadenza, posizione FROM prodotti "
        "WHERE ean=? AND scadenza IS NOT NULL AND scadenza != '' "
        "AND (note IS NULL OR note NOT LIKE '%Aperto il%') ORDER BY id DESC LIMIT 8",
        (ean,),
    ).fetchall()
    giorni = []
    for r in righe:
        ins, sc = _data(r["data_inserimento"]), _data(r["scadenza"])
        if ins and sc and 0 < (sc - ins).days <= 3650:
            giorni.append((sc - ins).days)
    if not giorni:
        return None
    return {
        "posizione": (righe[0]["posizione"] or "Dispensa"),
        "scadenza_giorni": int(round(statistics.median(giorni))),
        "fonte": "storico",
        "campioni": len(giorni),
    }


def costruisci_suggerimento(conn, ean: str, categorie, nome: str = "", marca: str = "") -> dict:
    """Posizione e scadenza proposte. Prima la storia dello stesso prodotto; poi le regole: la posizione viene
    dalla classificazione (saponi, altro, congelatore, frigo, dispensa), la scadenza dalla categoria."""
    storico = suggerisci_da_storico(conn, ean)
    if storico:
        return storico
    from posizioni import classifica       # import locale: posizioni usa questo modulo
    base = suggerisci_da_categoria(categorie, nome)
    k = classifica(nome, marca, "", categorie)
    base["livello"] = k["livello"]
    if k["livello"] != "basso":
        base["posizione"] = k["posizione"]
    if k["posizione"] in ("Saponi", "Altro") and k["livello"] != "basso":
        base.update(scadenza_giorni=None, fonte=None, senza_scadenza=True)      # igiene e casa: nessuna scadenza da proporre
    elif k["posizione"] == "Freezer" and k["livello"] == "alto":
        base.update(scadenza_giorni=150, fonte="categoria")
    return base
