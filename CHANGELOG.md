# Changelog — Dispensa Manager

Tutte le modifiche rilevanti al progetto sono documentate in questo file.
Il formato segue [Keep a Changelog](https://keepachangelog.com/it/1.0.0/).

---

## [2.5.0] — 2026-11-04

**Vegano o no, e un inventario da rifare.** Ogni prodotto dice se è vegano o vegetariano e quali valori nutrizionali ha; e si può segnare tutto come esaurito per riscansionare quello che c'è in casa, senza doppioni e senza una raffica di notifiche.

### Dieta (`dieta.py`)
- Cinque stati per vegano e per vegetariano: **certo** (etichetta «vegan» o analisi di Open Food Facts tutta vegana), **probabile** (nessun ingrediente animale nell'elenco, ma non certificato), **da verificare** (E471, vitamina D3, vino, birra… o dati che si contraddicono), **no** (con il motivo: «latte», «E120»…) e **sconosciuto**. Un prodotto senza ingredienti non è mai dato per vegano.
- Il controllo sugli ingredienti legge italiano, inglese, tedesco e francese, toglie le tracce («può contenere latte») e capisce le frasi che sembrano animali ma non lo sono: latte di soia o di cocco, burro di cacao o di arachidi, lievito di birra, «senza latticini», «aroma di mozzarella», cremor tartaro, acido lattico. Le tracce di latte e uova si mostrano a parte.
- Provato sui 195 prodotti veri che Open Food Facts conosce: dove l'analisi di Open Food Facts è netta, i due giudizi coincidono; il suo «forse vegano» (che dà anche alla pasta di sola semola) diventa «probabile» se nel testo non c'è niente di animale.
- **Giudizio tuo**: «Ho controllato: è vegano» / «Non è vegano» vince su tutto, ed è per prodotto (EAN), non per singola riga. Gli ingredienti si possono scrivere o incollare (anche in scansione, per i prodotti non online) con l'anteprima del giudizio mentre si scrive.
- La **dieta di casa** (vegana, vegetariana, nessuna) la sceglie l'amministratore in Impostazioni: decide i badge nella lista, il filtro «Dieta» e l'avviso rosso in scansione («🚫 Non adatto alla dieta vegana: latte»). Saponi e Altro non hanno badge.

### Valori nutrizionali (`profilo_nutrizionale`)
- Per 100 g, con le soglie dei claim europei: alto contenuto di proteine (almeno il 20% delle calorie), fonte di proteine (12%), ricco di fibre (6 g), pochi zuccheri (5 g), poco sale (0,3 g), pochi grassi saturi (1,5 g); e gli eccessi del «semaforo» britannico (zuccheri 22,5 g, sale 1,5 g, saturi 5 g, grassi 17,5 g). In più Nutri-Score e livello di lavorazione (NOVA).

### Dati da Open Food Facts
- Si raccolgono anche ingredienti, analisi vegana/vegetariana, etichette, allergeni, tracce, NOVA e categorie; il giudizio si ricalcola ogni volta, quindi un miglioramento delle regole vale subito per tutti i prodotti.
- La cache locale di prima della 2.5.0 non li ha: alla prima scansione di un prodotto già in cache si chiedono una volta sola.
- **«Aggiorna i dati dei prodotti»** (Impostazioni) raccoglie in background i dati di tutti i prodotti con codice a barre. Va piano, una richiesta ogni 1,5 secondi (circa 6 minuti per 230 prodotti), e si adatta: Open Food Facts risponde «troppe richieste» (429) se si va troppo veloci, senza dire quanto aspettare; l'app allunga la pausa a ogni 429 e la riaccorcia dopo i successi, e un codice che resta senza risposta viene ritentato alla raccolta successiva invece di essere dato per «non trovato». Nella prima prova senza queste cautele 151 prodotti su 232 sembravano «non trovati» (erano 37). Le richieste si presentano con nome, versione e indirizzo del progetto, come chiede Open Food Facts.

### Nuovo inventario
- **«Segna tutto come esaurito»** (Impostazioni, solo admin): copia il database (controllando che le righe siano tutte), azzera le quantità e accende la **riscansione**. Serve scrivere AZZERA; c'è l'Annulla (che rispetta ciò che nel frattempo hai riscansionato).
- **Scansionare un prodotto finito ricarica la sua riga**: niente doppioni tra gli esauriti, e restano foto, ingredienti, dieta e posizione. Vale sempre, non solo in riscansione.
- Durante la riscansione: banner «Riscansione in corso: 41 di 183», nessun suggerito nella spesa, nessun elenco degli esauriti nei report e negli alert, nessun messaggio Telegram per ogni scansione (restano le eliminazioni). «Termina» la spegne.

### Altro
- Il salvataggio di un prodotto controlla la risposta del server (prima un errore diceva comunque «Prodotto salvato!»).
- Il backup JSON e il ripristino portano i campi nuovi. La versione nel piè di pagina è quella vera.

### Migrazione (schema 11)
- Colonne `ingredienti`, `off_dati`, `nova`, `dieta_override` in `prodotti`; `ingredienti`, `off_dati`, `nova` in `barcode_cache`; tabella `azzeramento_log`. Niente cambia finché non lo chiedi.

### Test
- `tests/test_dieta.py` (23), `tests/test_inventario.py` (26) e 40 nuovi controlli in `tests/test_gui.js`

---

## [2.4.0] — 2026-11-02

**Cinque posizioni, scelte da sole.** Oltre a Dispensa, Frigo e Congelatore (nel database resta «Freezer») arrivano **Saponi** 🧴 (igiene, pulizia della casa) e **Altro** 📦 (sacchetti, pile, lampadine…). I prodotti nuovi finiscono nel posto giusto senza pensarci, e quelli già in casa si possono sistemare in un colpo solo.

### Classificazione (`posizioni.py`)
- Si guarda il nome, la marca e le categorie di Open Food Facts, in ordine di sicurezza: igiene e casa → Saponi (o Altro per sacchetti, pile, lampadine…), surgelati e gelati → Congelatore, poi le regole del fresco (frigo) e della dispensa. Ogni risposta ha un **livello**: alto (non è cibo, o è surgelato), medio (frigo/dispensa dal solo nome), basso (non si capisce: resta Dispensa).
- Più attenzione ai falsi amici: «cavolo» non è un cavo, il caffè o le tisane non sono «fresche», gli affettati e le alternative vegetali (burger, tofu, yogurt di soia…) vanno in frigo.
- **Scansione**: la posizione suggerita usa la nuova classificazione (lo storico dello stesso prodotto vince sempre); per Saponi e Altro non si propone nessuna scadenza.
- **Inserimento a mano**: mentre scrivi il nome la posizione si aggiorna da sola e ti dice quale ha scelto; se la cambi tu, non viene più toccata. Il server classifica anche i prodotti inseriti senza posizione (API, Home Assistant).

### Prodotti già in casa
- Un **banner** sull'inventario («42 prodotti sembrano nella posizione sbagliata») e il pulsante «🧭 Controlla le posizioni» in Impostazioni aprono l'elenco delle proposte.
- **Consigliati** (non sono cibo, o sono surgelati) sono già spuntati; **Da verificare** (frigo/dispensa dal solo nome) no. Non si sposta niente senza conferma.
- «Sposta i selezionati» applica e mostra **Annulla** per 8 secondi (l'annullo rispetta i prodotti che nel frattempo hai spostato a mano); «Lascia dove sono i non selezionati» li mette da parte e non te li ripropone.
- Il server ricalcola le proposte al momento dell'applicazione: non si fida di ciò che invia il client.

### Interfaccia
- Filtri, menu a tendina, azioni in blocco, statistiche e lista della spesa conoscono le cinque posizioni; unica tabella `POS` in `app.js`.
- Le API rifiutano posizioni sconosciute (prima il valore veniva scritto così com'era).

### Migrazione (schema 10)
- Tabelle `posizioni_log` (lotti annullabili) e `riclassifica_ignorati`. I prodotti non si toccano finché non confermi dall'app.

### Test
- `tests/test_posizioni.py` (16 test: classificatore, API, riclassifica con annullo, scarti, id non numerici) e nuovi controlli in `tests/test_gui.js`

---

## [2.3.0] — 2026-11-02

**La lista della spesa sul telefono.** Dispensa sincronizza la lista con una lista to-do di Home Assistant: il widget «To-do list» dell'app Companion (Android) la mostra, si spunta e si aggiunge dal telefono, e tutto compare anche nell'app. Guida in `docs/widget_telefono.md`.

### Sincronizzazione (`sync_todo.py`)
- **Bidirezionale e senza rimbalzi**: ogni elemento remoto è legato a una voce locale da una mappa (`spesa_sync_map`) che ricorda l'ultimo stato concordato; confrontando locale e remoto con quell'istantanea si capisce chi ha cambiato cosa. Un giro senza differenze non scrive niente.
- **Tempi**: dall'app al telefono 2-3 secondi (ogni modifica sveglia la sincronizzazione), dal telefono all'app entro 30 secondi.
- **Prima attivazione = unione**: le voci presenti da entrambe le parti (stesso nome, singolare o plurale) diventano una sola; non si cancella niente.
- **Dal telefono**: «pane», «2 mele», «latte x3» vengono letti come nell'app (quantità, maiuscole, reparto); i nomi senza senso («2») si ignorano; due voci uguali scritte nel widget diventano una.
- **Spunte, rinomine e quantità** viaggiano nei due sensi. Se cambiano entrambe le parti insieme vince lo stato «fatto» e il nome locale. Una rinomina dal telefono che coinciderebbe con un'altra voce si ignora.
- **Cancellazioni**: svuotare il carrello o rimuovere una voce nell'app toglie l'elemento dal telefono; una cancellazione dal telefono vale in locale solo dopo **due giri consecutivi** e mai in massa (almeno 4 elementi e più della metà): una lettura incompleta di Home Assistant non può svuotare la lista.
- **Errori**: se Home Assistant non risponde l'app funziona normalmente, riprova ogni minuto e non perde nulla. Il token del Supervisor non compare mai nei messaggi.
- Lo stato si vede in **Admin → «Lista condivisa»** (collegata, voci, ultimo scambio, errore con il suggerimento giusto) con «🔄 Sincronizza ora»; la lista si sceglie in «Impostazioni sistema» (`todo_widget_entity`, di default `todo.lista_della_spesa`; `todo_sync_attivo` 0 la ferma). Le voci arrivate dal telefono mostrano «📱 dal telefono».
- I sensori `sensor.dispensa_lista_spesa` e `sensor.dispensa_suggeriti` si aggiornano a ogni modifica della lista, anche dal telefono.
- Il motore è generico sui connettori: la lista di Alexa si aggiungerà come secondo connettore quando il login di Alexa Devices funzionerà (HA 2026.11).

### Migrazione (schema 9)
- Tabella `spesa_sync_map` e due impostazioni (`todo_widget_entity`, `todo_sync_attivo`). Senza la lista in Home Assistant l'add-on resta in attesa e lo dice nel pannello Admin.

### Test
- `tests/test_sync_todo.py` (28 test: scenari di sincronizzazione con una lista finta, chiamate REST verso HA, endpoint Admin, trigger) e `tests/finto_ha.py`, un Home Assistant finto per provare tutto a mano. In totale 102 test Python. Prova completa con l'add-on reale e il finto HA: aggiunte, spunte, cancellazioni, errore e ripresa.

---

## [2.2.0] — 2026-11-02

Lista della spesa rifatta: i prodotti finiti sono **suggerimenti**, non voci automatiche; le voci si aggiungono in modo intelligente e sono pronte per la fusione con la lista di Alexa (versione successiva).

### Suggeriti (finiti in dispensa)
- **Gli esauriti non entrano più da soli nella lista.** Prima ogni prodotto a zero veniva aggiunto a ogni sincronizzazione: su un database reale 66 voci su 67 erano generate così. Ora la schermata Spesa ha una sezione «Finiti in dispensa» con **+** (aggiungi alla lista) e **✕** (non serve), più «Aggiungi tutti» e «Nascondi i finiti da più di 3 mesi».
- Non si suggerisce un prodotto di cui hai ancora una scorta (stesso EAN o stesso nome in un'altra riga), uno già coperto da una voce in lista o nel carrello (con lo stesso reparto), né i doppioni (se ne propone uno, l'ultimo inserito). Ogni suggerimento dice da quanti giorni è finito, dall'ultimo consumo registrato; i più recenti stanno in cima.
- «Non serve» vale finché il prodotto non torna in dispensa: se lo ricompri e lo finisci di nuovo, ricompare.

### Da comprare, per reparto
- Le voci sono raggruppate per **reparto** nell'ordine di un giro al supermercato: frutta e verdura, pane, latticini, carne e pesce, surgelati, dispensa, bevande, igiene, casa, animali, altro (`reparti.py`, regole in italiano).
- **Aggiunta intelligente** dal campo in cima alla schermata (non più un `prompt()`): «dentifricio», «2 latte», «latte x3», «due mele», «2 confezioni di pasta»; «500 g pasta» e «Farina 00» restano interi (misure e numeri che non sono quantità).
- **Niente doppioni**: «Dentifricio», «dentifrici», «il dentifricio» sono la stessa voce (nomi confrontati senza articoli, accenti e maiuscole, singolare = plurale). Una voce già in lista non cambia, salvo quantità esplicita; una nel carrello torna in lista.
- **Avviso «in dispensa»**: se hai già qualcosa che copre la voce nello stesso reparto, l'app lo dice («Aggiunto: Latte · in dispensa hai Latte intero ×2 (Frigo)») e lo mostra sulla voce. Il controllo del reparto evita i falsi avvisi (non confonde «latte» con «cioccolato al latte di cocco»).
- **Completamento mentre scrivi**: voci usate spesso (con storico) e nomi di prodotti che conosci.
- Annulla su spunta e rimozione, quantità con +/−, e chi ha aggiunto la voce («di laura»).
- **Badge** con il numero di voci da comprare sull'icona della scheda Spesa.

### Integrazioni
- Nuovi sensori HA: `sensor.dispensa_lista_spesa` (voci da comprare, con elenco) e `sensor.dispensa_suggeriti` (finiti da ricomprare).
- **Telegram**: la lista esce per reparto e, a parte, i prodotti finiti non ancora in lista.
- API nuove: `GET /api/spesa`, `/api/spesa/conteggi`, `/api/spesa/cerca`, `POST /api/spesa/suggeriti/<id>/aggiungi|ignora`, `/aggiungi-tutti`, `/ignora-vecchi`. `GET /api/lista-spesa` resta com'era (righe grezze); `PUT` aggiorna solo i campi inviati (prima azzerava `completato` se mancava).

### Migrazione (schema 8)
- Colonne nuove su `lista_spesa` (`uid`, `origine`, `nome_norm`, `reparto`, `aggiunto_da`, `aggiornato_il`, `completato_il`), tabelle `suggerimenti_ignorati` e `spesa_storico`: la base per la sincronizzazione con Alexa.
- Le voci **automatiche** (non spuntate, che combaciano con un prodotto esaurito per EAN o nome) vengono tolte dalla lista e diventano suggerimenti; le altre restano. Le righe tolte si copiano in `lista_spesa_legacy`. Provato su una copia di un database reale: 1 voce conservata, 66 tolte, 54 suggerimenti dopo la rimozione dei doppioni.
- I backup precedenti si ripristinano: le righe senza le colonne nuove vengono completate alla prima lettura.

### Test
- `tests/test_normalizza.py` (quantità, chiavi, reparti), `tests/test_spesa.py` (voci, suggeriti, API, sensori, Telegram, migrazione, backup), `tests/test_gui.js` esteso alla schermata Spesa. In totale 74 test Python.

---

## [2.1.2] — 2026-11-02

Revisione della GUI pagina per pagina (inventario, scansione, conferma, dettaglio, modifica, spesa, statistiche, impostazioni, admin) su telefono e PC.

### Icone
- **Barra delle schede con le icone complete.** La barra in basso era copiata 5 volte nell'HTML, una per schermata, e in 4 copie le icone erano troncate: nelle pagine Spesa, Statistiche, Impostazioni e Admin «Scansiona» era un semplice quadrato, «Impostazioni» un puntino, «Admin» un cerchio, «Statistiche» una sola barra. Ora la barra e' una sola (`<nav id="tab-bar">`) e `showScreen()` evidenzia la scheda attiva; le schermate di dettaglio, scansione e modifica non la mostrano, come prima.
- La barra e' navigabile da tastiera (Tab, Invio, Spazio) e le schede hanno etichetta per i lettori di schermo.
- **Icone della PWA** (`icon-192.png`, `icon-512.png`) con lo stesso disegno dell'icona dell'add-on, a quadrato pieno (iOS e le maschere di Android arrotondano da soli) e con il disegno nella zona sicura. Il vecchio quadrato verde con sagome bianche e' sostituito. Una PWA gia' installata puo' tenere la vecchia icona finche' non viene reinstallata.

### Layout e aspetto
- **Schermi larghi** (PC, tablet orizzontale): colonna centrale di 640 px, con la barra delle schede centrata, invece di righe lunghe quanto lo schermo.
- **Tema scuro**: il campo della chiave API era bianco e ora ha lo stile degli altri campi; checkbox, scrollbar e controlli nativi seguono il tema (`color-scheme: dark`) con l'accento verde dell'app.
- **Aree di tocco**: pulsanti +/−, spunta e interruttori della lista spesa e delle impostazioni restano com'erano alla vista ma hanno una zona di tocco di circa 40 px (erano 28 px).

### Test
- `tests/test_gui.js` (16 controlli): una sola barra, sei schede nell'ordine giusto, ogni icona con tutti i suoi elementi, mappa schermata→scheda, regola per schermi larghi dopo quella base, campo chiave API.

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
