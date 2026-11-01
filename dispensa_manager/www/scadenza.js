// Estrazione della data di scadenza dal testo letto dall'OCR (v2.1.0).
// Modulo senza dipendenze dal DOM: gira nel browser e in node (test).
// Principi: le correzioni di carattere (O→0, I→1...) valgono solo dentro i
// token numerici e non toccano le parole; ogni data trovata e' un candidato
// con un punteggio (parola chiave di scadenza, produzione, lotto) e si sceglie
// il migliore invece del primo che combacia.
(function (root) {
  'use strict';

  const MESI = {
    GEN: 1, GENNAIO: 1, JAN: 1, JANUARY: 1,
    FEB: 2, FEBBRAIO: 2, FEBRUARY: 2,
    MAR: 3, MARZO: 3, MARCH: 3,
    APR: 4, APRILE: 4, APRIL: 4,
    MAG: 5, MAGGIO: 5, MAY: 5,
    GIU: 6, GIUGNO: 6, JUN: 6, JUNE: 6,
    LUG: 7, LUGLIO: 7, JUL: 7, JULY: 7,
    AGO: 8, AGOSTO: 8, AUG: 8, AUGUST: 8,
    SET: 9, SETT: 9, SETTEMBRE: 9, SEP: 9, SEPT: 9, SEPTEMBER: 9,
    OTT: 10, OTTOBRE: 10, OCT: 10, OCTOBER: 10,
    NOV: 11, NOVEMBRE: 11, NOVEMBER: 11,
    DIC: 12, DICEMBRE: 12, DEC: 12, DECEMBER: 12,
  };
  const NOMI_MESI = Object.keys(MESI).sort((a, b) => b.length - a.length).join('|');

  // Parole chiave vicine a una data (cercate nei 26 caratteri che la precedono)
  const KW = {
    scad: /SCAD(?:ENZA)?|EXPIRY(?:\s*DATE)?|EXP\.?|TMC|BBE|BB|MHD|USE\s*BY|BEST\s*BEFORE(?:\s*END(?:\s*OF)?)?|CONSUMARSI\s*ENTRO|CONSUMARE\s*ENTRO|CONS\.?\s*ENT\.?|PREFERIBILMENTE\s*ENTRO|ENTRO(?:\s*IL)?/g,
    prod: /PRODUZIONE|PRODOTTO\s*IL|PROD\.?|CONFEZIONAT[OA]|CONF\.?|PACKED|PACK\s*DATE|MFG|MFD|DATA\s*DI\s*PROD/g,
    lotto: /LOTTO|LOT|LOTT/g,
  };
  const PAROLE_NOTE = new Set(Object.keys(MESI).concat(
    ['SCAD', 'SCADENZA', 'EXP', 'TMC', 'BBE', 'BB', 'MHD', 'LOT', 'LOTTO', 'PROD', 'CONF', 'MFG', 'MFD']));

  const NUM = { O: '0', Q: '0', I: '1', L: '1', '|': '1', S: '5', B: '8', Z: '2' };

  function normalizza(testo) {
    let t = String(testo || '').toUpperCase().replace(/[\r\n\t]+/g, ' ').replace(/\s+/g, ' ');
    t = t.replace(/[0-9A-Z|]+/g, w => {
      // codici tipo L250627 / A12345: lotti, si lasciano intatti
      if (/^[A-Z]\d{3,}$/.test(w)) return w;
      // token numerico con lettere scambiate per cifre ("1O", "O5", "2O27")
      if (/\d/.test(w) && /^[0-9OQILSBZ|]+$/.test(w)) return w.replace(/[OQILSBZ|]/g, c => NUM[c]);
      // parola con cifre scambiate per lettere ("0TT", "D1C", "AG0"), solo se diventa un mese/parola nota
      if ((w.match(/[A-Z]/g) || []).length >= 2 && /\d/.test(w)) {
        const f = w.replace(/0/g, 'O').replace(/1/g, 'I').replace(/5/g, 'S').replace(/8/g, 'B');
        if (PAROLE_NOTE.has(f)) return f;
      }
      return w;
    });
    return t;
  }

  function ultimoGiorno(anno, mese) { return new Date(anno, mese, 0).getDate(); }
  function annoCompleto(a) { const n = parseInt(a, 10); return a.length === 2 ? 2000 + n : n; }

  function dataValida(a, m, g) {
    if (m < 1 || m > 12 || g < 1 || g > 31) return null;
    const d = new Date(a, m - 1, g);
    if (d.getFullYear() !== a || d.getMonth() !== m - 1 || d.getDate() !== g) return null;
    return d;
  }

  function iso(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  // Parola chiave piu' vicina prima della posizione idx, senza altre cifre in mezzo
  function parolaChiavePrima(t, idx) {
    const inizio = Math.max(0, idx - 26);
    const finestra = t.slice(inizio, idx);
    let migliore = null;
    for (const [tipo, re] of Object.entries(KW)) {
      re.lastIndex = 0;
      let m;
      while ((m = re.exec(finestra)) !== null) {
        const fine = m.index + m[0].length;
        if (/\d/.test(finestra.slice(fine))) continue;
        if (!migliore || fine > migliore.fine) migliore = { tipo, fine };
      }
    }
    return migliore ? migliore.tipo : null;
  }

  function trovaCandidati(t) {
    const out = [];
    const aggiungi = (m, d, forma, soloConKw) => {
      if (d) out.push({ d, da: m.index, a: m.index + m[0].length, forma, soloConKw: !!soloConKw, grezzo: m[0] });
    };
    let m, re;

    // gg/mm/aaaa, gg-mm-aa, gg.mm.aaaa, gg mm aa
    re = /(?<!\d)(\d{1,2})[\s\/\-.]{1,3}(\d{1,2})[\s\/\-.]{1,3}(\d{4}|\d{2})(?!\d)/g;
    while ((m = re.exec(t)) !== null) {
      const a = annoCompleto(m[3]);
      let d = dataValida(a, +m[2], +m[1]);
      if (!d && +m[2] > 12 && +m[1] <= 12) d = dataValida(a, +m[1], +m[2]); // mm/gg all'americana
      aggiungi(m, d, 'completa');
    }
    // aaaa-mm-gg
    re = /(?<!\d)(20\d{2})[\s\/\-.]{1,3}(\d{1,2})[\s\/\-.]{1,3}(\d{1,2})(?!\d)/g;
    while ((m = re.exec(t)) !== null) aggiungi(m, dataValida(+m[1], +m[2], +m[3]), 'iso');
    // giorno + mese in lettere + anno, oppure solo mese + anno
    re = new RegExp('(?<!\\d)(?:(\\d{1,2})\\s*)?(?<![A-Z])(' + NOMI_MESI + ')(?![A-Z])\\.?\\s*[\\/\\-.]?\\s*(20\\d{2}|\\d{2})(?!\\d)', 'g');
    while ((m = re.exec(t)) !== null) {
      const mese = MESI[m[2]];
      const a = annoCompleto(m[3]);
      if (m[3].length === 2 && (a < 2024 || a > 2040)) continue;
      const g = m[1] ? +m[1] : ultimoGiorno(a, mese);
      aggiungi(m, dataValida(a, mese, g), m[1] ? 'mese-nome-giorno' : 'mese-nome');
    }
    // mm/aaaa e aaaa/mm (scadenza a fine mese); mm/aa solo con parola chiave
    re = /(?<![\d\/\-.])(\d{1,2})[\s\/\-.]{1,3}(20\d{2}|\d{2})(?![\d\/\-.]?\d)/g;
    while ((m = re.exec(t)) !== null) {
      const a = annoCompleto(m[2]);
      if (+m[1] < 1 || +m[1] > 12) continue;
      aggiungi(m, dataValida(a, +m[1], ultimoGiorno(a, +m[1])), 'mese-anno', m[2].length === 2);
    }
    re = /(?<![\d\/\-.])(20\d{2})[\s\/\-.]{1,3}(\d{1,2})(?![\d\/\-.]?\d)/g;
    while ((m = re.exec(t)) !== null) {
      if (+m[2] < 1 || +m[2] > 12) continue;
      aggiungi(m, dataValida(+m[1], +m[2], ultimoGiorno(+m[1], +m[2])), 'mese-anno');
    }
    // formati compatti: solo con parola chiave (altrimenti sono quasi sempre lotti)
    re = /(?<!\d)(\d{2})(\d{2})(\d{4}|\d{2})(?!\d)/g;
    while ((m = re.exec(t)) !== null) aggiungi(m, dataValida(annoCompleto(m[3]), +m[2], +m[1]), 'compatta', true);
    re = /(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)/g;
    while ((m = re.exec(t)) !== null) aggiungi(m, dataValida(+m[1], +m[2], +m[3]), 'compatta', true);

    // niente sovrapposizioni: vince la forma piu' lunga
    out.sort((x, y) => (y.a - y.da) - (x.a - x.da));
    const tenuti = [];
    for (const c of out) {
      if (!tenuti.some(k => c.da < k.a && c.a > k.da)) tenuti.push(c);
    }
    return tenuti;
  }

  // Ritorna i candidati ordinati dal migliore: [{iso, punteggio, parolaChiave, forma, grezzo}]
  function analizzaScadenza(testo, oggi) {
    const ora = oggi ? new Date(oggi) : new Date();
    const minimo = new Date(ora); minimo.setDate(minimo.getDate() - 365);
    const massimo = new Date(ora); massimo.setFullYear(massimo.getFullYear() + 12);
    const t = normalizza(testo);
    const risultati = [];
    for (const c of trovaCandidati(t)) {
      if (c.d < minimo || c.d > massimo) continue;
      const kw = parolaChiavePrima(t, c.da);
      if (kw === 'prod') continue;
      if (c.soloConKw && kw !== 'scad') continue;
      let p = 0;
      if (kw === 'scad') p += 100;
      if (kw === 'lotto') p -= 30;
      if (c.forma === 'completa' || c.forma === 'iso' || c.forma === 'mese-nome-giorno') p += 5;
      risultati.push({ iso: iso(c.d), punteggio: p, parolaChiave: kw, forma: c.forma, grezzo: c.grezzo.trim(), _t: c.d.getTime() });
    }
    risultati.sort((x, y) => (y.punteggio - x.punteggio) || (y._t - x._t));
    risultati.forEach(r => delete r._t);
    return risultati;
  }

  function estraiDataScadenza(testo, oggi) {
    const r = analizzaScadenza(testo, oggi);
    return r.length ? r[0].iso : null;
  }

  const api = { analizzaScadenza, estraiDataScadenza, normalizza };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else Object.assign(root, api);
})(typeof self !== 'undefined' ? self : this);
