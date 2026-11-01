# Changelog — Dispensa Manager

Tutte le modifiche rilevanti al progetto sono documentate in questo file.
Il formato segue [Keep a Changelog](https://keepachangelog.com/it/1.0.0/).

---

## [2.1.1] — 2026-11-01

### Ban IP con scadenza
- **Il ban automatico finisce da solo.** Prima, dopo i tentativi di login falliti, l'IP restava bannato per sempre: bastava un errore di digitazione di troppo e solo un amministratore poteva sbloccarlo. Ora il ban dura `ban_durata_minuti` (default **60**; **0** = permanente) e alla prima richiesta dopo la scadenza l'IP viene sbloccato e i suoi vecchi tentativi azzerati, cosi' non viene ribannato al primo errore.
- La durata si cambia dal pannello Admin (Impostazioni), insieme a tentativi massimi e finestra.
- Il pannello **Ban IP** mostra quando ogni ban si sblocca da solo oppure «Permanente»; i ban scaduti non compaiono. Corretto anche l'orario mostrato, che era sfalsato di 1-2 ore (le date del database sono UTC).
- Il ban manuale resta permanente; l'API accetta `minuti` per un ban a tempo (`POST /api/admin/ip-bans`).
- **Migrazione schema 7**: aggiunge `ip_bans.scade_il`. I ban gia' presenti restano permanenti.

### Immagini nel backup
- Il backup JSON (download, backup automatico settimanale e copie ruotate) ora include le **foto dei prodotti** in base64 (`immagini`), quelle salvate in `/dispensa-images/`. Il ripristino le riscrive su disco: dopo un disastro i prodotti non restano piu' senza foto. Le immagini mancanti su disco vengono saltate senza interrompere il backup.
- Il ripristino controlla ogni immagine del file caricato: nome `<id>.jpg|png|webp` (niente percorsi), firma del file coerente con l'estensione, base64 valido, massimo 5 MB; le altre vengono scartate e contate («immagini scartate»).
- I backup della 2.1.0 e precedenti, senza immagini, si ripristinano come prima. Il formato resta `dispensa-manager-backup-v1`.
- Il file cresce di circa 60-100 KB per prodotto con foto: con qualche centinaio di foto sono pochi MB.

### Icona
- **Icona dell'add-on** (`icon.png`, 128x128) per lo store e il pannello di Home Assistant: barattolo con etichetta a barre e orologio della scadenza.

### Test
- `tests/test_ban_immagini.py`: 13 test (scadenza e fine del ban, ban permanente, validazione, migrazione da schema 6, backup e ripristino delle immagini, file pericolosi). In totale 33 test Python.

---

## [2.1.0] — 2026-11-01

### Scansione barcode
- **Checksum e doppia lettura**: un codice vale solo se e' un EAN-13/8, UPC-A o UPC-E valido (checksum corretto) e viene letto due volte di fila. Prima il primo Code128 qualsiasi, anche un lotto, veniva preso per un EAN.
- **Fotocamera**: ZXing parte con la camera posteriore a 1280×720 (prima senza ne' facingMode ne' risoluzione) e legge ogni 120 ms invece di 500; messa a fuoco continua, **torcia** e **zoom** dove il telefono li supporta.
- **Fotocamera spenta davvero**: se si esce dalla schermata mentre lo scanner sta partendo, lo stream si ferma da solo (prima restava acceso).
- **Foto del barcode**: prova il rilevatore nativo, poi ZXing anche su versioni ridotte dell'immagine.
- **Scansione continua** (opzione nella schermata Scansiona): dopo ogni prodotto salvato o +1 torna alla fotocamera.

### OCR della scadenza
- **Parser riscritto** (`www/scadenza.js`, 40 test): le correzioni O→0, I→1, S→5, B→8 valgono solo dentro i numeri. Prima si applicavano a tutto il testo e i mesi OTT, SET, LUG, AGO, NOV, DIC non venivano mai riconosciuti, e SCAD/BB/LOT non venivano tolti. Sulle stesse 19 frasi: da 11 a 19 giuste, piu' le nuove (due date, lotti, date ISO).
- **Scadenza, produzione, lotto**: con due date vince quella dopo SCAD/EXP/TMC/BB; si scartano PROD/CONF/MFG; un numero a 6 cifre dopo LOTTO non e' piu' una data. Prima un lotto `250627` diventava 2027-06-25 e con PROD+SCAD veniva scelta la produzione. Una data ISO `2027-05-15` non diventa piu' fine mese.
- **Legge solo la cornice** (prima l'intero fotogramma, ingrandito 2×), con contrasto allargato e tre preparazioni (soglia locale, Otsu, solo grigi) che funzionano anche con scritte chiare su fondo scuro.
- **Lettura automatica** ogni mezzo secondo, risultato da **confermare** («Ho letto: …», alternative, Riprova) invece di scrivere subito nel campo.
- **Motore persistente**: il worker Tesseract resta in memoria mentre si legge (prima veniva ricreato a ogni scatto, due volte per foto) e la whitelist dei caratteri e' impostata dove tesseract.js v5 la legge (passata a `recognize()` veniva ignorata).
- **Torcia e zoom** anche per l'OCR.

### Suggerimenti alla conferma del prodotto
- **Categoria corretta**: si usa il tag piu' specifico (prima il primo, il piu' generico e in inglese, quindi le regole italiane non scattavano quasi mai e la scadenza di default era sempre oggi+365). Tabella con termini italiani e inglesi.
- **Dallo storico**: se hai gia' comprato quel prodotto, la scadenza suggerita e' la mediana dei giorni tra inserimento e scadenza degli ultimi acquisti (esclusi quelli segnati «Aperto»).
- **Niente date inventate**: senza un'indicazione affidabile il campo scadenza resta vuoto, con la nota «Scadenza non suggerita».
- I prodotti non trovati online ma inseriti a mano si ricordano nella cache locale.

### Ricerca online piu' veloce
- Richiesta dei soli campi utili a Open Food Facts: ~700 byte invece di ~117 KB.
- I tre database (OFF, Products, Beauty) si interrogano **insieme**, non uno dopo l'altro (prima fino a 24 s per un prodotto sconosciuto, ora al massimo ~6 s).
- Gli EAN non trovati non si ricercano per 6 ore (`?refresh=1` per forzare); un errore di rete non viene ricordato come «non trovato». L'EAN deve essere numerico.

### Nuove funzioni
- **Aperto oggi** nel dettaglio prodotto: accorcia la scadenza in base alla categoria e annota «Aperto il gg/mm»; con Annulla.
- **Azioni per le notifiche di HA**: `POST /api/prodotti/<id>/consuma` e `/butta` (con `x-api-key`), e i sensori `sensor.dispensa_in_scadenza`/`scaduti` ora riportano l'`id` di ogni prodotto. Esempio in `docs/azioni_notifica_ha.md`.

### Corretto
- **Token Telegram nei log**: gli errori di rete di `requests` includono l'URL con `/bot<TOKEN>` e finivano nel log dell'add-on; ora il token e' sempre oscurato.
- **Telegram con nomi speciali**: un `_`, `*`, `[` nel nome del prodotto faceva rifiutare tutto il messaggio (Markdown); ora i nomi sono protetti e, se Telegram rifiuta comunque, si riprova in testo semplice.
- **Lista spesa**: gli esauriti senza EAN non si bloccano piu' a vicenda (bastava una voce manuale per impedire di aggiungere gli altri) e un prodotto spuntato come comprato non rientra in lista a ogni sincronizzazione.
- **Estendi scadenze** con un valore negativo non cancella piu' le date (scriveva `+-5 days`, che SQLite legge come NULL); valore limitato a ±3650 giorni.
- **Quantita'** non valida o negativa rifiutata (prima errore 500 su una stringa).
- **Amministratori**: non si puo' piu' togliere i privilegi, disattivare o eliminare l'ultimo amministratore attivo.
- **Ripristino backup**: si usano solo le colonne che esistono nella tabella (i nomi arrivavano dal file caricato).
- **Backup automatico** con copie datate: le ultime 4 (prima un solo file sovrascritto ogni settimana).
- **Sensori HA**: elenchi limitati a 25 voci (oltre ~16 KB gli attributi non vengono salvati dal recorder).
- La scadenza di default usava `toISOString()` (UTC): a ridosso della mezzanotte sbagliava di un giorno.

### Sicurezza e manutenzione
- **Niente piu' CDN**: Chart.js, ZXing e Tesseract (con core WASM e dati lingua) sono in `www/vendor/` a versione fissa. Funziona anche senza Internet, la Content-Security-Policy non ammette piu' unpkg/jsdelivr e non c'e' piu' codice di terzi caricato senza controllo di integrita'.
- `requirements.txt` con versioni fisse (prima `>=`: una nuova major poteva rompere la build).
- Service worker `dispensa-v12`: anche `scanner.js` e `scadenza.js` sono network-first, le librerie in locale cache-first.
- Test: `tests/test_scadenza.js` (40 casi) e `tests/test_backend.py` (20 test su database temporaneo).

### Non incluso
- Cambio obbligatorio della password `admin` al primo accesso (scelta di progetto da discutere). Ban IP con scadenza e immagini nel backup sono arrivati nella 2.1.1.

---

## [2.0.21] — 2026-10-03

### Rimosso
- **Opzioni `jwt_secret_key` e `cloudflare_url`** dalla configurazione dell'add-on. La chiave JWT si genera al primo avvio e resta nel database (il codice la cercava gia' li' se l'opzione era vuota). `cloudflare_url` non serve piu': Dispensa si usa in LAN su HTTPS (porta 5443) e da fuori tramite VPN, senza tunnel Cloudflare; senza opzione il CORS resta spento e l'API e' sempre sulla stessa origine.

---

## [2.0.20] — 2026-10-03

### Aggiunto
- **HTTPS in LAN** (opzione `ssl`): con `ssl: true` l'add-on avvia anche un server HTTPS sulla porta **5443** (Cheroot) con `certfile`/`keyfile` letti da `/ssl`, per esempio il certificato dell'add-on Let's Encrypt. Serve alla fotocamera: il browser concede `getUserMedia` (scanner barcode, OCR scadenze) solo in un contesto sicuro, quindi su `http://IP:5000` non funzionava. La porta 5000 resta HTTP per Ingress. Dopo un rinnovo del certificato l'add-on va riavviato.

### Corretto
- **`cf-url` iniettato solo sul dominio esterno**: se la pagina non è servita dal dominio di `cloudflare_url` (LAN, Ingress) il frontend chiama l'API sulla stessa origine invece del tunnel, dove il login di Cloudflare Access falliva.

---

## [2.0.19] — 2026-09-25

### Sicurezza
- **XSS**: nomi, marche, categorie e posizioni dei prodotti (anche quelli scaricati da Open Food Facts, database pubblico modificabile da chiunque), EAN letti dalla fotocamera, username, IP bannati e impostazioni ora passano da `esc()` prima di finire in `innerHTML`. Gli argomenti negli `onclick` usano `jsArg()`; l'URL dell'immagine prodotto accetta solo `http(s)` o percorsi relativi (`safeUrl()`). Prima un nome prodotto con HTML poteva eseguire script e rubare i token JWT salvati in `localStorage`.
- **CORS**: non più aperto a qualunque origine (`*`). Il frontend usa la stessa origine; il CORS si abilita solo per `cloudflare_url`, se impostato. Rimosso l'header obsoleto `x-jarvis-token`.
- **Header di sicurezza** su tutte le risposte: Content-Security-Policy (script solo da self, jsdelivr e unpkg; `connect-src` limitato; `frame-ancestors 'self'` compatibile con Ingress), `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `Permissions-Policy` (fotocamera solo per l'app).
- **IP del client**: `CF-Connecting-IP` e `X-Forwarded-For` sono considerati solo se la richiesta arriva dalla rete interna degli add-on (cloudflared, Ingress). Dalla LAN (porta 5000) non si possono più falsificare per aggirare il ban.
- **Server di produzione**: Flask ora gira su Waitress invece del server di sviluppo Werkzeug.
- **Opzioni add-on**: `telegram_token` e `jwt_secret_key` diventano di tipo `password` (mascherati nel form di configurazione). Supportato `!secret nome` per tenere il token in `secrets.yaml`.

### Modificato
- Service Worker cache `dispensa-v11` per forzare il ricaricamento di `app.js`.

---

## [1.5.9] — 2026-04-29

### Aggiunto
- **Screenshot PWA**: aggiunti `screenshot-narrow.png` (390×844) e `screenshot-wide.png` (1280×800), richiesti da Chrome 119+ per mostrare il dialogo "Installa app" su Android al posto del semplice "Aggiungi a schermata Home".

### Modificato
- **Web App Manifest**: aggiunto campo `id: "/"` (raccomandato da Chrome 113+ per identità stabile dell'app); `start_url` e `scope` cambiati da percorsi relativi (`"./"`) ad assoluti (`"/"`) per piena conformità PWA.

---

## [1.5.8] — 2026-04-28

### Modificato
- **Service Worker**: aggiunto pass-through per le richieste `/api/` — il SW non intercetta le chiamate API, evitando conflitti con la WAF Cloudflare che richiedeva header specifici su tutte le richieste in cache.
- **Web App Manifest**: gli icon entry sono stati sdoppiati — ogni icona ha ora due entry separati con `purpose: "any"` e `purpose: "maskable"` rispettivamente, per piena conformità PWA.

---

## [1.5.7] — 2026-04-28

### Corretto
- **Visualizzazione versione nel frontend**: fix nella sostituzione regex in Flask che causava la visualizzazione di una versione errata nell'interfaccia.

---

## [1.5.6] — 2026-04-28

### Aggiunto
- **Meccanismo force re-fetch**: le risorse statiche (JS, CSS) includono ora un query-string con il numero di versione, bypassando la cache del browser ad ogni aggiornamento dell'add-on.

---

## [1.5.5] — 2026-04-27

### Corretto
- **BOM (U+FEFF)**: rimosso carattere BOM invisibile all'inizio di alcuni file Python che causava errori di parsing al caricamento dell'add-on.
- **`cloudflare_url`**: fix nel parsing dell'opzione di configurazione che impediva il corretto rilevamento dell'URL esterno.

---

## [1.5.0] — 2026-04-27

### Modificato (breaking)
- **Architettura frontend**: Flask serve ora il frontend direttamente dalla cartella `dispensa_manager/www/`. Eliminato il meccanismo di sync automatico verso `/config/www/dispensa/` introdotto in v1.4.5. Il frontend è parte integrante del container dell'add-on e non richiede più accesso in scrittura a `/config/`.
- **Rimossa opzione `pwa_url`**: non è più necessaria — la PWA è accessibile direttamente tramite il pulsante "Apri interfaccia utente web" in HA (ingress) oppure all'indirizzo `http://IP:5000/`.

### Rimosso
- Cartella `www/dispensa/` dal repository (codice legacy).
- Opzione di configurazione `pwa_url` da `config.yaml`.
- Logica di sync GitHub → `/config/www/dispensa/` da `app.py`.

---

## [1.4.7] — 2026-04-26

### Aggiunto
- **Banner aggiornamento disponibile**: quando il backend viene aggiornato a una versione superiore a quella caricata sul telefono, appare automaticamente un banner arancione in cima all'app con il numero della nuova versione.
- **Pulsante "Aggiorna ora"**: svuota tutte le cache del service worker, deregistra il SW e forza il ricaricamento completo dell'app dalla rete. Garantisce che la versione più recente venga caricata immediatamente senza dover chiudere e riaprire manualmente l'app.
- Il controllo versione avviene all'avvio, ogni 5 minuti in background e ogni volta che l'app torna in primo piano (`visibilitychange`).

---

## [1.4.6] — 2026-04-26

### Aggiunto
- **Filtro "Scaduti"** nella filter-row dell'inventario: nuovo chip 🔴 che mostra solo i prodotti con data di scadenza già passata (giorni < 0), distinto dal filtro "In scadenza" che mostra i prodotti in scadenza entro la soglia configurata.

---

## [1.4.5] — 2026-04-26

### Aggiunto
- **Sync automatico frontend**: ad ogni avvio dell'add-on, `app.py` scaricava automaticamente i file dell'interfaccia (`index.html`, `manifest.json`, `sw.js`, icone) da GitHub Raw e li copiava in `/config/www/dispensa/`, aggiornando solo i file effettivamente cambiati. (Sostituito in v1.5.0 dall'architettura con Flask che serve direttamente il frontend.)

### Corretto
- **Service Worker — strategia network-first per `index.html`**: il SW non mette più in cache statica la pagina principale. Ogni apertura dell'app scarica sempre la versione aggiornata dal server, con la cache usata solo come fallback offline. Risolve il problema di versioni stale dopo gli aggiornamenti.
- Versione cache SW aggiornata da `dispensa-v2` a `dispensa-v3` per forzare il clear della vecchia cache sui dispositivi già installati.

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
- `pwa_url` accettava solo la base URL; il path `/local/dispensa/index.html` veniva aggiunto automaticamente da `app.py`.

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
