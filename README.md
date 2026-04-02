# 🛒 Dispensa Manager — Home Assistant Add-on

Un add-on per **Home Assistant OS** che trasforma il tuo smartphone in uno scanner di barcode per gestire la dispensa di casa. Integra notifiche Telegram, lista della spesa automatica, valori nutrizionali e statistiche sui consumi.

---

## ✨ Funzionalità

- 📱 **PWA iPhone/Android** — installabile come app, funziona offline
- 📦 **Scanner barcode** — scansiona i prodotti con la fotocamera (ZXing)
- 🗄️ **Posizione automatica** — Frigo 🧊 / Dispensa 🗄️ / Freezer ❄️ suggeriti dalla categoria
- 📅 **Scadenza suggerita** — calcolata automaticamente dalla categoria del prodotto
- 📊 **Valori nutrizionali** — da Open Food Facts (energia, grassi, carboidrati, ecc.)
- 🏷️ **Nutri-Score** — visualizzato nel dettaglio prodotto
- 🗃️ **Cache locale** — i prodotti non trovati online vengono salvati per le scansioni future
- 🔍 **Multi-database** — Open Food Facts + Open Products Facts + Open Beauty Facts
- 🏠 **Sensori Home Assistant** — 3 sensori aggiornati in tempo reale
- 📲 **Notifiche Telegram** — su scadenza, esaurimento scorte, aggiornamenti
- 🛒 **Lista della spesa** — automatica quando un prodotto si esaurisce
- 📈 **Statistiche consumi** — prodotti più acquistati, consumati, per posizione
- 🔔 **Alexa** — annunci vocali tramite Alexa Media Player
- ⏰ **Automazioni HA** — report mattutino, sync all'avvio

---

## 📋 Requisiti

- Home Assistant OS o Supervised
- Add-on **File Editor** o **Studio Code Server** (per copiare i file)
- Bot Telegram (opzionale, per le notifiche)
- Alexa Media Player (opzionale, per gli annunci vocali)

---

## 🚀 Installazione

### 1. Copia l'add-on

Copia la cartella `dispensa_manager/` in `/addons/dispensa_manager/` sul tuo Home Assistant.

### 2. Installa l'add-on

Vai in **Impostazioni** → **Add-on** → **Add-on Store** → ⋮ → **Controlla aggiornamenti** → cerca **Dispensa Manager** → **Installa**.

### 3. Copia la PWA

Copia la cartella `www/dispensa/` in `/config/www/dispensa/` sul tuo Home Assistant.

### 4. Configura l'add-on

Vai nella scheda **Configurazione** dell'add-on e compila:

```yaml
telegram_token: "IL_TUO_BOT_TOKEN"       # opzionale
telegram_chat_id: "IL_TUO_CHAT_ID"       # opzionale, supporta più ID separati da virgola
giorni_alert_scadenza: 3                  # giorni prima della scadenza per l'alert
soglia_scorte_minime: 1                   # quantità minima prima di aggiungere alla lista spesa
```

### 5. Avvia l'add-on

Clicca **Avvia** e verifica i log.

### 6. Accedi alla PWA

Apri nel browser:
```
http://IP_HOME_ASSISTANT:8123/local/dispensa/index.html
```

Su iPhone puoi installarla come app: **Condividi** → **Aggiungi a schermata Home**.

---

## 🏠 Integrazione Home Assistant

### Sensori creati automaticamente

| Entità | Descrizione |
|--------|-------------|
| `sensor.dispensa_totale_prodotti` | Numero totale di prodotti |
| `sensor.dispensa_in_scadenza` | Prodotti in scadenza entro N giorni |
| `sensor.dispensa_esauriti` | Prodotti con quantità zero |

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

### Automazioni consigliate

**Sync all'avvio di HA:**
```yaml
alias: 🔄 Sync Dispensa all'avvio
trigger:
  - platform: homeassistant
    event: start
action:
  - delay:
      seconds: 30
  - action: rest_command.sync_dispensa
mode: single
```

**Report mattutino:**
```yaml
alias: 🌅 Report dispensa mattutino
trigger:
  - platform: time
    at: "08:00:00"
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
        in scadenza in dispensa.
      data:
        type: announce
mode: single
```

---

## 🌐 API Endpoints

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/api/prodotti` | Lista tutti i prodotti |
| POST | `/api/prodotti` | Aggiunge un prodotto |
| PUT | `/api/prodotti/<id>` | Aggiorna un prodotto |
| DELETE | `/api/prodotti/<id>` | Elimina un prodotto |
| GET | `/api/barcode/<ean>` | Cerca un prodotto per EAN |
| POST | `/api/barcode-cache` | Salva in cache locale |
| DELETE | `/api/barcode-cache/<ean>` | Rimuove dalla cache |
| GET | `/api/lista-spesa` | Lista della spesa |
| POST | `/api/lista-spesa` | Aggiunge alla lista spesa |
| GET | `/api/lista-spesa/invia-telegram` | Invia lista su Telegram |
| GET | `/api/statistiche` | Statistiche consumi |
| GET | `/api/report` | Report completo su Telegram |
| GET | `/api/sync-ha` | Aggiorna sensori HA |
| GET | `/api/test-telegram` | Test notifiche Telegram |
| GET | `/api/health` | Stato del servizio |

---

## 📱 Screenshot

*Coming soon*

---

## 🔧 Struttura del progetto

```
dispensa_manager/
├── dispensa_manager/       # Add-on HAOS
│   ├── Dockerfile
│   ├── config.yaml
│   ├── app.py              # Backend Flask
│   └── requirements.txt
└── www/
    └── dispensa/
        └── index.html      # PWA frontend
```

---

## 🤝 Contribuire

Pull request e issue sono benvenute! Se hai miglioramenti o nuove funzionalità da proporre, apri una issue o una PR.

---

## 📄 Licenza

MIT License — vedi [LICENSE](LICENSE) per i dettagli.

---

## 👤 Autore

Creato da **Bart** ([@elbarto8383](https://github.com/elbarto8383))

Sviluppato con ❤️ per la community di Home Assistant Italia.
