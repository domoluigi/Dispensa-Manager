"""Riclassificazione dei prodotti esistenti tra le posizioni (v2.4.0).

Si propone di spostare un prodotto solo se la classificazione dal nome e' diversa dalla posizione attuale:
- livello «alto» (non e' cibo, oppure e' surgelato): consigliato, si puo' applicare in blocco;
- livello «medio» (frigo/dispensa dal solo nome): da verificare, mai applicato senza una scelta esplicita.
Cio' che l'utente scarta non viene riproposto. Ogni applicazione e' un «lotto» annullabile.
"""
import uuid

from posizioni import classifica, ETICHETTE


def proposte(conn) -> list:
    ignorati = {r["prodotto_id"]: r["posizione"] for r in conn.execute("SELECT prodotto_id, posizione FROM riclassifica_ignorati")}
    out = []
    for p in conn.execute("SELECT id, nome, marca, quantita, posizione FROM prodotti").fetchall():
        k = classifica(p["nome"], p["marca"] or "")          # solo nome e marca: la categoria dei prodotti vecchi e' generica
        attuale = p["posizione"] or "Dispensa"
        if k["livello"] == "basso" or k["posizione"] == attuale:
            continue
        if ignorati.get(p["id"]) == k["posizione"]:
            continue
        out.append({
            "id": p["id"], "nome": p["nome"], "marca": p["marca"] or "", "quantita": p["quantita"],
            "da": attuale, "a": k["posizione"], "da_etichetta": ETICHETTE.get(attuale, attuale),
            "a_etichetta": ETICHETTE[k["posizione"]], "livello": k["livello"], "fonte": k["fonte"],
        })
    out.sort(key=lambda x: (0 if x["livello"] == "alto" else 1, x["a"], x["nome"].lower()))
    return out


def conteggi(conn) -> dict:
    pr = proposte(conn)
    return {"alto": sum(1 for x in pr if x["livello"] == "alto"), "medio": sum(1 for x in pr if x["livello"] == "medio")}


def applica(conn, ids, ignora=()) -> dict:
    """Sposta i prodotti scelti (la proposta si ricalcola qui: non ci si fida di quello che invia il client)
    e mette da parte quelli scartati."""
    corrente = {x["id"]: x for x in proposte(conn)}
    lotto = uuid.uuid4().hex
    cambiati = 0
    with conn:
        for pid in ids:
            x = corrente.get(pid)
            if not x:
                continue
            conn.execute("UPDATE prodotti SET posizione=? WHERE id=?", (x["a"], pid))
            conn.execute("INSERT INTO posizioni_log (lotto, prodotto_id, da, a) VALUES (?, ?, ?, ?)", (lotto, pid, x["da"], x["a"]))
            cambiati += 1
        for pid in ignora:
            x = corrente.get(pid)
            if x and pid not in ids:
                conn.execute("INSERT OR REPLACE INTO riclassifica_ignorati (prodotto_id, posizione) VALUES (?, ?)", (pid, x["a"]))
    return {"lotto": lotto if cambiati else None, "cambiati": cambiati}


def annulla(conn, lotto: str) -> int:
    """Rimette le posizioni di un lotto, tranne i prodotti spostati di nuovo a mano nel frattempo."""
    righe = conn.execute("SELECT * FROM posizioni_log WHERE lotto=?", (lotto,)).fetchall()
    ripristinati = 0
    with conn:
        for r in righe:
            cur = conn.execute("UPDATE prodotti SET posizione=? WHERE id=? AND posizione=?", (r["da"], r["prodotto_id"], r["a"]))
            ripristinati += cur.rowcount
        conn.execute("DELETE FROM posizioni_log WHERE lotto=?", (lotto,))
    return ripristinati
