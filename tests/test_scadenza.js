// Test del parser delle scadenze: node tests/test_scadenza.js
const { estraiDataScadenza } = require('../dispensa_manager/www/scadenza.js');
const OGGI = '2026-11-01T12:00:00';
const casi = [
  ['EXP 09/09/27', '2027-09-09'],
  ['09/09/2027', '2027-09-09'],
  ['SCAD 15/03/2027', '2027-03-15'],
  ['TMC 03/2027', '2027-03-31'],
  ['MAR 2027', '2027-03-31'],
  ['OTT 2027', '2027-10-31'],
  ['SET 2027', '2027-09-30'],
  ['LUG 2027', '2027-07-31'],
  ['DIC 2027', '2027-12-31'],
  ['AGO 2027', '2027-08-31'],
  ['NOV 2027', '2027-11-30'],
  ['10 OTT 2027', '2027-10-10'],
  ['L123456 SCAD 10/05/27', '2027-05-10'],
  ['LOTTO 230415 EXP 10/05/27', '2027-05-10'],
  ['LOTTO 250627 EXP 10/05/27', '2027-05-10'],
  ['LOTTO L240101 15.08.2027', '2027-08-15'],
  ['da consumarsi entro 12.12.2026', '2026-12-12'],
  ['BB 12/2027', '2027-12-31'],
  ['15 05 2027', '2027-05-15'],
  ['2027-05-15', '2027-05-15'],
  // due date: vince la scadenza
  ['PROD 01/02/26 SCAD 01/02/27', '2027-02-01'],
  ['01/02/26 01/02/27', '2027-02-01'],
  ['CONFEZIONATO IL 10/10/2026 DA CONSUMARSI ENTRO 20/10/2026', '2026-10-20'],
  // rumore tipico dell'OCR
  ['1O/O5/2O27', '2027-05-10'],
  ['EXP:09.09.2027', '2027-09-09'],
  ['EXP 09 09 27', '2027-09-09'],
  ['09.09.27 L25', '2027-09-09'],
  ['0TT 2027', '2027-10-31'],
  ['D1C 2027', '2027-12-31'],
  ['BEST BEFORE END 12/2027', '2027-12-31'],
  ['EXP 05/28', '2028-05-31'],
  ['scad. 3 NOV 2027', '2027-11-03'],
  ['12DIC2027', '2027-12-12'],
  ['EXP 250527', '2027-05-25'],
  ['EXP 20270525', '2027-05-25'],
  // senza data: deve restituire null, non inventare
  ['LOTTO 250627', null],
  ['PESO NETTO 500 g', null],
  ['', null],
  ['0.5 L 4 12 2019', null],
  ['31/02/2027', null],
];
let ok = 0;
for (const [t, atteso] of casi) {
  const r = estraiDataScadenza(t, OGGI);
  const bene = r === atteso;
  if (bene) ok++;
  console.log((bene ? 'OK  ' : 'FAIL') + ' | ' + t.padEnd(56) + ' | atteso ' + atteso + ' | ottenuto ' + r);
}
console.log(ok + '/' + casi.length);
process.exit(ok === casi.length ? 0 : 1);
