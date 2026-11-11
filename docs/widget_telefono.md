# La lista della spesa sul telefono (widget Home Assistant)

Dalla 2.3.0 la lista della spesa di Dispensa si sincronizza con una lista **to-do** di Home Assistant. Il widget
«To-do list» dell'app Companion per Android mostra quella lista, permette di **spuntare** le voci e di
**aggiungerne**; tutto compare anche in Dispensa, e viceversa.

## 1. Creare la lista in Home Assistant (una volta sola)

1. Impostazioni → Dispositivi e servizi → **Aggiungi integrazione** → **Local To-do**.
2. Nome della lista: **Lista della spesa** (l'entità diventa `todo.lista_della_spesa`, quella che Dispensa cerca di default).
3. Dopo al massimo 30 secondi Dispensa la trova: nel pannello **Admin → «Lista condivisa»** compare «✅ Collegata a todo.lista_della_spesa».
   «🔄 Sincronizza ora» fa partire subito un giro. Se la lista ha un altro nome, si scrive l'entità in «Impostazioni sistema».

La prima volta le due liste si **uniscono** senza cancellare niente: le voci che esistono da entrambe le parti
(stesso nome, singolare o plurale) diventano una sola.

## 2. Il widget sul telefono (Luigi e Laura)

1. Tieni premuto su uno spazio vuoto della schermata Home → **Widget** → **Home Assistant** → **To-do list**.
2. Scegli la lista **Lista della spesa** e un tema, poi salva.
3. Spunta una voce: in Dispensa passa nel carrello. Tocca «+» per aggiungerne: in Dispensa compare entro pochi secondi
   (con 📱 «dal telefono») e prende reparto e nome corretti.

Laura vede la lista con il proprio utente di Home Assistant (le liste to-do sono visibili a tutti gli utenti).

## Come funziona

- **Dispensa → telefono**: ogni modifica nell'app parte entro 2-3 secondi. **Telefono → Dispensa**: entro 30 secondi.
- Le voci con quantità compaiono come «Dentifricio ×2»; scrivendo «2 latte» o «latte x3» nel widget la quantità viene letta.
- Una voce cancellata dal telefono sparisce da Dispensa solo dopo **due giri consecutivi** (circa un minuto) e mai in massa:
  una lettura incompleta di Home Assistant non può svuotare la lista.
- Se Home Assistant è spento o lento, Dispensa funziona normalmente e riprova da sola ogni minuto: non si perde niente.
- Le voci del tipo «suggeriti» (prodotti finiti) **non** vanno nel widget finché non le aggiungi alla lista.
- Si ferma dalle impostazioni (`todo_sync_attivo` = 0) o svuotando l'entità.

## La lista della spesa di Alexa (dalla 2.6.0)

Con l'integrazione **Alexa Devices** (Home Assistant 2026.11 o successivo) la lista della spesa di Alexa diventa una lista
to-do (`todo.<account>_shopping_list`). Dispensa la sincronizza come il widget: «Alexa, aggiungi dentifricio alla lista della
spesa» e la voce compare in Dispensa (con 🎤 «Alexa») e nel widget; aggiungere o spuntare in Dispensa vale anche su Alexa.

1. In **Admin → «Lista della spesa di Alexa»** scrivi l'entità della lista e premi **Anteprima**: vedi quali voci entrano e
   quali escono, senza che venga scritto niente.
2. Se va bene, **Conferma e attiva**. Dalla prima unione in poi si sincronizza da sola (circa ogni 90 secondi, subito dopo una modifica in Dispensa).
3. **Metti in pausa** la ferma senza scollegare niente.

Cose da sapere:
- Le voci già **spuntate su Alexa** sono il suo storico (al massimo 100 voci visibili): non entrano in Dispensa e il carrello di
  Dispensa non va su Alexa.
- Amazon limita le richieste: quando succede Home Assistant dichiara la lista «non disponibile». Dispensa salta il giro, non
  segna errori e riprende da sola. Se capita spesso, aumenta «Secondi tra le scansioni» di **Alexa Media Player** (300 va bene):
  anche lui interroga Amazon con lo stesso account.
- Le voci aggiunte a voce arrivano a Dispensa entro un minuto o due.

## Prova senza Home Assistant

`python tests/finto_ha.py` avvia due liste finte (widget e Alexa, quest'ultima può diventare «non disponibile»); poi l'add-on con
`HA_URL=http://127.0.0.1:8124 SUPERVISOR_TOKEN=prova DISPENSA_SYNC_SECONDI=3 python app.py`
(usare `127.0.0.1`: con `localhost` su Windows ogni chiamata aspetta 2 secondi).
