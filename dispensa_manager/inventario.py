"""Nuovo inventario (v2.5.0): azzeramento con annullo e modalita' riscansione.

Per rifare l'inventario si segna tutto come esaurito (quantita' 0: le righe restano, con foto, ingredienti e posizione) e si
riscansiona quello che c'e' davvero. Scansionando un prodotto con una riga esaurita si ricarica quella riga (vedi
`aggiungi_prodotto`), quindi non nascono doppioni.

Mentre si riscansiona (`riscansione_attiva`) l'app non propone i «finiti» nella spesa, non li elenca nei report e non manda
una notifica Telegram per ogni scansione. Prima di azzerare si copia il database: si controlla che la copia abbia le stesse righe.
"""
import glob
import logging
import os
import sqlite3
import uuid
from datetime import datetime

from database import DB_PATH, BACKUPS_DIR, get_setting, set_setting, riscansione_attiva

logger = logging.getLogger(__name__)

COPIE_DB = 3          # copie «prima dell'azzeramento» che si tengono
LOTTI_LOG = 3         # azzeramenti di cui si conserva il registro (per l'Annulla)


def backup_database() -> str:
    """Copia il database in BACKUPS_DIR e ne controlla il contenuto. Ritorna il percorso."""
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    dest = os.path.join(BACKUPS_DIR, "dispensa_pre_azzeramento_%s.db" % datetime.now().strftime("%Y%m%d-%H%M%S"))
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
        for tabella in ("prodotti", "lista_spesa", "storico_movimenti", "barcode_cache"):
            a = src.execute("SELECT COUNT(*) FROM %s" % tabella).fetchone()[0]
            b = dst.execute("SELECT COUNT(*) FROM %s" % tabella).fetchone()[0]
            if a != b:
                raise RuntimeError("copia del database incompleta (%s: %d righe invece di %d)" % (tabella, b, a))
    except Exception:
        dst.close()
        src.close()
        if os.path.exists(dest):
            os.remove(dest)
        raise
    dst.close()
    src.close()
    for vecchia in sorted(glob.glob(os.path.join(BACKUPS_DIR, "dispensa_pre_azzeramento_*.db")))[:-COPIE_DB]:
        try:
            os.remove(vecchia)
        except OSError as e:
            logger.warning("Impossibile rimuovere la copia vecchia %s: %s", vecchia, e)
    return dest


def anteprima(conn) -> dict:
    r = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(quantita), 0) AS pezzi FROM prodotti WHERE quantita>0").fetchone()
    return {"attivi": r["n"], "pezzi": r["pezzi"],
            "esauriti": conn.execute("SELECT COUNT(*) FROM prodotti WHERE quantita<=0").fetchone()[0]}


def stato(conn) -> dict:
    lotto = get_setting(conn, "riscansione_lotto", "")
    out = {"attiva": riscansione_attiva(conn), "lotto": lotto, "totale": 0, "riscansionati": 0, "da_riscansionare": 0, "nuovi": 0}
    if lotto:
        out["totale"] = conn.execute("SELECT COUNT(*) FROM azzeramento_log WHERE lotto=?", (lotto,)).fetchone()[0]
        out["riscansionati"] = conn.execute(
            "SELECT COUNT(*) FROM azzeramento_log l JOIN prodotti p ON p.id=l.prodotto_id WHERE l.lotto=? AND p.quantita>0", (lotto,)).fetchone()[0]
        out["da_riscansionare"] = conn.execute(
            "SELECT COUNT(*) FROM azzeramento_log l JOIN prodotti p ON p.id=l.prodotto_id WHERE l.lotto=? AND p.quantita<=0", (lotto,)).fetchone()[0]
        out["nuovi"] = conn.execute(
            "SELECT COUNT(*) FROM prodotti WHERE quantita>0 AND id NOT IN (SELECT prodotto_id FROM azzeramento_log WHERE lotto=?)", (lotto,)).fetchone()[0]
    return out


def azzera(conn) -> dict:
    """Segna come esauriti tutti i prodotti in casa e accende la modalita' riscansione."""
    copia = backup_database()
    lotto = uuid.uuid4().hex[:12]
    with conn:
        righe = conn.execute("SELECT id, quantita FROM prodotti WHERE quantita>0").fetchall()
        conn.executemany("INSERT INTO azzeramento_log (lotto, prodotto_id, quantita_prima) VALUES (?, ?, ?)",
                         [(lotto, r["id"], r["quantita"]) for r in righe])
        conn.execute("UPDATE prodotti SET quantita=0 WHERE quantita>0")
        conn.execute("DELETE FROM azzeramento_log WHERE lotto NOT IN "
                     "(SELECT lotto FROM azzeramento_log GROUP BY lotto ORDER BY MAX(id) DESC LIMIT ?)", (LOTTI_LOG,))
        set_setting(conn, "riscansione_attiva", "1")
        set_setting(conn, "riscansione_lotto", lotto)
    rimasti = conn.execute("SELECT COUNT(*) FROM prodotti WHERE quantita>0").fetchone()[0]
    if rimasti:
        raise RuntimeError("azzeramento incompleto: %d prodotti ancora in casa" % rimasti)
    logger.info("Inventario azzerato: %d prodotti (%d pezzi), copia %s", len(righe), sum(r["quantita"] for r in righe), os.path.basename(copia))
    return {"lotto": lotto, "azzerati": len(righe), "pezzi": sum(r["quantita"] for r in righe), "copia": os.path.basename(copia)}


def annulla(conn, lotto: str) -> dict:
    """Rimette le quantita' di prima ai prodotti che sono ancora a zero. Quelli gia' riscansionati restano come sono."""
    righe = conn.execute(
        "SELECT l.prodotto_id AS id, l.quantita_prima AS q FROM azzeramento_log l JOIN prodotti p ON p.id=l.prodotto_id "
        "WHERE l.lotto=? AND p.quantita<=0", (lotto,)).fetchall()
    gia = conn.execute(
        "SELECT COUNT(*) FROM azzeramento_log l JOIN prodotti p ON p.id=l.prodotto_id WHERE l.lotto=? AND p.quantita>0", (lotto,)).fetchone()[0]
    with conn:
        conn.executemany("UPDATE prodotti SET quantita=? WHERE id=?", [(r["q"], r["id"]) for r in righe])
        conn.execute("DELETE FROM azzeramento_log WHERE lotto=?", (lotto,))
        if get_setting(conn, "riscansione_lotto", "") == lotto:
            set_setting(conn, "riscansione_attiva", "0")
            set_setting(conn, "riscansione_lotto", "")
    return {"ripristinati": len(righe), "gia_riscansionati": gia}


def imposta_riscansione(conn, attiva: bool):
    with conn:
        set_setting(conn, "riscansione_attiva", "1" if attiva else "0")
