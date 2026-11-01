// Fotocamera, scanner barcode e OCR della scadenza (v2.1.0).
// Dipende da app.js (toast, esc, showScreen, scanMode, cercaProdotto...) e da
// scadenza.js (analizzaScadenza). Librerie in locale: vendor/zxing.min.js,
// vendor/tesseract/*.

// ── Controlli fotocamera: torcia, zoom, messa a fuoco continua ───────────────
const _cam = { scan: null, ocr: null };

async function preparaControlliCamera(chiave, stream) {
  const track = stream && stream.getVideoTracks && stream.getVideoTracks()[0];
  const ctrl = document.getElementById(chiave + '-ctrl');
  const btn = document.getElementById(chiave + '-torcia');
  const zoom = document.getElementById(chiave + '-zoom');
  _cam[chiave] = track ? { track, torcia: false } : null;
  if (!track || !ctrl) return;
  let caps = {};
  try { caps = track.getCapabilities ? track.getCapabilities() : {}; } catch (e) { caps = {}; }
  try {
    if ((caps.focusMode || []).includes('continuous')) await track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] });
  } catch (e) { /* non supportato: si va avanti */ }
  btn.style.display = caps.torch ? '' : 'none';
  btn.classList.remove('attivo');
  if (caps.zoom && caps.zoom.max > caps.zoom.min) {
    zoom.min = caps.zoom.min; zoom.max = caps.zoom.max; zoom.step = caps.zoom.step || 0.1;
    let corrente = caps.zoom.min;
    try { corrente = track.getSettings().zoom || corrente; } catch (e) {}
    zoom.value = corrente;
    zoom.style.display = '';
  } else {
    zoom.style.display = 'none';
  }
  ctrl.style.display = (caps.torch || caps.zoom) ? 'flex' : 'none';
}

function resetControlliCamera(chiave) {
  _cam[chiave] = null;
  const ctrl = document.getElementById(chiave + '-ctrl');
  if (ctrl) ctrl.style.display = 'none';
}

async function alternaTorcia(chiave) {
  const c = _cam[chiave];
  if (!c) return;
  const btn = document.getElementById(chiave + '-torcia');
  try {
    const nuova = !c.torcia;
    await c.track.applyConstraints({ advanced: [{ torch: nuova }] });
    c.torcia = nuova;
    btn.classList.toggle('attivo', nuova);
  } catch (e) {
    c.torcia = false; btn.classList.remove('attivo');
    toast('Torcia non disponibile');
  }
}

async function impostaZoom(chiave, valore) {
  const c = _cam[chiave];
  if (!c) return;
  try { await c.track.applyConstraints({ advanced: [{ zoom: parseFloat(valore) }] }); } catch (e) {}
}

// ── Validazione dei codici: checksum GTIN (EAN-13/8, UPC-A, UPC-E) ───────────
function gtinValido(c) {
  if (!/^(\d{8}|\d{12,14})$/.test(c)) return false;
  const cifre = c.split('').map(Number);
  const controllo = cifre.pop();
  let somma = 0;
  for (let i = cifre.length - 1, peso = 3; i >= 0; i--, peso = peso === 3 ? 1 : 3) somma += cifre[i] * peso;
  return ((10 - (somma % 10)) % 10) === controllo;
}

function upceInUpca(c) {
  const ns = c[0], d = c.slice(1, 7), chk = c[7];
  const u = d[5];
  let corpo;
  if ('012'.includes(u)) corpo = d[0] + d[1] + u + '0000' + d[2] + d[3] + d[4];
  else if (u === '3') corpo = d[0] + d[1] + d[2] + '00000' + d[3] + d[4];
  else if (u === '4') corpo = d[0] + d[1] + d[2] + d[3] + '00000' + d[4];
  else corpo = d[0] + d[1] + d[2] + d[3] + d[4] + '0000' + u;
  return ns + corpo + chk;
}

// Ritorna il codice normalizzato oppure null se non e' un codice prodotto valido
function normalizzaCodice(grezzo) {
  const c = String(grezzo || '').replace(/\s+/g, '');
  if (!/^\d+$/.test(c)) return null;
  if (gtinValido(c)) return c;
  if (c.length === 8 && (c[0] === '0' || c[0] === '1')) {
    const a = upceInUpca(c);
    if (gtinValido(a)) return a;
  }
  return null;
}

// Un codice vale solo se letto due volte di fila entro 1,5 s (evita le letture sbagliate)
let _ultimaLettura = { codice: null, n: 0, t: 0 };
function confermaLettura(grezzo) {
  const c = normalizzaCodice(grezzo);
  if (!c) return null;
  const ora = Date.now();
  if (_ultimaLettura.codice === c && ora - _ultimaLettura.t < 1500) _ultimaLettura.n++;
  else _ultimaLettura = { codice: c, n: 1, t: ora };
  _ultimaLettura.t = ora;
  return _ultimaLettura.n >= 2 ? c : null;
}

// ── Scansione continua ───────────────────────────────────────────────────────
function scanContinuoAttivo() {
  try { return localStorage.getItem('dispensa_scan_continuo') === '1'; } catch (e) { return false; }
}
function impostaScanContinuo(v) {
  try { localStorage.setItem('dispensa_scan_continuo', v ? '1' : '0'); } catch (e) {}
}
// Dopo aver salvato un prodotto: in modalita' continua si torna alla fotocamera
function dopoAggiunta() {
  if (scanMode === 'add' && scanContinuoAttivo()) showScreen('screen-scan');
  else showScreen('screen-inventario');
}

// ── Barcode scanner: BarcodeDetector nativo, ZXing come ripiego ──────────────
let _audioCtx = null;
function beep(freq = 900, duration = 100) {
  try {
    _audioCtx = _audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    if (_audioCtx.state === 'suspended') _audioCtx.resume();
    const osc = _audioCtx.createOscillator();
    const gain = _audioCtx.createGain();
    osc.frequency.value = freq;
    osc.connect(gain); gain.connect(_audioCtx.destination);
    gain.gain.setValueAtTime(0.1, _audioCtx.currentTime);
    osc.start(); osc.stop(_audioCtx.currentTime + duration / 1000);
  } catch (e) {}
}

// Ogni avvio ha un numero: se nel frattempo si esce dalla schermata (fermaScanner)
// il numero cambia e l'avvio in corso si ferma da solo, senza lasciare la fotocamera accesa.
let _scanToken = 0;
const FORMATI_NATIVI = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128'];

async function avviaScanner() {
  if (codeReader || barcodeDetectorActive) return;
  const token = ++_scanToken;
  const box = document.getElementById('scan-continuo-box');
  if (box) {
    box.style.display = scanMode === 'add' ? 'flex' : 'none';
    document.getElementById('scan-continuo').checked = scanContinuoAttivo();
  }
  _ultimaLettura = { codice: null, n: 0, t: 0 };
  const hasCamera = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  if (!hasCamera) {
    document.getElementById('video-container').style.display = 'none';
    document.getElementById('scan-foto-btn').style.display = 'block';
    document.getElementById('scan-status').textContent = scanMode === 'search' ? 'Scatta foto del barcode per cercarlo' : 'Scatta foto del barcode per aggiungerlo';
    return;
  }
  document.getElementById('video-container').style.display = '';
  document.getElementById('scan-foto-btn').style.display = 'none';
  document.getElementById('scan-status').className = 'scan-active';
  document.getElementById('scan-status').textContent = '📷 Avvio fotocamera...';

  if ('BarcodeDetector' in window) {
    try {
      const supportati = await BarcodeDetector.getSupportedFormats();
      if (token !== _scanToken) return;
      const formats = FORMATI_NATIVI.filter(f => supportati.includes(f));
      if (formats.length > 0) {
        await startNativeScanner(new BarcodeDetector({ formats }), token);
        return;
      }
    } catch (e) { console.warn('BarcodeDetector non utilizzabile, ripiego su ZXing:', e); }
  }
  if (token !== _scanToken) return;
  await startZXingScanner(token);
}

async function startNativeScanner(detector, token) {
  const video = document.getElementById('video');
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } }
    });
    if (token !== _scanToken) { stream.getTracks().forEach(t => t.stop()); return; }
    video.srcObject = stream;
    await video.play();
    if (token !== _scanToken) { stream.getTracks().forEach(t => t.stop()); video.srcObject = null; return; }
    barcodeDetectorActive = { stream };
    preparaControlliCamera('scan', stream);
    document.getElementById('scan-status').innerHTML = '<span class="scan-active">📷 Scansione attiva (nativa)</span>';

    const scan = async () => {
      if (!barcodeDetectorActive || token !== _scanToken) return;
      try {
        const codes = await detector.detect(video);
        for (const x of codes) {
          const c = confermaLettura(x.rawValue);
          if (c) { fermaScanner(); onBarcodeDetected(c); return; }
        }
      } catch (e) {}
      if (barcodeDetectorActive && token === _scanToken) requestAnimationFrame(scan);
    };
    requestAnimationFrame(scan);
  } catch (e) {
    document.getElementById('scan-status').textContent = '⚠️ Errore fotocamera: ' + e.message;
  }
}

function suggerimentiZXing() {
  const hints = new Map();
  hints.set(ZXing.DecodeHintType.POSSIBLE_FORMATS, [
    ZXing.BarcodeFormat.EAN_13, ZXing.BarcodeFormat.EAN_8,
    ZXing.BarcodeFormat.UPC_A, ZXing.BarcodeFormat.UPC_E,
    ZXing.BarcodeFormat.CODE_128,
  ]);
  hints.set(ZXing.DecodeHintType.TRY_HARDER, true);
  return hints;
}

async function startZXingScanner(token) {
  try {
    codeReader = new ZXing.BrowserMultiFormatReader(suggerimentiZXing(), 120);
    document.getElementById('scan-status').innerHTML = '<span class="scan-active">📷 Scansione attiva</span>';
    await codeReader.decodeFromConstraints(
      { video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } } },
      'video',
      (result) => {
        if (token !== _scanToken || !result) return;
        const c = confermaLettura(result.getText());
        if (c) { fermaScanner(); onBarcodeDetected(c); }
      });
    if (token !== _scanToken) { fermaScanner(); return; }
    preparaControlliCamera('scan', document.getElementById('video').srcObject);
  } catch (e) {
    document.getElementById('scan-status').textContent = '⚠️ Errore: ' + e.message;
  }
}

function onBarcodeDetected(ean) {
  navigator.vibrate?.(150);
  beep();
  document.getElementById('scan-status').className = 'scan-found';
  document.getElementById('scan-status').innerHTML = `✅ Codice letto: <code>${esc(ean)}</code>`;
  setTimeout(() => {
    if (scanMode === 'search') cercaNellaDispensa(ean);
    else cercaProdotto(ean);
  }, 250);
}

function fermaScanner() {
  _scanToken++;
  if (codeReader) { try { codeReader.reset(); } catch (e) {} codeReader = null; }
  if (barcodeDetectorActive) {
    try { barcodeDetectorActive.stream?.getTracks().forEach(t => t.stop()); } catch (e) {}
    barcodeDetectorActive = false;
  }
  const video = document.getElementById('video');
  if (video && video.srcObject) {
    try { video.srcObject.getTracks().forEach(t => t.stop()); } catch (e) {}
    video.srcObject = null;
  }
  resetControlliCamera('scan');
}

// Barcode da una foto: prima il rilevatore nativo, poi ZXing (anche su versione ridotta)
async function scansionaFoto(input) {
  const file = input.files[0];
  if (!file) return;
  input.value = '';
  const status = document.getElementById('scan-status');
  status.textContent = 'Analisi barcode in corso...';
  const imgUrl = URL.createObjectURL(file);
  let codice = null;
  try {
    const img = await new Promise((ok, ko) => { const i = new Image(); i.onload = () => ok(i); i.onerror = ko; i.src = imgUrl; });
    if ('BarcodeDetector' in window) {
      try {
        const det = new BarcodeDetector({ formats: FORMATI_NATIVI });
        for (const x of await det.detect(img)) { codice = normalizzaCodice(x.rawValue); if (codice) break; }
      } catch (e) {}
    }
    for (const lato of [0, 1600, 900]) {
      if (codice) break;
      let url = imgUrl, extra = null;
      if (lato) {
        const k = Math.min(1, lato / Math.max(img.width, img.height));
        const cv = document.createElement('canvas');
        cv.width = Math.round(img.width * k); cv.height = Math.round(img.height * k);
        cv.getContext('2d').drawImage(img, 0, 0, cv.width, cv.height);
        const blob = await new Promise(r => cv.toBlob(r, 'image/jpeg', 0.92));
        url = extra = URL.createObjectURL(blob);
      }
      try {
        const reader = new ZXing.BrowserMultiFormatReader(suggerimentiZXing());
        codice = normalizzaCodice((await reader.decodeFromImageUrl(url)).getText());
      } catch (e) {}
      if (extra) URL.revokeObjectURL(extra);
    }
  } catch (e) {}
  URL.revokeObjectURL(imgUrl);
  if (codice) onBarcodeDetected(codice);
  else { status.textContent = '⚠️ Barcode non riconosciuto'; toast('Barcode non riconosciuto, riprova'); }
}

// ── OCR della scadenza ───────────────────────────────────────────────────────
const OCR_FRAME = { l: 0.84, a: 0.30 };       // cornice verde, in frazione del video (vedi #ocr-cornice)
const OCR_CARATTERI = '0123456789/-.: ABCDEFGHIJKLMNOPQRSTUVWXYZ';
let ocrStream = null;
let _ocrToken = 0;
let _ocrWorkerPromise = null;
let _ocrDismettiTimer = null;
let _ocrBusy = false;
let _ocrTimer = null;
let _ocrTentativi = 0;
let _ocrUltimo = null;
let _ocrRisultato = false;

function ocrUrl(p) { return new URL(p, document.baseURI).href; }

function ocrWorker() {
  if (_ocrDismettiTimer) { clearTimeout(_ocrDismettiTimer); _ocrDismettiTimer = null; }
  if (!_ocrWorkerPromise) {
    _ocrWorkerPromise = (async () => {
      const w = await Tesseract.createWorker('eng', Tesseract.OEM.LSTM_ONLY, {
        workerPath: ocrUrl('vendor/tesseract/worker.min.js'),
        corePath: ocrUrl('vendor/tesseract'),
        langPath: ocrUrl('vendor/tesseract/lang'),
        logger: () => {},
      });
      await w.setParameters({
        tessedit_char_whitelist: OCR_CARATTERI,
        tessedit_pageseg_mode: Tesseract.PSM.SINGLE_BLOCK,
        preserve_interword_spaces: '1',
        user_defined_dpi: '300',
      });
      return w;
    })().catch(e => { _ocrWorkerPromise = null; throw e; });
  }
  return _ocrWorkerPromise;
}

function dismettiOCRWorker() {
  const p = _ocrWorkerPromise;
  _ocrWorkerPromise = null;
  if (p) p.then(w => w.terminate()).catch(() => {});
}

function avviaOCRScadenza() {
  const token = ++_ocrToken;
  document.getElementById('ocr-modal').style.display = 'flex';
  document.getElementById('ocr-manuale').style.display = 'none';
  document.getElementById('ocr-risultato').style.display = 'none';
  document.getElementById('ocr-testo-letto').textContent = '';
  document.getElementById('ocr-status').textContent = 'Avvio fotocamera...';
  _ocrTentativi = 0; _ocrUltimo = null; _ocrRisultato = false; _ocrBusy = false;
  ocrWorker().catch(e => console.warn('OCR non disponibile:', e));   // precarica mentre parte la fotocamera
  if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) {
    document.getElementById('ocr-status').textContent = 'Fotocamera non disponibile (serve HTTPS). Inserisci la data a mano.';
    document.getElementById('ocr-manuale').style.display = 'block';
    return;
  }
  navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } } })
    .then(stream => {
      if (token !== _ocrToken) { stream.getTracks().forEach(t => t.stop()); return; }
      ocrStream = stream;
      document.getElementById('ocr-video').srcObject = stream;
      preparaControlliCamera('ocr', stream);
      document.getElementById('ocr-status').textContent = 'Inquadra la data nella cornice verde: la leggo da sola';
      pianificaOCR(token, 1200);
    }).catch(err => { document.getElementById('ocr-status').textContent = 'Errore fotocamera: ' + err.message; });
}

function chiudiOCR() {
  _ocrToken++;
  if (_ocrTimer) { clearTimeout(_ocrTimer); _ocrTimer = null; }
  if (ocrStream) { ocrStream.getTracks().forEach(t => t.stop()); ocrStream = null; }
  resetControlliCamera('ocr');
  document.getElementById('ocr-modal').style.display = 'none';
  document.getElementById('ocr-risultato').style.display = 'none';
  // libera la memoria del motore OCR se non serve piu' (si ricarica in un attimo dalla cache)
  if (_ocrDismettiTimer) clearTimeout(_ocrDismettiTimer);
  _ocrDismettiTimer = setTimeout(dismettiOCRWorker, 60000);
}

function pianificaOCR(token, ms) {
  if (_ocrTimer) clearTimeout(_ocrTimer);
  _ocrTimer = setTimeout(() => cicloOCR(token), ms);
}

// Lettura automatica: ogni mezzo secondo prova sul fotogramma corrente.
// Si ferma quando trova una data con parola chiave di scadenza, o la stessa data due volte di fila.
async function cicloOCR(token) {
  if (token !== _ocrToken || _ocrRisultato) return;
  if (_ocrBusy || document.hidden) { pianificaOCR(token, 800); return; }
  if (++_ocrTentativi > 45) {
    document.getElementById('ocr-status').textContent = 'Non riesco a leggerla: premi Scatta o inseriscila a mano';
    document.getElementById('ocr-manuale').style.display = 'block';
    return;
  }
  _ocrBusy = true;
  try {
    const esito = await leggiScadenzaDalVideo(false, _ocrTentativi);
    if (token !== _ocrToken) return;
    if (esito && esito.candidati.length) {
      const top = esito.candidati[0];
      if (top.parolaChiave === 'scad' || _ocrUltimo === top.iso) { mostraRisultatoOCR(esito); return; }
      _ocrUltimo = top.iso;
    } else {
      _ocrUltimo = null;
    }
  } catch (e) {
    console.warn('OCR:', e);
  } finally {
    _ocrBusy = false;
  }
  pianificaOCR(token, 500);
}

// Ritaglia la cornice verde dal fotogramma
function ritagliaCornice(video) {
  const vw = video.videoWidth, vh = video.videoHeight;
  const cw = vw * OCR_FRAME.l * 1.08, ch = vh * OCR_FRAME.a * 1.12;     // un po' di margine
  const sx = Math.max(0, (vw - cw) / 2), sy = Math.max(0, (vh - ch) / 2);
  const w = Math.min(vw - sx, cw), h = Math.min(vh - sy, ch);
  const scala = Math.min(3, Math.max(1, 1000 / w));
  const cv = document.createElement('canvas');
  cv.width = Math.round(w * scala); cv.height = Math.round(h * scala);
  const ctx = cv.getContext('2d', { willReadFrequently: true });
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(video, sx, sy, w, h, 0, 0, cv.width, cv.height);
  return cv;
}

// Scala di grigi con contrasto allargato (percentili 2%-98%)
function grigiContrasto(cv) {
  const w = cv.width, h = cv.height;
  const d = cv.getContext('2d', { willReadFrequently: true }).getImageData(0, 0, w, h).data;
  const g = new Uint8ClampedArray(w * h);
  const istog = new Uint32Array(256);
  for (let i = 0, j = 0; i < d.length; i += 4, j++) {
    const v = (0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]) | 0;
    g[j] = v; istog[v]++;
  }
  const tot = w * h;
  let acc = 0, lo = 0, hi = 255;
  for (let v = 0; v < 256; v++) { acc += istog[v]; if (acc >= tot * 0.02) { lo = v; break; } }
  acc = 0;
  for (let v = 255; v >= 0; v--) { acc += istog[v]; if (acc >= tot * 0.02) { hi = v; break; } }
  const range = Math.max(1, hi - lo);
  for (let j = 0; j < g.length; j++) g[j] = Math.max(0, Math.min(255, ((g[j] - lo) * 255) / range));
  return { g, w, h };
}

function inCanvas(g, w, h) {
  const cv = document.createElement('canvas');
  cv.width = w; cv.height = h;
  const ctx = cv.getContext('2d');
  const img = ctx.createImageData(w, h);
  for (let j = 0, i = 0; j < g.length; j++, i += 4) { img.data[i] = img.data[i + 1] = img.data[i + 2] = g[j]; img.data[i + 3] = 255; }
  ctx.putImageData(img, 0, 0);
  return cv;
}

// Testo scuro su fondo chiaro: se la maggioranza e' nera si inverte (scritte bianche su fondo scuro)
function allineaPolarita(out) {
  let neri = 0;
  for (let j = 0; j < out.length; j++) if (out[j] === 0) neri++;
  if (neri > out.length * 0.5) for (let j = 0; j < out.length; j++) out[j] = 255 - out[j];
}

// Soglia locale (Bradley): regge luce irregolare e confezioni curve
function sogliaAdattiva({ g: grigi, w, h }) {
  // La scritta e' la classe di pixel meno numerosa (Otsu): se e' quella chiara, si inverte prima di
  // cercare il "più scuro della media locale". La mediana non basta: dopo l'allargamento del contrasto
  // un fondo scuro puo' coprire tutta la scala.
  const soglia = valoreOtsu(grigi);
  let sopra = 0;
  for (let j = 0; j < grigi.length; j++) if (grigi[j] > soglia) sopra++;
  let g = grigi;
  if (sopra < grigi.length - sopra) { g = new Uint8ClampedArray(grigi.length); for (let j = 0; j < g.length; j++) g[j] = 255 - grigi[j]; }
  const integrale = new Uint32Array((w + 1) * (h + 1));
  for (let y = 1; y <= h; y++) {
    let riga = 0;
    for (let x = 1; x <= w; x++) {
      riga += g[(y - 1) * w + (x - 1)];
      integrale[y * (w + 1) + x] = integrale[(y - 1) * (w + 1) + x] + riga;
    }
  }
  const s = Math.max(15, (w / 8) | 0), mezzo = s >> 1, t = 0.25;
  const out = new Uint8ClampedArray(w * h);
  for (let y = 0; y < h; y++) {
    const y1 = Math.max(0, y - mezzo), y2 = Math.min(h - 1, y + mezzo);
    for (let x = 0; x < w; x++) {
      const x1 = Math.max(0, x - mezzo), x2 = Math.min(w - 1, x + mezzo);
      const n = (x2 - x1 + 1) * (y2 - y1 + 1);
      const somma = integrale[(y2 + 1) * (w + 1) + (x2 + 1)] - integrale[y1 * (w + 1) + (x2 + 1)]
        - integrale[(y2 + 1) * (w + 1) + x1] + integrale[y1 * (w + 1) + x1];
      // valore del pixel = media 3x3 (smorza il rumore del sensore, che l'allargamento del contrasto amplifica)
      const a1 = Math.max(0, x - 1), a2 = Math.min(w - 1, x + 1), b1 = Math.max(0, y - 1), b2 = Math.min(h - 1, y + 1);
      const pix = (integrale[(b2 + 1) * (w + 1) + (a2 + 1)] - integrale[b1 * (w + 1) + (a2 + 1)]
        - integrale[(b2 + 1) * (w + 1) + a1] + integrale[b1 * (w + 1) + a1]) / ((a2 - a1 + 1) * (b2 - b1 + 1));
      // nero solo se piu' scuro della media locale E con un contrasto minimo: sui fondi uniformi
      // la sola soglia relativa riempirebbe tutto di puntini
      out[y * w + x] = (pix * n < somma * (1 - t) && somma / n - pix > 40) ? 0 : 255;
    }
  }
  allineaPolarita(out);
  return inCanvas(out, w, h);
}

// Valore di soglia di Otsu (massimizza la varianza tra le due classi di pixel)
function valoreOtsu(g) {
  const istog = new Uint32Array(256);
  for (let j = 0; j < g.length; j++) istog[g[j]]++;
  const tot = g.length;
  let sommaTot = 0;
  for (let v = 0; v < 256; v++) sommaTot += v * istog[v];
  let sB = 0, wB = 0, migliore = 0, soglia = 128;
  for (let v = 0; v < 256; v++) {
    wB += istog[v]; if (!wB) continue;
    const wF = tot - wB; if (!wF) break;
    sB += v * istog[v];
    const mB = sB / wB, mF = (sommaTot - sB) / wF;
    const varianza = wB * wF * (mB - mF) * (mB - mF);
    if (varianza > migliore) { migliore = varianza; soglia = v; }
  }
  return soglia;
}

// Soglia globale di Otsu
function sogliaOtsu({ g, w, h }) {
  const soglia = valoreOtsu(g);
  const out = new Uint8ClampedArray(g.length);
  for (let j = 0; j < g.length; j++) out[j] = g[j] > soglia ? 255 : 0;
  allineaPolarita(out);
  return inCanvas(out, w, h);
}

// In ordine di affidabilita' (prova su immagini con luce irregolare, rumore e scritte chiare su fondo scuro)
const OCR_VARIANTI = [
  g => inCanvas(g.g, g.w, g.h),       // solo grigi con contrasto
  g => sogliaOtsu(g),
  g => sogliaAdattiva(g),
];

// completo=false: una sola variante, a rotazione tra un tentativo e l'altro (lettura automatica);
// completo=true: tutte, finche' non trova una data con parola chiave (pulsante «Scatta»)
async function leggiScadenzaDalVideo(completo, giro = 0) {
  const video = document.getElementById('ocr-video');
  if (!video.videoWidth) return null;
  const grigi = grigiContrasto(ritagliaCornice(video));
  const worker = await ocrWorker();
  const per = new Map();
  const testi = [];
  for (const variante of (completo ? OCR_VARIANTI : [OCR_VARIANTI[giro % OCR_VARIANTI.length]])) {
    const r = await worker.recognize(variante(grigi));
    const testo = r.data.text || '';
    testi.push(testo.replace(/\s+/g, ' ').trim());
    const cand = analizzaScadenza(testo);
    for (const c of cand) {
      const prec = per.get(c.iso);
      if (!prec || c.punteggio > prec.punteggio) per.set(c.iso, c);
    }
    if (cand.length && cand[0].parolaChiave === 'scad') break;
  }
  const candidati = [...per.values()].sort((a, b) => b.punteggio - a.punteggio);
  return { candidati, testo: testi.filter(Boolean).join(' | ') };
}

function mostraRisultatoOCR(esito) {
  _ocrRisultato = true;
  if (_ocrTimer) { clearTimeout(_ocrTimer); _ocrTimer = null; }
  navigator.vibrate?.(80);
  const [top, ...altri] = esito.candidati;
  document.getElementById('ocr-status').textContent = 'Ho letto: «' + top.grezzo + '»';
  document.getElementById('ocr-testo-letto').textContent = esito.testo.substring(0, 100);
  let html = `<button type="button" class="ocr-chip principale" onclick="usaDataOCR(${jsArg(top.iso)})">✓ Usa ${esc(formatDataIT(top.iso))}</button>`;
  altri.slice(0, 3).forEach(c => { html += `<button type="button" class="ocr-chip" onclick="usaDataOCR(${jsArg(c.iso)})">${esc(formatDataIT(c.iso))}</button>`; });
  html += '<button type="button" class="ocr-chip" onclick="riprovaOCR()">↻ Riprova</button>';
  const box = document.getElementById('ocr-risultato');
  box.innerHTML = html;
  box.style.display = 'block';
}

function usaDataOCR(iso) {
  document.getElementById('conf-scadenza').value = iso;
  chiudiOCR();
  toast('✅ Scadenza impostata: ' + formatDataIT(iso));
}

function riprovaOCR() {
  document.getElementById('ocr-risultato').style.display = 'none';
  document.getElementById('ocr-testo-letto').textContent = '';
  document.getElementById('ocr-status').textContent = 'Inquadra la data nella cornice verde: la leggo da sola';
  _ocrRisultato = false; _ocrUltimo = null; _ocrTentativi = 0;
  pianificaOCR(_ocrToken, 300);
}

// Pulsante «Scatta»: legge il fotogramma con tutte le varianti di preparazione
async function scattaFotoOCR() {
  const token = _ocrToken;
  if (_ocrTimer) { clearTimeout(_ocrTimer); _ocrTimer = null; }
  const stato = document.getElementById('ocr-status');
  document.getElementById('ocr-risultato').style.display = 'none';
  _ocrRisultato = false;
  stato.textContent = '🔍 Elaborazione...';
  while (_ocrBusy && token === _ocrToken) await new Promise(r => setTimeout(r, 100));
  _ocrBusy = true;
  try {
    const esito = await leggiScadenzaDalVideo(true);
    if (token !== _ocrToken) return;
    if (esito && esito.candidati.length) {
      mostraRisultatoOCR(esito);
    } else {
      stato.textContent = '⚠️ Data non rilevata.';
      document.getElementById('ocr-testo-letto').textContent = esito ? esito.testo.substring(0, 100) : '';
      document.getElementById('ocr-manuale').style.display = 'block';
      _ocrTentativi = 0;
      pianificaOCR(token, 1500);
    }
  } catch (e) {
    stato.textContent = '⚠️ Errore OCR.';
    document.getElementById('ocr-manuale').style.display = 'block';
  } finally {
    _ocrBusy = false;
  }
}

function confermaManualeOCR() {
  const input = document.getElementById('ocr-input-manuale').value.trim();
  const data = estraiDataScadenza(input);
  if (data) usaDataOCR(data);
  else document.getElementById('ocr-status').textContent = '⚠️ Formato non riconosciuto.';
}

// ── Suggerimenti alla conferma del prodotto ──────────────────────────────────
function isoLocale(d) {
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

// Posizione e scadenza proposte: dal server (storico dello stesso prodotto, poi categoria);
// se non c'e' nulla di affidabile la data resta vuota invece di inventarne una.
function suggerimentoPer(p) {
  const s = p.suggerimento;
  let posizione, giorni, nota;
  if (s) {
    posizione = s.posizione || 'Dispensa';
    giorni = s.scadenza_giorni;
    if (giorni != null) {
      nota = s.fonte === 'storico'
        ? `Suggerita dal tuo storico (${s.campioni} ${s.campioni === 1 ? 'acquisto' : 'acquisti'}): ${giorni} giorni dall'acquisto`
        : `Stima dalla categoria: ${giorni} giorni. Controlla la confezione`;
    }
  } else {
    const loc = suggerisciDaCategoria(p.categoria);
    posizione = loc.posizione;
    giorni = loc.giorni;
    if (giorni != null) nota = `Stima dalla categoria: ${giorni} giorni. Controlla la confezione`;
  }
  if (giorni == null) return { posizione, scadenza: '', nota: 'Scadenza non suggerita: scansionala con 📷 o inseriscila' };
  const d = new Date();
  d.setDate(d.getDate() + giorni);
  return { posizione, scadenza: isoLocale(d), nota };
}

// ── «Aperto oggi»: dopo l'apertura la scadenza si accorcia ───────────────────
const GIORNI_DOPO_APERTURA = [
  [/latte|milk/, 3], [/yogurt|yoghurt/, 3], [/panna|cream|besciamella/, 3],
  [/mozzarella|ricotta|mascarpone|burrata|fresh.?chees/, 3], [/formagg|chees/, 5], [/burro|butter/, 14],
  [/affettat|salum|prosciutt|\bham\b|cold.?cuts|wurstel|sausage/, 3],
  [/carne|meat|pollo|chicken|hamburger|pesce|fish/, 2],
  [/succo|juice|spremut/, 4], [/sugo|salsa|sauce|pesto|passata|pelati|tomato/, 4],
  [/tonno|tuna|conserv|canned|legum|beans|mais|sweetcorn/, 2],
  [/maionese|mayonnaise|ketchup|senape|mustard/, 60], [/marmellata|jam|nutella|spread/, 30],
];
function giorniDopoApertura(p) {
  const testo = ((p.categoria || '') + ' ' + (p.nome || '')).toLowerCase();
  for (const [re, g] of GIORNI_DOPO_APERTURA) if (re.test(testo)) return g;
  return 5;
}

async function segnaAperto(id) {
  const p = prodottiCache.find(x => x.id === id);
  if (!p) return;
  const giorni = giorniDopoApertura(p);
  const limite = new Date();
  limite.setDate(limite.getDate() + giorni);
  const limiteIso = isoLocale(limite);
  const scadVecchia = p.scadenza || null;
  const noteVecchie = p.note || '';
  const scadNuova = scadVecchia && scadVecchia <= limiteIso ? scadVecchia : limiteIso;
  const oggi = new Date();
  const marcatore = 'Aperto il ' + String(oggi.getDate()).padStart(2, '0') + '/' + String(oggi.getMonth() + 1).padStart(2, '0');
  const noteNuove = noteVecchie.includes('Aperto il') ? noteVecchie : (noteVecchie ? noteVecchie + ' · ' : '') + marcatore;
  try {
    const r = await apiFetch(`${API_BASE()}/api/prodotti/${id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scadenza: scadNuova, note: noteNuove }),
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
  } catch (e) { toast('Errore, riprova'); return; }
  showScreen('screen-inventario');
  toastUndo(scadNuova === scadVecchia ? 'Segnato come aperto' : `Aperto: scade ${formatDataIT(scadNuova)}`, async () => {
    await apiFetch(`${API_BASE()}/api/prodotti/${id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scadenza: scadVecchia, note: noteVecchie, _skip_log: true }),
    });
    caricaInventario();
  }, 6000);
}
