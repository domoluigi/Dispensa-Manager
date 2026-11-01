// Controlli statici sulla GUI: node tests/test_gui.js
// La barra delle schede era copiata in 5 schermate e in 4 copie le icone erano troncate:
// questo test fallisce se una copia torna o se un'icona perde pezzi.
const fs = require('fs');
const path = require('path');
const www = path.join(__dirname, '..', 'dispensa_manager', 'www');
const html = fs.readFileSync(path.join(www, 'index.html'), 'utf8');
const js = fs.readFileSync(path.join(www, 'app.js'), 'utf8');
const css = fs.readFileSync(path.join(www, 'style.css'), 'utf8');

let ok = 0, tot = 0;
function verifica(nome, vero) { tot++; if (vero) ok++; console.log((vero ? 'OK  ' : 'FAIL') + ' | ' + nome); }

verifica('una sola barra delle schede', (html.match(/class="tab-bar"/g) || []).length === 1);

const barra = (html.match(/<nav class="tab-bar"[\s\S]*?<\/nav>/) || [''])[0];
const schede = [...barra.matchAll(/<div class="tab[^"]*" data-tab="([a-z]+)"[\s\S]*?<\/svg><span>([^<]+)<\/span><\/div>/g)];
verifica('sei schede', schede.length === 6);
verifica('ordine e nomi', schede.map(s => s[1]).join() === 'inventario,scan,spesa,statistiche,impostazioni,admin');

// elementi minimi per riconoscere l'icona (la casa ha tetto+porta, la scansione il riquadro+4 barre, ecc.)
const minimi = { inventario: 2, scan: 5, spesa: 3, statistiche: 3, impostazioni: 2, admin: 4 };
for (const s of schede) {
  const figli = (s[0].match(/<(path|line|rect|circle|polyline)\b/g) || []).length;
  verifica('icona completa: ' + s[1] + ' (' + figli + ' elementi, minimo ' + minimi[s[1]] + ')', figli >= minimi[s[1]]);
}
verifica("l'icona delle impostazioni e' un ingranaggio, non un punto", /data-tab="impostazioni"[\s\S]*?<path d="M19\.4 15/.test(barra));

// ogni scheda porta a una schermata che esiste e ha la sua scheda evidenziata
const mappa = [...js.matchAll(/'(screen-[a-z]+)': '([a-z]+)'/g)].map(m => [m[1], m[2]]);
verifica('mappa schermata→scheda coerente con la barra',
  mappa.length === 5 && mappa.every(([sch, tab]) => html.includes('id="' + sch + '"') && schede.some(s => s[1] === tab)));
verifica('showScreen aggiorna la barra', /function showScreen\(id\) \{[\s\S]{0,400}aggiornaTabBar\(id\)/.test(js));

verifica('colonna centrale su schermi larghi', /@media \(min-width: 700px\)[\s\S]*\.tab-bar \{ left: 50%/.test(css));
verifica("la regola per schermi larghi sta dopo la regola base di .tab-bar (altrimenti viene sovrascritta)",
  css.lastIndexOf('.tab-bar { left: 50%') > css.indexOf('.tab-bar {\n  position: fixed') || css.lastIndexOf('.tab-bar { left: 50%') > css.indexOf('.tab-bar {\r\n  position: fixed'));
verifica('campo chiave API con lo stile degli altri campi', /id="api-key-display" class="setting-input"/.test(html));
verifica('controlli nativi scuri in tema scuro', /\.dark \{ color-scheme: dark; \}/.test(css));

console.log(ok + '/' + tot);
process.exit(ok === tot ? 0 : 1);
