"""Reparto del supermercato per una voce della lista della spesa (v2.2.0).

L'ordine dei reparti e' quello di un giro tipico; le regole si valutano in ordine e vince la prima
(per questo «pizza surgelata» finisce nei surgelati e «carta igienica» nell'igiene, non nella carta da cucina).
I pattern sono prefissi di parola: «dentifric» copre dentifricio e dentifrici.
"""
import re
import unicodedata

# (codice, etichetta): l'ordine e' quello mostrato nell'app
REPARTI = [
    ("frutta_verdura", "🥬 Frutta e verdura"),
    ("pane", "🥖 Pane e forno"),
    ("latticini", "🥛 Latticini e uova"),
    ("carne_pesce", "🥩 Carne, pesce e salumi"),
    ("surgelati", "❄️ Surgelati"),
    ("dispensa", "🥫 Dispensa"),
    ("bevande", "🥤 Bevande"),
    ("igiene", "🧴 Igiene e cura persona"),
    ("casa", "🧽 Casa e pulizia"),
    ("animali", "🐾 Animali"),
    ("altro", "🛒 Altro"),
]
ETICHETTA = dict(REPARTI)
ORDINE = {codice: i for i, (codice, _) in enumerate(REPARTI)}

# Regole in ordine di valutazione: le piu' specifiche prima
_REGOLE = [(codice, re.compile(r"\b(?:" + pattern + r")")) for codice, pattern in [
    ("surgelati", r"surgelat|congelat|gelat|ghiacciol|ghiaccio|frozen|bastoncin|sorbett"),
    ("animali", r"crocchett|lettier|cibo (?:per )?(?:cani|cane|gatti|gatto)|(?:cani|cane|gatti|gatto) (?:cibo|umido|secco)|"
                r"snack (?:per )?(?:cani|cane|gatti|gatto)|antiparassit|guinzagli|osso (?:per )?cane"),
    ("casa", r"detersiv|ammorbident|candeggin|sgrassator|anticalcare|spugn|panno\b|panni\b|straccio|scopa|"
             r"pastigli|sacchett|sacchi|pellicola|alluminio|carta (?:forno|cucina|alluminio)|scottex|tovaglioli|"
             r"piatti (?:usa|di carta|di plastica)|bicchieri (?:usa|di carta|di plastica)|lampadin|pile\b|batteri|candel|"
             r"insetticid|deodorante (?:per )?(?:ambiente|casa)|lucidante|vetri|lavastoviglie|lavatrice|brillantante|"
             r"sale (?:per )?lavastoviglie|disinfettant|igienizzant|guanti|zanzar"),
    ("igiene", r"dentifric|spazzolin|collutori|filo interdentale|shampoo|balsamo|bagnoschiuma|bagno doccia|doccia|sapone|"
               r"saponetta|deodorante|rasoi|lamett|schiuma da barba|dopobarba|assorbent|carta igienica|fazzolett|"
               r"cotton ?fioc|dischett|crema (?:viso|mani|corpo|idratante|antirughe|notte|giorno|depilatoria|solare)|struccant|"
               r"profum|preservativ|pannolin|salviett|cerott|tampon|lacca|gel capelli|tinta|lima\b|smalto|acetone|"
               r"protezione solare|solare"),
    ("bevande", r"acqua|birra|vino|prosecco|spumante|succo|succhi|coca|cola\b|aranciata|gassosa|bibita|"
                r"te freddo|limonata|energy|amaro|liquor|grappa|whisky|vodka|gin\b|spritz|aperol|chinotto|sidro|kombucha|"
                r"latte di (?:soia|mandorla|avena|riso|cocco)"),
    # prodotti trasformati che contengono il nome di un ortaggio o di un pesce: prima delle regole fresche
    ("dispensa", r"passata|pelati|polpa|sugo|conserva di|concentrato|salsa di|in scatola|scatol|sott olio|sottaceti|"
                 r"tonno|biscott|marmellat|confettur|nutella|crema spalmabile|brodo|dado|tisan|infus|camomill|caff|cioccolat"),
    ("carne_pesce", r"carne|pollo|manzo|maiale|tacchino|vitello|agnello|coniglio|hamburger|salsicc|bistecc|fettine|"
                    r"macinato|prosciutt|salame|mortadella|bresaola|speck|pancetta|guanciale|wurstel|salumi|affettat|"
                    r"pesce|salmone|merluzzo|gamberi|gamberett|calamar|cozze|vongole|polpo|orata|branzino|spada|sgombro|"
                    r"trota|baccal|acciugh|alici|cotolett|arrosto|spezzatino|filetto"),
    ("latticini", r"latte|yogurt|burro|panna|formagg|mozzarella|ricotta|parmigian|grana|pecorino|mascarpone|stracchino|"
                  r"provol|scamorza|philadelphia|kefir|uov|gorgonzola|fontina|asiago|emmental|taleggio|burrata|"
                  r"feta|halloumi|skyr|budino|besciamella"),
    ("frutta_verdura", r"mel[ae]\b|pere\b|pera\b|banan|aranc|limon|mandarin|clementin|pompelm|kiwi|fragol|uva|ananas|"
                       r"pesch|albicocc|ciliegi|anguri|melon|mirtill|lampon|frutta|verdur|insalat|lattug|rucola|"
                       r"spinaci|bietol|cavol|broccol|cavolfior|carot|patat|cipoll|aglio|scalogn|porr|sedano|finocch|"
                       r"zucchin|melanzan|peperon|pomodor|cetriol|zucca|funghi|fungo|asparag|carciof|radicchio|"
                       r"basilic|prezzemol|rosmarin|salvia|menta|erbe aromatiche|avocado|limoni|zenzero|barbabietol|"
                       r"piselli freschi|fagiolini|ravanell|insalata"),
    ("pane", r"pane|focaccia|piadin|panin|cornett|brioche|croissant|bauletto|pancarr|ciabatta|baguette|"
             r"grissin|schiacciat|taralli|friselle|panettone|pandoro|colomba|torta|crostat|ciambell|muffin"),
    ("dispensa", r"pasta|spaghett|penne|rigaton|fusill|tagliatell|pastina|riso|farina|zucchero|sale\b|olio|aceto|"
                 r"passata|pelati|polpa|sugo|pesto|legum|ceci|fagioli|lenticchi|piselli|tonno|sgombro|scatol|conserv|"
                 r"biscott|cereali|muesli|corn ?flakes|fette biscottate|marmellat|miele|nutella|crema spalmabile|"
                 r"caff|camomill|tisana|infuso|cracker|patatine|snack|popcorn|noccioline|frutta secca|mandorle|noci\b|"
                 r"cioccolat|caramell|caramelle|gomme|spezie|pepe\b|origano|curry|paprica|lievito|brodo|dado|"
                 r"farro|orzo|couscous|quinoa|polenta|semola|amido|maizena|salsa|maionese|ketchup|senape|"
                 r"olive|capperi|sottaceti|sott olio|tahin|hummus|avena|te\b|"
                 r"cacao|vaniglia|budino in polvere|gelatina|zucchero a velo|pangrattato"),
]]


def _normalizza(testo: str) -> str:
    t = "".join(c for c in unicodedata.normalize("NFKD", str(testo or "").lower()) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", t)


def reparto_di(*testi: str) -> str:
    """Codice del reparto per uno o piu' testi (nome, categoria...). 'altro' se nessuna regola combacia."""
    t = " ".join(_normalizza(x) for x in testi if x)
    t = re.sub(r"\s+", " ", t).strip()
    for codice, regola in _REGOLE:
        if regola.search(t):
            return codice
    return "altro"
