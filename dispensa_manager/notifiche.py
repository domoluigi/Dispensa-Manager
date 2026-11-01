"""Invio messaggi Telegram (v2.1.0).

- il token non finisce mai nei log: le eccezioni di `requests` includono l'URL
  con /bot<TOKEN>, quindi ogni errore passa da `redact()`;
- i nomi dei prodotti vanno nel Markdown di Telegram con `md_esc()`: un `_` o un `*`
  nel nome (capita con i dati di Open Food Facts) faceva rifiutare tutto il messaggio;
- se Telegram rifiuta comunque il Markdown, si riprova una volta in testo semplice.
"""
import logging
import re

import requests as http_requests

from database import get_db, get_setting, get_ha_option

logger = logging.getLogger(__name__)

# Telegram limita i messaggi a 4096 caratteri
TELEGRAM_MAX_LEN = 4000

_MD_SPECIALI = re.compile(r"([_*`\[])")
_TOKEN_NEL_TESTO = re.compile(r"bot\d+:[A-Za-z0-9_-]+")


def md_esc(testo) -> str:
    """Rende sicuro un testo variabile dentro un messaggio Markdown (legacy) di Telegram."""
    return _MD_SPECIALI.sub(r"\\\1", "" if testo is None else str(testo))


def redact(testo, token: str = "") -> str:
    """Toglie il token da un messaggio d'errore prima di scriverlo nel log."""
    s = str(testo)
    if token:
        s = s.replace(token, "<token>")
    return _TOKEN_NEL_TESTO.sub("bot<token>", s)


def chat_ids() -> list:
    raw = get_ha_option("telegram_chat_id", "")
    return [c.strip() for c in str(raw).split(",") if c.strip()]


def invia_a_chat(token: str, cid: str, testo: str) -> dict:
    """Invia a una chat. Ritorna {"ok": bool, "http_status": int|None, "errore": str|None}."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = http_requests.post(url, json={"chat_id": cid, "text": testo, "parse_mode": "Markdown"}, timeout=10)
        if r.status_code == 400 and "parse entities" in r.text:
            logger.warning("Telegram chat %s: Markdown rifiutato, riprovo in testo semplice", cid)
            r = http_requests.post(url, json={"chat_id": cid, "text": testo}, timeout=10)
        if r.status_code != 200:
            logger.error("Telegram chat %s respinto (HTTP %d): %s", cid, r.status_code, redact(r.text[:300], token))
            return {"ok": False, "http_status": r.status_code, "errore": None}
        return {"ok": True, "http_status": 200, "errore": None}
    except Exception as e:
        msg = redact(e, token)
        logger.error("Errore Telegram %s: %s", cid, msg)
        return {"ok": False, "http_status": None, "errore": msg}


def invia_telegram(testo, categoria=None):
    """categoria opzionale ('acquisto', 'modifica', 'eliminazione') → check setting notif_telegram_<categoria>"""
    token = get_ha_option("telegram_token", "")
    chat_id_raw = get_ha_option("telegram_chat_id", "")
    if not token or not chat_id_raw:
        logger.warning("Telegram non configurato (token o chat_id mancanti nelle opzioni HA)")
        return
    if categoria:
        conn = get_db()
        try:
            if get_setting(conn, f"notif_telegram_{categoria}", "1") != "1":
                logger.info("Notifica Telegram '%s' disabilitata da settings", categoria)
                return
        finally:
            conn.close()
    if len(testo) > TELEGRAM_MAX_LEN:
        logger.warning("Messaggio Telegram troppo lungo (%d char) — troncato a %d", len(testo), TELEGRAM_MAX_LEN)
        testo = testo[:TELEGRAM_MAX_LEN - 60] + "\n\n_…messaggio troncato, apri l'app per il dettaglio_"
    for cid in chat_ids():
        esito = invia_a_chat(token, cid, testo)
        if esito["ok"]:
            logger.info("Telegram chat %s OK (%d char, cat=%s)", cid, len(testo), categoria or "default")
