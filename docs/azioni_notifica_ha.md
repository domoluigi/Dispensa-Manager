# Notifica di Home Assistant con pulsanti «Consumato» e «Buttato»

Dalla 2.1.0 l'add-on espone due azioni pensate per le notifiche azionabili dell'app HA:

| Azione | Endpoint | Effetto |
|---|---|---|
| Consumato | `POST /api/prodotti/<id>/consuma` | toglie 1 pezzo (mai sotto zero) e registra il consumo |
| Buttato | `POST /api/prodotti/<id>/butta` | elimina il prodotto e lo conta come spreco nelle statistiche |

Entrambe accettano l'header `x-api-key` (la chiave si legge dal pannello Admin dell'app) oppure un JWT.
I sensori `sensor.dispensa_in_scadenza` e `sensor.dispensa_scaduti` hanno nell'attributo `prodotti` un
elenco di `{id, nome, scadenza, giorni}` (al massimo 25 voci).

## 1. Comandi REST in `configuration.yaml`

La chiave va in `secrets.yaml` (`dispensa_api_key`). L'indirizzo e' quello che HA gia' usa per `sync-ha`.

```yaml
rest_command:
  dispensa_consuma:
    url: "http://192.168.1.5:5000/api/prodotti/{{ id }}/consuma"
    method: post
    headers:
      x-api-key: !secret dispensa_api_key
  dispensa_butta:
    url: "http://192.168.1.5:5000/api/prodotti/{{ id }}/butta"
    method: post
    headers:
      x-api-key: !secret dispensa_api_key
```

## 2. Automazioni

Sostituire `notify.mobile_app_telefono` con il proprio servizio (le azioni funzionano solo con
`notify.mobile_app_*`, non con `notify.send_message`).

```yaml
automation:
  - alias: "Dispensa: prodotti in scadenza con pulsanti"
    triggers:
      - trigger: time
        at: "08:00:00"
    conditions:
      - condition: numeric_state
        entity_id: sensor.dispensa_in_scadenza
        above: 0
    actions:
      - repeat:
          for_each: "{{ state_attr('sensor.dispensa_in_scadenza', 'prodotti') | default([], true) }}"
          sequence:
            - action: notify.mobile_app_telefono
              data:
                title: "In scadenza: {{ repeat.item.nome }}"
                message: >-
                  {% if repeat.item.giorni == 0 %}Scade oggi
                  {% elif repeat.item.giorni == 1 %}Scade domani
                  {% else %}Scade tra {{ repeat.item.giorni }} giorni{% endif %}
                data:
                  tag: "dispensa_{{ repeat.item.id }}"
                  actions:
                    - action: "DISPENSA_consuma_{{ repeat.item.id }}"
                      title: "Consumato"
                    - action: "DISPENSA_butta_{{ repeat.item.id }}"
                      title: "Buttato"

  - alias: "Dispensa: risposta ai pulsanti della notifica"
    triggers:
      - trigger: event
        event_type: mobile_app_notification_action
    conditions:
      - condition: template
        value_template: "{{ trigger.event.data.action.startswith('DISPENSA_') }}"
    actions:
      - variables:
          parti: "{{ trigger.event.data.action.split('_') }}"
      - action: "rest_command.dispensa_{{ parti[1] }}"
        data:
          id: "{{ parti[2] }}"
      - action: notify.mobile_app_telefono
        data:
          message: clear_notification
          data:
            tag: "dispensa_{{ parti[2] }}"
```

Note:
- `rest_command` con un nome ricavato dal template funziona solo per `consuma` e `butta`: altri valori danno errore, come voluto.
- Dopo l'azione l'add-on aggiorna da solo i sensori (e quindi la card in dashboard).
- Se si preferisce un solo messaggio riassuntivo, l'attributo `prodotti` basta per costruirlo; i pulsanti hanno senso con poche notifiche.
