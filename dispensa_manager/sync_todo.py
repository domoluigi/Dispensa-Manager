"""Sincronizzazione della lista della spesa con una lista «to-do» di Home Assistant (v2.3.0).

Serve ai widget del telefono (app Companion → widget «To-do list») e, piu' avanti, alla lista di Alexa.

Principi:
- il database di Dispensa e' la fonte di verita': se Home Assistant e' lento o spento l'app funziona lo stesso;
- ogni elemento remoto e' legato a una voce locale da una mappa (spesa_sync_map) che ricorda anche l'ultimo
  stato concordato: confrontando locale e remoto con quell'istantanea si capisce chi ha cambiato cosa, e non
  si creano rimbalzi (nessun «eco» tra le due liste);
- le cancellazioni remote valgono solo se confermate in due giri consecutivi e mai in massa: una lettura
  incompleta non deve svuotare la lista;
- la prima attivazione unisce le due liste, senza cancellare niente;
- un giro a vuoto (nessuna differenza) non fa nessuna chiamata di scrittura.

Home Assistant si raggiunge dal Supervisor (`homeassistant_api: true`) con i servizi `todo.*`.
"""
import logging
import os
import threading
import time
from datetime import datetime, timezone

import requests as http_requests

from database import get_db, get_setting
import spesa as sp
from normalizza import estrai_quantita, bella, token_chiave
from reparti import reparto_di

logger = logging.getLogger(__name__)

INTERVALLO = int(os.environ.get("DISPENSA_SYNC_SECONDI", "30"))   # secondi tra un giro e l'altro (la variabile serve alle prove)
INTERVALLO_ERRORE = 60     # dopo un errore si rallenta
TIMEOUT = 10               # secondi per ogni chiamata a Home Assistant
GRACE_CICLI = 2            # giri consecutivi in cui un elemento deve mancare prima di cancellare la voce locale
MAX_SCRITTURE = 120        # scritture remote per giro (il resto al giro dopo)

# connettore → (chiave dell'impostazione con l'entita', origine delle voci create da quel lato)
CONNETTORI = {"widget": ("todo_widget_entity", "widget")}

_evento = threading.Event()
_sensori = threading.Event()     # la lista e' cambiata: da riportare nei sensori di Home Assistant
_lock = threading.Lock()
_stato: dict = {}


class ErroreHA(Exception):
    """Home Assistant non risponde o rifiuta la richiesta."""


# ── Home Assistant: servizi todo.* ───────────────────────────────────────────

def _chiama(servizio: str, dati: dict, risposta: bool = False):
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        raise ErroreHA("SUPERVISOR_TOKEN assente: serve l'add-on dentro Home Assistant")
    url = f"{os.environ.get('HA_URL', 'http://supervisor/core')}/api/services/todo/{servizio}"
    if risposta:
        url += "?return_response"
    try:
        r = http_requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=dati, timeout=TIMEOUT)
    except http_requests.RequestException as e:
        raise ErroreHA(f"Home Assistant non raggiungibile ({e.__class__.__name__})") from None
    if r.status_code >= 400:
        raise ErroreHA(f"Home Assistant ha risposto {r.status_code}: {r.text[:160].strip()}")
    try:
        return r.json()
    except ValueError:
        return {}


def leggi_remoti(entity: str) -> dict:
    """{uid: {"summary", "status"}} di tutti gli elementi della lista."""
    ris = _chiama("get_items", {"entity_id": entity, "status": ["needs_action", "completed"]}, True)
    try:
        elementi = ris["service_response"][entity]["items"]
    except (KeyError, TypeError):
        raise ErroreHA("risposta inattesa da Home Assistant: l'entita' esiste ed e' una lista to-do?") from None
    return {e["uid"]: {"summary": e.get("summary") or "", "status": e.get("status") or "needs_action"}
            for e in elementi if e.get("uid")}


def aggiungi_remoto(entity: str, summary: str):
    _chiama("add_item", {"entity_id": entity, "item": summary})


def aggiorna_remoto(entity: str, uid: str, summary=None, status=None):
    dati = {"entity_id": entity, "item": uid}
    if summary is not None:
        dati["rename"] = summary
    if status is not None:
        dati["status"] = status
    _chiama("update_item", dati)


def rimuovi_remoto(entity: str, uid: str):
    _chiama("remove_item", {"entity_id": entity, "item": [uid]})


# ── Voci locali ──────────────────────────────────────────────────────────────

def riassunto(riga) -> str:
    """Testo mostrato nella lista remota: «Latte» oppure «Dentifricio ×2»."""
    q = riga["quantita"] or 1
    return riga["nome"] if q <= 1 else f"{riga['nome']} ×{q}"


def stato_di(riga) -> str:
    return "completed" if riga["completato"] else "needs_action"


def _leggi(testo: str):
    """Testo remoto → (nome, quantita, radici, valido)."""
    nome, q = estrai_quantita(testo)
    nome = bella(nome)
    tok = token_chiave(nome)
    return nome, q, tok, bool(nome and tok and any(c.isalpha() for c in nome))


def _riga(conn, voce_id):
    r = conn.execute("SELECT * FROM lista_spesa WHERE id=?", (voce_id,)).fetchone()
    return dict(r) if r else None


def _aggiorna_locale(conn, voce_id, nome=None, quantita=None, completato=None):
    campi, valori = ["aggiornato_il=?"], [sp.ora_utc()]
    if nome is not None:
        riga = _riga(conn, voce_id)
        campi += ["nome=?", "nome_norm=?", "reparto=?"]
        valori += [nome, " ".join(sorted(token_chiave(nome))), reparto_di(nome, riga["marca"] if riga else "")]
    if quantita is not None:
        campi.append("quantita=?")
        valori.append(max(1, min(int(quantita), 99)))
    if completato is not None:
        campi += ["completato=?", "completato_il=?"]
        valori += [1 if completato else 0, sp.ora_utc() if completato else None]
    with conn:
        conn.execute(f"UPDATE lista_spesa SET {', '.join(campi)} WHERE id=?", valori + [voce_id])


def _salva_mappa(conn, connettore, uid, voce_id, summary, status):
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO spesa_sync_map (connettore, uid_remoto, voce_id, summary_visto, status_visto, mancante) "
            "VALUES (?, ?, ?, ?, ?, 0)", (connettore, uid, voce_id, summary, status))


def _togli_mappa(conn, connettore, uid):
    with conn:
        conn.execute("DELETE FROM spesa_sync_map WHERE connettore=? AND uid_remoto=?", (connettore, uid))


# ── Un giro di sincronizzazione ──────────────────────────────────────────────

def sincronizza(connettore: str, entity: str, conn=None) -> dict:
    """Riallinea la lista locale e quella remota. Ritorna i conteggi di cio' che e' cambiato.
    Solleva ErroreHA se Home Assistant non risponde (in quel caso non cambia nulla in modo parziale
    oltre alle singole operazioni gia' completate e registrate in mappa)."""
    propria = conn is None
    if propria:
        conn = get_db()
    origine = CONNETTORI.get(connettore, (None, connettore))[1]
    st = {k: 0 for k in ("locali_aggiunte", "locali_aggiornate", "locali_rimosse",
                         "remote_aggiunte", "remote_aggiornate", "remote_rimosse", "ignorate")}
    scritture = [0]

    def scrivi_ok():
        scritture[0] += 1
        return scritture[0] <= MAX_SCRITTURE

    try:
        remoti = leggi_remoti(entity)
        sp.assicura_righe(conn)
        mappa = {r["uid_remoto"]: dict(r) for r in
                 conn.execute("SELECT * FROM spesa_sync_map WHERE connettore=?", (connettore,)).fetchall()}
        righe = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM lista_spesa").fetchall()}
        per_voce = {}
        for uid, m in mappa.items():
            per_voce.setdefault(m["voce_id"], uid)
        da_rimuovere = []      # uid remoti da togliere
        mancanti = []          # uid in mappa che non si vedono piu' in remoto

        # 1. elementi gia' collegati
        for uid, m in mappa.items():
            riga = righe.get(m["voce_id"])
            if per_voce.get(m["voce_id"]) != uid:          # secondo elemento remoto per la stessa voce: doppione
                if uid in remoti:
                    da_rimuovere.append(uid)
                else:
                    _togli_mappa(conn, connettore, uid)
                continue
            if uid not in remoti:
                if riga is None:                            # sparito da entrambe le parti
                    _togli_mappa(conn, connettore, uid)
                else:
                    mancanti.append(uid)
                continue
            if riga is None:                                # voce locale cancellata: via anche da remoto
                da_rimuovere.append(uid)
                continue
            r = remoti[uid]
            if m["mancante"]:
                with conn:
                    conn.execute("UPDATE spesa_sync_map SET mancante=0 WHERE connettore=? AND uid_remoto=?", (connettore, uid))
            snap = (m["summary_visto"], m["status_visto"])
            att_r = (r["summary"], r["status"])
            att_l = (riassunto(riga), stato_di(riga))
            if att_r == snap and att_l == snap:
                continue
            if att_l == snap:                               # e' cambiato solo il remoto
                nome, q, tok, valido = _leggi(r["summary"])
                if valido and any(a["id"] != riga["id"] and a["nome_norm"] == " ".join(sorted(tok)) for a in righe.values()):
                    valido = False                          # il nuovo nome coinciderebbe con un'altra voce: si tiene il locale
                _aggiorna_locale(conn, riga["id"], nome if valido else None, q if valido else None, r["status"] == "completed")
                st["locali_aggiornate"] += 1
            elif att_r == snap:                             # e' cambiato solo il locale
                pass
            else:                                           # cambiati entrambi: stato «fatto» se lo e' da una parte, resto dal locale
                if r["status"] == "completed" and not riga["completato"]:
                    _aggiorna_locale(conn, riga["id"], completato=True)
                    st["locali_aggiornate"] += 1
            riga = _riga(conn, riga["id"])
            righe[riga["id"]] = riga
            finale = (riassunto(riga), stato_di(riga))
            if finale != att_r and scrivi_ok():
                aggiorna_remoto(entity, uid,
                                summary=finale[0] if finale[0] != att_r[0] else None,
                                status=finale[1] if finale[1] != att_r[1] else None)
                st["remote_aggiornate"] += 1
            _salva_mappa(conn, connettore, uid, riga["id"], finale[0], finale[1])

        # voci remote sparite: si cancella la voce locale solo dopo GRACE_CICLI giri e mai in massa
        sospetto = len(mancanti) >= 4 and len(mancanti) > len(mappa) / 2
        for uid in mancanti:
            if sospetto:
                continue
            m = mappa[uid]
            if m["mancante"] + 1 >= GRACE_CICLI:
                with conn:
                    conn.execute("DELETE FROM lista_spesa WHERE id=?", (m["voce_id"],))
                righe.pop(m["voce_id"], None)
                per_voce.pop(m["voce_id"], None)
                _togli_mappa(conn, connettore, uid)
                st["locali_rimosse"] += 1
            else:
                with conn:
                    conn.execute("UPDATE spesa_sync_map SET mancante=mancante+1 WHERE connettore=? AND uid_remoto=?", (connettore, uid))
        if sospetto:
            logger.warning("Sync %s: %d elementi su %d non risultano in remoto, nessuna voce cancellata (lettura incompleta?)",
                           connettore, len(mancanti), len(mappa))

        # 2. elementi remoti nuovi (aggiunti dal telefono o gia' presenti alla prima attivazione)
        for uid, r in remoti.items():
            if uid in mappa:
                continue
            nome, q, tok, valido = _leggi(r["summary"])
            if not valido:
                st["ignorate"] += 1
                continue
            chiave = " ".join(sorted(tok))
            fatto = r["status"] == "completed"
            candidata = next((a for a in righe.values() if a["nome_norm"] == chiave), None)
            if candidata and candidata["id"] in per_voce:   # la voce e' gia' collegata a un altro elemento: questo e' un doppione
                da_rimuovere.append(uid)
                continue
            if candidata:                                   # stessa voce da entrambe le parti: si uniscono, senza cancellare
                nuovo_c = bool(candidata["completato"]) or fatto
                nuova_q = max(candidata["quantita"] or 1, q)
                if (nuovo_c, nuova_q) != (bool(candidata["completato"]), candidata["quantita"] or 1):
                    _aggiorna_locale(conn, candidata["id"], quantita=nuova_q, completato=nuovo_c)
                    st["locali_aggiornate"] += 1
                riga = _riga(conn, candidata["id"])
            else:
                try:
                    ris = sp.aggiungi_voce(conn, nome, q, "", "", origine, "")
                except ValueError:
                    st["ignorate"] += 1
                    continue
                if fatto:
                    _aggiorna_locale(conn, ris["id"], completato=True)
                riga = _riga(conn, ris["id"])
                st["locali_aggiunte"] += 1
            righe[riga["id"]] = riga
            per_voce[riga["id"]] = uid
            finale = (riassunto(riga), stato_di(riga))
            if finale != (r["summary"], r["status"]) and scrivi_ok():
                aggiorna_remoto(entity, uid,
                                summary=finale[0] if finale[0] != r["summary"] else None,
                                status=finale[1] if finale[1] != r["status"] else None)
                st["remote_aggiornate"] += 1
            _salva_mappa(conn, connettore, uid, riga["id"], finale[0], finale[1])

        # 3. voci locali non ancora in remoto
        pendenti = [a for a in righe.values() if a["id"] not in per_voce]
        spinte = []
        for riga in pendenti:
            if not scrivi_ok():
                break
            aggiungi_remoto(entity, riassunto(riga))
            st["remote_aggiunte"] += 1
            spinte.append(riga)
        if spinte:
            noti = set(remoti) | set(mappa)
            liberi = {u: x for u, x in leggi_remoti(entity).items() if u not in noti}
            for riga in spinte:
                testo = riassunto(riga)
                uid = next((u for u, x in liberi.items() if x["summary"] == testo), None)
                if uid is None:
                    continue                                # lo ritrovera' il giro dopo come elemento remoto nuovo
                del liberi[uid]
                stato = "needs_action"
                if riga["completato"] and scrivi_ok():
                    aggiorna_remoto(entity, uid, status="completed")
                    stato = "completed"
                _salva_mappa(conn, connettore, uid, riga["id"], testo, stato)

        # 4. elementi remoti da togliere (voci cancellate in locale, doppioni)
        for uid in da_rimuovere:
            if not scrivi_ok():
                break
            rimuovi_remoto(entity, uid)
            _togli_mappa(conn, connettore, uid)
            st["remote_rimosse"] += 1
        return st
    finally:
        if propria:
            conn.close()


# ── Stato, giri periodici, richieste di sincronizzazione ─────────────────────

def _ora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def esegui(connettore: str, entity: str) -> dict:
    """Un giro con registrazione dello stato (per il pannello Admin). Non solleva."""
    with _lock:
        s = _stato.setdefault(connettore, {})
        s["entity"] = entity
        t0 = time.time()
        try:
            st = sincronizza(connettore, entity)
            s.update(ok=True, errore=None, ultimo_ok=_ora_iso(), risultato=st, durata_ms=round((time.time() - t0) * 1000))
            if st["locali_aggiunte"] or st["locali_aggiornate"] or st["locali_rimosse"]:
                _sensori.set()
        except ErroreHA as e:
            if s.get("errore") != str(e):
                logger.warning("Sync %s (%s): %s", connettore, entity, e)
            s.update(ok=False, errore=str(e), ultimo_errore=_ora_iso())
        except Exception as e:      # un bug non deve fermare il thread
            logger.exception("Sync %s: errore interno", connettore)
            s.update(ok=False, errore=f"errore interno ({e.__class__.__name__})", ultimo_errore=_ora_iso())
        return dict(s)


def _aggiorna_sensori():
    try:
        from routes.products import aggiorna_sensori_ha
        aggiorna_sensori_ha()
    except Exception as e:
        logger.warning("Aggiornamento dei sensori dopo una modifica della lista non riuscito: %s", e)


def impostazioni(conn) -> dict:
    return {cid: get_setting(conn, chiave, "").strip() for cid, (chiave, _) in CONNETTORI.items()} | {
        "_attivo": get_setting(conn, "todo_sync_attivo", "1") == "1"}


def stato() -> dict:
    conn = get_db()
    try:
        imp = impostazioni(conn)
        mappate = {r["connettore"]: r["n"] for r in conn.execute(
            "SELECT connettore, COUNT(*) AS n FROM spesa_sync_map GROUP BY connettore").fetchall()}
    finally:
        conn.close()
    out = {}
    for cid in CONNETTORI:
        s = dict(_stato.get(cid, {}))
        s.update(entity=imp[cid], attivo=imp["_attivo"] and bool(imp[cid]), voci_collegate=mappate.get(cid, 0))
        out[cid] = s
    return out


def richiedi_sync():
    """Chiamata dopo ogni modifica della lista: il giro parte entro un paio di secondi."""
    _sensori.set()
    _evento.set()


def _giro_periodico():
    time.sleep(min(25, INTERVALLO))           # lascia finire l'avvio
    while True:
        errore = False
        try:
            conn = get_db()
            try:
                imp = impostazioni(conn)
            finally:
                conn.close()
            if imp["_attivo"]:
                for cid in CONNETTORI:
                    if imp[cid]:
                        errore |= not esegui(cid, imp[cid]).get("ok")
        except Exception:
            logger.exception("Sync: errore nel giro periodico")
            errore = True
        _evento.wait(INTERVALLO_ERRORE if errore else INTERVALLO)
        if _evento.is_set():
            time.sleep(1.5)      # raggruppa piu' modifiche ravvicinate in un solo giro
        _evento.clear()
        if _sensori.is_set():
            _sensori.clear()
            _aggiorna_sensori()


def avvia_thread():
    threading.Thread(target=_giro_periodico, daemon=True, name="sync-todo").start()
