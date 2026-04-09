# 🛒 Dispensa Manager — Home Assistant Add-on

[![Version](https://img.shields.io/badge/version-1.3.2-green)](https://github.com/domoluigi/Dispensa-Manager/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![HA](https://img.shields.io/badge/Home%20Assistant-Add--on-blue)](https://www.home-assistant.io/)

Un add-on per **Home Assistant OS** che trasforma il tuo smartphone in uno scanner di barcode per gestire la dispensa di casa. Integra notifiche Telegram, lista della spesa automatica, valori nutrizionali, statistiche sui consumi e integrazione con Alexa.

---

## ✨ Funzionalità

- 📱 **PWA iPhone/Android** — installabile come app, funziona offline
- 📦 **Scanner barcode** — scansiona i prodotti con la fotocamera (ZXing)
- 🗄️ **Posizione automatica** — Frigo 🧊 / Dispensa 🗄️ / Freezer ❄️ suggeriti dalla categoria
- 📅 **Scadenza suggerita** — calcolata automaticamente dalla categoria del prodotto
- 🔍 **OCR scadenza** — scansiona la data di scadenza con la fotocamera (Tesseract.js), supporta DD/MM/YYYY, MM/YYYY e mesi in italiano
- 📊 **Valori nutrizionali** — da Open Food Facts (energia, grassi, carboidrati, ecc.)
- 🏷️ **Nutri-Score** — visualizzato nel dettaglio prodotto
- 🗃️ **Cache locale** — i prodotti non trovati online vengono salvati per le scansioni future
- 🔍 **Multi-database** — Open Food Facts + Open Products Facts + Open Beauty Facts
- 🏠 **Sensori Home Assistant** — 3 sensori aggiornati in tempo reale
- 📲 **Notifiche Telegram** — su scadenza, esaurimento scorte, aggiornamenti
- 🛒 **Lista della spesa** — automatica quando un prodotto si esaurisce, con invio Telegram
- 📈 **Statistiche consumi** — prodotti più acquistati, consumati, per posizione
- 🔔 **Alexa** — annunci vocali tramite Alexa Media Player
- ⏰ **Automazioni HA** — report mattutino, sync all'avvio
- 🔗 **API REST completa** — per integrazioni personalizzate
- ↩️ **Pulsante Annulla** — annulla l'ultima modifica di quantità entro 4 secondi
- 🌐 **Accesso esterno sicuro** — supporto Cloudflare Tunnel con autenticazione header

---

## 📋 Requisiti

- Home Assistant OS o Supervised
- Add-on **File Editor** o **Studio Code Server** (per copiare i file PWA)
- Bot Telegram (opzionale, per le notifiche)
- Alexa Media Player (opzionale, per gli annunci vocali)

---

## 🚀 Installazione

### 1. Aggiungi il repository custom

Vai in HA → **Impostazioni** → **Add-on** → **Add-on Store** → ⋮ → **Repository** → incolla:

```
https://github.com/domoluigi/Dispensa-Manager
```

Clicca **Aggiungi** → **Chiudi**.

### 2. Installa l'add-on

Cerca **Dispensa Manager** nell'Add-on Store → **Installa**.

### 3. Copia la PWA

Copia la cartella `www/dispensa/` in `/config/www/dispensa/` sul tuo Home Assistant.

### 4. Configura l'add-on

Vai nella scheda **Configurazione** dell'add-on e compila:

```yaml
telegram_token: "IL_TUO_BOT_TOKEN"       # opzionale
telegram_chat_id: "IL_TUO_CHAT_ID"       # opzionale, supporta più ID separati da virgola
giorni_alert_scadenza: 3                  # giorni prima della scadenza per l'alert
soglia_scorte_minime: 1                   # quantità minima prima di aggiungere alla lista spesa
cloudflare_token: ""                      # opzionale, vedi sezione Cloudflare
pwa_url: "http://IP_HOME_ASSISTANT:8123/local/dispensa/index.html"  # opzionale, vedi sotto
```

> **Nota:** `telegram_chat_id` supporta più ID separati da virgola es. `123456,789012`

> **Nota:** `pwa_url` è l'indirizzo della tua PWA. Se configurato, il pulsante **"Apri interfaccia utente web"** nell'add-on aprirà direttamente la PWA. Usa l'indirizzo locale o il tuo dominio esterno (es. Cloudflare). Non viene mai incluso nel codice sorgente per preservare la privacy.

### 5. Avvia l'add-on

Clicca **Avvia** e verifica i log.

### 6. Accedi alla PWA

**Opzione A — dal pannello HA:**
Configura `pwa_url` nelle opzioni dell'add-on (passaggio 4), poi clicca **"Apri interfaccia utente web"** nella pagina dell'add-on.

**Opzione B — direttamente dal browser:**
```
http://IP_HOME_ASSISTANT:8123/local/dispensa/index.html
```

Su iPhone puoi installarla come app: **Condividi** → **Aggiungi a schermata Home**.
Su Android: Chrome → menu ⋮ → **Installa app**.

---

## 🌐 Accesso Esterno con Cloudflare Tunnel

Se esponi Home Assistant su internet tramite **Cloudflare Tunnel**, puoi rendere il backend accessibile in HTTPS in modo sicuro senza aprire porte aggiuntive.

### Architettura

```
Telefono (HTTPS)
    ↓
Cloudflare Tunnel
    ├── tuodominio.it → HA :8123  (dashboard)
    └── dispensa-api.tuodominio.it → HA :5000  (backend Flask)
```

### 1. Aggiungi un hostname nel tunnel

Nel dashboard Cloudflare → **Zero Trust** → **Networks** → **Tunnels** → seleziona il tuo tunnel → **Public Hostnames** → **Add a public hostname**:

| Campo | Valore |
|---|---|
| Subdomain | `dispensa-api` |
| Domain | `tuodominio.it` |
| Service Type | `HTTP` |
| URL | `192.168.1.X:5000` |

### 2. Configura le WAF Custom Rules

Crea due regole in **Security** → **WAF** → **Custom Rules**:

**Regola 1 — Skip antibot per richieste autenticate** (azione: Skip, priorità: First)
```
(http.request.uri.path contains "/api/") and
(http.request.headers["x-jarvis-token"][0] eq "IL_TUO_TOKEN_SEGRETO")
```

**Regola 2 — Blocca accesso non autenticato al backend** (azione: Block, priorità: Last)
```
(http.host eq "dispensa-api.tuodominio.it") and
not (http.request.headers["x-jarvis-token"][0] eq "IL_TUO_TOKEN_SEGRETO") and
not (http.request.method eq "OPTIONS")
```

> La regola 2 deve essere **Last** — la regola 1 scatta prima per le richieste autenticate; i preflight CORS (`OPTIONS`) passano sempre perché necessari al browser.

### 3. Configura l'add-on

Nelle opzioni dell'add-on inserisci il token scelto:
```yaml
cloudflare_token: "IL_TUO_TOKEN_SEGRETO"
```

### 4. Configura la PWA

Apri la PWA → **Impostazioni** → imposta:

- **URL backend**: `https://dispensa-api.tuodominio.it`
- **Token Cloudflare**: il token scelto nel passaggio precedente

Il token viene salvato in localStorage e aggiunto automaticamente a ogni chiamata API tramite l'header `x-jarvis-token`.

### 5. Installa come app

Con l'accesso HTTPS il service worker si attiva correttamente e la PWA è installabile come app nativa:
- **Android**: Chrome → menu ⋮ → **Installa app**
- **iPhone**: Safari → Condividi → **Aggiungi a schermata Home**

---

## ↩️ Pulsante Annulla

Quando modifichi la quantità di un prodotto tramite i pulsanti rapidi **+** / **−** (sia nella lista che nel dettaglio prodotto), appare in basso un toast con il pulsante **Annulla**:

- Il toast rimane visibile per **4 secondi**
- Se clicchi **Annulla** entro 4 secondi, la quantità torna al valore precedente
- Dopo 4 secondi il pulsante scompare e la modifica è definitiva

---

## 📱 PWA — Schermate

La PWA è composta da 5 sezioni accessibili dalla barra in basso:

| Schermata | Descrizione |
|-----------|-------------|
| 🏠 **Dispensa** | Lista prodotti con metriche (totale, in scadenza, esauriti) |
| 📷 **Scansiona** | Scanner barcode con ricerca automatica su Open Food Facts |
| 🛒 **Spesa** | Lista della spesa con spunta e invio Telegram |
| 📊 **Statistiche** | Consumi, acquisti, top prodotti, prodotti per posizione |
| ⚙️ **Impostazioni** | URL backend, token Cloudflare, alert scadenza, tema scuro |

---

## 🏠 Integrazione Home Assistant

### Sensori creati automaticamente

| Entità | Descrizione |
|--------|-------------|
| `sensor.dispensa_totale_prodotti` | Numero totale di prodotti |
| `sensor.dispensa_in_scadenza` | Prodotti in scadenza entro N giorni |
| `sensor.dispensa_esauriti` | Prodotti con quantità zero |

### configuration.yaml

```yaml
rest_command:
  report_dispensa:
    url: http://localhost:5000/api/report
    method: GET
  sync_dispensa:
    url: http://localhost:5000/api/sync-ha
    method: GET
  lista_spesa_telegram:
    url: http://localhost:5000/api/lista-spesa/invia-telegram
    method: GET
```

### Card dashboard

```yaml
type: entities
title: 🛒 Dispensa
entities:
  - entity: sensor.dispensa_totale_prodotti
    name: Prodotti totali
    icon: mdi:package-variant
  - entity: sensor.dispensa_in_scadenza
    name: In scadenza
    icon: mdi:calendar-alert
  - entity: sensor.dispensa_esauriti
    name: Esauriti
    icon: mdi:package-variant-remove
  - entity: script.report_dispensa
  - type: button
    name: 🛒 Invia Lista Spesa
    icon: mdi:cart
    tap_action:
      action: perform-action
      perform_action: rest_command.lista_spesa_telegram
```

### Card iframe PWA nella dashboard

```yaml
type: iframe
url: http://IP_HOME_ASSISTANT:8123/local/dispensa/index.html
aspect_ratio: 75%
title: 📦 Lista Prodotti Dispensa
```

---

## ⚙️ Automazioni consigliate

**Sync sensori all'avvio di HA:**
```yaml
alias: 🔄 Sync Dispensa all'avvio
description: Aggiorna i sensori della dispensa quando HA si avvia
trigger:
  - platform: homeassistant
    event: start
condition: []
action:
  - delay:
      seconds: 30
  - action: rest_command.sync_dispensa
mode: single
```

**Report mattutino su Telegram:**
```yaml
alias: 🌅 Report dispensa mattutino
description: Ogni mattina alle 8 invia il report dispensa su Telegram
trigger:
  - platform: time
    at: "08:00:00"
condition: []
action:
  - action: rest_command.report_dispensa
mode: single
```

**Alexa — avvisa prodotti in scadenza:**
```yaml
alias: 🔔 Alexa avvisa prodotti in scadenza
trigger:
  - platform: time
    at: "08:30:00"
condition:
  - condition: numeric_state
    entity_id: sensor.dispensa_in_scadenza
    above: 0
action:
  - action: notify.alexa_media_NOME_DISPOSITIVO
    data:
      message: >
        Attenzione! Hai {{ states('sensor.dispensa_in_scadenza') }} prodotti
        in scadenza in dispensa. Controlla l'app Dispensa per i dettagli.
      data:
        type: announce
mode: single
```

**Alexa — avvisa prodotti esauriti:**
```yaml
alias: 🔔 Alexa avvisa prodotti esauriti
trigger:
  - platform: numeric_state
    entity_id: sensor.dispensa_esauriti
    above: 0
condition: []
action:
  - action: notify.alexa_media_NOME_DISPOSITIVO
    data:
      message: >
        Attenzione! Hai {{ states('sensor.dispensa_esauriti') }} prodotti
        esauriti in dispensa. Ricordati di aggiungerli alla lista della spesa!
      data:
        type: announce
mode: single
```

---

## 🛒 Lista della Spesa

La lista della spesa è gestita automaticamente:

- Quando un prodotto scende a **quantità 0** viene aggiunto automaticamente alla lista
- Puoi aggiungere prodotti **manualmente** dalla schermata Spesa nella PWA
- **Spunta** gli articoli mentre sei al supermercato
- **Invia su Telegram** la lista prima di uscire
- **Rimuovi completati** per pulire la lista

---

## 📈 Statistiche

La schermata Statistiche mostra:

- **Acquisti totali** — numero di prodotti acquistati nel tempo
- **Consumi totali** — numero di prodotti consumati
- **Acquisti questo mese** — acquisti nel mese corrente
- **Prodotti per posizione** — quanti prodotti in Frigo, Dispensa, Freezer
- **Top 5 più acquistati** — prodotti acquistati più frequentemente
- **Top 5 più consumati** — prodotti consumati più frequentemente

> Le statistiche si accumulano automaticamente ad ogni aggiunta, consumo o eliminazione prodotto.

---

## 🌐 API Endpoints

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/api/prodotti` | Lista tutti i prodotti |
| POST | `/api/prodotti` | Aggiunge un prodotto |
| PUT | `/api/prodotti/<id>` | Aggiorna un prodotto |
| DELETE | `/api/prodotti/<id>` | Elimina un prodotto |
| GET | `/api/prodotti/by-ean/<ean>` | Cerca prodotti duplicati per EAN |
| GET | `/api/barcode/<ean>` | Cerca un prodotto per EAN |
| POST | `/api/barcode-cache` | Salva in cache locale |
| DELETE | `/api/barcode-cache/<ean>` | Rimuove dalla cache |
| GET | `/api/lista-spesa` | Lista della spesa |
| POST | `/api/lista-spesa` | Aggiunge alla lista spesa |
| PUT | `/api/lista-spesa/<id>` | Aggiorna elemento lista spesa |
| DELETE | `/api/lista-spesa/<id>` | Elimina elemento lista spesa |
| DELETE | `/api/lista-spesa/svuota-completati` | Rimuove completati |
| GET | `/api/lista-spesa/invia-telegram` | Invia lista su Telegram |
| GET | `/api/statistiche` | Statistiche consumi |
| GET | `/api/report` | Report completo su Telegram |
| GET | `/api/alerts` | Invia alert scadenze/esauriti su Telegram |
| GET | `/api/export-csv` | Scarica inventario in formato CSV |
| GET | `/api/sync-ha` | Aggiorna sensori HA |
| GET | `/api/config` | Configurazione pubblica (token CF) via ingress |
| GET | `/api/test-telegram` | Test notifiche Telegram |
| GET | `/api/health` | Stato del servizio |

---

## 🗄️ Database

L'add-on utilizza SQLite con le seguenti tabelle:

| Tabella | Descrizione |
|---------|-------------|
| `prodotti` | Inventario prodotti con EAN, nutriments, posizione, scadenza |
| `barcode_cache` | Cache locale per prodotti non trovati online |
| `lista_spesa` | Lista della spesa con stato completato |
| `storico_movimenti` | Log acquisti, consumi ed eliminazioni per le statistiche |

---

## 🔧 Struttura del progetto

```
Dispensa-Manager/
├── dispensa_manager/       # Add-on HAOS
│   ├── Dockerfile
│   ├── config.yaml
│   ├── app.py              # Backend Flask
│   └── requirements.txt
├── www/
│   └── dispensa/
│       ├── index.html      # PWA frontend
│       ├── sw.js           # Service Worker (offline + cache)
│       ├── manifest.json   # Web App Manifest (installazione PWA)
│       ├── icon-192.png    # Icona app 192×192
│       └── icon-512.png    # Icona app 512×512
├── repository.json         # Custom store HA
├── .gitignore
└── README.md
```

---

## 🔍 OCR Scadenza

Dalla schermata di conferma prodotto, accanto al campo data di scadenza è presente il pulsante 📷:

1. Clicca 📷 — si apre la fotocamera con una cornice verde
2. Inquadra la data di scadenza stampata sulla confezione
3. Clicca **📸 Scatta** — Tesseract.js analizza il testo
4. Se riconosce la data la compila automaticamente nel campo

**Formati riconosciuti:**
- `DD/MM/YYYY`, `DD-MM-YYYY`, `DD.MM.YYYY`
- `MM/YYYY` → imposta automaticamente l'ultimo giorno del mese (es. `07/2026` → `31/07/2026`)
- Mesi in italiano: `GEN 2026`, `GENNAIO 2026`, ecc.

> **Nota:** La prima volta Tesseract.js scarica il modello OCR (~5MB). Le volte successive è immediato. Funziona meglio su testi stampati chiari e con buona illuminazione.

---

## 📋 Changelog

### v1.3.2
- 🔗 Opzione `pwa_url` nelle configurazioni addon — il pulsante "Apri interfaccia utente web" apre la PWA direttamente dal pannello HA
- 🔒 L'URL della PWA rimane locale e non è mai incluso nel codice sorgente

### v1.3.1
- 🛠️ Fix ingress HA: aggiunta route `/` nel backend Flask (prima restituiva 404)

### v1.3.0
- 🌐 Token Cloudflare configurabile nelle opzioni addon (non più nel sorgente)
- 🔒 Endpoint `/api/config` per recupero automatico token via ingress HA
- ⚙️ Campo Token Cloudflare nelle impostazioni PWA
- 🔧 CORS: aggiunto `x-jarvis-token` negli header permessi

### v1.2.0
- 🚇 Ingress HA abilitato (accesso HTTPS nativo senza configurazione extra)
- 🏠 Icona panel HA `mdi:fridge-outline`

### v1.1.0
- 🔍 Endpoint `/api/prodotti/by-ean/<ean>` per rilevare duplicati
- 🔔 Endpoint `/api/alerts` — alert dettagliati su Telegram (scadenze ed esauriti)
- 📥 Endpoint `/api/export-csv` — esporta inventario in CSV

### v1.0.2
- 🔍 OCR scadenza automatica con fotocamera (Tesseract.js)
- 📅 Supporto formato MM/YYYY → ultimo giorno del mese automatico
- 🗓️ Riconoscimento mesi in italiano (GEN, FEB, MAR, ecc.)

### v1.0.1
- 📊 Statistiche consumi (acquisti, consumi, top prodotti, per posizione)
- 🛒 Lista della spesa automatica con invio Telegram
- 🍽️ Valori nutrizionali e Nutri-Score da Open Food Facts
- 🗃️ Cache barcode locale per prodotti non trovati online
- 🔔 Integrazione Alexa Media Player per annunci vocali
- 📍 Posizione automatica (Frigo/Dispensa/Freezer) dalla categoria
- 📅 Scadenza suggerita automaticamente dalla categoria
- 🔍 Multi-database (Food + Products + Beauty Facts)
- 🏷️ Supporto più chat ID Telegram separati da virgola
- 🗑️ Endpoint pulizia cache barcode

### v1.0.0
- 🎉 Release iniziale
- Scanner barcode con ZXing
- Integrazione Open Food Facts
- Sensori Home Assistant
- Notifiche Telegram base

---

## 🤝 Contribuire

Pull request e issue sono benvenute! Se hai miglioramenti o nuove funzionalità da proporre, apri una issue o una PR.

---

## 📄 Licenza

MIT License — vedi [LICENSE](LICENSE) per i dettagli.

---

## 👤 Autore

Creato da **Luigi** ([@domoluigi](https://github.com/domoluigi))

Sviluppato con ❤️ per la community di Home Assistant Italia.
