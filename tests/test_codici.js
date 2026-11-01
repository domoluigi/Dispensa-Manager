// Test della validazione dei codici a barre: node tests/test_codici.js
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const ctx = { console, Date, Math, Number, String, Map, Set, Uint8ClampedArray, Uint32Array, URL };
vm.createContext(ctx);
// scanner.js usa solo funzioni e costanti a livello superiore: si carica senza DOM
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'dispensa_manager', 'www', 'scanner.js'), 'utf8')
  + '\n;globalThis.__api = { gtinValido, normalizzaCodice, confermaLettura, upceInUpca, resetLettura: () => { _ultimaLettura = { codice: null, n: 0, t: 0 }; } };', ctx);
const { gtinValido, normalizzaCodice, confermaLettura, resetLettura } = ctx.__api;

let ok = 0, tot = 0;
function verifica(nome, vero) { tot++; if (vero) ok++; console.log((vero ? 'OK  ' : 'FAIL') + ' | ' + nome); }

verifica('EAN-13 valido (8076809513388)', gtinValido('8076809513388'));
verifica('EAN-13 valido (4006381333931)', gtinValido('4006381333931'));
verifica('EAN-13 con ultima cifra sbagliata', !gtinValido('8076809513387'));
verifica('EAN-13 con due cifre adiacenti scambiate (0 e 7)', !gtinValido('8706809513388'));
verifica('EAN-8 valido (96385074)', gtinValido('96385074'));
verifica('EAN-8 sbagliato', !gtinValido('96385075'));
verifica('UPC-A valido (036000291452)', gtinValido('036000291452'));
verifica('lunghezza 10 rifiutata', !gtinValido('1234567890'));
verifica('UPC-E espanso in UPC-A', normalizzaCodice('04252614') === '042100005264');
verifica('testo non numerico rifiutato (lotto Code128)', normalizzaCodice('L250627A') === null);
verifica('stringa vuota rifiutata', normalizzaCodice('') === null);
verifica('spazi ignorati', normalizzaCodice(' 8076809513388 ') === '8076809513388');

resetLettura();
verifica('prima lettura non basta', confermaLettura('8076809513388') === null);
verifica('seconda lettura uguale conferma', confermaLettura('8076809513388') === '8076809513388');
resetLettura();
confermaLettura('8076809513388');
verifica('codice diverso riparte da capo', confermaLettura('4006381333931') === null);
verifica('lettura con checksum errato non conta mai', (() => { resetLettura(); confermaLettura('8076809513387'); return confermaLettura('8076809513387') === null; })());

console.log(ok + '/' + tot);
process.exit(ok === tot ? 0 : 1);
