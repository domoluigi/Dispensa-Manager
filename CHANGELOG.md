# Changelog — Dispensa Manager

Tutte le modifiche rilevanti al progetto sono documentate in questo file.
Il formato segue [Keep a Changelog](https://keepachangelog.com/it/1.0.0/).

---

## [1.4.0] — 2026-04-14

### Aggiunto
- **Foto prodotto per barcode non trovato**: quando la scansione non trova il prodotto su Open Food Facts, nella schermata di conferma appare una nuova sezione 📷 per scattare o scegliere una foto dalla galleria. La foto viene ridimensionata automaticamente (max 600px, JPEG 82%) e salvata nel database come immagine del prodotto.
- **Sezione Esauriti separata**: i prodotti con quantità = 0 non vengono più mescolati all'inventario principale. Appaiono in una sezione collassabile "Esauriti" in fondo alla lista, con pallino grigio, nessuna scadenza mostrata e un tasto `+` per rifornire rapidamente.
- **Nuovo endpoint** `GET /api/prodotti/esauriti` per recupero separato dei prodotti esauriti.

### Modificato
- Il contatore **"Totale"** nella dashboard esclude ora i prodotti esauriti (conteggia solo `quantita > 0`).
- Il sensore HA `sensor.dispensa_totale_prodotti` riflette lo stesso criterio (solo prodotti attivi).
- Il sensore HA `sensor.dispensa_esauriti` include la lista completa dei prodotti a zero.
- Le **Statistiche** per posizione (`per_posizione`) contano solo prodotti con `quantita > 0`.
- Il report Telegram mattutino mostra separatamente attivi e esauriti con contatori distinti.

---

## [1.3.3] — 2026-03-01

### Modificato
- `pwa_url` accetta solo la base URL; il path `/local/dispensa/index.html` viene aggiunto automaticamente da `app.py`.

---

## [1.3.2] — 2026-02-20

### Aggiunto
- Opzione `pwa_url` nelle opzioni addon per configurare l'URL della PWA senza esporre il path nel sorgente GitHub.

---

## [1.3.1] — 2026-02-10

### Corretto
- Fix ingress HA: aggiunta route `/` in Flask (prima restituiva 404 al click su "Apri interfaccia utente web").

---

## [1.3.0] — 2026-02-01

### Aggiunto
- Opzione `cloudflare_token` nelle opzioni addon.
- Endpoint `/api/config` esposto via ingress per auto-fetch del token nella PWA.
- Il token non è più nel sorgente PWA su GitHub.

---

## [1.2.1] — 2026-01-20

### Corretto
- Fix CORS: aggiunto `x-jarvis-token` in `Access-Control-Allow-Headers`.

---

## [1.2.0] — 2026-01-10

### Aggiunto
- Ingress HA abilitato (`ingress: true`, `ingress_port: 5000`).

---

## [1.1.0] — 2025-12-15

### Aggiunto
- Endpoint `/api/prodotti/by-ean` per rilevare duplicati.
- Endpoint `/api/alerts` per notifiche giornaliere via automazione HA.
- Endpoint `/api/export-csv` per esportazione inventario.

---

## [1.0.2] — 2025-12-01

### Prima versione pubblica
- Backend Flask con SQLite: gestione prodotti, lista spesa, storico movimenti.
- Ricerca barcode su Open Food Facts, OpenProductsFacts, OpenBeautyFacts.
- Cache locale barcode.
- Notifiche Telegram per aggiunte, modifiche, eliminazioni, scadenze.
- PWA installabile (manifest, service worker, icone).
- Scanner barcode con ZXing.
- OCR scadenze con Tesseract.js.
- Sensori HA: totale prodotti, in scadenza, esauriti.
- Automazioni HA: sync avvio, report mattutino, alert Alexa.
