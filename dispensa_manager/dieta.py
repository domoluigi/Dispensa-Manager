"""Dieta (vegano / vegetariano) e profilo nutrizionale di un prodotto (v2.5.0).

Stati di `vegano` e `vegetariano`:
  si         certo: etichetta «vegan» o analisi di Open Food Facts tutta vegana
  probabile  nell'elenco ingredienti non c'e' niente di animale, ma nessuno l'ha certificato
  verifica   ingrediente dubbio (E471, vitamina D3, vino...) o i dati si contraddicono
  no         c'e' un ingrediente animale (il motivo e' nell'elenco `motivi`)
  ignoto     niente elenco ingredienti: non si puo' dire

Un prodotto senza dati non e' mai «si» e nemmeno «probabile». I valori nutrizionali vanno letti per 100 g.
"""
import re
import unicodedata

SI, PROBABILE, VERIFICA, NO, IGNOTO = "si", "probabile", "verifica", "no", "ignoto"

# ── Ingredienti ──────────────────────────────────────────────────────────────

_PIANTE = (r"soia|soja|soy|soya|avena|oat|mandorl\w*|almond|riso|rice|cocco|coconut|nocciol\w*|hazelnut|anacard\w*|cashew|"
           r"pisell\w*|pea|canapa|hemp|lupin\w*|pistacch\w*|cacao|cocoa|karit\w*|shea|arachid\w*|peanut|sesamo|sesame|"
           r"girasole|sunflower|lino|nut")

# Frasi che contengono una parola animale ma non lo sono: si tolgono prima di cercare
_NEUTRI = [re.compile(p) for p in (
    r"\b(?:latte|milk|lait|milch|panna|cream|crema|burro|butter|beurre|formaggio|cheese|fromage|k[aä]se|yogurt|yoghurt|gelato|bevanda)"
    r"\s+(?:di|d'|de|of|from|aus|da)?\s*(?:noce di |nuts? |nut )?(?:" + _PIANTE + r")\b",
    r"\b(?:" + _PIANTE + r")\s+(?:cream|milk|butter|panna|latte|burro)\b",
    r"\b(?:latte|panna|burro|formagg\w*|yogurt|uova|uovo|carne|salsicc\w+|burger|bacon|speck|salame|prosciutt\w*|tonno|pesce|"
    r"gamber\w*|gelatin\w*|maionese|miele|egg|eggs|milk|cheese|meat|butter|cream)\s+(?:vegetal\w*|vegan\w*|veg|plant[- ]based)\b",
    r"\b(?:vegetable|vegetal|plant|veg)\s+(?:gelatin\w*|gelatina|butter|cream|milk|cheese|egg)\b",
    r"\b(?:senza|privo di|priva di|free from|ohne|sans|non contiene|esente da|no)\s+(?:latte|lattosio|latticini|uova|uovo|derivati del latte|"
    r"milk|egg\w*|lactose|dairy|gelatina|carne|glutine|laktose|milch)\b",
    r"\b(?:lactose|lattosio|dairy|milk|egg|eggs|laktose|milch)[- ]?(?:free|frei)\b|\blactosefrei\b",
    # aromi «di» qualcosa (aroma di mozzarella): e' un aroma, non l'ingrediente
    r"\b(?:aromi?|aromatizzant\w*|flavou?r\w*|aromen?|aroma)\s+(?:di\s+|al\s+|alla\s+|naturale\s+di\s+|natural\s+)?\w+",
    r"\b\w+\s+(?:aroma|aromi|aromen|flavou?r(?:ing)?s?)\b",     # «mozzarella aroma»
    r"\b(?:cream of tartar|cremor tartaro|acido lattico|lactic acid|fermenti lattici|aceto di vino|wine vinegar|burro di cacao|cocoa butter|"
    r"lievito di birra|brewer'?s yeast|beer yeast)\b",
)]

_CARNE = re.compile(
    r"\b(?:carn[ei]|manzo|bovin\w*|suin\w*|maial\w*|pollo|polli|tacchin\w*|agnell\w*|vitell\w*|coniglio|anatra|prosciutt\w*|"
    r"salam[ei]|speck|pancetta|guanciale|bresaola|mortadella|wurstel|salsicc\w*|cotechino|lardo|strutto|grass[oi] animal\w*|"
    r"estratto di carne|brodo di carne|pesc[ei]|tonno|salmone|acciug\w*|alic[ei]|sardin\w*|merluzz\w*|baccal[aà]|gamber\w*|"
    r"crostacei|molluschi|calamar\w*|seppi\w*|cozz\w*|vongol\w*|polpo|surimi|trota|orata|branzino|gelatin\w*|colla di pesce|"
    r"isinglass|meat|beef|pork|chicken|turkey|ham|bacon|lard|tallow|fish|anchov\w*|shrimp|prawn\w*|fleisch|schwein\w*|"
    r"rind\w*|fisch|viande|porc|poisson|saumon|thon|olio di pesce|fish oil|krill|carminio|cochineal|gommalacca|shellac)\b")

_DERIVATI = re.compile(
    r"\b(?:latte|milk|lait|milch|latticin\w*|lattosio|lactose|siero|whey|molke|casein\w*|lattoalbumin\w*|lattoglobulin\w*|"
    r"panna|(?:ice|whipping|sour|double|heavy|single|clotted|dairy) cream|cream cheese|cream powder|sahne|"
    r"burro|butter|beurre|ghee|yogurt|yoghurt|kefir|ricotta|mozzarella|parmigian\w*|grana|pecorino|"
    r"mascarpone|gorgonzola|emmental|formagg\w*|cheese|k[aä]se|fromage|cagliata|uov[ao]|uova|ovoalbumin\w*|albume|tuorlo|"
    r"lisozima|eggs?|eier|ei|oeufs?|huevos?|miele|miel|honey|honig|propoli|pappa reale|royal jelly|cera d'api|beeswax)\b")

_DUBBI = re.compile(
    r"\b(?:mono[- ]?e[- ]?di[- ]?glicerid\w*|mono[- ]?and[- ]?di[- ]?glycerid\w*|mono[- ]?(?:e|and)[- ]?digliceridi|"
    r"vitamina d3|vitamin d3|colecalciferolo|cholecalciferol|omega[- ]?3|dha|l[- ]?cisteina|l[- ]?cysteine|vino|wine|birra|beer)\b")

# Additivi (numero E): animali, derivati vegetariani, dubbi
_E_CARNE = {120: "carminio", 441: "gelatina", 542: "fosfato d'ossa", 904: "gommalacca"}
_E_DERIVATI = {901: "cera d'api", 913: "lanolina", 1105: "lisozima (uovo)"}
_E_DUBBI = {422: "glicerolo", 470: "sali degli acidi grassi", 471: "mono e digliceridi", 472: "esteri dei mono e digliceridi",
            477: "esteri del glicole propilenico", 481: "stearoil lattilato", 482: "stearoil lattilato", 570: "acido stearico",
            627: "guanilato", 631: "inosinato", 635: "ribonucleotidi", 920: "L-cisteina"}
_E_NUM = re.compile(r"\be[\s-]?(\d{3,4})[a-z]{0,2}\b")

_TRACCE = re.compile(r"(?:pu[oò] contenere|puo contenere|tracce di|contiene tracce|may contain|traces of|kann spuren|peut contenir|"
                     r"stabilimento|impianto|facility)[^.;\n]*")
_TRACCE_PAROLE = (("latte", r"\blatte\b|\bmilk\b|\blattosio\b|\bmilch\b"), ("uova", r"\buov[ao]\b|\beggs?\b|\beier\b"),
                  ("pesce", r"\bpesce\b|\bfish\b|\bfisch\b"), ("crostacei", r"\bcrostacei\b|\bcrustaceans?\b"),
                  ("molluschi", r"\bmolluschi\b|\bmolluscs?\b"))
_TRACCE_TAG = {"en:milk": "latte", "en:eggs": "uova", "en:fish": "pesce", "en:crustaceans": "crostacei", "en:molluscs": "molluschi"}

# Parole comuni in italiano, inglese, tedesco, francese, spagnolo: servono a capire se il testo e' una lingua che sappiamo leggere
_LINGUE = re.compile(r"\b(?:acqua|water|wasser|eau|agua|zucchero|sugar|zucker|sucre|az[uú]car|sale|salt|salz|sel|sal|olio|oil|[oö]l|huile|"
                     r"aceite|farina|flour|mehl|farine|harina|di|e|and|und|et|de|con|with|mit|avec|contiene|contains|enth[aä]lt|"
                     r"aromi|flavou?rings?|aromen|ar[oô]mes|riso|rice|reis|riz|arroz|pomodor\w*|tomato\w*|tomaten|soia|soy)\b")

_CAT_CARNE = re.compile(r"(?:^|:)(?:meats?|poultry|beef|pork|fishes?|seafoods?|cured-meats?|sausages?|hams?|charcuterie|canned-fish|tunas?|salmons?)(?:$|-)")
_CAT_DERIVATI = re.compile(r"(?:^|:)(?:dairies|dairy|milks?|cheeses?|yogh?urts?|eggs?|honeys?|butters?|creams?|fermented-milk-products)(?:$|-)")
_CAT_PIANTE = re.compile(r"plant-based|substitute|alternative|vegan|vegetarian-")

_NOME_CLAIM = re.compile(r"\b(?:veg(?:an\w*|etal\w*)|plant[- ]based|tofu|seitan|tempeh|hummus|hummus)\b")
_ETICHETTA_VEGAN = re.compile(r"(?:^|[:-])vegan(?:$|-)")


def _norm(testo) -> str:
    t = unicodedata.normalize("NFC", str(testo or "")).lower().replace("_", "").replace("’", "'").replace("*", "")
    return re.sub(r"\s+", " ", t).strip()


def _unici(seq):
    out = []
    for x in seq:
        if x not in out:
            out.append(x)
    return out


def analizza_ingredienti(testo) -> dict:
    """Cerca ingredienti animali in un elenco ingredienti.
    Ritorna {"presente", "carne": [...], "derivati": [...], "dubbi": [...], "tracce": [...], "lingua_ok"}."""
    t = _norm(testo)
    tracce = []
    for m in _TRACCE.finditer(t):
        clausola = m.group(0)
        tracce += [nome for nome, rx in _TRACCE_PAROLE if re.search(rx, clausola)]
    t = _TRACCE.sub(" ", t)
    presente = len(re.findall(r"[a-zà-ü]{3,}", t)) >= 2       # prima di togliere le frasi neutre: «latte di soia, acqua» e' un elenco
    lingua_ok = bool(_LINGUE.search(t))
    for rx in _NEUTRI:
        t = rx.sub(" ", t)
    carne = [m.group(0) for m in _CARNE.finditer(t)]
    derivati = [m.group(0) for m in _DERIVATI.finditer(t)]
    dubbi = [m.group(0) for m in _DUBBI.finditer(t)]
    for m in _E_NUM.finditer(t):
        n = int(m.group(1))
        if n in _E_CARNE:
            carne.append("E%d (%s)" % (n, _E_CARNE[n]))
        elif n in _E_DERIVATI:
            derivati.append("E%d (%s)" % (n, _E_DERIVATI[n]))
        elif n in _E_DUBBI:
            dubbi.append("E%d (%s)" % (n, _E_DUBBI[n]))
    return {
        "presente": presente,
        "carne": _unici(carne), "derivati": _unici(derivati), "dubbi": _unici(dubbi), "tracce": _unici(tracce),
        "lingua_ok": lingua_ok or bool(carne or derivati or dubbi),     # se ha riconosciuto un ingrediente, la lingua la sa leggere
    }


def _stato_off(tags, radice):
    """Legge i tag di Open Food Facts ("en:vegan", "en:non-vegan", "en:maybe-vegan", "en:vegan-status-unknown")."""
    tags = [str(x).lower() for x in (tags or [])]
    if "en:non-" + radice in tags:
        return NO
    if "en:maybe-" + radice in tags:
        return VERIFICA
    if "en:" + radice in tags:
        return SI
    return IGNOTO


def _da_categorie(categorie_tag):
    """(carne, derivati) dedotti dalle categorie, solo se non c'e' traccia di alternative vegetali."""
    tags = [str(c).lower() for c in (categorie_tag or [])]
    if not tags or any(_CAT_PIANTE.search(t) for t in tags):
        return False, False
    return any(_CAT_CARNE.search(t) for t in tags), any(_CAT_DERIVATI.search(t) for t in tags)


def valuta_dieta(ingredienti="", analisi=(), etichette=(), categorie_tag=(), nome="", tracce=(), override=None) -> dict:
    """Valutazione di un prodotto. `override` ('si'/'no') e' la parola dell'utente sul vegano e vince su tutto."""
    a = analizza_ingredienti(ingredienti)
    motivi = []
    tracce_tot = _unici(list(a["tracce"]) + [_TRACCE_TAG[t] for t in (tracce or []) if t in _TRACCE_TAG])
    off_vegano, off_veg = _stato_off(analisi, "vegan"), _stato_off(analisi, "vegetarian")
    etichetta = any(_ETICHETTA_VEGAN.search(str(e).lower()) and "non" not in str(e).lower() for e in (etichette or []))
    ha_testo = a["presente"] and len(_norm(ingredienti)) >= 10
    animale = a["carne"] or a["derivati"]
    cat_carne, cat_derivati = _da_categorie(categorie_tag)
    n = _norm(nome)

    fonte = None
    # vegano
    if animale and (etichetta or off_vegano == SI):
        vegano, fonte = VERIFICA, "contraddizione"
        motivi = ["l'etichetta dice vegano ma tra gli ingredienti c'e': " + ", ".join(_unici(a["carne"] + a["derivati"]))]
    elif animale:
        vegano, fonte, motivi = NO, "ingredienti", _unici(a["carne"] + a["derivati"])
    elif etichetta:
        vegano, fonte = SI, "etichetta"
    elif off_vegano == NO:
        vegano, fonte, motivi = NO, "Open Food Facts", ["segnalato non vegano da Open Food Facts"]
    elif off_vegano == SI:
        vegano, fonte = SI, "Open Food Facts"
    elif a["dubbi"]:
        vegano, fonte, motivi = VERIFICA, "ingredienti", a["dubbi"]
    elif ha_testo and a["lingua_ok"]:      # anche se Open Food Facts dice «forse»: lo dice anche della pasta di sola semola
        vegano, fonte = PROBABILE, "ingredienti"
    elif off_vegano == VERIFICA:
        vegano, fonte, motivi = VERIFICA, "Open Food Facts", ["Open Food Facts segnala ingredienti dubbi"]
    elif cat_carne or cat_derivati:
        vegano, fonte, motivi = NO, "categoria", ["categoria animale (carne, pesce, latticini, uova o miele)"]
    elif _NOME_CLAIM.search(n):
        vegano, fonte = PROBABILE, "nome"
    elif _CARNE.search(n) or _DERIVATI.search(n):
        vegano, fonte = VERIFICA, "nome"
        motivi = ["nel nome: " + (_CARNE.search(n) or _DERIVATI.search(n)).group(0)]
    else:
        vegano, fonte = IGNOTO, None

    # vegetariano
    if a["carne"]:
        veget = NO
    elif off_veg == NO:
        veget = NO
    elif vegano in (SI, PROBABILE) and fonte != "nome":
        veget = vegano
    elif off_veg == SI:
        veget = SI
    elif ha_testo and a["lingua_ok"] and not a["carne"]:
        veget = PROBABILE
    elif off_veg == VERIFICA:
        veget = VERIFICA
    elif cat_carne:
        veget = NO
    elif vegano == PROBABILE:
        veget = PROBABILE
    elif _CARNE.search(n):
        veget = VERIFICA
    else:
        veget = IGNOTO

    if override in (SI, NO):
        vegano, fonte = override, "manuale"
        motivi = [] if override == SI else ["segnato non vegano da te"]
        if override == SI:
            veget = SI
    return {"vegano": vegano, "vegetariano": veget, "motivi": motivi[:6], "tracce": tracce_tot, "fonte": fonte,
            "ha_ingredienti": ha_testo}


# ── Profilo nutrizionale ─────────────────────────────────────────────────────
# Soglie dei claim del regolamento UE 1924/2006 (alimenti solidi, per 100 g) e del «semaforo» britannico per gli eccessi.

def _num(v):
    try:
        return None if v is None or v == "" else float(v)
    except (ValueError, TypeError):
        return None


def profilo_nutrizionale(nutriments, nutriscore="", nova=None) -> dict:
    n = nutriments or {}
    kcal, prot, fibre = _num(n.get("energia_kcal")), _num(n.get("proteine")), _num(n.get("fibre"))
    zucc, sale, sat, grassi = _num(n.get("zuccheri")), _num(n.get("sale")), _num(n.get("grassi_saturi")), _num(n.get("grassi"))
    punti = []

    def ok(i, t):
        punti.append({"id": i, "testo": t, "tono": "ok"})

    def att(i, t):
        punti.append({"id": i, "testo": t, "tono": "attenzione"})

    if prot is not None and kcal:
        quota = prot * 4 / kcal
        if quota >= 0.20 and prot >= 5:
            ok("proteine", "Alto contenuto di proteine (%g g)" % round(prot, 1))
        elif quota >= 0.12 and prot >= 3:
            ok("proteine", "Fonte di proteine (%g g)" % round(prot, 1))
    if fibre is not None:
        if fibre >= 6:
            ok("fibre", "Ricco di fibre (%g g)" % round(fibre, 1))
        elif fibre >= 3:
            ok("fibre", "Fonte di fibre (%g g)" % round(fibre, 1))
    if zucc is not None and zucc <= 5 and kcal is not None and kcal >= 20:
        ok("zuccheri", "Pochi zuccheri")
    if sale is not None and sale <= 0.3 and kcal is not None and kcal >= 20:
        ok("sale", "Poco sale")
    if sat is not None and sat <= 1.5 and kcal is not None and kcal >= 20:
        ok("saturi", "Pochi grassi saturi")
    gravi = 0
    if zucc is not None and zucc > 22.5:
        att("zuccheri", "Molto zucchero (%g g)" % round(zucc, 1))
        gravi += 1
    if sale is not None and sale > 1.5:
        att("sale", "Molto sale (%g g)" % round(sale, 1))
        gravi += 1
    if sat is not None and sat > 5:
        att("saturi", "Molti grassi saturi (%g g)" % round(sat, 1))
        gravi += 1
    if grassi is not None and grassi > 17.5:
        att("grassi", "Molti grassi (%g g)" % round(grassi, 1))
        gravi += 1
    try:
        nova = int(nova) if nova not in (None, "") else None
    except (ValueError, TypeError):
        nova = None
    if nova == 4:
        att("nova", "Ultra-lavorato (NOVA 4)")
    elif nova == 1:
        ok("nova", "Poco lavorato (NOVA 1)")

    ns = (nutriscore or "").strip().upper()[:1]
    salute = None
    if ns in ("A", "B"):
        salute = {"livello": "buono", "testo": "Nutri-Score " + ns}
    elif ns == "C":
        salute = {"livello": "medio", "testo": "Nutri-Score C"}
    elif ns in ("D", "E"):
        salute = {"livello": "scarso", "testo": "Nutri-Score " + ns}
    elif gravi >= 2:
        salute = {"livello": "scarso", "testo": "Diversi valori elevati"}
    elif gravi == 1:
        salute = {"livello": "medio", "testo": "Un valore elevato"}
    return {"punti": punti, "salute": salute, "nova": nova, "ha_dati": any(v is not None for v in (kcal, prot, fibre, zucc, sale, sat, grassi))}


# ── Dati da Open Food Facts ──────────────────────────────────────────────────

OFF_CAMPI_DIETA = ("ingredients_text_it,ingredients_text,ingredients_analysis_tags,labels_tags,allergens_tags,traces_tags,"
                   "nova_group,categories_tags")


def estrai_off(prodotto) -> dict:
    """Dal dict "product" di Open Food Facts: i dati grezzi da conservare (la valutazione si ricalcola quando serve)."""
    p = prodotto or {}
    nova = p.get("nova_group")
    try:
        nova = int(nova) if nova not in (None, "") else None
    except (ValueError, TypeError):
        nova = None
    return {
        "ingredienti": (p.get("ingredients_text_it") or p.get("ingredients_text") or "").strip()[:4000],
        "nova": nova,
        "off_dati": {
            "analisi": list(p.get("ingredients_analysis_tags") or []),
            "etichette": list(p.get("labels_tags") or [])[:40],
            "allergeni": list(p.get("allergens_tags") or []),
            "tracce": list(p.get("traces_tags") or []),
            "categorie": list(p.get("categories_tags") or [])[:60],
        },
    }
