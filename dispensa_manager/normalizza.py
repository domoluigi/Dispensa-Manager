"""Nomi della lista della spesa: quantita', chiave di confronto, corrispondenze (v2.2.0).

Serve a far capire all'app che «Dentifricio», «dentifrici», «2 dentifricio» e «Il dentifricio»
sono la stessa voce, e che una voce generica come «latte» e' coperta da un prodotto
«Latte intero parzialmente scremato». Niente librerie: regole semplici e prevedibili.
"""
import re
import unicodedata

# Parole che non cambiano il significato della voce
_STOP = {
    "il", "lo", "la", "le", "gli", "i", "un", "uno", "una", "di", "del", "dello", "della", "dei", "degli",
    "delle", "al", "alla", "alle", "ai", "allo", "con", "per", "da", "e", "in", "a", "d", "l", "dal", "dalla",
}
_NUMERI = {"un": 1, "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6,
           "sette": 7, "otto": 8, "nove": 9, "dieci": 10}
# «500 g di pasta», «1 l latte»: il numero e' una misura, non una quantita'
_MISURE = r"(?:kg|g|gr|grammi|etti|etto|hg|l|lt|litri|litro|ml|cl|dl|cm|mm|m)"
# «2 confezioni di pasta», «6 bottiglie acqua»: il numero e' una quantita' e l'unita' si scarta
_CONTEGGI = (r"(?:pz|pezzi|pezzo|conf|confezioni|confezione|bottiglie|bottiglia|buste|busta|lattine|lattina|"
             r"vasetti|vasetto|rotoli|rotolo|scatole|scatola|barattoli|barattolo|pacchi|pacco|pacchetti|pacchetto|"
             r"cartoni|cartone|sacchi|sacco|flaconi|flacone)")


def _senza_accenti(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _pulisci_spazi(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" \t-–—,;:.")


def estrai_quantita(testo: str):
    """'2 dentifricio' → ('dentifricio', 2); 'latte x3' → ('latte', 3); '500 g pasta' → ('500 g pasta', 1)."""
    t = _pulisci_spazi(str(testo or ""))
    if not t:
        return "", 1

    def valida(n):
        return 1 <= n <= 99

    m = re.match(r"^(\d{1,2})\s*[x×]\s*(.+)$", t, re.I)           # 3x latte, 3 x latte
    if m and not m.group(1).startswith("0") and valida(int(m.group(1))):
        return _pulisci_spazi(m.group(2)), int(m.group(1))
    m = re.match(r"^(.+?)\s*[x×]\s*(\d{1,2})$", t, re.I)           # latte x3
    if m and not m.group(2).startswith("0") and valida(int(m.group(2))):
        return _pulisci_spazi(m.group(1)), int(m.group(2))
    m = re.match(r"^(\d{1,2})\s+" + _CONTEGGI + r"\b\s*(?:di\s+|d')?(.+)$", t, re.I)   # 2 confezioni di pasta
    if m and not m.group(1).startswith("0") and valida(int(m.group(1))):
        return _pulisci_spazi(m.group(2)), int(m.group(1))
    m = re.match(r"^(\d{1,2})\s+(.+)$", t)                          # 2 dentifricio
    if m and not m.group(1).startswith("0") and valida(int(m.group(1))) \
            and not re.match(r"^" + _MISURE + r"\b", m.group(2), re.I):
        return _pulisci_spazi(m.group(2)), int(m.group(1))
    m = re.match(r"^(" + "|".join(_NUMERI) + r")\s+(.+)$", t, re.I)  # due dentifrici, una mela
    if m:
        return _pulisci_spazi(m.group(2)), _NUMERI[m.group(1).lower()]
    return t, 1


def _radice(token: str) -> str:
    """Radice grossolana per confrontare singolare e plurale: dentifricio/dentifrici → dentifric."""
    t = token
    if len(t) <= 3:
        return t
    for suf, sost in (("che", "ca"), ("ghe", "ga"), ("chi", "co"), ("ghi", "go")):
        if t.endswith(suf):
            t = t[: -len(suf)] + sost
            break
    while len(t) > 3 and t[-1] in "aeiou":
        t = t[:-1]
    return t


def token_chiave(nome: str) -> frozenset:
    """Insieme delle radici significative di un nome, senza articoli, quantita' e punteggiatura."""
    pulito, _ = estrai_quantita(nome)
    t = _senza_accenti(pulito.lower())
    parti = [p for p in re.split(r"[^a-z0-9]+", t) if p]
    return frozenset(_radice(p) for p in parti if p not in _STOP)


def chiave(nome: str) -> str:
    """Chiave di confronto stabile (token ordinati). Vuota se il nome non ha parole utili."""
    return " ".join(sorted(token_chiave(nome)))


def bella(nome: str) -> str:
    """Nome da mostrare: spazi puliti e iniziale maiuscola, il resto com'era scritto."""
    t = _pulisci_spazi(str(nome or ""))
    return t[:1].upper() + t[1:] if t else t


def copre(voce: frozenset, prodotto: frozenset) -> bool:
    """La voce generica «voce» e' coperta dal prodotto? Uguali, oppure tutte le parole della voce
    sono nel nome del prodotto («latte» ⊂ «latte intero»). Una voce vuota non copre nulla."""
    return bool(voce) and voce <= prodotto


def stessa_voce(a: frozenset, b: frozenset) -> bool:
    """Due voci della lista sono lo stesso articolo: stesse radici (l'ordine non conta)."""
    return bool(a) and a == b
