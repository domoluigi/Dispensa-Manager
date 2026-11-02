"""Dove va un prodotto: dispensa, frigo, congelatore, saponi, altro (v2.4.0).

Cinque posizioni (il valore salvato e' la prima colonna):

    Dispensa  alimenti a temperatura ambiente, anche liquidi (acqua, succhi, olio, vino…)
    Frigo     alimenti da tenere in frigorifero
    Freezer   surgelati e gelati (nell'app si chiama «Congelatore»)
    Saponi    igiene e cura della persona, detersivi e pulizia della casa
    Altro     tutto il resto che non si mangia: animali, pile, carta da cucina, sacchetti…

La classificazione parte dal nome e dalle categorie di Open Food Facts (in inglese) e dice quanto e' sicura.
Prova sui prodotti veri (una dispensa quasi tutta vegetale): riconoscere cio' che NON e' cibo e i surgelati
e' affidabile; decidere tra frigo e dispensa dal solo nome no (un burger vegetale e' in frigo, un ragu' in
barattolo no). Per questo i prodotti esistenti si spostano in blocco solo con livello «alto».
"""
import re
import unicodedata

from reparti import reparto_di
from suggerimenti import suggerisci_da_categoria

POSIZIONI = ("Dispensa", "Frigo", "Freezer", "Saponi", "Altro")
ETICHETTE = {"Dispensa": "Dispensa", "Frigo": "Frigo", "Freezer": "Congelatore", "Saponi": "Saponi", "Altro": "Altro"}
ICONE = {"Dispensa": "🗄️", "Frigo": "🧊", "Freezer": "❄️", "Saponi": "🧴", "Altro": "📦"}

# Igiene e pulizia, anche nei termini inglesi delle categorie di Open Beauty/Products Facts
_SAPONI = re.compile(
    r"\b(?:soaps?|sapon|shampoo|conditioners?|toothpastes?|dentifric|toothbrush|spazzolin|mouthwash|collutori|"
    r"deodorants?|shower|body ?wash|bagnoschiuma|detergents?|detersiv|laundry|dishwash|lavastoviglie|cleaning|"
    r"cleaners?|bleach|candeggin|fabric ?softener|ammorbident|sponges?|spugn|cosmetics?|skincare|razors?|rasoi|"
    r"diapers?|nappies|pannolin|wipes|salviett|tissues|fazzolett|toilet ?paper|carta igienica|sanitary|assorbent|"
    r"micellar|struccant|sgrassator|anticalcare|disinfettant|igienizzant|brillantante|lucidante|"
    r"crema (?:viso|mani|corpo|solare)|cotton ?fioc|dischett|profum|preservativ|cerott)\w*"
)
# Surgelati: solo parole inequivocabili
_FREEZER = re.compile(r"\b(?:surgelat|congelat|frozen|gelato|gelati|ghiacciol|ice ?cream|sorbett)")
# Cose di casa che non sono sapone ne' cibo
_ALTRO = re.compile(
    r"\b(?:sacchett|sacchi|pellicola|alluminio|carta (?:forno|cucina|alluminio|regalo)|scottex|tovaglioli|"
    r"piatti (?:usa|di carta|di plastica)|bicchieri (?:usa|di carta|di plastica)|lampadin|pile\b|batteri|candel|"
    r"insetticid|zanzar|guanti|accendin|fiammifer|cancelleri|quaderno|nastro|colla\b|cavo\b|cavi\b|caricabatter|"
    r"giocattol|light ?bulbs?|batteries|plastic ?bags?|aluminium|aluminum|cling ?film|kitchen ?roll)\w*"
)


def _norm(*testi) -> str:
    t = " ".join(str(x) for x in testi if x)
    t = "".join(c for c in unicodedata.normalize("NFKD", t.lower()) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", t)


def classifica(nome: str, marca: str = "", categoria: str = "", categorie=()) -> dict:
    """{"posizione", "livello", "sicuro", "fonte"}.

    livello «alto»: non e' cibo (Saponi, Altro) o e' surgelato per parola esplicita: si puo' applicare in blocco;
    livello «medio»: regola su nome/categoria per Frigo e Dispensa: buona per proporre una posizione a un prodotto
    nuovo, non per spostarne uno esistente; livello «basso»: nessuna regola, si lascia com'e'.
    «sicuro» e' livello == alto.

    Il campo «categoria» dei prodotti vecchi e' la prima categoria di Open Food Facts (la piu' generica) e porta
    fuori strada: per i prodotti esistenti passare solo nome e marca.
    """
    categorie = [c for c in (categorie or []) if c]
    elenco = categorie + ([categoria] if categoria else [])
    testo = _norm(nome, marca, categoria, " ".join(categorie))
    rep = reparto_di(nome, categoria, marca, *categorie)

    def esito(pos, livello, fonte):
        return {"posizione": pos, "livello": livello, "sicuro": livello == "alto", "fonte": fonte}

    if rep == "animali":
        return esito("Altro", "alto", "animali")
    if rep in ("igiene", "casa") or _SAPONI.search(testo):
        return esito("Altro" if _ALTRO.search(testo) else "Saponi", "alto", "igiene/casa")
    if _ALTRO.search(testo):
        return esito("Altro", "alto", "casa")
    if _FREEZER.search(testo):
        return esito("Freezer", "alto", "surgelato")

    cat = suggerisci_da_categoria(elenco, nome)
    if cat.get("trovata"):
        return esito(cat["posizione"], "medio", "categoria")
    ripiego = {"surgelati": "Freezer", "latticini": "Frigo", "carne_pesce": "Frigo", "frutta_verdura": "Frigo",
               "dispensa": "Dispensa", "bevande": "Dispensa", "pane": "Dispensa"}.get(rep)
    if ripiego:
        return esito(ripiego, "medio", "reparto")
    return esito("Dispensa", "basso", None)
