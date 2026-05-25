const API_BASE = () => {
  const u = document.querySelector('meta[name="cf-url"]')?.content || '';
  return u || window.location.pathname.replace(/\/+$/g, '');
};

// ── Auth helpers ──────────────────────────────────────────────────────────────
const AUTH_KEY = 'dispensa_access';
const REFRESH_KEY = 'dispensa_refresh';
const USER_KEY = 'dispensa_user';

function getAccessToken() { return localStorage.getItem(AUTH_KEY) || ''; }
function getRefreshToken() { return localStorage.getItem(REFRESH_KEY) || ''; }
function getCurrentUser() { try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null'); } catch { return null; } }

function saveAuth({ access_token, refresh_token, username, is_admin }) {
  localStorage.setItem(AUTH_KEY, access_token);
  if (refresh_token) localStorage.setItem(REFRESH_KEY, refresh_token);
  localStorage.setItem(USER_KEY, JSON.stringify({ username, is_admin }));
}

function clearAuth() {
  localStorage.removeItem(AUTH_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
}

async function tryRefreshToken() {
  const rt = getRefreshToken();
  if (!rt) return false;
  try {
    const r = await fetch(API_BASE() + '/api/auth/refresh', { method: 'POST', headers: { 'Authorization': 'Bearer ' + rt } });
    if (!r.ok) return false;
    const data = await r.json();
    localStorage.setItem(AUTH_KEY, data.access_token);
    return true;
  } catch { return false; }
}

async function apiFetch(url, opts = {}) {
  const jwt = getAccessToken();
  const headers = Object.assign({}, opts.headers || {});
  if (jwt) headers['Authorization'] = 'Bearer ' + jwt;
  opts.headers = headers;
  let r = await fetch(url, opts);
  if (r.status === 401) {
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      opts.headers['Authorization'] = 'Bearer ' + getAccessToken();
      r = await fetch(url, opts);
    }
    if (r.status === 401) {
      clearAuth();
      showLoginOverlay();
      throw new Error('Sessione scaduta – effettua nuovamente il login');
    }
  }
  return r;
}

async function doLogin() {
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  const errEl = document.getElementById('login-error');
  errEl.textContent = '';
  if (!username || !password) { errEl.textContent = 'Inserisci username e password'; return; }
  try {
    const r = await fetch(API_BASE() + '/api/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    const data = await r.json();
    if (!r.ok) { errEl.textContent = data.error || 'Credenziali non valide'; return; }
    saveAuth(data);
    hideLoginOverlay();
    applyUserUI();
    caricaInventario();
  } catch (e) { errEl.textContent = 'Errore di rete – riprova'; }
}

function showLoginOverlay() {
  document.getElementById('login-overlay').classList.remove('hidden');
  document.getElementById('login-password').value = '';
  document.getElementById('login-error').textContent = '';
}
function hideLoginOverlay() { document.getElementById('login-overlay').classList.add('hidden'); }
function doLogout() { clearAuth(); showLoginOverlay(); }

function applyUserUI() {
  const user = getCurrentUser();
  if (!user) return;
  document.querySelectorAll('.tab-admin').forEach(el => { el.style.display = user.is_admin ? 'flex' : 'none'; });
  const el = document.getElementById('current-username');
  if (el) el.textContent = user.username + (user.is_admin ? ' (admin)' : '');
}

async function initAuth() {
  if (!getAccessToken()) { showLoginOverlay(); return; }
  try {
    const r = await fetch(API_BASE() + '/api/auth/me', { headers: { 'Authorization': 'Bearer ' + getAccessToken() } });
    if (r.ok) {
      const me = await r.json();
      saveAuth({ access_token: getAccessToken(), username: me.username, is_admin: me.is_admin });
      hideLoginOverlay(); applyUserUI(); return;
    }
    const refreshed = await tryRefreshToken();
    if (refreshed) { hideLoginOverlay(); applyUserUI(); }
    else { clearAuth(); showLoginOverlay(); }
  } catch { hideLoginOverlay(); applyUserUI(); }
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('login-password')?.addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
  document.getElementById('login-username')?.addEventListener('keydown', e => { if (e.key === 'Enter') document.getElementById('login-password')?.focus(); });
});

// ── PWA install ──────────────────────────────────────────────────────────────
let deferredInstallPrompt = null;
function isStandalonePWA() {
  return window.matchMedia('(display-mode: standalone)').matches
      || window.matchMedia('(display-mode: fullscreen)').matches
      || window.navigator.standalone === true;
}
window.addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); deferredInstallPrompt = e; updatePWAInstallUI(); });
window.addEventListener('appinstalled', () => { deferredInstallPrompt = null; toast('✅ App installata!'); updatePWAInstallUI(); });

function updatePWAInstallUI() {
  const installedInfo = document.getElementById('pwa-status-installed');
  const installBtn = document.getElementById('install-pwa-btn');
  const helpBtn = document.getElementById('install-pwa-help-btn');
  if (!installedInfo || !installBtn || !helpBtn) return;
  if (isStandalonePWA()) { installedInfo.style.display = 'block'; installBtn.style.display = 'none'; helpBtn.style.display = 'none'; }
  else if (deferredInstallPrompt) { installedInfo.style.display = 'none'; installBtn.style.display = 'block'; helpBtn.style.display = 'none'; }
  else { installedInfo.style.display = 'none'; installBtn.style.display = 'none'; helpBtn.style.display = 'block'; }
}

async function installaPWA() {
  if (!deferredInstallPrompt) { mostraIstruzioniInstall(); return; }
  deferredInstallPrompt.prompt();
  const { outcome } = await deferredInstallPrompt.userChoice;
  toast(outcome === 'accepted' ? '⏳ Installazione in corso...' : 'Installazione annullata');
  deferredInstallPrompt = null; updatePWAInstallUI();
}

function mostraIstruzioniInstall() {
  const ua = navigator.userAgent;
  const isIOS = /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
  const isAndroid = /Android/.test(ua);
  const isFirefox = /Firefox/.test(ua);
  const isChrome = /Chrome|CriOS/.test(ua) && !/Edg/.test(ua);
  let html = '';
  if (isIOS) html = `<p><strong>iOS (Safari):</strong></p><ol style="margin-left:18px;"><li>Tocca <strong>Condividi</strong> ⬆️</li><li><strong>"Aggiungi alla schermata Home"</strong></li></ol>`;
  else if (isAndroid && isChrome) html = `<p><strong>Android (Chrome):</strong></p><ol style="margin-left:18px;"><li>Menu <strong>⋮</strong></li><li><strong>"Installa app"</strong></li></ol>`;
  else if (isFirefox) html = `<p><strong>Firefox:</strong></p><ol style="margin-left:18px;"><li>Menu <strong>⋮</strong></li><li><strong>"Installa"</strong></li></ol>`;
  else html = `<p>Apri menu browser → cerca <strong>"Installa app"</strong>.</p>`;
  document.getElementById('modal-install-content').innerHTML = html;
  openModal('modal-install-help');
}
setTimeout(updatePWAInstallUI, 1500);

// ── State ────────────────────────────────────────────────────────────────────
let codeReader = null;
let barcodeDetectorActive = false;
let prodottoCorrente = {};
let qtyCorrente = 1;
let fotoBase64 = null;
let prodottiCache = [];
let scanMode = 'add';
let filtroAttivo = 'tutti';
let modProdottoId = null;
let modQtyCorrente = 1;
let detQtyDelta = 1;
let esauritiOpen = false;

// Bulk mode state
let bulkMode = false;
let bulkSelected = new Set();

function showScreen(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  // Exit bulk mode quando lasciamo inventario
  if (id !== 'screen-inventario' && bulkMode) exitBulkMode();
  if (id === 'screen-inventario') caricaInventario();
  if (id === 'screen-spesa') caricaListaSpesa();
  if (id === 'screen-statistiche') caricaStatistiche();
  if (id === 'screen-scan') avviaScanner();
  else fermaScanner();
}

function showTab(tab) {
  if (tab === 'inventario') showScreen('screen-inventario');
  else if (tab === 'scan') { scanMode = 'add'; showScreen('screen-scan'); }
  else if (tab === 'spesa') showScreen('screen-spesa');
  else if (tab === 'statistiche') showScreen('screen-statistiche');
  else if (tab === 'impostazioni') { showScreen('screen-impostazioni'); applyUserUI(); updatePWAInstallUI(); }
  else if (tab === 'admin') { showScreen('screen-admin'); caricaAdmin(); }
}

function toast(msg, durata = 2500) {
  const t = document.getElementById('toast');
  if (_undoTimer) { clearTimeout(_undoTimer); _undoTimer = null; _undoFn = null; }
  t.classList.remove('with-undo'); t.innerHTML = ''; t.textContent = msg;
  t.classList.add('show'); setTimeout(() => t.classList.remove('show'), durata);
}

let _undoTimer = null;
let _undoFn = null;
function toastUndo(msg, undoFn, durata = 4000) {
  const t = document.getElementById('toast');
  if (_undoTimer) { clearTimeout(_undoTimer); _undoTimer = null; }
  _undoFn = undoFn;
  t.innerHTML = `<span>${msg}</span><button class="toast-undo-btn" onclick="_eseguiUndo()">Annulla</button>`;
  t.classList.add('show', 'with-undo');
  _undoTimer = setTimeout(() => { t.classList.remove('show', 'with-undo'); _undoFn = null; _undoTimer = null; }, durata);
}
async function _eseguiUndo() {
  if (!_undoFn) return;
  const fn = _undoFn; _undoFn = null;
  if (_undoTimer) { clearTimeout(_undoTimer); _undoTimer = null; }
  document.getElementById('toast').classList.remove('show', 'with-undo');
  await fn(); toast('Annullato ✓');
}

async function caricaInventario() {
  try {
    const r = await apiFetch(`${API_BASE()}/api/prodotti`);
    prodottiCache = await r.json();
    applicaFiltroSort();
  } catch(e) {
    document.getElementById('lista-prodotti').innerHTML = `<div class="empty"><div class="empty-icon">⚠️</div><div>Backend non raggiungibile.</div></div>`;
  }
}

function setFiltro(f) {
  filtroAttivo = f;
  document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
  document.querySelector(`.chip[data-filtro="${f}"]`).classList.add('active');
  applicaFiltroSort();
}

let _searchTimer = null;
function ricercaDebounce() { if (_searchTimer) clearTimeout(_searchTimer); _searchTimer = setTimeout(applicaFiltroSort, 200); }

function applicaFiltroSort() {
  const q = (document.getElementById('ricerca-input')?.value || '').toLowerCase().trim();
  const ord = document.getElementById('sort-select')?.value || 'inserimento';
  const giorniAlert = parseInt(localStorage.getItem('dispensa_giorni') || '3');
  const oggi = new Date(); oggi.setHours(0,0,0,0);

  let attivi = prodottiCache.filter(p => p.quantita > 0);
  let esauriti = prodottiCache.filter(p => p.quantita <= 0);

  if (filtroAttivo === 'scadenza') {
    attivi = attivi.filter(p => { if (!p.scadenza) return false; const gg = Math.round((new Date(p.scadenza) - oggi) / 86400000); return gg >= 0 && gg <= giorniAlert; });
    esauriti = [];
  } else if (filtroAttivo === 'scaduti') {
    attivi = attivi.filter(p => { if (!p.scadenza) return false; const gg = Math.round((new Date(p.scadenza) - oggi) / 86400000); return gg < 0; });
    esauriti = [];
  } else if (filtroAttivo === 'frigo') { attivi = attivi.filter(p => p.posizione === 'Frigo'); esauriti = esauriti.filter(p => p.posizione === 'Frigo'); }
  else if (filtroAttivo === 'freezer') { attivi = attivi.filter(p => p.posizione === 'Freezer'); esauriti = esauriti.filter(p => p.posizione === 'Freezer'); }
  else if (filtroAttivo === 'dispensa') { attivi = attivi.filter(p => p.posizione === 'Dispensa'); esauriti = esauriti.filter(p => p.posizione === 'Dispensa'); }

  if (q) {
    attivi = attivi.filter(p => (p.nome||'').toLowerCase().includes(q) || (p.marca||'').toLowerCase().includes(q) || (p.posizione||'').toLowerCase().includes(q));
    esauriti = esauriti.filter(p => (p.nome||'').toLowerCase().includes(q) || (p.marca||'').toLowerCase().includes(q));
  }

  if (ord === 'nome') attivi.sort((a,b) => (a.nome||'').localeCompare(b.nome||''));
  else if (ord === 'quantita') attivi.sort((a,b) => b.quantita - a.quantita);
  else if (ord === 'scadenza') attivi.sort((a,b) => {
    if (!a.scadenza && !b.scadenza) return 0;
    if (!a.scadenza) return 1; if (!b.scadenza) return -1;
    return new Date(a.scadenza) - new Date(b.scadenza);
  });
  esauriti.sort((a,b) => (a.nome||'').localeCompare(b.nome||''));

  renderInventario(attivi, esauriti);
}

function avviaScannerRicerca() { scanMode = 'search'; showScreen('screen-scan'); }

function cercaNellaDispensa(ean) {
  const trovato = prodottiCache.find(p => p.ean === ean);
  showScreen('screen-inventario');
  if (trovato) apriDettaglio(trovato.id);
  else toast('Prodotto non trovato in dispensa');
}

async function consumaRapido(id, qtyAttuali) {
  const nuova = Math.max(0, qtyAttuali - 1);
  await apiFetch(`${API_BASE()}/api/prodotti/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({quantita: nuova}) });
  const p = prodottiCache.find(x => x.id === id);
  if (p) p.quantita = nuova;
  applicaFiltroSort();
  toastUndo('−1', async () => {
    await apiFetch(`${API_BASE()}/api/prodotti/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({quantita: qtyAttuali, _skip_log: true}) });
    const p2 = prodottiCache.find(x => x.id === id);
    if (p2) p2.quantita = qtyAttuali;
    applicaFiltroSort();
  });
}

async function aggiungiRapido(id, qtyAttuali) {
  const nuova = qtyAttuali + 1;
  await apiFetch(`${API_BASE()}/api/prodotti/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({quantita: nuova}) });
  const p = prodottiCache.find(x => x.id === id);
  if (p) p.quantita = nuova;
  applicaFiltroSort();
  toastUndo('+1', async () => {
    await apiFetch(`${API_BASE()}/api/prodotti/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({quantita: qtyAttuali, _skip_log: true}) });
    const p2 = prodottiCache.find(x => x.id === id);
    if (p2) p2.quantita = qtyAttuali;
    applicaFiltroSort();
  });
}

function apriModifica(id) {
  const p = prodottiCache.find(x => x.id === id);
  if (!p) return;
  modProdottoId = id;
  modQtyCorrente = p.quantita;
  document.getElementById('mod-nome').value = p.nome || '';
  document.getElementById('mod-marca').value = p.marca || '';
  document.getElementById('mod-qty-val').textContent = modQtyCorrente;
  document.getElementById('mod-scadenza').value = p.scadenza || '';
  document.getElementById('mod-posizione').value = p.posizione || 'Dispensa';
  document.getElementById('mod-note').value = p.note || '';
  document.getElementById('mod-prezzo').value = p.prezzo || '';
  showScreen('screen-modifica');
}

function cambiaQtyMod(delta) {
  modQtyCorrente = Math.max(0, modQtyCorrente + delta);
  document.getElementById('mod-qty-val').textContent = modQtyCorrente;
}

async function salvaModifica() {
  const prezzo = document.getElementById('mod-prezzo').value;
  const payload = {
    nome: document.getElementById('mod-nome').value.trim() || 'Prodotto',
    marca: document.getElementById('mod-marca').value.trim(),
    quantita: modQtyCorrente,
    scadenza: document.getElementById('mod-scadenza').value || null,
    posizione: document.getElementById('mod-posizione').value,
    note: document.getElementById('mod-note').value.trim(),
    prezzo: prezzo === '' ? null : parseFloat(prezzo),
  };
  try {
    await apiFetch(`${API_BASE()}/api/prodotti/${modProdottoId}`, {
      method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)
    });
    toast('Prodotto aggiornato!');
    showScreen('screen-inventario');
  } catch(e) { toast('Errore salvataggio. Riprova.'); }
}

// Dark mode
function initDarkMode() {
  const stored = localStorage.getItem('dispensa_dark');
  let isDark;
  if (stored === '1') isDark = true;
  else if (stored === '0') isDark = false;
  else isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.classList.toggle('dark', isDark);
  const btn = document.getElementById('dark-toggle');
  if (btn) btn.classList.toggle('on', isDark);
  if (!stored && window.matchMedia('(prefers-color-scheme: dark)').addEventListener) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
      if (!localStorage.getItem('dispensa_dark')) {
        document.documentElement.classList.toggle('dark', e.matches);
        const b = document.getElementById('dark-toggle');
        if (b) b.classList.toggle('on', e.matches);
      }
    });
  }
}
function toggleDarkMode() {
  const isDark = document.documentElement.classList.toggle('dark');
  localStorage.setItem('dispensa_dark', isDark ? '1' : '0');
  const btn = document.getElementById('dark-toggle');
  if (btn) btn.classList.toggle('on', isDark);
  const info = document.getElementById('dark-mode-info');
  if (info) info.textContent = 'Impostato manualmente. Tieni premuto per ritornare automatico.';
}
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('dark-toggle');
  if (!btn) return;
  let _lpTimer = null;
  btn.addEventListener('touchstart', () => {
    _lpTimer = setTimeout(() => {
      localStorage.removeItem('dispensa_dark'); initDarkMode();
      const info = document.getElementById('dark-mode-info');
      if (info) info.textContent = 'Segue automaticamente il tema di sistema. Tocca per sovrascrivere.';
      toast('🌗 Tema automatico (sistema)');
    }, 800);
  }, { passive: true });
  btn.addEventListener('touchend', () => { if (_lpTimer) clearTimeout(_lpTimer); });
  btn.addEventListener('touchcancel', () => { if (_lpTimer) clearTimeout(_lpTimer); });
});

function esportaCSV() {
  if (!prodottiCache.length) { toast('Nessun prodotto da esportare'); return; }
  const cols = ['ID','Nome','Marca','Categoria','Quantità','Scadenza','Posizione','EAN','Note','Prezzo'];
  const righe = prodottiCache.map(p => [
    p.id, p.nome, p.marca||'', p.categoria||'', p.quantita,
    p.scadenza||'', p.posizione||'', p.ean||'', (p.note||'').replace(/"/g,"'"),
    p.prezzo || ''
  ].map(v => `"${v}"`).join(','));
  const csv = [cols.join(','), ...righe].join('\n');
  const blob = new Blob(['﻿' + csv], {type: 'text/csv;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = `dispensa_${new Date().toISOString().split('T')[0]}.csv`;
  a.click(); URL.revokeObjectURL(url);
  toast('CSV esportato!');
}

// ── Render inventario (con bulk mode) ────────────────────────────────────────
function renderInventario(attivi, esauriti) {
  const oggi = new Date(); oggi.setHours(0,0,0,0);
  const giorniAlert = parseInt(localStorage.getItem('dispensa_giorni') || '3');
  let inScadenza = 0;

  let html = '';
  if (attivi.length === 0 && esauriti.length === 0) {
    html = `<div class="empty"><div class="empty-icon">🛒</div><div>Nessun prodotto in dispensa.<br>Scansiona il primo!</div></div>`;
  } else if (attivi.length === 0) {
    html = `<div class="empty" style="padding:24px 20px;"><div style="font-size:14px;color:var(--muted);">Nessun prodotto disponibile</div></div>`;
  } else {
    attivi.forEach(p => {
      let dotClass = 'dot-ok', metaText = '', badgeHtml = '';
      if (p.scadenza) {
        const scad = new Date(p.scadenza);
        const giorni = Math.round((scad - oggi) / 86400000);
        if (giorni < 0) { dotClass = 'dot-exp'; metaText = 'Scaduto'; badgeHtml = `<span class="badge badge-exp">Scaduto</span>`; }
        else if (giorni === 0) { dotClass = 'dot-warn'; metaText = 'Scade oggi'; badgeHtml = `<span class="badge badge-warn">Scade oggi</span>`; inScadenza++; }
        else if (giorni <= giorniAlert) { dotClass = 'dot-warn'; metaText = `Scade tra ${giorni}g`; badgeHtml = `<span class="badge badge-warn">In scadenza</span>`; inScadenza++; }
        else { metaText = `Scade ${scad.toLocaleDateString('it-IT', {day:'numeric', month:'short'})}`; }
      }
      const selected = bulkSelected.has(p.id) ? 'bulk-selected' : '';
      html += `<div class="prod-item ${selected}" data-id="${p.id}" onclick="onProdottoClick(${p.id})" oncontextmenu="event.preventDefault(); enterBulkMode(${p.id});">
        <div class="bulk-check"></div>
        <div class="prod-dot ${dotClass}"></div>
        <div class="prod-info">
          <div class="prod-nome">${p.nome}</div>
          <div class="prod-meta">${p.marca ? p.marca + ' · ' : ''}${p.posizione ? p.posizione + (metaText ? ' · ' : '') : ''}${metaText}</div>
          ${badgeHtml}
        </div>
        <div class="prod-actions" onclick="event.stopPropagation()">
          <div class="quick-btn" onclick="consumaRapido(${p.id},${p.quantita})">−</div>
          <div class="prod-qty">×${p.quantita}</div>
          <div class="quick-btn" onclick="aggiungiRapido(${p.id},${p.quantita})">+</div>
        </div>
      </div>`;
    });
  }

  let esauritiHtml = '';
  if (esauriti.length > 0) {
    const chevron = esauritiOpen ? 'open' : '';
    const listStyle = esauritiOpen ? 'open' : '';
    esauritiHtml = `<div class="esauriti-section">
      <div class="esauriti-header" onclick="toggleEsauriti()">
        <span style="font-size:14px;">⬜</span>
        <span class="esauriti-header-title">Esauriti</span>
        <span class="esauriti-header-count">${esauriti.length}</span>
        <span class="esauriti-chevron ${chevron}">›</span>
      </div>
      <div class="esauriti-list ${listStyle}" id="esauriti-list-inner">`;
    esauriti.forEach(p => {
      esauritiHtml += `<div class="prod-item esaurito" data-id="${p.id}" onclick="apriDettaglio(${p.id})">
        <div class="prod-dot dot-out"></div>
        <div class="prod-info">
          <div class="prod-nome esaurito-text">${p.nome}</div>
          <div class="prod-meta">${p.marca ? p.marca + ' · ' : ''}${p.posizione || 'Dispensa'}</div>
        </div>
        <div class="prod-actions" onclick="event.stopPropagation()">
          <div class="quick-btn" onclick="aggiungiRapido(${p.id},0)">+</div>
        </div>
      </div>`;
    });
    esauritiHtml += `</div></div>`;
  }

  document.getElementById('lista-prodotti').innerHTML = html + esauritiHtml;
  document.getElementById('metrics').innerHTML = `
    <div class="metric"><div class="metric-val">${attivi.length}</div><div class="metric-label">In dispensa</div></div>
    <div class="metric"><div class="metric-val" style="color:#EF9F27">${inScadenza}</div><div class="metric-label">In scadenza</div></div>
    <div class="metric"><div class="metric-val" style="color:var(--gray)">${esauriti.length}</div><div class="metric-label">Esauriti</div></div>
  `;

  // Long-press handler per attivare bulk mode
  setupLongPress();
}

function toggleEsauriti() {
  esauritiOpen = !esauritiOpen;
  const list = document.getElementById('esauriti-list-inner');
  const chevron = document.querySelector('.esauriti-chevron');
  if (list) list.classList.toggle('open', esauritiOpen);
  if (chevron) chevron.classList.toggle('open', esauritiOpen);
}

// ── Bulk mode (multi-select) ─────────────────────────────────────────────────
function setupLongPress() {
  document.querySelectorAll('#lista-prodotti .prod-item[data-id]').forEach(el => {
    let lpTimer = null;
    const id = parseInt(el.dataset.id);
    el.addEventListener('touchstart', (e) => {
      lpTimer = setTimeout(() => { enterBulkMode(id); navigator.vibrate?.(50); }, 600);
    }, { passive: true });
    el.addEventListener('touchend', () => { if (lpTimer) clearTimeout(lpTimer); });
    el.addEventListener('touchmove', () => { if (lpTimer) clearTimeout(lpTimer); });
    el.addEventListener('touchcancel', () => { if (lpTimer) clearTimeout(lpTimer); });
  });
}

function onProdottoClick(id) {
  if (bulkMode) toggleBulkSelect(id);
  else apriDettaglio(id);
}

function enterBulkMode(initialId = null) {
  bulkMode = true;
  bulkSelected.clear();
  if (initialId) bulkSelected.add(initialId);
  document.body.classList.add('bulk-mode');
  document.getElementById('topbar-inventario-normal').style.display = 'none';
  document.getElementById('topbar-inventario-bulk').style.display = 'flex';
  applicaFiltroSort();
  updateBulkCount();
}

function exitBulkMode() {
  bulkMode = false;
  bulkSelected.clear();
  document.body.classList.remove('bulk-mode');
  document.getElementById('topbar-inventario-normal').style.display = 'flex';
  document.getElementById('topbar-inventario-bulk').style.display = 'none';
  applicaFiltroSort();
}

function toggleBulkSelect(id) {
  if (bulkSelected.has(id)) bulkSelected.delete(id);
  else bulkSelected.add(id);
  const el = document.querySelector(`#lista-prodotti .prod-item[data-id="${id}"]`);
  if (el) el.classList.toggle('bulk-selected', bulkSelected.has(id));
  updateBulkCount();
  if (bulkSelected.size === 0) exitBulkMode();
}

function updateBulkCount() {
  const el = document.getElementById('bulk-count');
  if (el) el.textContent = bulkSelected.size;
}

function bulkActionMenu() {
  if (bulkSelected.size === 0) { toast('Nessun prodotto selezionato'); return; }
  document.getElementById('bulk-action-count').textContent = bulkSelected.size;
  openModal('modal-bulk-action');
}

async function bulkMoveTo(posizione) {
  closeModal('modal-bulk-action');
  const ids = Array.from(bulkSelected);
  try {
    const r = await apiFetch(`${API_BASE()}/api/prodotti/bulk`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ ids, action: 'set_posizione', value: posizione })
    });
    const data = await r.json();
    toast(`✅ ${data.affected} prodotti spostati in ${posizione}`);
    exitBulkMode(); caricaInventario();
  } catch(e) { toast('Errore'); }
}

function bulkExtendScadenza() {
  closeModal('modal-bulk-action');
  document.getElementById('extend-giorni-input').value = '7';
  openModal('modal-extend-scad');
}

async function confirmExtendScadenza() {
  const giorni = parseInt(document.getElementById('extend-giorni-input').value);
  if (!giorni || giorni < 1) { toast('Inserisci giorni validi'); return; }
  closeModal('modal-extend-scad');
  const ids = Array.from(bulkSelected);
  try {
    const r = await apiFetch(`${API_BASE()}/api/prodotti/bulk`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ ids, action: 'extend_scadenza', value: giorni })
    });
    const data = await r.json();
    toast(`✅ ${data.affected} scadenze estese di ${giorni} giorni`);
    exitBulkMode(); caricaInventario();
  } catch(e) { toast('Errore'); }
}

function bulkDelete() {
  closeModal('modal-bulk-action');
  const count = bulkSelected.size;
  if (!confirm(`Eliminare definitivamente ${count} prodotti?`)) return;
  const ids = Array.from(bulkSelected);
  apiFetch(`${API_BASE()}/api/prodotti/bulk`, {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ ids, action: 'delete' })
  }).then(r => r.json()).then(data => {
    toast(`🗑️ ${data.affected} prodotti eliminati`);
    exitBulkMode(); caricaInventario();
  }).catch(() => toast('Errore'));
}

// ── Renderer nutriments + dettaglio ──────────────────────────────────────────
function renderNutriments(p) {
  if (!p.nutriments) return '';
  const n = typeof p.nutriments === 'string' ? JSON.parse(p.nutriments) : p.nutriments;
  const righe = [
    ['Energia', n.energia_kcal, 'kcal'], ['Grassi', n.grassi, 'g'],
    ['di cui saturi', n.grassi_saturi, 'g'], ['Carboidrati', n.carboidrati, 'g'],
    ['di cui zuccheri', n.zuccheri, 'g'], ['Fibre', n.fibre, 'g'],
    ['Proteine', n.proteine, 'g'], ['Sale', n.sale, 'g'],
  ].filter(r => r[1] != null);
  if (!righe.length) return '';
  const nsColor = {'A':'#1D9E75','B':'#8BC34A','C':'#FFC107','D':'#FF9800','E':'#F44336'};
  let rows = '';
  righe.forEach(function(r, i) {
    const notLast = i < righe.length - 1;
    const isDi = r[0].startsWith('di');
    const borderStyle = notLast ? 'border-bottom:0.5px solid var(--border);' : '';
    const indentStyle = isDi ? 'padding-left:12px;' : '';
    const weightStyle = isDi ? '400' : '600';
    rows += '<tr><td style="color:var(--muted);padding:6px 0;' + borderStyle + indentStyle + '">' + r[0] + '</td><td style="text-align:right;font-weight:' + weightStyle + ';' + borderStyle + '">' + Number(r[1]).toFixed(1) + ' ' + r[2] + '</td></tr>';
  });
  let nsHtml = '';
  if (p.nutriscore) {
    const color = nsColor[p.nutriscore] || 'var(--text)';
    nsHtml = '<div style="margin-top:12px;font-size:13px;color:var(--muted);">Nutri-Score: <strong style="font-size:16px;color:' + color + '">● ' + p.nutriscore + '</strong></div>';
  }
  return '<div class="card card-body" style="margin-top:8px;"><div style="font-size:13px;font-weight:600;color:var(--muted);margin-bottom:12px;">📊 Valori nutrizionali per 100g</div><table style="width:100%;font-size:13px;border-collapse:collapse;">' + rows + '</table>' + nsHtml + '</div>';
}

function apriDettaglio(id) {
  const p = prodottiCache.find(x => x.id === id);
  if (!p) return;
  detQtyDelta = 1;
  document.getElementById('det-title').textContent = p.nome;
  const scadFormatted = p.scadenza ? new Date(p.scadenza).toLocaleDateString('it-IT', {day:'numeric',month:'long',year:'numeric'}) : 'Non specificata';
  const isEsaurito = p.quantita <= 0;
  const imgHtml = p.immagine_url ? '<img src="' + p.immagine_url + '" style="width:100%;max-height:180px;object-fit:contain;border-radius:12px;margin-bottom:16px;background:var(--bg);" onerror="this.style.display=\'none\'">' : '';
  const esauritoHtml = isEsaurito ? '<div style="background:var(--gray-l);border-radius:10px;padding:8px 12px;margin-bottom:12px;font-size:13px;color:var(--gray);font-weight:500;">□ Prodotto esaurito — rimane nel database</div>' : '';
  const posizioneLabel = p.posizione === 'Frigo' ? '🧊 Frigo' : p.posizione === 'Freezer' ? '❄️ Freezer' : '🗄️ Dispensa';
  const eanLabel = p.ean ? (p.ean.startsWith('MANUAL-') ? '—' : p.ean) : '—';
  const prezzoRow = p.prezzo ? `<tr><td style="color:var(--muted);padding:8px 0;border-bottom:0.5px solid var(--border);">Prezzo</td><td style="text-align:right;font-weight:600;border-bottom:0.5px solid var(--border);color:var(--green-d);">${Number(p.prezzo).toFixed(2)}€</td></tr>` : '';
  document.getElementById('det-content').innerHTML =
    '<div class="card card-body">' + imgHtml
    + '<div style="font-size:20px;font-weight:700;margin-bottom:4px;">' + p.nome + '</div>'
    + '<div style="font-size:14px;color:var(--muted);margin-bottom:20px;">' + (p.marca || '') + (p.categoria ? ' · ' + p.categoria : '') + '</div>'
    + esauritoHtml + '<table style="width:100%;font-size:14px;border-collapse:collapse;">'
    + '<tr><td style="color:var(--muted);padding:8px 0;border-bottom:0.5px solid var(--border);">Posizione</td><td style="text-align:right;font-weight:600;border-bottom:0.5px solid var(--border);">' + posizioneLabel + '</td></tr>'
    + '<tr><td style="color:var(--muted);padding:8px 0;border-bottom:0.5px solid var(--border);">Quantità</td><td style="text-align:right;font-weight:600;border-bottom:0.5px solid var(--border);">' + p.quantita + '</td></tr>'
    + '<tr><td style="color:var(--muted);padding:8px 0;border-bottom:0.5px solid var(--border);">Scadenza</td><td style="text-align:right;font-weight:600;border-bottom:0.5px solid var(--border);">' + scadFormatted + '</td></tr>'
    + prezzoRow
    + '<tr><td style="color:var(--muted);padding:8px 0;">EAN</td><td style="text-align:right;font-size:12px;font-family:monospace;">' + eanLabel + '</td></tr></table></div>'
    + renderNutriments(p)
    + '<div class="card card-body" style="margin-top:8px;"><div style="font-size:13px;color:var(--muted);margin-bottom:10px;">Quantità da aggiornare</div>'
    + '<div class="qty-row" style="margin-bottom:12px;"><div class="qty-btn" onclick="cambiaQtyDet(-1)">−</div><div class="qty-val" id="det-qty-delta">1</div><div class="qty-btn" onclick="cambiaQtyDet(1)">+</div></div>'
    + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;"><button class="btn btn-secondary" onclick="consumaProdotto(' + p.id + ',' + p.quantita + ')">− Consuma</button><button class="btn btn-secondary" onclick="aggiungiQty(' + p.id + ',' + p.quantita + ')">+ Aggiungi</button></div></div>'
    + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:8px;"><button class="btn btn-secondary" onclick="apriModifica(' + p.id + ')">✏️ Modifica</button><button class="btn btn-danger" onclick="eliminaProdotto(' + p.id + ')">🗑️ Elimina</button></div>';
  showScreen('screen-dettaglio');
}

function cambiaQtyDet(delta) {
  detQtyDelta = Math.max(1, detQtyDelta + delta);
  const el = document.getElementById('det-qty-delta');
  if (el) el.textContent = detQtyDelta;
}
async function consumaProdotto(id, qtyAttuali) {
  const delta = detQtyDelta;
  const nuova = Math.max(0, qtyAttuali - delta);
  await apiFetch(`${API_BASE()}/api/prodotti/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({quantita: nuova}) });
  showScreen('screen-inventario');
  toastUndo(`−${delta}`, async () => {
    await apiFetch(`${API_BASE()}/api/prodotti/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({quantita: qtyAttuali, _skip_log: true}) });
    const p = prodottiCache.find(x => x.id === id);
    if (p) p.quantita = qtyAttuali;
    applicaFiltroSort();
  });
}
async function aggiungiQty(id, qtyAttuali) {
  const delta = detQtyDelta;
  const nuova = qtyAttuali + delta;
  await apiFetch(`${API_BASE()}/api/prodotti/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({quantita: nuova}) });
  showScreen('screen-inventario');
  toastUndo(`+${delta}`, async () => {
    await apiFetch(`${API_BASE()}/api/prodotti/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({quantita: qtyAttuali, _skip_log: true}) });
    const p = prodottiCache.find(x => x.id === id);
    if (p) p.quantita = qtyAttuali;
    applicaFiltroSort();
  });
}
async function eliminaProdotto(id) {
  if (!confirm('Eliminare questo prodotto dalla dispensa?')) return;
  await apiFetch(`${API_BASE()}/api/prodotti/${id}`, { method: 'DELETE' });
  toast('Prodotto eliminato');
  showScreen('screen-inventario');
}

// ── Barcode scanner — veloce con BarcodeDetector native, fallback ZXing ──
function beep(freq = 900, duration = 100) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = freq;
    osc.connect(gain); gain.connect(ctx.destination);
    gain.gain.setValueAtTime(0.1, ctx.currentTime);
    osc.start(); osc.stop(ctx.currentTime + duration / 1000);
  } catch(e) {}
}

async function avviaScanner() {
  if (codeReader || barcodeDetectorActive) return;
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

  // Try BarcodeDetector nativo (più veloce su Chrome Android)
  if ('BarcodeDetector' in window) {
    try {
      const supportedFormats = await BarcodeDetector.getSupportedFormats();
      const formats = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128'].filter(f => supportedFormats.includes(f));
      if (formats.length > 0) {
        await startNativeScanner(new BarcodeDetector({ formats }));
        return;
      }
    } catch(e) { console.warn('BarcodeDetector failed, fallback ZXing:', e); }
  }

  // Fallback ZXing con hints per soli formati prodotti
  await startZXingScanner();
}

async function startNativeScanner(detector) {
  const video = document.getElementById('video');
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } }
    });
    video.srcObject = stream;
    await video.play();
    barcodeDetectorActive = { stream };
    document.getElementById('scan-status').innerHTML = '<span class="scan-active">📷 Scansione attiva (nativa)</span>';

    const scan = async () => {
      if (!barcodeDetectorActive) return;
      try {
        const codes = await detector.detect(video);
        if (codes && codes.length > 0) {
          const ean = codes[0].rawValue;
          fermaScanner();
          onBarcodeDetected(ean);
          return;
        }
      } catch(e) {}
      if (barcodeDetectorActive) requestAnimationFrame(scan);
    };
    requestAnimationFrame(scan);
  } catch(e) {
    document.getElementById('scan-status').textContent = '⚠️ Errore fotocamera: ' + e.message;
  }
}

async function startZXingScanner() {
  try {
    codeReader = new ZXing.BrowserMultiFormatReader();
    // Hints per soli formati prodotti (più veloce)
    const formats = [
      ZXing.BarcodeFormat.EAN_13, ZXing.BarcodeFormat.EAN_8,
      ZXing.BarcodeFormat.UPC_A, ZXing.BarcodeFormat.UPC_E,
      ZXing.BarcodeFormat.CODE_128,
    ];
    const hints = new Map();
    hints.set(ZXing.DecodeHintType.POSSIBLE_FORMATS, formats);
    hints.set(ZXing.DecodeHintType.TRY_HARDER, true);
    codeReader.hints = hints;

    document.getElementById('scan-status').innerHTML = '<span class="scan-active">📷 Scansione attiva</span>';
    codeReader.decodeFromVideoDevice(null, 'video', async (result, err) => {
      if (result) {
        fermaScanner();
        onBarcodeDetected(result.getText());
      }
    });
  } catch(e) {
    document.getElementById('scan-status').textContent = '⚠️ Errore: ' + e.message;
  }
}

function onBarcodeDetected(ean) {
  navigator.vibrate?.(150);
  beep();
  document.getElementById('scan-status').className = 'scan-found';
  document.getElementById('scan-status').innerHTML = `✅ Codice letto: <code>${ean}</code>`;
  setTimeout(() => {
    if (scanMode === 'search') cercaNellaDispensa(ean);
    else cercaProdotto(ean);
  }, 250);
}

function fermaScanner() {
  if (codeReader) { try { codeReader.reset(); } catch(e) {} codeReader = null; }
  if (barcodeDetectorActive) {
    try { barcodeDetectorActive.stream?.getTracks().forEach(t => t.stop()); } catch(e) {}
    barcodeDetectorActive = false;
  }
  const video = document.getElementById('video');
  if (video && video.srcObject) {
    try { video.srcObject.getTracks().forEach(t => t.stop()); } catch(e) {}
    video.srcObject = null;
  }
}

function avviaFotoScan() { document.getElementById('barcode-file-input').click(); }

async function scansionaFoto(input) {
  const file = input.files[0];
  if (!file) return;
  input.value = '';
  const status = document.getElementById('scan-status');
  status.textContent = 'Analisi barcode in corso...';
  const imgUrl = URL.createObjectURL(file);
  try {
    const reader = new ZXing.BrowserMultiFormatReader();
    const result = await reader.decodeFromImageUrl(imgUrl);
    onBarcodeDetected(result.getText());
  } catch(e) {
    status.textContent = '⚠️ Barcode non riconosciuto';
    toast('Barcode non riconosciuto, riprova');
  } finally { URL.revokeObjectURL(imgUrl); }
}

// ── Cerca prodotto: check dispensa → cache locale → online (con status feedback) ─
let _scanDuplicateEan = null;
let _scanDuplicateProdotti = null;

async function cercaProdotto(ean) {
  const statusEl = document.getElementById('scan-status');
  statusEl.className = '';
  statusEl.innerHTML = `✅ Codice: <code>${ean}</code><br><span style="font-size:12px;color:var(--muted);">🔍 Controllo se è in dispensa...</span>`;
  try {
    const r1 = await apiFetch(`${API_BASE()}/api/prodotti/by-ean/${encodeURIComponent(ean)}`);
    if (r1.ok) {
      const esistenti = await r1.json();
      if (Array.isArray(esistenti) && esistenti.length > 0) {
        statusEl.innerHTML = `✅ Codice: <code>${ean}</code><br><span style="font-size:12px;color:var(--green-d);font-weight:600;">📦 Già in dispensa!</span>`;
        _scanDuplicateEan = ean;
        _scanDuplicateProdotti = esistenti;
        setTimeout(() => mostraModalDuplicato(esistenti), 350);
        return;
      }
    }
  } catch(e) { console.warn('Errore check duplicato:', e); }
  statusEl.innerHTML = `✅ Codice: <code>${ean}</code><br><span style="font-size:12px;color:var(--muted);">🌐 Cerco su database online...</span>`;
  await cercaProdottoOnline(ean);
}

async function cercaProdottoOnline(ean) {
  const statusEl = document.getElementById('scan-status');
  try {
    const r = await apiFetch(`${API_BASE()}/api/barcode/${ean}`);
    const data = await r.json();
    if (data.trovato) {
      const fonte = data.fonte === 'cache_locale' ? '💾 cache locale' : '🌐 Open Food Facts';
      statusEl.innerHTML = `✅ Trovato! <strong>${data.nome}</strong><br><span style="font-size:12px;color:var(--green-d);">${fonte}</span>`;
    } else {
      statusEl.innerHTML = `⚠️ Non trovato online (${ean})<br><span style="font-size:12px;">Inserisci dettagli manualmente</span>`;
    }
    setTimeout(() => apriConferma(data), 600);
  } catch(e) {
    apriConferma({ trovato: false, ean, nome: '', marca: '', categoria: '', immagine_url: '' });
  }
}

function mostraModalDuplicato(esistenti) {
  const totale = esistenti.reduce((acc, p) => acc + (p.quantita || 0), 0);
  const primo = esistenti[0];
  let html = `<p>Hai già <strong>${totale}</strong> <strong>${primo.nome}</strong>:</p><ul style="margin:10px 0 10px 20px;line-height:1.8;">`;
  esistenti.forEach(p => {
    const pos = p.posizione || 'Dispensa';
    const scadStr = p.scadenza ? ' — scade <em>' + new Date(p.scadenza).toLocaleDateString('it-IT', {day:'numeric',month:'short',year:'numeric'}) + '</em>' : '';
    html += `<li>${pos}: <strong>${p.quantita}</strong> pz${scadStr}</li>`;
  });
  html += '</ul>';
  document.getElementById('modal-dup-content').innerHTML = html;
  openModal('modal-scan-duplicato');
}

async function aggiungiAEsistente() {
  closeModal('modal-scan-duplicato');
  if (!_scanDuplicateProdotti || _scanDuplicateProdotti.length === 0) return;
  const primo = _scanDuplicateProdotti[0];
  const nuovaQty = primo.quantita + 1;
  try {
    await apiFetch(`${API_BASE()}/api/prodotti/${primo.id}`, {
      method: 'PUT', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({quantita: nuovaQty})
    });
    toast(`✅ ${primo.nome}: ${primo.quantita} → ${nuovaQty}`);
    showScreen('screen-inventario');
  } catch(e) { toast('Errore'); }
  _scanDuplicateEan = null; _scanDuplicateProdotti = null;
}

function creaNuovoDopoDuplicato() {
  closeModal('modal-scan-duplicato');
  const ean = _scanDuplicateEan;
  _scanDuplicateEan = null; _scanDuplicateProdotti = null;
  if (ean) cercaProdottoOnline(ean);
}

function suggerisciDaCategoria(categoria) {
  const cat = (categoria || '').toLowerCase();
  let posizione = 'Dispensa';
  if (/latte|yogurt|formaggio|latticin|burro|panna|affettat|salum|carne|pesce|fresc|verdur|frutta|uov|salsa aperta|succo aperto/.test(cat)) posizione = 'Frigo';
  if (/surgelat|gelat|frozen|ice/.test(cat)) posizione = 'Freezer';
  let giorni = 365;
  if (/latte/.test(cat)) giorni = 7;
  else if (/yogurt/.test(cat)) giorni = 14;
  else if (/formaggio|cheese/.test(cat)) giorni = 21;
  else if (/burro|panna/.test(cat)) giorni = 30;
  else if (/carne|pesce|affettat|salum/.test(cat)) giorni = 5;
  else if (/frutta|verdur/.test(cat)) giorni = 7;
  else if (/pane|bread/.test(cat)) giorni = 5;
  else if (/biscott|cracker|snack/.test(cat)) giorni = 180;
  else if (/pasta|riso|cereali|legum|farin/.test(cat)) giorni = 365;
  else if (/surgelat|frozen/.test(cat)) giorni = 90;
  else if (/conserv|scatolam|tonno|sughi/.test(cat)) giorni = 730;
  else if (/olio|aceto|condiment/.test(cat)) giorni = 365;
  else if (/bevand|succo|drink/.test(cat)) giorni = 180;
  return { posizione, giorni };
}

function apriConferma(prodotto) {
  prodottoCorrente = prodotto;
  qtyCorrente = 1;
  fotoBase64 = null;
  document.getElementById('conf-nome').textContent = prodotto.nome || 'Prodotto sconosciuto';
  document.getElementById('conf-marca').textContent = [prodotto.marca, prodotto.categoria].filter(Boolean).join(' · ');
  document.getElementById('conf-nome-edit').value = prodotto.nome || '';
  document.getElementById('conf-qty').textContent = '1';
  document.getElementById('conf-note').value = '';
  document.getElementById('conf-prezzo').value = '';
  const { posizione, giorni } = suggerisciDaCategoria(prodotto.categoria);
  const oggi = new Date();
  oggi.setDate(oggi.getDate() + giorni);
  document.getElementById('conf-scadenza').value = oggi.toISOString().split('T')[0];
  document.getElementById('conf-posizione').value = posizione;
  const img = document.getElementById('conf-img');
  if (prodotto.immagine_url) { img.src = prodotto.immagine_url; img.style.display = 'block'; }
  else img.style.display = 'none';
  const fotoSection = document.getElementById('foto-section');
  fotoSection.style.display = prodotto.trovato ? 'none' : 'block';
  document.getElementById('foto-preview').classList.remove('visible');
  document.getElementById('foto-placeholder').style.display = 'flex';
  document.getElementById('foto-upload-area').classList.remove('has-photo');
  const badge = document.getElementById('found-badge-container');
  badge.innerHTML = prodotto.trovato
    ? `<div class="found-badge"><div class="found-badge-dot"></div><div class="found-badge-text">Trovato su Open Food Facts · ${posizione === 'Frigo' ? '🧊 Frigo' : posizione === 'Freezer' ? '❄️ Freezer' : '🗄️ Dispensa'} suggerito</div></div>`
    : `<div class="found-badge" style="background:#FAEEDA"><div class="found-badge-dot" style="background:#EF9F27"></div><div class="found-badge-text" style="color:#854F0B">Prodotto non trovato — inserisci i dettagli</div></div>`;
  showScreen('screen-conferma');
}

function apriFotoMenu() {
  const input = document.getElementById('foto-input');
  input.setAttribute('capture', 'environment');
  input.click();
}

document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('foto-input');
  if (input) {
    input.addEventListener('change', async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      fotoBase64 = await ridimensionaFoto(file, 600);
      const preview = document.getElementById('foto-preview');
      const placeholder = document.getElementById('foto-placeholder');
      const area = document.getElementById('foto-upload-area');
      preview.src = fotoBase64;
      preview.classList.add('visible');
      placeholder.style.display = 'none';
      area.classList.add('has-photo');
    });
  }
});

function ridimensionaFoto(file, maxSize) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const img = new Image();
      img.onload = () => {
        const canvas = document.createElement('canvas');
        let w = img.width, h = img.height;
        if (w > maxSize || h > maxSize) {
          if (w > h) { h = Math.round(h * maxSize / w); w = maxSize; }
          else { w = Math.round(w * maxSize / h); h = maxSize; }
        }
        canvas.width = w; canvas.height = h;
        canvas.getContext('2d').drawImage(img, 0, 0, w, h);
        resolve(canvas.toDataURL('image/jpeg', 0.82));
      };
      img.src = e.target.result;
    };
    reader.readAsDataURL(file);
  });
}

function cambiaQty(delta) {
  qtyCorrente = Math.max(1, qtyCorrente + delta);
  document.getElementById('conf-qty').textContent = qtyCorrente;
}

async function salvaInDispensa() {
  const immagineDaSalvare = fotoBase64 || prodottoCorrente.immagine_url || '';
  const prezzoVal = document.getElementById('conf-prezzo').value;
  const payload = {
    ean: prodottoCorrente.ean || '',
    nome: document.getElementById('conf-nome-edit').value || prodottoCorrente.nome || 'Prodotto',
    marca: prodottoCorrente.marca || '',
    categoria: prodottoCorrente.categoria || '',
    immagine_url: immagineDaSalvare,
    quantita: qtyCorrente,
    scadenza: document.getElementById('conf-scadenza').value || null,
    note: document.getElementById('conf-note').value || '',
    posizione: document.getElementById('conf-posizione').value || 'Dispensa',
    nutriments: prodottoCorrente.nutriments || null,
    nutriscore: prodottoCorrente.nutriscore || '',
    prezzo: prezzoVal === '' ? null : parseFloat(prezzoVal),
  };
  try {
    await apiFetch(`${API_BASE()}/api/prodotti`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
    if (payload.ean && !payload.ean.startsWith('MANUAL-') && prodottoCorrente.trovato) {
      await apiFetch(`${API_BASE()}/api/barcode-cache`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({
          ean: payload.ean, nome: payload.nome, marca: payload.marca,
          categoria: payload.categoria, immagine_url: prodottoCorrente.immagine_url || '',
          nutriments: payload.nutriments, nutriscore: payload.nutriscore
        })
      });
    }
    fotoBase64 = null;
    toast('Prodotto salvato!');
    showScreen('screen-inventario');
  } catch(e) { toast('Errore salvataggio. Riprova.'); }
}

function inserisciManuale() {
  const ean = prompt('Inserisci il codice a barre (EAN):\n(vuoto per inserimento manuale senza barcode)');
  if (ean === null) return;
  if (ean.trim() !== '') cercaProdotto(ean.trim());
  else apriConferma({ trovato: false, ean: 'MANUAL-' + Date.now(), nome: '', marca: '', categoria: '', immagine_url: '' });
}

// ── Lista spesa ──────────────────────────────────────────────────────────────
async function caricaListaSpesa() {
  try {
    const r = await apiFetch(`${API_BASE()}/api/lista-spesa`);
    const items = await r.json();
    renderListaSpesa(items);
  } catch(e) {
    document.getElementById('lista-spesa').innerHTML = `<div class="empty"><div class="empty-icon">⚠️</div><div>Backend non raggiungibile.</div></div>`;
  }
}

function renderListaSpesa(items) {
  if (!items.length) {
    document.getElementById('lista-spesa').innerHTML = `<div class="empty"><div class="empty-icon">🛒</div><div>Lista spesa vuota!</div></div>`;
    return;
  }
  let html = '';
  items.forEach(item => {
    const done = item.completato === 1;
    const qty = item.quantita || 1;
    html += `<div class="spesa-item">
      <div class="spesa-check ${done ? 'done' : ''}" onclick="toggleSpesa(${item.id}, ${done ? 0 : 1}, ${qty})"></div>
      <div class="spesa-info" style="flex:1;min-width:0;">
        <div class="spesa-nome ${done ? 'done' : ''}">${item.nome}</div>
        ${item.marca ? `<div style="font-size:12px;color:var(--muted);">${item.marca}</div>` : ''}
      </div>
      <div style="display:flex;align-items:center;gap:4px;flex-shrink:0;margin-right:4px;" onclick="event.stopPropagation()">
        <div class="quick-btn" style="width:28px;height:28px;font-size:14px;" onclick="cambiaQtySpesa(${item.id}, ${qty - 1}, ${item.completato})">−</div>
        <span style="font-weight:600;min-width:22px;text-align:center;font-size:13px;color:var(--text);">${qty}</span>
        <div class="quick-btn" style="width:28px;height:28px;font-size:14px;" onclick="cambiaQtySpesa(${item.id}, ${qty + 1}, ${item.completato})">+</div>
      </div>
      <div class="spesa-del" onclick="eliminaSpesa(${item.id})">✕</div>
    </div>`;
  });
  document.getElementById('lista-spesa').innerHTML = html;
}

async function cambiaQtySpesa(id, nuovaQty, completato) {
  if (nuovaQty < 1) {
    if (confirm('Quantità a 0: rimuovere dalla lista?')) await eliminaSpesa(id);
    return;
  }
  await apiFetch(`${API_BASE()}/api/lista-spesa/${id}`, {
    method: 'PUT', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ completato: completato || 0, quantita: nuovaQty })
  });
  caricaListaSpesa();
}

async function toggleSpesa(id, completato, quantita) {
  await apiFetch(`${API_BASE()}/api/lista-spesa/${id}`, {
    method: 'PUT', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ completato, quantita: quantita || 1 })
  });
  caricaListaSpesa();
}

async function eliminaSpesa(id) {
  await apiFetch(`${API_BASE()}/api/lista-spesa/${id}`, { method: 'DELETE' });
  caricaListaSpesa();
}

async function svuotaCompletati() {
  await apiFetch(`${API_BASE()}/api/lista-spesa/svuota-completati`, { method: 'DELETE' });
  toast('Completati rimossi');
  caricaListaSpesa();
}

async function inviaListaSpesaTelegram() {
  const r = await apiFetch(`${API_BASE()}/api/lista-spesa/invia-telegram`);
  const data = await r.json();
  toast(data.ok ? '📤 Lista inviata su Telegram!' : '⚠️ ' + (data.errore || 'Errore'));
}

function aggiungiSpesaManuale() {
  const nome = prompt('Nome del prodotto da aggiungere alla lista:');
  if (!nome || !nome.trim()) return;
  apiFetch(`${API_BASE()}/api/lista-spesa`, {
    method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({nome: nome.trim(), quantita: 1})
  }).then(() => { toast('Aggiunto alla lista!'); caricaListaSpesa(); });
}

// ── Statistiche con Chart.js + anti-spreco insights ──────────────────────────
let _statsCharts = [];

async function caricaStatistiche() {
  try {
    const r = await apiFetch(`${API_BASE()}/api/statistiche`);
    const s = await r.json();
    // Destroy charts vecchi
    _statsCharts.forEach(c => { try { c.destroy(); } catch(e) {} });
    _statsCharts = [];

    const posIcon = {'Frigo':'🧊','Freezer':'❄️','Dispensa':'🗄️'};

    let html = `
      <div class="metric-row" style="grid-template-columns:repeat(2,1fr);">
        <div class="metric"><div class="metric-val">${s.totali.acquisti}</div><div class="metric-label">Acquisti totali</div></div>
        <div class="metric"><div class="metric-val">${s.totali.consumi}</div><div class="metric-label">Consumi totali</div></div>
        <div class="metric"><div class="metric-val">${s.totali.acquisti_mese}</div><div class="metric-label">Acquisti questo mese</div></div>
        <div class="metric"><div class="metric-val" style="color:var(--red);">${s.totali.eliminati}</div><div class="metric-label">Eliminati totali</div></div>
      </div>`;

    // Anti-spreco section
    const spreco = s.spreco || {};
    if (spreco.eliminati_6m > 0 || spreco.consumati_6m > 0) {
      const pct = spreco.percentuale;
      const pctColor = pct < 10 ? 'var(--green)' : pct < 25 ? '#EF9F27' : 'var(--red)';
      html += `<div class="card card-body" style="margin-bottom:12px;">
        <div style="font-size:13px;font-weight:600;color:var(--muted);margin-bottom:12px;">💸 Anti-spreco (ultimi 6 mesi)</div>
        <div style="display:flex;align-items:center;gap:16px;margin-bottom:12px;">
          <div style="font-size:32px;font-weight:700;color:${pctColor};">${pct}%</div>
          <div style="font-size:13px;color:var(--muted);flex:1;">
            <div><strong>${spreco.eliminati_6m}</strong> prodotti eliminati</div>
            <div><strong>${spreco.consumati_6m}</strong> prodotti consumati</div>
          </div>
        </div>`;
      if (spreco.top_categorie && spreco.top_categorie.length) {
        html += `<div style="font-size:12px;color:var(--muted);margin-bottom:6px;">Categorie più sprecate:</div>`;
        spreco.top_categorie.forEach(c => {
          html += `<div style="display:flex;justify-content:space-between;padding:4px 0;font-size:13px;"><span>${c.categoria}</span><strong style="color:var(--red);">×${c.n}</strong></div>`;
        });
      }
      html += `</div>`;
    }

    // Spesa stimata (solo se ci sono prezzi)
    if (s.spesa_stimata && s.spesa_stimata.mese_corrente > 0) {
      html += `<div class="card card-body" style="margin-bottom:12px;">
        <div style="font-size:13px;font-weight:600;color:var(--muted);margin-bottom:12px;">💰 Spesa stimata mese corrente</div>
        <div style="display:flex;gap:16px;">
          <div style="flex:1;"><div style="font-size:24px;font-weight:700;color:var(--green-d);">${s.spesa_stimata.mese_corrente.toFixed(2)}€</div><div style="font-size:12px;color:var(--muted);">Acquisti</div></div>
          ${s.spesa_stimata.spreco_mese_corrente > 0 ? `<div style="flex:1;"><div style="font-size:24px;font-weight:700;color:var(--red);">${s.spesa_stimata.spreco_mese_corrente.toFixed(2)}€</div><div style="font-size:12px;color:var(--muted);">Sprecati</div></div>` : ''}
        </div>
      </div>`;
    }

    // Chart trend 6 mesi (line chart)
    if (s.trend_6mesi && Object.keys(s.trend_6mesi).length > 0) {
      html += `<div class="card card-body" style="margin-bottom:12px;">
        <div style="font-size:13px;font-weight:600;color:var(--muted);margin-bottom:12px;">📈 Trend ultimi 6 mesi</div>
        <canvas id="chart-trend" height="160"></canvas>
      </div>`;
    }

    // Chart posizioni (doughnut)
    if (s.per_posizione && s.per_posizione.length > 0) {
      html += `<div class="card card-body" style="margin-bottom:12px;">
        <div style="font-size:13px;font-weight:600;color:var(--muted);margin-bottom:12px;">📍 Prodotti per posizione</div>
        <div style="max-width:240px;margin:auto;"><canvas id="chart-posizioni" height="200"></canvas></div>
      </div>`;
    }

    if (s.top_acquistati.length) {
      html += `<div class="card card-body" style="margin-bottom:12px;"><div style="font-size:13px;font-weight:600;color:var(--muted);margin-bottom:12px;">🏆 Più acquistati</div>`;
      s.top_acquistati.forEach((p,i) => {
        html += `<div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:0.5px solid var(--border);"><span style="font-size:16px;font-weight:700;color:var(--muted);width:20px;">${i+1}</span><div style="flex:1;font-size:14px;">${p.nome}<br><span style="font-size:12px;color:var(--muted);">${p.marca||''}</span></div><span style="font-size:13px;color:var(--green);font-weight:600;">×${p.totale}</span></div>`;
      });
      html += `</div>`;
    }
    if (s.top_consumati.length) {
      html += `<div class="card card-body" style="margin-bottom:12px;"><div style="font-size:13px;font-weight:600;color:var(--muted);margin-bottom:12px;">🔥 Più consumati</div>`;
      s.top_consumati.forEach((p,i) => {
        html += `<div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:0.5px solid var(--border);"><span style="font-size:16px;font-weight:700;color:var(--muted);width:20px;">${i+1}</span><div style="flex:1;font-size:14px;">${p.nome}<br><span style="font-size:12px;color:var(--muted);">${p.marca||''}</span></div><span style="font-size:13px;color:var(--amber);font-weight:600;">×${p.totale}</span></div>`;
      });
      html += `</div>`;
    }
    if (s.top_sprecati && s.top_sprecati.length) {
      html += `<div class="card card-body" style="margin-bottom:12px;"><div style="font-size:13px;font-weight:600;color:var(--muted);margin-bottom:12px;">🗑️ Più sprecati</div>`;
      s.top_sprecati.forEach((p,i) => {
        html += `<div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:0.5px solid var(--border);"><span style="font-size:16px;font-weight:700;color:var(--muted);width:20px;">${i+1}</span><div style="flex:1;font-size:14px;">${p.nome}<br><span style="font-size:12px;color:var(--muted);">${p.marca||''}</span></div><span style="font-size:13px;color:var(--red);font-weight:600;">×${p.totale}</span></div>`;
      });
      html += `</div>`;
    }

    if (!s.top_acquistati.length && !s.top_consumati.length) {
      html += `<div class="empty"><div class="empty-icon">📊</div><div>Nessun dato ancora.<br>Le statistiche si accumulano con l'uso!</div></div>`;
    }

    document.getElementById('stat-content').innerHTML = html;

    // Render charts dopo che il DOM è pronto
    setTimeout(() => renderStatsCharts(s), 50);

  } catch(e) {
    document.getElementById('stat-content').innerHTML = `<div class="empty"><div class="empty-icon">⚠️</div><div>Backend non raggiungibile.</div></div>`;
  }
}

function renderStatsCharts(s) {
  if (typeof Chart === 'undefined') return;
  Chart.defaults.color = getComputedStyle(document.documentElement).getPropertyValue('--text').trim() || '#333';
  Chart.defaults.font.family = '-apple-system, sans-serif';
  Chart.defaults.font.size = 11;

  // Trend 6 mesi
  const trendCanvas = document.getElementById('chart-trend');
  if (trendCanvas && s.trend_6mesi) {
    const mesi = Object.keys(s.trend_6mesi).sort();
    const labels = mesi.map(m => {
      const [y, mm] = m.split('-');
      return ['', 'Gen','Feb','Mar','Apr','Mag','Giu','Lug','Ago','Set','Ott','Nov','Dic'][parseInt(mm)] + ' \'' + y.slice(2);
    });
    const acquisti = mesi.map(m => s.trend_6mesi[m].acquisto || 0);
    const consumi = mesi.map(m => s.trend_6mesi[m].consumo || 0);
    const eliminati = mesi.map(m => s.trend_6mesi[m].eliminato || 0);
    _statsCharts.push(new Chart(trendCanvas, {
      type: 'line',
      data: {
        labels,
        datasets: [
          { label: 'Acquisti', data: acquisti, borderColor: '#1D9E75', backgroundColor: 'rgba(29,158,117,0.15)', tension: 0.3, fill: true },
          { label: 'Consumi', data: consumi, borderColor: '#EF9F27', backgroundColor: 'rgba(239,159,39,0.15)', tension: 0.3, fill: true },
          { label: 'Eliminati', data: eliminati, borderColor: '#A32D2D', backgroundColor: 'rgba(163,45,45,0.15)', tension: 0.3, fill: true },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, padding: 8 } } },
        scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } }
      }
    }));
  }

  // Posizioni doughnut
  const posCanvas = document.getElementById('chart-posizioni');
  if (posCanvas && s.per_posizione) {
    const labels = s.per_posizione.map(p => p.posizione || 'N/D');
    const data = s.per_posizione.map(p => p.n);
    const colors = labels.map(l => l === 'Frigo' ? '#4FC3F7' : l === 'Freezer' ? '#81D4FA' : l === 'Dispensa' ? '#1D9E75' : '#888');
    _statsCharts.push(new Chart(posCanvas, {
      type: 'doughnut',
      data: { labels, datasets: [{ data, backgroundColor: colors, borderWidth: 0 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, padding: 8 } } }
      }
    }));
  }
}

// ── OCR scadenza ──────────────────────────────────────────────────────────────
let ocrStream = null;
function avviaOCRScadenza() {
  const modal = document.getElementById('ocr-modal');
  modal.style.display = 'flex';
  document.getElementById('ocr-status').textContent = 'Avvio fotocamera...';
  document.getElementById('ocr-manuale').style.display = 'none';
  navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment', width: { ideal: 1920 }, height: { ideal: 1080 } } })
    .then(stream => {
      ocrStream = stream;
      document.getElementById('ocr-video').srcObject = stream;
      document.getElementById('ocr-status').textContent = 'Inquadra la data di scadenza nella cornice verde';
    }).catch(err => { document.getElementById('ocr-status').textContent = 'Errore fotocamera: ' + err.message; });
}

function chiudiOCR() {
  if (ocrStream) { ocrStream.getTracks().forEach(t => t.stop()); ocrStream = null; }
  document.getElementById('ocr-modal').style.display = 'none';
}

function preprocessCanvas(canvas) {
  const w = canvas.width, h = canvas.height;
  const scaled = document.createElement('canvas');
  scaled.width = w * 2; scaled.height = h * 2;
  const sCtx = scaled.getContext('2d');
  sCtx.imageSmoothingEnabled = false;
  sCtx.drawImage(canvas, 0, 0, scaled.width, scaled.height);
  const imgData = sCtx.getImageData(0, 0, scaled.width, scaled.height);
  const data = imgData.data;
  for (let i = 0; i < data.length; i += 4) {
    const lum = 0.299 * data[i] + 0.587 * data[i+1] + 0.114 * data[i+2];
    const val = lum > 128 ? 255 : 0;
    data[i] = data[i+1] = data[i+2] = val;
  }
  sCtx.putImageData(imgData, 0, 0);
  return scaled;
}

async function scattaFotoOCR() {
  const video = document.getElementById('ocr-video');
  const canvas = document.getElementById('ocr-canvas');
  canvas.width = video.videoWidth; canvas.height = video.videoHeight;
  canvas.getContext('2d').drawImage(video, 0, 0);
  document.getElementById('ocr-status').textContent = '🔍 Elaborazione...';
  try {
    const processed = preprocessCanvas(canvas);
    let text = '';
    const r1 = await Tesseract.recognize(processed, 'ita+eng', { logger: () => {}, tessedit_char_whitelist: '0123456789/-.ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz ' });
    text = r1.data.text;
    let data = estraiDataScadenza(text);
    if (!data) {
      const r2 = await Tesseract.recognize(canvas, 'ita+eng', { logger: () => {} });
      text = r2.data.text;
      data = estraiDataScadenza(text);
    }
    if (data) {
      document.getElementById('conf-scadenza').value = data;
      chiudiOCR();
      toast('✅ Scadenza rilevata: ' + formatDataIT(data));
    } else {
      document.getElementById('ocr-status').textContent = '⚠️ Data non rilevata.';
      document.getElementById('ocr-testo-letto').textContent = text.replace(/\n/g, ' ').trim().substring(0, 100);
      document.getElementById('ocr-manuale').style.display = 'block';
    }
  } catch(e) {
    document.getElementById('ocr-status').textContent = '⚠️ Errore OCR.';
    document.getElementById('ocr-manuale').style.display = 'block';
  }
}

function confermaManualeOCR() {
  const input = document.getElementById('ocr-input-manuale').value.trim();
  const data = estraiDataScadenza(input);
  if (data) {
    document.getElementById('conf-scadenza').value = data;
    chiudiOCR();
    toast('✅ Scadenza impostata: ' + formatDataIT(data));
  } else {
    document.getElementById('ocr-status').textContent = '⚠️ Formato non riconosciuto.';
  }
}

function estraiDataScadenza(testo) {
  if (!testo) return null;
  let t = testo.toUpperCase().replace(/[Oo]/g, '0').replace(/[Il\|]/g, '1').replace(/[Ss]/g, '5').replace(/[Bb]/g, '8').replace(/\r/g, ' ').replace(/\n/g, ' ');
  t = t.replace(/\b(EXP|SCAD|TMC|BB|USE BY|BEST BY|CONSUMARE ENTRO|CONS\.?\s*ENT\.?|LOT|LOTTO|L\.?)\s*/g, ' ');
  let m = t.match(/\b(\d{2})(\d{2})(\d{2})\b/);
  if (m) { const [, g, ms, aa] = m; const a = '20' + aa; const d = new Date(parseInt(a), parseInt(ms)-1, parseInt(g)); if (isDataValida(d, parseInt(g), parseInt(ms))) return formatISO(d); }
  m = t.match(/\b(\d{2})(\d{2})(\d{4})\b/);
  if (m) { const [, g, ms, a] = m; const d = new Date(parseInt(a), parseInt(ms)-1, parseInt(g)); if (isDataValida(d, parseInt(g), parseInt(ms))) return formatISO(d); }
  m = t.match(/\b(202\d)(\d{2})(\d{2})\b/);
  if (m) { const [, a, ms, g] = m; const d = new Date(parseInt(a), parseInt(ms)-1, parseInt(g)); if (isDataValida(d, parseInt(g), parseInt(ms))) return formatISO(d); }
  m = t.match(/\b(\d{1,2})[\s\/\-\.](\d{1,2})[\s\/\-\.](\d{2,4})\b/);
  if (m) { let [, g, ms, a] = m; if (a.length === 2) a = '20' + a; const d = new Date(parseInt(a), parseInt(ms)-1, parseInt(g)); if (isDataValida(d, parseInt(g), parseInt(ms))) return formatISO(d); }
  m = t.match(/\b(202\d)[\s\/\-\.](\d{1,2})\b/);
  if (m) { const [, a, ms] = m; const ug = new Date(parseInt(a), parseInt(ms), 0).getDate(); const d = new Date(parseInt(a), parseInt(ms)-1, ug); if (isDataValida(d, ug, parseInt(ms))) return formatISO(d); }
  m = t.match(/\b(\d{1,2})[\s\/\-\.](202\d)\b/);
  if (m) { const [, ms, a] = m; const ug = new Date(parseInt(a), parseInt(ms), 0).getDate(); const d = new Date(parseInt(a), parseInt(ms)-1, ug); if (isDataValida(d, ug, parseInt(ms))) return formatISO(d); }
  m = t.match(/\b(202\d)(0[1-9]|1[0-2])\b/);
  if (m) { const [, a, ms] = m; const ug = new Date(parseInt(a), parseInt(ms), 0).getDate(); const d = new Date(parseInt(a), parseInt(ms)-1, ug); if (isDataValida(d, ug, parseInt(ms))) return formatISO(d); }
  const mesiIT = { GEN:1,FEB:2,MAR:3,APR:4,MAG:5,GIU:6,LUG:7,AGO:8,SET:9,OTT:10,NOV:11,DIC:12, GENNAIO:1,FEBBRAIO:2,MARZO:3,APRILE:4,MAGGIO:5,GIUGNO:6,LUGLIO:7,AGOSTO:8,SETTEMBRE:9,OTTOBRE:10,NOVEMBRE:11,DICEMBRE:12, JAN:1,MAY:5,JUN:6,JUL:7,AUG:8,SEP:9,OCT:10,DEC:12 };
  for (const [nome, num] of Object.entries(mesiIT)) {
    const re = new RegExp(`\\b(\\d{1,2})?\\s*${nome}\\s*(\\d{4}|\\d{2})\\b`);
    m = t.match(re);
    if (m) { let a = m[2]; if (a.length === 2) a = '20' + a; const g = m[1] ? parseInt(m[1]) : new Date(parseInt(a), num, 0).getDate(); const d = new Date(parseInt(a), num-1, g); if (isDataValida(d, g, num)) return formatISO(d); }
  }
  return null;
}

function isDataValida(data, giorno, mese) {
  if (isNaN(data.getTime())) return false;
  if (giorno < 1 || giorno > 31) return false;
  if (mese < 1 || mese > 12) return false;
  const anno = data.getFullYear();
  if (anno < 2024 || anno > 2040) return false;
  return true;
}
function formatISO(data) {
  const y = data.getFullYear();
  const m = String(data.getMonth()+1).padStart(2,'0');
  const d = String(data.getDate()).padStart(2,'0');
  return `${y}-${m}-${d}`;
}
function formatDataIT(iso) { const [y, m, d] = iso.split('-'); return `${d}/${m}/${y}`; }

function salvaImpostazioni() {
  const giorni = document.getElementById('set-giorni').value;
  if (giorni) localStorage.setItem('dispensa_giorni', giorni);
  toast('Impostazioni salvate');
}

// ── Pull-to-refresh ──────────────────────────────────────────────────────────
let _ptrStartY = 0;
let _ptrCurrent = 0;
let _ptrActive = false;
let _ptrIndicator = null;
const PTR_THRESHOLD = 70;
const PTR_MAX = 100;
const PTR_SCREENS = ['screen-inventario', 'screen-spesa', 'screen-statistiche'];

function initPullToRefresh() {
  document.body.style.overscrollBehaviorY = 'contain';
  _ptrIndicator = document.createElement('div');
  _ptrIndicator.id = 'ptr-indicator';
  _ptrIndicator.style.cssText = 'position:fixed;top:-50px;left:50%;transform:translateX(-50%) rotate(0deg);width:40px;height:40px;background:var(--surface);border:0.5px solid var(--border);border-radius:50%;display:flex;align-items:center;justify-content:center;z-index:9000;transition:top 0.2s,transform 0.1s;font-size:18px;color:var(--text);box-shadow:0 2px 12px rgba(0,0,0,0.18);pointer-events:none;';
  _ptrIndicator.textContent = '↓';
  document.body.appendChild(_ptrIndicator);

  document.addEventListener('touchstart', e => {
    const active = document.querySelector('.screen.active');
    if (!active || !PTR_SCREENS.includes(active.id)) return;
    const scroller = active.querySelector('.content');
    if (!scroller || scroller.scrollTop > 0) return;
    _ptrStartY = e.touches[0].clientY;
    _ptrActive = true; _ptrCurrent = 0;
  }, { passive: true });

  document.addEventListener('touchmove', e => {
    if (!_ptrActive) return;
    _ptrCurrent = e.touches[0].clientY - _ptrStartY;
    if (_ptrCurrent <= 0) { _ptrIndicator.style.top = '-50px'; return; }
    const pos = Math.min(_ptrCurrent / 2, PTR_MAX) - 50;
    _ptrIndicator.style.top = pos + 'px';
    _ptrIndicator.textContent = _ptrCurrent > PTR_THRESHOLD ? '↻' : '↓';
    _ptrIndicator.style.transform = `translateX(-50%) rotate(${_ptrCurrent * 1.5}deg)`;
  }, { passive: true });

  document.addEventListener('touchend', async () => {
    if (!_ptrActive) return;
    _ptrActive = false;
    if (_ptrCurrent > PTR_THRESHOLD) {
      _ptrIndicator.textContent = '⏳';
      _ptrIndicator.style.top = '20px';
      _ptrIndicator.style.transform = 'translateX(-50%) rotate(0deg)';
      const active = document.querySelector('.screen.active');
      try {
        if (active?.id === 'screen-inventario') await caricaInventario();
        else if (active?.id === 'screen-spesa') await caricaListaSpesa();
        else if (active?.id === 'screen-statistiche') await caricaStatistiche();
      } catch(e) {}
      setTimeout(() => { _ptrIndicator.style.top = '-50px'; }, 400);
    } else {
      _ptrIndicator.style.top = '-50px';
      _ptrIndicator.style.transform = 'translateX(-50%) rotate(0deg)';
    }
    _ptrCurrent = 0;
  }, { passive: true });
}

const APP_VERSION = document.querySelector('meta[name="app-version"]')?.content || '0';

async function checkForUpdates() {
  try {
    const r = await fetch(API_BASE() + '/api/health', { cache: 'no-store' });
    if (!r.ok) return;
    const data = await r.json();
    if (data.version && data.version !== APP_VERSION) {
      document.getElementById('update-msg').textContent = `🔄 Versione ${data.version} disponibile`;
      document.getElementById('update-banner').classList.add('visible');
    }
  } catch (e) {}
}

async function applicaAggiornamento() {
  document.getElementById('update-msg').textContent = '⏳ Aggiornamento in corso...';
  document.querySelector('#update-banner button').disabled = true;
  if ('caches' in window) { const keys = await caches.keys(); await Promise.all(keys.map(k => caches.delete(k))); }
  if ('serviceWorker' in navigator) { const regs = await navigator.serviceWorker.getRegistrations(); await Promise.all(regs.map(r => r.unregister())); }
  location.reload(true);
}

document.getElementById('set-giorni').value = localStorage.getItem('dispensa_giorni') || '3';
initDarkMode();
initAuth().then(() => caricaInventario());
initPullToRefresh();

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js').catch(err => console.warn('SW non registrato:', err));
}

checkForUpdates();
setInterval(checkForUpdates, 5 * 60 * 1000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) checkForUpdates(); });

function applyDeepLink() {
  const params = new URLSearchParams(window.location.search);
  const filtro = params.get('filter');
  const validi = ['tutti', 'scadenza', 'scaduti', 'frigo', 'freezer', 'dispensa'];
  if (filtro && validi.indexOf(filtro) !== -1) setFiltro(filtro);
  const action = params.get('action');
  if (action === 'scan') { scanMode = 'add'; showScreen('screen-scan'); }
  const tab = params.get('tab');
  if (tab === 'spesa') showScreen('screen-spesa');
}
window.addEventListener('popstate', applyDeepLink);
setTimeout(applyDeepLink, 800);

// ── Admin panel ───────────────────────────────────────────────────────────────
async function caricaAdmin() {
  await Promise.all([caricaUtenti(), caricaImpostazioniAdmin(), caricaIPBans(), caricaApiKey(), caricaBackupStatus()]);
}

async function caricaUtenti() {
  const r = await apiFetch(`${API_BASE()}/api/admin/users`);
  const users = await r.json();
  const el = document.getElementById('admin-users-list');
  el.innerHTML = users.map(u => `
    <div class="user-row" id="user-row-${u.id}">
      <div class="user-name">${u.username}</div>
      ${u.is_admin ? '<span class="user-badge admin-badge">admin</span>' : ''}
      ${!u.is_active ? '<span class="user-badge inactive">disabilitato</span>' : ''}
      <div style="display:flex;gap:6px">
        <button class="btn-sm btn-sm-green" onclick="editUser(${u.id},'${u.username}',${u.is_admin},${u.is_active})">Modifica</button>
        <button class="btn-sm btn-sm-red" onclick="deleteUser(${u.id},'${u.username}')">Elimina</button>
      </div>
    </div>`).join('');
}

async function caricaImpostazioniAdmin() {
  const r = await apiFetch(`${API_BASE()}/api/admin/settings`);
  const settings = await r.json();
  const el = document.getElementById('admin-settings-form');
  const toggles = settings.filter(s => s.key.startsWith('notif_'));
  const inputs = settings.filter(s => !s.key.startsWith('notif_'));
  let html = '';
  if (toggles.length) {
    html += '<div style="font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px;">🔔 Notifiche Telegram</div>';
    toggles.forEach(s => {
      const on = s.value === '1';
      html += `<div class="setting-row" style="padding:10px 0;">
          <span style="font-size:14px;flex:1;">${s.description || s.key}</span>
          <button class="toggle ${on ? 'on' : ''}" id="setting-${s.key}" data-key="${s.key}" data-value="${on ? '1' : '0'}" data-istoggle="1" onclick="toggleNotif(this)"></button>
        </div>`;
    });
    html += '<div style="height:16px;"></div>';
  }
  inputs.forEach(s => {
    html += `<div class="setting-key">${s.description || s.key}</div>
      <input class="setting-input" type="${s.key.includes('password') || s.key.includes('token') ? 'password' : 'text'}" id="setting-${s.key}" value="${s.value}" placeholder="${s.key}">`;
  });
  el.innerHTML = html;
}

function toggleNotif(btn) {
  const on = btn.classList.toggle('on');
  btn.dataset.value = on ? '1' : '0';
}

async function salvaImpostazioniAdmin() {
  const payload = {};
  document.querySelectorAll('#admin-settings-form .setting-input').forEach(inp => {
    payload[inp.id.replace('setting-', '')] = inp.value;
  });
  document.querySelectorAll('#admin-settings-form [data-istoggle="1"]').forEach(t => {
    payload[t.id.replace('setting-', '')] = t.dataset.value;
  });
  const r = await apiFetch(`${API_BASE()}/api/admin/settings`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
  });
  if (r.ok) toast('Impostazioni salvate');
  else { const d = await r.json(); toast(d.error || 'Errore nel salvataggio'); }
}

async function creaUtente() {
  const username = document.getElementById('new-username').value.trim();
  const password = document.getElementById('new-password').value;
  const isAdmin = document.getElementById('new-is-admin').checked;
  if (!username || password.length < 6) { toast('Username e password (min 6) richiesti'); return; }
  const r = await apiFetch(`${API_BASE()}/api/admin/users`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, is_admin: isAdmin })
  });
  if (r.ok) {
    toast(`Utente ${username} creato`);
    document.getElementById('new-username').value = '';
    document.getElementById('new-password').value = '';
    document.getElementById('new-is-admin').checked = false;
    caricaUtenti();
  } else { const d = await r.json(); toast(d.error || 'Errore creazione utente'); }
}

function openModal(id) { document.getElementById(id).classList.remove('hidden'); }
function closeModal(id) { document.getElementById(id).classList.add('hidden'); }

let _editUserId = null;
function editUser(id, username, isAdmin, isActive) {
  _editUserId = id;
  document.getElementById('edit-user-username').textContent = username;
  document.getElementById('edit-user-password').value = '';
  document.getElementById('edit-user-is-admin').checked = !!isAdmin;
  document.getElementById('edit-user-is-active').checked = !!isActive;
  openModal('modal-edit-user');
}

async function submitEditUser() {
  const payload = {};
  const pwd = document.getElementById('edit-user-password').value;
  if (pwd.length > 0) {
    if (pwd.length < 6) { toast('Password di almeno 6 caratteri'); return; }
    payload.password = pwd;
  }
  payload.is_admin = document.getElementById('edit-user-is-admin').checked;
  payload.is_active = document.getElementById('edit-user-is-active').checked;
  const r = await apiFetch(`${API_BASE()}/api/admin/users/${_editUserId}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
  });
  closeModal('modal-edit-user');
  if (r.ok) { toast('Utente aggiornato'); caricaUtenti(); }
  else toast('Errore aggiornamento');
}

function deleteUser(id, username) {
  document.getElementById('modal-confirm-title').textContent = 'Elimina utente';
  document.getElementById('modal-confirm-msg').textContent = `Eliminare definitivamente "${username}"?`;
  const btn = document.getElementById('modal-confirm-ok');
  btn.className = 'btn btn-danger'; btn.textContent = 'Elimina';
  btn.onclick = async () => {
    closeModal('modal-confirm');
    const r = await apiFetch(`${API_BASE()}/api/admin/users/${id}`, { method: 'DELETE' });
    if (r.ok) { toast(`Utente ${username} eliminato`); caricaUtenti(); }
    else { const d = await r.json(); toast(d.error || 'Errore eliminazione'); }
  };
  openModal('modal-confirm');
}

async function caricaIPBans() {
  const r = await apiFetch(`${API_BASE()}/api/admin/ip-bans`);
  const bans = await r.json();
  const el = document.getElementById('admin-ip-bans-list');
  if (!bans.length) { el.innerHTML = '<div style="color:var(--muted);font-size:14px;padding:8px 0;">Nessun IP bannato</div>'; return; }
  el.innerHTML = bans.map(b => `
    <div class="ip-ban-row">
      <div style="flex:1;min-width:0;">
        <div class="ip-ban-ip">${b.ip}</div>
        <div class="ip-ban-info">${b.failed_attempts} tentativi falliti – ${new Date(b.banned_at).toLocaleString('it-IT')}</div>
      </div>
      <button class="btn-sm btn-sm-green" onclick="unbanIP('${b.ip}')">Sblocca</button>
    </div>`).join('');
}

function unbanIP(ip) {
  document.getElementById('modal-confirm-title').textContent = 'Sblocca IP';
  document.getElementById('modal-confirm-msg').textContent = `Sbloccare "${ip}"?`;
  const btn = document.getElementById('modal-confirm-ok');
  btn.className = 'btn btn-primary'; btn.textContent = 'Sblocca';
  btn.onclick = async () => {
    closeModal('modal-confirm');
    const r = await apiFetch(`${API_BASE()}/api/admin/ip-bans/${encodeURIComponent(ip)}`, { method: 'DELETE' });
    if (r.ok) { toast(`IP ${ip} sbloccato`); caricaIPBans(); }
    else toast('Errore sblocco IP');
  };
  openModal('modal-confirm');
}

async function banIP() {
  const ip = document.getElementById('ban-ip-input').value.trim();
  if (!ip) { toast('Inserisci un IP'); return; }
  const r = await apiFetch(`${API_BASE()}/api/admin/ip-bans`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ip })
  });
  if (r.ok) { toast(`IP ${ip} bannato`); document.getElementById('ban-ip-input').value = ''; caricaIPBans(); }
  else { const d = await r.json(); toast(d.error || 'Errore ban IP'); }
}

// ── API Key ───────────────────────────────────────────────────────────────────
async function caricaApiKey() {
  try {
    const r = await apiFetch(`${API_BASE()}/api/admin/api-key`);
    if (r.ok) { const data = await r.json(); document.getElementById('api-key-display').value = data.api_key || ''; }
  } catch(e) {}
}
function copiaApiKey() {
  const el = document.getElementById('api-key-display');
  if (!el || !el.value) { toast('Nessuna API key'); return; }
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(el.value).then(() => toast('🔑 API key copiata!')).catch(() => { el.select(); document.execCommand('copy'); toast('🔑 API key copiata!'); });
  } else { el.select(); document.execCommand('copy'); toast('🔑 API key copiata!'); }
}
function apriRigeneraApiKey() {
  document.getElementById('regen-confirm-input').value = '';
  const btn = document.getElementById('btn-regen-confirm');
  btn.disabled = true; btn.style.opacity = '0.4'; btn.style.cursor = 'not-allowed';
  openModal('modal-regen-apikey');
  setTimeout(() => document.getElementById('regen-confirm-input')?.focus(), 100);
}
function checkRegenConfirm() {
  const v = document.getElementById('regen-confirm-input').value.trim().toUpperCase();
  const btn = document.getElementById('btn-regen-confirm');
  const ok = (v === 'RIGENERA');
  btn.disabled = !ok; btn.style.opacity = ok ? '1' : '0.4'; btn.style.cursor = ok ? 'pointer' : 'not-allowed';
}
async function rigeneraApiKey() {
  const btn = document.getElementById('btn-regen-confirm');
  if (btn.disabled) return;
  btn.disabled = true;
  try {
    const r = await apiFetch(`${API_BASE()}/api/admin/api-key/regenerate`, { method: 'POST' });
    closeModal('modal-regen-apikey');
    if (r.ok) { const data = await r.json(); document.getElementById('api-key-display').value = data.api_key; toast('🔑 Nuova API key generata!', 5000); }
    else toast('Errore');
  } catch(e) { closeModal('modal-regen-apikey'); toast('Errore di rete'); }
}

// ── Backup / Restore ─────────────────────────────────────────────────────────
async function caricaBackupStatus() {
  try {
    const r = await apiFetch(`${API_BASE()}/api/admin/backup/auto-status`);
    const s = await r.json();
    const el = document.getElementById('auto-backup-status');
    if (!el) return;
    if (s.exists) {
      const sizeKB = (s.size_bytes / 1024).toFixed(1);
      const data = new Date(s.modified_at).toLocaleString('it-IT');
      el.innerHTML = `📅 Ultimo backup auto: <strong>${data}</strong><br>📦 ${sizeKB} KB · ${s.age_days} giorni fa`;
    } else {
      el.textContent = 'Nessun backup automatico ancora generato (prossimo entro 1h).';
    }
  } catch(e) {}
}

async function scaricaBackup() {
  toast('⏳ Generazione backup...');
  try {
    const r = await apiFetch(`${API_BASE()}/api/admin/backup`);
    if (!r.ok) { toast('Errore generazione backup'); return; }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `dispensa_backup_${new Date().toISOString().split('T')[0]}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast('✅ Backup scaricato');
  } catch(e) { toast('Errore download'); }
}

async function forzaBackupAuto() {
  if (!confirm('Generare ora un nuovo backup automatico (sovrascrive il precedente)?')) return;
  toast('⏳ Generazione backup...');
  try {
    const r = await apiFetch(`${API_BASE()}/api/admin/backup/auto-now`, { method: 'POST' });
    const data = await r.json();
    if (r.ok) { toast(`✅ Backup salvato (${(data.size_bytes/1024).toFixed(1)} KB)`); caricaBackupStatus(); }
    else toast('Errore: ' + (data.error || ''));
  } catch(e) { toast('Errore di rete'); }
}

let _restoreFileData = null;
function apriRestoreBackup() {
  document.getElementById('restore-file').value = '';
  document.getElementById('restore-confirm-input').value = '';
  const btn = document.getElementById('btn-restore-confirm');
  btn.disabled = true; btn.style.opacity = '0.4';
  _restoreFileData = null;
  openModal('modal-restore');
  document.getElementById('restore-file').onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const text = await file.text();
      _restoreFileData = JSON.parse(text);
      if (!_restoreFileData._meta || _restoreFileData._meta.version !== 'dispensa-manager-backup-v1') {
        toast('⚠️ File backup non valido');
        _restoreFileData = null;
      } else {
        toast('✅ File caricato');
      }
    } catch(err) { toast('⚠️ File JSON non valido'); _restoreFileData = null; }
    checkRestoreConfirm();
  };
}

function checkRestoreConfirm() {
  const v = document.getElementById('restore-confirm-input').value.trim().toUpperCase();
  const btn = document.getElementById('btn-restore-confirm');
  const ok = (v === 'RIPRISTINA') && _restoreFileData;
  btn.disabled = !ok;
  btn.style.opacity = ok ? '1' : '0.4';
  btn.style.cursor = ok ? 'pointer' : 'not-allowed';
}

async function eseguiRestore() {
  const btn = document.getElementById('btn-restore-confirm');
  if (btn.disabled || !_restoreFileData) return;
  btn.disabled = true;
  toast('⏳ Ripristino in corso...');
  try {
    const r = await apiFetch(`${API_BASE()}/api/admin/restore`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ confirm: 'RIPRISTINA', backup: _restoreFileData })
    });
    const data = await r.json();
    closeModal('modal-restore');
    if (r.ok) {
      toast(`✅ Ripristinati: ${Object.entries(data.ripristinati).map(([k,v]) => `${v} ${k}`).join(', ')}`, 6000);
      setTimeout(() => location.reload(), 2000);
    } else {
      toast('Errore: ' + (data.error || ''), 4000);
    }
  } catch(e) { closeModal('modal-restore'); toast('Errore di rete'); }
  _restoreFileData = null;
}
