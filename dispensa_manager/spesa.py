"""Logica della lista della spesa (v2.2.0).

La lista ha tre parti:
- «Da comprare»: voci aggiunte a mano (o, piu' avanti, da Alexa), generiche o legate a un prodotto;
- «Nel carrello»: voci spuntate;
- «Suggeriti»: prodotti finiti in dispensa. NON sono nella lista: si propongono e si sceglie.

Una voce e' coperta da un prodotto o ne e' il duplicato in base ai nomi normalizzati (normalizza.py).
"""
import uuid
from datetime import datetime, timezone

from database import riscansione_attiva
from normalizza import estrai_quantita, bella, token_chiave, copre, stessa_voce
from reparti import reparto_di, ETICHETTA, ORDINE, REPARTI

MAX_VOCI = 500            # limite di sicurezza per la lista


def ora_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _chiave_testo(tok: frozenset) -> str:
    return " ".join(sorted(tok))


def assicura_righe(conn):
    """Completa le righe senza uid/chiave/reparto (backup ripristinati da versioni precedenti)."""
    righe = conn.execute(
        "SELECT id, nome, marca FROM lista_spesa WHERE uid IS NULL OR uid='' OR nome_norm IS NULL OR reparto IS NULL"
    ).fetchall()
    if not righe:
        return
    with conn:
        for r in righe:
            conn.execute(
                "UPDATE lista_spesa SET uid=COALESCE(NULLIF(uid,''), ?), nome_norm=COALESCE(nome_norm, ?), "
                "reparto=COALESCE(reparto, ?), aggiornato_il=COALESCE(aggiornato_il, ?), "
                "origine=COALESCE(origine, 'manuale') WHERE id=?",
                (uuid.uuid4().hex, _chiave_testo(token_chiave(r["nome"])), reparto_di(r["nome"], r["marca"]), ora_utc(), r["id"]),
            )


def _attivi(conn):
    """Prodotti presenti in dispensa (quantita' > 0) con le radici del nome."""
    out = []
    for p in conn.execute(
        "SELECT id, nome, marca, ean, quantita, posizione, categoria FROM prodotti WHERE quantita>0"
    ).fetchall():
        out.append({**dict(p), "_tok": token_chiave(p["nome"]), "_rep": reparto_di(p["nome"], p["categoria"], p["marca"])})
    return out


def _in_dispensa(tok: frozenset, rep: str, attivi) -> list:
    """Prodotti in dispensa che coprono una voce generica: serve ad avvisare «ne hai gia' due in frigo».
    Oltre alle parole conta il reparto: «latte» non e' coperto da «cioccolato al latte di cocco»."""
    trovati = [a for a in attivi if copre(tok, a["_tok"]) and a["_rep"] == rep]
    return [{"nome": a["nome"], "quantita": a["quantita"], "posizione": a["posizione"] or "Dispensa"} for a in trovati[:3]]


def _voce_dict(r, attivi=None) -> dict:
    d = {
        "id": r["id"], "uid": r["uid"], "nome": r["nome"], "quantita": r["quantita"] or 1,
        "reparto": r["reparto"] or "altro", "origine": r["origine"] or "manuale",
        "aggiunto_da": r["aggiunto_da"] or "", "completato": int(r["completato"] or 0),
        "ean": r["ean"] or "", "marca": r["marca"] or "", "data_aggiunta": r["data_aggiunta"],
    }
    d["reparto_etichetta"] = ETICHETTA.get(d["reparto"], ETICHETTA["altro"])
    if attivi is not None and not d["completato"]:
        d["in_dispensa"] = _in_dispensa(token_chiave(r["nome"]), r["reparto"] or "altro", attivi)
    return d


def _registra_uso(conn, nome: str, tok: frozenset):
    chiave = _chiave_testo(tok)
    if not chiave:
        return
    conn.execute(
        "INSERT INTO spesa_storico (nome_norm, nome, volte, ultimo) VALUES (?, ?, 1, ?) "
        "ON CONFLICT(nome_norm) DO UPDATE SET volte=volte+1, nome=excluded.nome, ultimo=excluded.ultimo",
        (chiave, nome, ora_utc()),
    )


def aggiungi_voce(conn, nome, quantita=None, ean="", marca="", origine="manuale", utente="") -> dict:
    """Aggiunge una voce senza creare doppioni.

    - «2 dentifricio» / «dentifricio x2» / «due dentifrici»: la quantita' viene dal testo;
    - voce gia' in lista (stesse radici): se non e' stata chiesta una quantita' maggiore di 1 non cambia nulla,
      altrimenti la quantita' si somma;
    - voce gia' nel carrello: torna in «Da comprare»;
    - ritorna anche cosa c'e' gia' in dispensa che la copre.
    Solleva ValueError se il nome non contiene parole utili.
    """
    testo, q_testo = estrai_quantita(nome)
    nome_vis = bella(testo)
    tok = token_chiave(nome_vis)
    if not nome_vis or not tok or not any(c.isalpha() for c in nome_vis):   # un numero da solo non e' un prodotto
        raise ValueError("Scrivi il nome del prodotto")
    if len(nome_vis) > 120:
        raise ValueError("Nome troppo lungo")
    try:
        q_esplicita = int(quantita) if quantita not in (None, "") else None
    except (TypeError, ValueError):
        q_esplicita = None
    q = q_esplicita if q_esplicita and q_esplicita > 0 else q_testo
    q = max(1, min(q, 99))
    chiave = _chiave_testo(tok)

    esito = {"unita": False, "riattivata": False}
    adesso = ora_utc()
    righe = conn.execute(
        "SELECT * FROM lista_spesa WHERE nome_norm=? ORDER BY completato ASC, id ASC", (chiave,)
    ).fetchall()
    with conn:
        if righe:
            r = righe[0]
            if r["completato"]:
                conn.execute(
                    "UPDATE lista_spesa SET completato=0, completato_il=NULL, quantita=?, aggiornato_il=? WHERE id=?",
                    (q, adesso, r["id"]),
                )
                esito.update(riattivata=True, id=r["id"], nome=r["nome"])
            else:
                esito.update(unita=True, id=r["id"], nome=r["nome"])
                if q > 1:
                    conn.execute("UPDATE lista_spesa SET quantita=quantita+?, aggiornato_il=? WHERE id=?", (q, adesso, r["id"]))
        else:
            totale = conn.execute("SELECT COUNT(*) AS n FROM lista_spesa").fetchone()["n"]
            if totale >= MAX_VOCI:
                raise ValueError("Lista troppo lunga: svuota il carrello")
            cur = conn.execute(
                "INSERT INTO lista_spesa (uid, nome, quantita, ean, marca, completato, origine, nome_norm, reparto, "
                "aggiunto_da, aggiornato_il) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, nome_vis, q, ean or "", marca or "", origine, chiave,
                 reparto_di(nome_vis, marca), utente or "", adesso),
            )
            esito["id"] = cur.lastrowid
        _registra_uso(conn, nome_vis, tok)
    esito.setdefault("nome", nome_vis)
    esito["in_dispensa"] = _in_dispensa(tok, reparto_di(nome_vis, marca), _attivi(conn))
    return esito


def lista(conn):
    """(da_comprare, carrello): voci della lista, nell'ordine di un giro al supermercato."""
    assicura_righe(conn)
    attivi = _attivi(conn)
    righe = conn.execute("SELECT * FROM lista_spesa ORDER BY id").fetchall()
    da_comprare = [_voce_dict(r, attivi) for r in righe if not r["completato"]]
    carrello = [_voce_dict(r) for r in righe if r["completato"]]
    da_comprare.sort(key=lambda v: (ORDINE.get(v["reparto"], 99), v["nome"].lower()))
    carrello.sort(key=lambda v: v["nome"].lower())
    return da_comprare, carrello


def suggeriti(conn) -> list:
    """Prodotti finiti in dispensa che si possono proporre.

    Si escludono: quelli messi da parte con «Non serve» finche' non tornano in dispensa, quelli di cui c'e' ancora
    una scorta (stesso EAN o stesso nome in un'altra riga), quelli gia' coperti da una voce in lista (anche nel
    carrello) e i doppioni (stesso EAN o stesso nome: se ne propone uno solo, l'ultimo inserito).
    """
    if riscansione_attiva(conn):     # dopo un azzeramento tutto e' «finito»: finche' si riscansiona non si propone niente
        return []
    assicura_righe(conn)
    with conn:   # un «Non serve» cade quando il prodotto torna in dispensa o sparisce
        conn.execute("DELETE FROM suggerimenti_ignorati WHERE prodotto_id NOT IN (SELECT id FROM prodotti WHERE quantita<=0)")
    ignorati = {r["prodotto_id"] for r in conn.execute("SELECT prodotto_id FROM suggerimenti_ignorati").fetchall()}
    attivi = _attivi(conn)
    eans_attivi = {a["ean"] for a in attivi if a["ean"] and not a["ean"].startswith("MANUAL-")}
    chiavi_attive = {a["_tok"] for a in attivi}
    voci = [(token_chiave(r["nome"]), r["reparto"] or "altro") for r in conn.execute("SELECT nome, reparto FROM lista_spesa").fetchall()]

    ultimo_consumo = {}
    for r in conn.execute("SELECT ean, nome, MAX(data) AS d FROM storico_movimenti WHERE tipo IN ('consumo','eliminato') GROUP BY ean, nome").fetchall():
        if r["ean"]:
            ultimo_consumo[("e", r["ean"])] = r["d"]
        ultimo_consumo[("n", (r["nome"] or "").lower())] = r["d"]

    visti_ean, visti_chiave, out = set(), set(), []
    oggi = datetime.now(timezone.utc)
    for p in conn.execute("SELECT * FROM prodotti WHERE quantita<=0 ORDER BY id DESC").fetchall():
        tok = token_chiave(p["nome"])
        ean = p["ean"] or ""
        ean_reale = ean and not ean.startswith("MANUAL-")
        if not tok or p["id"] in ignorati:
            continue
        if ean_reale and ean in eans_attivi:
            continue
        if any(stessa_voce(tok, t) for t in chiavi_attive):
            continue
        rep = reparto_di(p["nome"], p["categoria"], p["marca"])
        if any(copre(v, tok) and r == rep for v, r in voci):   # voce gia' in lista (anche nel carrello), stesso reparto
            continue
        k = _chiave_testo(tok)
        if (ean_reale and ean in visti_ean) or k in visti_chiave:
            continue
        if ean_reale:
            visti_ean.add(ean)
        visti_chiave.add(k)
        quando = ultimo_consumo.get(("e", ean)) if ean_reale else None
        quando = quando or ultimo_consumo.get(("n", (p["nome"] or "").lower())) or p["data_inserimento"]
        giorni = None
        try:
            giorni = max(0, (oggi - datetime.strptime(str(quando)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)).days)
        except (ValueError, TypeError):
            pass
        out.append({
            "prodotto_id": p["id"], "nome": p["nome"], "marca": p["marca"] or "", "ean": ean if ean_reale else "",
            "posizione": p["posizione"] or "Dispensa", "reparto": rep, "reparto_etichetta": ETICHETTA[rep],
            "immagine_url": p["immagine_url"] or "", "giorni": giorni,
        })
    # prima i finiti da meno tempo (sono quelli che servono davvero), poi per nome
    out.sort(key=lambda s: (s["giorni"] if s["giorni"] is not None else 9999, s["nome"].lower()))
    return out


def aggiungi_suggerito(conn, prodotto_id: int, utente: str = ""):
    p = conn.execute("SELECT * FROM prodotti WHERE id=?", (prodotto_id,)).fetchone()
    if not p:
        return None
    ean = p["ean"] or ""
    ris = aggiungi_voce(conn, p["nome"], 1, "" if ean.startswith("MANUAL-") else ean, p["marca"] or "", "suggerimento", utente)
    ris["prodotto_id"] = prodotto_id
    return ris


def ignora_suggerito(conn, prodotto_id: int) -> int:
    """«Non serve»: nasconde il suggerimento (e i doppioni dello stesso prodotto) finche' non torna in dispensa."""
    p = conn.execute("SELECT * FROM prodotti WHERE id=? AND quantita<=0", (prodotto_id,)).fetchone()
    if not p:
        return 0
    tok, ean = token_chiave(p["nome"]), p["ean"] or ""
    ids = {prodotto_id}
    for q in conn.execute("SELECT id, nome, ean FROM prodotti WHERE quantita<=0").fetchall():
        if (ean and not ean.startswith("MANUAL-") and q["ean"] == ean) or stessa_voce(tok, token_chiave(q["nome"])):
            ids.add(q["id"])
    with conn:
        for i in ids:
            conn.execute("INSERT OR REPLACE INTO suggerimenti_ignorati (prodotto_id, data) VALUES (?, ?)", (i, ora_utc()))
    return len(ids)


def ignora_vecchi(conn, giorni: int = 90) -> int:
    """«Non serve» in blocco per i suggerimenti finiti da almeno `giorni` giorni: quasi sempre prodotti che non si
    ricomprano piu', e tenerli in elenco copre quelli che servono davvero."""
    nascosti = 0
    for s in suggeriti(conn):
        if s["giorni"] is not None and s["giorni"] >= giorni:
            nascosti += ignora_suggerito(conn, s["prodotto_id"]) and 1
    return nascosti


def cerca(conn, q: str, limite: int = 8) -> list:
    """Completamento mentre si scrive: voci usate spesso, poi nomi di prodotti conosciuti."""
    testo, _ = estrai_quantita(q)
    tok = token_chiave(testo)
    grezzo = testo.strip().lower()
    if len(grezzo) < 2:
        return []
    gia = {_chiave_testo(token_chiave(r["nome"])) for r in conn.execute("SELECT nome FROM lista_spesa WHERE completato=0").fetchall()}
    out, visti = [], set()

    def aggiungi(nome, fonte):
        k = _chiave_testo(token_chiave(nome))
        if k and k not in visti and k not in gia and len(out) < limite:
            visti.add(k)
            out.append({"nome": bella(nome), "fonte": fonte})

    like = "%" + grezzo.replace("%", "").replace("_", "") + "%"
    for r in conn.execute("SELECT nome FROM spesa_storico WHERE LOWER(nome) LIKE ? ORDER BY volte DESC, ultimo DESC LIMIT 20", (like,)).fetchall():
        aggiungi(r["nome"], "frequente")
    for r in conn.execute("SELECT DISTINCT nome FROM prodotti WHERE LOWER(nome) LIKE ? ORDER BY nome LIMIT 30", (like,)).fetchall():
        aggiungi(r["nome"], "prodotto")
    return out


def conteggi(conn) -> dict:
    da_comprare, carrello = lista(conn)
    return {"da_comprare": len(da_comprare), "carrello": len(carrello), "suggeriti": len(suggeriti(conn))}


def elenco_reparti() -> list:
    return [{"codice": c, "etichetta": e} for c, e in REPARTI]
