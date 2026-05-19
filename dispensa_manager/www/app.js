const API_BASE = () => {
  const u = document.querySelector('meta[name="cf-url"]')?.content || '';
  return u || window.location.pathname.replace(/\/+$/g, '');
};

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
    const r = await fetch(API_BASE() + '/api/auth/refresh', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + rt }
    });
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
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
function hideLoginOverlay() {
  document.getElementById('login-overlay').classList.add('hidden');
}

function doLogout() {
  clearAuth();
  showLoginOverlay();
}

function applyUserUI() {
  const user = getCurrentUser();
  if (!user) return;
  document.querySelectorAll('.tab-admin').forEach(el => {
    el.style.display = user.is_admin ? '' : 'none';
  });
  const el = document.getElementById('current-username');
  if (el) el.textContent = user.username + (user.is_admin ? ' (admin)' : '');
}

async function initAuth() {
  if (!getAccessToken()) { showLoginOverlay(); return; }
  try {
    const r = await fetch(API_BASE() + '/api/auth/me', {
      headers: { 'Authorization': 'Bearer ' + getAccessToken() }
    });
    if (r.ok) {
      const me = await r.json();
      saveAuth({ access_token: getAccessToken(), username: me.username, is_admin: me.is_admin });
      hideLoginOverlay();
      applyUserUI();
      return;
    }
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      hideLoginOverlay();
      applyUserUI();
    } else {
      clearAuth();
      showLoginOverlay();
    }
  } catch {
    hideLoginOverlay();
    applyUserUI();
  }
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('login-password')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') doLogin();
  });
  document.getElementById('login-username')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('login-password')?.focus();
  });
});

let codeReader = null;
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

function showScreen(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
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
  else if (tab === 'impostazioni') { showScreen('screen-impostazioni'); applyUserUI(); }
  else if (tab === 'admin') { showScreen('screen-admin'); caricaAdmin(); }
}

function toast(msg, durata = 2500) {
  const t = document.getElementById('toast');
  if (_undoTimer) { clearTimeout(_undoTimer); _undoTimer = null; _undoFn = null; }
  t.classList.remove('with-undo');
  t.innerHTML = '';
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), durata);
}

let _undoTimer = null;
let _undoFn = null;

function toastUndo(msg, undoFn, durata = 4000) {
  const t = document.getElementById('toast');
  if (_undoTimer) { clearTimeout(_undoTimer); _undoTimer = null; }
  _undoFn = undoFn;
  t.innerHTML = `<span>${msg}</span><button class="toast-undo-btn" onclick="_eseguiUndo()">Annulla</button>`;
  t.classList.add('show', 'with-undo');
  _undoTimer = setTimeout(() => {
    t.classList.remove('show', 'with-undo');
    _undoFn = null; _undoTimer = null;
  }, durata);
}

async function _eseguiUndo() {
  if (!_undoFn) return;
  const fn = _undoFn;
  _undoFn = null;
  if (_undoTimer) { clearTimeout(_undoTimer); _undoTimer = null; }
  const t = document.getElementById('toast');
  t.classList.remove('show', 'with-undo');
  await fn();
  toast('Annullato ✓');
}

async function caricaInventario() {
  try {
    const r = await apiFetch(`${API_BASE()}/api/prodotti`);
    prodottiCache = await r.json();
    applicaFiltroSort();
  } catch(e) {
    document.getElementById('lista-prodotti').innerHTML = `<div class="empty"><div class="empty-icon">⚠️</div><div>Backend non raggiungibile.<br>Controlla le impostazioni.</div></div>`;
  }
}

function setFiltro(f) {
  filtroAttivo = f;
  document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
  document.querySelector(`.chip[data-filtro="${f}"]`).classList.add('active');
  applicaFiltroSort();
}

function applicaFiltroSort() {
  const q = (document.getElementById('ricerca-input')?.value || '').toLowerCase().trim();
  const ord = document.getElementById('sort-select')?.value || 'inserimento';
  const giorniAlert = parseInt(localStorage.getItem('dispensa_giorni') || '3');
  const oggi = new Date(); oggi.setHours(0,0,0,0);

  let attivi = prodottiCache.filter(p => p.quantita > 0);
  let esauriti = prodottiCache.filter(p => p.quantita <= 0);

  if (filtroAttivo === 'scadenza') {
    attivi = attivi.filter(p => {
      if (!p.scadenza) return false;
      const gg = Math.round((new Date(p.scadenza) - oggi) / 86400000);
      return gg >= 0 && gg <= giorniAlert;
    });
    esauriti = [];
  } else if (filtroAttivo === 'scaduti') {
    attivi = attivi.filter(p => {
      if (!p.scadenza) return false;
      const gg = Math.round((new Date(p.scadenza) - oggi) / 86400000);
      return gg < 0;
    });
    esauriti = [];
  } else if (filtroAttivo === 'frigo') {
    attivi = attivi.filter(p => p.posizione === 'Frigo');
    esauriti = esauriti.filter(p => p.posizione === 'Frigo');
  } else if (filtroAttivo === 'freezer') {
    attivi = attivi.filter(p => p.posizione === 'Freezer');
    esauriti = esauriti.filter(p => p.posizione === 'Freezer');
  } else if (filtroAttivo === 'dispensa') {
    attivi = attivi.filter(p => p.posizione === 'Dispensa');
    esauriti = esauriti.filter(p => p.posizione === 'Dispensa');
  }

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

function avviaScannerRicerca() {
  scanMode = 'search';
  showScreen('screen-scan');
}

function cercaNellaDispensa(ean) {
  const trovato = prodottiCache.find(p => p.ean === ean);
  showScreen('screen-inventario');
  if (trovato) { apriDettaglio(trovato.id); }
  else { toast('Prodotto non trovato in dispensa'); }
}

async function consumaRapido(id, qtyAttuali) {
  const nuova = Math.max(0, qtyAttuali - 1);
  await apiFetch(`${API_BASE()}/api/prodotti/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({quantita: nuova}) });
  const p = prodottiCache.find(x => x.id === id);
  if (p) p.quantita = nuova;
  applicaFiltroSort();
  toastUndo('−1', async () => {
    await apiFetch(`${API_BASE()}/api/prodotti/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({quantita: qtyAttuali}) });
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
    await apiFetch(`${API_BASE()}/api/prodotti/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({quantita: qtyAttuali}) });
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
  showScreen('screen-modifica');
}

function cambiaQtyMod(delta) {
  modQtyCorrente = Math.max(0, modQtyCorrente + delta);
  document.getElementById('mod-qty-val').textContent = modQtyCorrente;
}

async function salvaModifica() {
  const payload = {
    nome: document.getElementById('mod-nome').value.trim() || 'Prodotto',
    marca: document.getElementById('mod-marca').value.trim(),
    quantita: modQtyCorrente,
    scadenza: document.getElementById('mod-scadenza').value || null,
    posizione: document.getElementById('mod-posizione').value,
    note: document.getElementById('mod-note').value.trim()
  };
  try {
    await apiFetch(`${API_BASE()}/api/prodotti/${modProdottoId}`, {
      method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)
    });
    toast('Prodotto aggiornato!');
    showScreen('screen-inventario');
  } catch(e) {
    toast('Errore salvataggio. Riprova.');
  }
}

function initDarkMode() {
  const isDark = localStorage.getItem('dispensa_dark') === '1';
  if (isDark) document.documentElement.classList.add('dark');
  const btn = document.getElementById('dark-toggle');
  if (btn) btn.classList.toggle('on', isDark);
}

function toggleDarkMode() {
  const isDark = document.documentElement.classList.toggle('dark');
  localStorage.setItem('dispensa_dark', isDark ? '1' : '0');
  const btn = document.getElementById('dark-toggle');
  if (btn) btn.classList.toggle('on', isDark);
}

function esportaCSV() {
  if (!prodottiCache.length) { toast('Nessun prodotto da esportare'); return; }
  const cols = ['ID','Nome','Marca','Categoria','Quantità','Scadenza','Posizione','EAN','Note'];
  const righe = prodottiCache.map(p => [
    p.id, p.nome, p.marca||'', p.categoria||'', p.quantita,
    p.scadenza||'', p.posizione||'', p.ean||'', (p.note||'').replace(/"/g,"'")
  ].map(v => `"${v}"`).join(','));
  const csv = [cols.join(','), ...righe].join('\n');
  const blob = new Blob(['﻿' + csv], {type: 'text/csv;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = `dispensa_${new Date().toISOString().split('T')[0]}.csv`;
  a.click(); URL.revokeObjectURL(url);
  toast('CSV esportato!');
}

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
      html += `<div class="prod-item" onclick="apriDettaglio(${p.id})">
        <div class="prod-dot ${dotClass}"></div>
        <div class="prod-info">
          <div class="prod-nome">${p.nome}</div>
          <div class="prod-meta">${p.marca ? p.marca + ' · ' : ''}${p.posizione ? p.posizione + (metaText ? ' · ' : '') : ''}${metaText}</div>
          ${badgeHtml}
        </div>
        <div class="prod-actions" onclick="event.stopPropagation()">
          <div class="quick-btn" onclick="consumaRapido(${p.id},${p.quantita})">&minus;</div>
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
      esauritiHtml += `<div class="prod-item esaurito" onclick="apriDettaglio(${p.id})">
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
}

function toggleEsauriti() {
  esauritiOpen = !esauritiOpen;
  const list = document.getElementById('esauriti-list-inner');
  const chevron = document.querySelector('.esauriti-chevron');
  if (list) list.classList.toggle('open', esauritiOpen);
  if (chevron) chevron.classList.toggle('open', esauritiOpen);
}

function apriDettaglio(id) {
  const p = prodottiCache.find(x => x.id === id);
  if (!p) return;
  detQtyDelta = 1;
  document.getElementById('det-title').textContent = p.nome;
  const scadFormatted = p.scadenza ? new Date(p.scadenza).toLocaleDateString('it-IT', {day:'numeric',month:'long',year:'numeric'}) : 'Non specificata';
  const isEsaurito = p.quantita <= 0;
  document.getElementById('det-content').innerHTML = `
    <div class="card card-body">
      ${p.immagine_url ? `<img src="${p.immagine_url}" style="width:100%;max-height:180px;object-fit:contain;border-radius:12px;margin-bottom:16px;background:var(--bg);">` : ''}
      <div style="font-size: 20px; font-weight: 700; margin-bottom: 4px;">${p.nome}</div>
      <div style="font-size: 14px; color: var(--muted); margin-bottom: 20px;">${p.marca || ''} ${p.categoria ? '· ' + p.categoria : ''}</div>
      ${isEsaurito ? '<div style="background:var(--gray-l);border-radius:10px;padding:8px 12px;margin-bottom:12px;font-size:13px;color:var(--gray);font-weight:500;">⬜ Prodotto esaurito — rimane nel database</div>' : ''}
      <table style="width:100%;font-size:14px;border-collapse:collapse;">
        <tr><td style="color:var(--muted);padding:8px 0;border-bottom:0.5px solid var(--border);">Posizione</td><td style="text-align:right;font-weight:600;border-bottom:0.5px solid var(--border);">${p.posizione === 'Frigo' ? '🧠 Frigo' : p.posizione === 'Freezer' ? '❄️ Freezer' : '🗄️ Dispensa'}</td></tr>
        <tr><td style="color:var(--muted);padding:8px 0;border-bottom:0.5px solid var(--border);">Quantità</td><td style="text-align:right;font-weight:600;border-bottom:0.5px solid var(--border);">${p.quantita}</td></tr>
        <tr><td style="color:var(--muted);padding:8px 0;border-bottom:0.5px solid var(--border);">Scadenza</td><td style="text-align:right;font-weight:600;border-bottom:0.5px solid var(--border);">${scadFormatted}</td></tr>
        <tr><td style="color:var(--muted);padding:8px 0;">EAN</td><td style="text-align:right;font-size:12px;font-family:monospace;">${p.ean}</td></tr>
      </table>
    </div>
    ${p.nutriments ? (() => {
      const n = typeof p.nutriments === 'string' ? JSON.parse(p.nutriments) : p.nutriments;
      const righe = [
        ['Energia', n.energia_kcal, 'kcal'],['Grassi', n.grassi, 'g'],['di cui saturi', n.grassi_saturi, 'g'],
        ['Carboidrati', n.carboidrati, 'g'],['di cui zuccheri', n.zuccheri, 'g'],['Fibre', n.fibre, 'g'],
        ['Proteine', n.proteine, 'g'],['Sale', n.sale, 'g'],
      ].filter(r => r[1] != null);
      if (!righe.length) return '';
      const nsColor = {'A':'#1D9E75','B':'#8BC34A','C':'#FFC107','D':'#FF9800','E':'#F44336'};
      return `<div class="card card-body" style="margin-top:8px;">
        <div style="font-size:13px;font-weight:600;color:var(--muted);margin-bottom:12px;">📊 Valori nutrizionali per 100g</div>
        <table style="width:100%;font-size:13px;border-collapse:collapse;">
          ${righe.map((r,i) => `<tr><td style="color:var(--muted);padding:6px 0;${i<righe.length-1?'border-bottom:0.5px solid var(--border);':''}${r[0].startsWith('di')?'padding-left:12px;':''} ">${r[0]}</td><td style="text-align:right;font-weight:${r[0].startsWith('di')?'400':'600'};${i<righe.length-1?'border-bottom:0.5px solid var(--border);':''">${Number(r[1]).toFixed(1)} ${r[2]}</td></tr>`).join('')}
        </table>
        ${p.nutriscore ? `<div style="margin-top:12px;font-size:13px;color:var(--muted);">Nutri-Score: <strong style="font-size:16px;color:${nsColor[p.nutriscore]||'var(--text)'}">● ${p.nutriscore}</strong></div>` : ''}
      </div>`;
    })() : ''}
    <div class="card card-body" style="margin-top:8px;">
      <div style="font-size:13px;color:var(--muted);margin-bottom:10px;">Quantità da aggiornare</div>
      <div class="qty-row" style="margin-bottom:12px;">
        <div class="qty-btn" onclick="cambiaQtyDet(-1)">&minus;</div>
        <div class="qty-val" id="det-qty-delta">1</div>
        <div class="qty-btn" onclick="cambiaQtyDet(1)">+</div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <button class="btn btn-secondary" onclick="consumaProdotto(${p.id},${p.quantita})">&minus; Consuma</button>
        <button class="btn btn-secondary" onclick="aggiungiQty(${p.id},${p.quantita})">+ Aggiungi</button>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:8px;">
      <button class="btn btn-secondary" onclick="apriModifica(${p.id})">✏️ Modifica</button>
      <button class="btn btn-danger" onclick="eliminaProdotto(${p.id})">🗑️ Elimina</button>
    </div>
  `;
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
    await apiFetch(`${API_BASE()}/api/prodotti/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({quantita: qtyAttuali}) });
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
    await apiFetch(`${API_BASE()}/api/prodotti/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({quantita: qtyAttuali}) });
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

function avviaScanner() {
  if (codeReader) return;
  const hasCamera = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  if (!hasCamera) {
    document.getElementById('video-container').style.display = 'none';
    document.getElementById('scan-foto-btn').style.display = 'block';
    document.getElementById('scan-status').textContent = scanMode === 'search'
      ? 'Scatta una foto del barcode per cercarlo'
      : 'Scatta una foto del barcode per aggiungerlo';
    return;
  }
  document.getElementById('video-container').style.display = '';
  document.getElementById('scan-foto-btn').style.display = 'none';
  document.getElementById('scan-status').textContent = 'Avvio fotocamera...';
  codeReader = new ZXing.BrowserMultiFormatReader();
  codeReader.decodeFromVideoDevice(null, 'video', async (result, err) => {
    if (result) {
      fermaScanner();
      document.getElementById('scan-status').textContent = 'Codice rilevato!';
      if (scanMode === 'search') { cercaNellaDispensa(result.getText()); }
      else { await cercaProdotto(result.getText()); }
    }
  });
  document.getElementById('scan-status').textContent = scanMode === 'search'
    ? 'Inquadra il barcode per cercare nella dispensa'
    : 'Inquadra il barcode del prodotto';
}

function fermaScanner() {
  if (codeReader) { codeReader.reset(); codeReader = null; }
  const video = document.getElementById('video');
  if (video && video.srcObject) { video.srcObject.getTracks().forEach(t => t.stop()); video.srcObject = null; }
  const vc = document.getElementById('video-container');
  if (vc) vc.style.display = '';
  const sfb = document.getElementById('scan-foto-btn');
  if (sfb) sfb.style.display = 'none';
}

function avviaFotoScan() {
  document.getElementById('barcode-file-input').click();
}

async function scansionaFoto(input) {
  const file = input.files[0];
  if (!file) return;
  input.value = '';
  const btn = document.getElementById('scan-foto-btn');
  const status = document.getElementById('scan-status');
  status.textContent = 'Analisi barcode in corso...';
  btn.disabled = true;
  const imgUrl = URL.createObjectURL(file);
  try {
    const reader = new ZXing.BrowserMultiFormatReader();
    const result = await reader.decodeFromImageUrl(imgUrl);
    status.textContent = 'Codice rilevato!';
    if (scanMode === 'search') { cercaNellaDispensa(result.getText()); }
    else { await cercaProdotto(result.getText()); }
  } catch(e) {
    status.textContent = 'Barcode non riconosciuto. Usa una foto nitida e ben illuminata.';
    btn.disabled = false;
    toast('Barcode non riconosciuto, riprova');
  } finally {
    URL.revokeObjectURL(imgUrl);
  }
}

async function cercaProdotto(ean) {
  document.getElementById('scan-status').textContent = 'Ricerca prodotto...';
  try {
    const r = await apiFetch(`${API_BASE()}/api/barcode/${ean}`);
    const data = await r.json();
    apriConferma(data);
  } catch(e) {
    apriConferma({ trovato: false, ean, nome: '', marca: '', categoria: '', immagine_url: '' });
  }
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
    ? `<div class="found-badge"><div class="found-badge-dot"></div><div class="found-badge-text">Trovato su Open Food Facts · ${posizione === 'Frigo' ? '🧠 Frigo' : posizione === 'Freezer' ? '❄️ Freezer' : '🗄️ Dispensa'} suggerito</div></div>`
    : `<div class="found-badge" style="background:#FAEEDA"><div class="found-badge-dot" style="background:#EF9F27"></div><div class="found-badge-text" style="color:#854F0B">Prodotto non trovato — inserisci i dettagli e aggiungi foto</div></div>`;
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
    nutriscore: prodottoCorrente.nutriscore || ''
  };
  try {
    await apiFetch(`${API_BASE()}/api/prodotti`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
    if (payload.ean && !payload.ean.startsWith('MANUAL-') && prodottoCorrente.trovato) {
      await apiFetch(`${API_BASE()}/api/barcode-cache`, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
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
  } catch(e) {
    toast('Errore salvataggio. Riprova.');
  }
}

function inserisciManuale() {
  const ean = prompt('Inserisci il codice a barre (EAN) del prodotto:\n(lascia vuoto per inserimento manuale senza barcode)');
  if (ean === null) return;
  if (ean.trim() !== '') { cercaProdotto(ean.trim()); }
  else { apriConferma({ trovato: false, ean: 'MANUAL-' + Date.now(), nome: '', marca: '', categoria: '', immagine_url: '' }); }
}

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
    document.getElementById('lista-spesa').innerHTML = `<div class="empty"><div class="empty-icon">🛒</div><div>Lista spesa vuota!<br>I prodotti esauriti appariranno qui.</div></div>`;
    return;
  }
  let html = '';
  items.forEach(item => {
    const done = item.completato === 1;
    html += `<div class="spesa-item">
      <div class="spesa-check ${done ? 'done' : ''}" onclick="toggleSpesa(${item.id}, ${done ? 0 : 1})"></div>
      <div class="spesa-info" style="flex:1;min-width:0;">
        <div class="spesa-nome ${done ? 'done' : ''}">${item.nome}</div>
        ${item.marca ? `<div style="font-size:12px;color:var(--muted);">${item.marca}</div>` : ''}
      </div>
      <div class="spesa-del" onclick="eliminaSpesa(${item.id})">✕</div>
    </div>`;
  });
  document.getElementById('lista-spesa').innerHTML = html;
}

async function toggleSpesa(id, completato) {
  await apiFetch(`${API_BASE()}/api/lista-spesa/${id}`, {
    method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({completato, quantita: 1})
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

async function caricaStatistiche() {
  try {
    const r = await apiFetch(`${API_BASE()}/api/statistiche`);
    const s = await r.json();
    const posIcon = {'Frigo':'🧠','Freezer':'❄️','Dispensa':'🗄️'};
    let html = `
      <div class="metric-row" style="grid-template-columns:repeat(2,1fr);">
        <div class="metric"><div class="metric-val">${s.totali.acquisti}</div><div class="metric-label">Acquisti totali</div></div>
        <div class="metric"><div class="metric-val">${s.totali.consumi}</div><div class="metric-label">Consumi totali</div></div>
        <div class="metric"><div class="metric-val">${s.totali.acquisti_mese}</div><div class="metric-label">Acquisti questo mese</div></div>
        <div class="metric"><div class="metric-val">${s.totali.eliminati}</div><div class="metric-label">Eliminati</div></div>
      </div>`;
    if (s.per_posizione.length) {
      html += `<div class="card card-body" style="margin-bottom:12px;"><div style="font-size:13px;font-weight:600;color:var(--muted);margin-bottom:12px;">📍 Prodotti per posizione</div>`;
      s.per_posizione.forEach(p => {
        html += `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:0.5px solid var(--border);font-size:14px;"><span>${posIcon[p.posizione]||'📦'} ${p.posizione || 'Non specificata'}</span><strong>${p.n}</strong></div>`;
      });
      html += `</div>`;
    }
    if (s.top_acquistati.length) {
      html += `<div class="card card-body" style="margin-bottom:12px;"><div style="font-size:13px;font-weight:600;color:var(--muted);margin-bottom:12px;">\ud83c� Più acquistati</div>`;
      s.top_acquistati.forEach((p,i) => {
        html += `<div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:0.5px solid var(--border);"><span style="font-size:16px;font-weight:700;color:var(--muted);width:20px;">${i+1}</span><div style="flex:1;font-size:14px;">${p.nome}<br><span style="font-size:12px;color:var(--muted);">${p.marca||''}</span></div><span style="font-size:13px;color:var(--green);font-weight:600;">&times;${p.totale}</span></div>`;
      });
      html += `</div>`;
    }
    if (s.top_consumati.length) {
      html += `<div class="card card-body" style="margin-bottom:12px;"><div style="font-size:13px;font-weight:600;color:var(--muted);margin-bottom:12px;">\ud83d� Più consumati</div>`;
      s.top_consumati.forEach((p,i) => {
        html += `<div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:0.5px solid var(--border);"><span style="font-size:16px;font-weight:700;color:var(--muted);width:20px;">${i+1}</span><div style="flex:1;font-size:14px;">${p.nome}<br><span style="font-size:12px;color:var(--muted);">${p.marca||''}</span></div><span style="font-size:13px;color:var(--amber);font-weight:600;">&times;${p.totale}</span></div>`;
      });
      html += `</div>`;
    }
    if (!s.top_acquistati.length && !s.top_consumati.length) {
      html += `<div class="empty"><div class="empty-icon">📊</div><div>Nessun dato ancora.<br>Le statistiche si accumulano con l'uso!</div></div>`;
    }
    document.getElementById('stat-content').innerHTML = html;
  } catch(e) {
    document.getElementById('stat-content').innerHTML = `<div class="empty"><div class="empty-icon">⚠️</div><div>Backend non raggiungibile.</div></div>`;
  }
}

let ocrStream = null;

function avviaOCRScadenza() {
  const modal = document.getElementById('ocr-modal');
  modal.style.display = 'flex';
  document.getElementById('ocr-status').textContent = 'Avvio fotocamera...';
  document.getElementById('ocr-manuale').style.display = 'none';
  navigator.mediaDevices.getUserMedia({
    video: { facingMode: 'environment', width: { ideal: 1920 }, height: { ideal: 1080 } }
  }).then(stream => {
    ocrStream = stream;
    const video = document.getElementById('ocr-video');
    video.srcObject = stream;
    document.getElementById('ocr-status').textContent = 'Inquadra la data di scadenza nella cornice verde';
  }).catch(err => {
    document.getElementById('ocr-status').textContent = 'Errore fotocamera: ' + err.message;
  });
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
  document.getElementById('ocr-status').textContent = '\ud83d� Elaborazione immagine...';
  try {
    const processed = preprocessCanvas(canvas);
    let text = '';
    const r1 = await Tesseract.recognize(processed, 'ita+eng', { logger: () => {},
      tessedit_char_whitelist: '0123456789/-.ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz '
    });
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
      const testoLetto = text.replace(/\n/g, ' ').trim().substring(0, 100);
      document.getElementById('ocr-status').textContent = '⚠️ Data non rilevata automaticamente.';
      document.getElementById('ocr-testo-letto').textContent = testoLetto ? `Testo letto: "${testoLetto}"` : '';
      document.getElementById('ocr-manuale').style.display = 'block';
    }
  } catch(e) {
    document.getElementById('ocr-status').textContent = '⚠️ Errore OCR. Inserisci manualmente.';
    document.getElementById('ocr-manuale').style.display = 'block';
  }
}

function confermaManualeOCR() {
  const input = document.getElementById('ocr-input-manuale').value.trim();
  const data = estraiDataScadenza(input) || estraiDataLibera(input);
  if (data) {
    document.getElementById('conf-scadenza').value = data;
    chiudiOCR();
    toast('✅ Scadenza impostata: ' + formatDataIT(data));
  } else {
    document.getElementById('ocr-status').textContent = '⚠️ Formato non riconosciuto. Prova: GG/MM/AAAA o MM/AAAA o AAAA/MM';
  }
}

function estraiDataLibera(input) {
  const t = input.trim().replace(/\s+/g, ' ');
  return estraiDataScadenza(t);
}

function estraiDataScadenza(testo) {
  if (!testo) return null;
  let t = testo.toUpperCase()
    .replace(/[Oo]/g, '0').replace(/[Il\|]/g, '1').replace(/[Ss]/g, '5')
    .replace(/[Bb]/g, '8').replace(/\r/g, ' ').replace(/\n/g, ' ');
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

function formatDataIT(iso) {
  const [y, m, d] = iso.split('-');
  return `${d}/${m}/${y}`;
}

function salvaImpostazioni() {
  const giorni = document.getElementById('set-giorni').value;
  if (giorni) localStorage.setItem('dispensa_giorni', giorni);
  toast('Impostazioni salvate');
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
  if ('caches' in window) {
    const keys = await caches.keys();
    await Promise.all(keys.map(k => caches.delete(k)));
  }
  if ('serviceWorker' in navigator) {
    const regs = await navigator.serviceWorker.getRegistrations();
    await Promise.all(regs.map(r => r.unregister()));
  }
  location.reload(true);
}

document.getElementById('set-giorni').value = localStorage.getItem('dispensa_giorni') || '3';
initDarkMode();
initAuth().then(() => caricaInventario());

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js')
    .catch(err => console.warn('SW non registrato:', err));
}

checkForUpdates();
setInterval(checkForUpdates, 5 * 60 * 1000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) checkForUpdates(); });

function applyDeepLink() {
  const params = new URLSearchParams(window.location.search);
  const filtro = params.get('filter');
  const validi = ['tutti', 'scadenza', 'scaduti', 'frigo', 'freezer', 'dispensa'];
  if (filtro && validi.indexOf(filtro) !== -1) setFiltro(filtro);
}
window.addEventListener('popstate', applyDeepLink);
setTimeout(applyDeepLink, 800);

async function caricaAdmin() {
  await Promise.all([caricaUtenti(), caricaImpostazioniAdmin(), caricaIPBans()]);
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
  el.innerHTML = settings.map(s => `
    <div class="setting-key">${s.description || s.key}</div>
    <input class="setting-input" type="${s.key.includes('password') || s.key.includes('token') ? 'password' : 'text'}"
      id="setting-${s.key}" value="${s.value}" placeholder="${s.key}">
  `).join('');
}

async function salvaImpostazioniAdmin() {
  const inputs = document.querySelectorAll('#admin-settings-form .setting-input');
  const payload = {};
  inputs.forEach(inp => {
    const key = inp.id.replace('setting-', '');
    payload[key] = inp.value;
  });
  const r = await apiFetch(`${API_BASE()}/api/admin/settings`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (r.ok) toast('Impostazioni salvate');
  else toast('Errore nel salvataggio');
}

async function creaUtente() {
  const username = document.getElementById('new-username').value.trim();
  const password = document.getElementById('new-password').value;
  const isAdmin = document.getElementById('new-is-admin').checked;
  if (!username || password.length < 6) { toast('Username e password (min 6 caratteri) richiesti'); return; }
  const r = await apiFetch(`${API_BASE()}/api/admin/users`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, is_admin: isAdmin })
  });
  if (r.ok) {
    toast(`Utente ${username} creato`);
    document.getElementById('new-username').value = '';
    document.getElementById('new-password').value = '';
    document.getElementById('new-is-admin').checked = false;
    caricaUtenti();
  } else {
    const d = await r.json();
    toast(d.error || 'Errore creazione utente');
  }
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
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  closeModal('modal-edit-user');
  if (r.ok) { toast('Utente aggiornato'); caricaUtenti(); }
  else toast('Errore aggiornamento');
}

function deleteUser(id, username) {
  document.getElementById('modal-confirm-title').textContent = 'Elimina utente';
  document.getElementById('modal-confirm-msg').textContent = `Eliminare definitivamente l'utente "${username}"?`;
  const btn = document.getElementById('modal-confirm-ok');
  btn.className = 'btn btn-danger';
  btn.textContent = 'Elimina';
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
  if (!bans.length) {
    el.innerHTML = '<div style="color:var(--muted);font-size:14px;padding:8px 0;">Nessun IP bannato</div>';
    return;
  }
  el.innerHTML = bans.map(b => `
    <div class="ip-ban-row">
      <div style="flex:1;min-width:0;">
        <div class="ip-ban-ip">${b.ip}</div>
        <div class="ip-ban-info">${b.failed_attempts} tentativi falliti – ${new Date(b.banned_at).toLocaleString('it-IT')}</div>
        ${b.reason ? `<div class="ip-ban-info">${b.reason}</div>` : ''}
      </div>
      <button class="btn-sm btn-sm-green" onclick="unbanIP('${b.ip}')">Sblocca</button>
    </div>`).join('');
}

function unbanIP(ip) {
  document.getElementById('modal-confirm-title').textContent = 'Sblocca IP';
  document.getElementById('modal-confirm-msg').textContent = `Sbloccare "${ip}" e cancellare i tentativi registrati?`;
  const btn = document.getElementById('modal-confirm-ok');
  btn.className = 'btn btn-primary';
  btn.textContent = 'Sblocca';
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
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ip })
  });
  if (r.ok) {
    toast(`IP ${ip} bannato`);
    document.getElementById('ban-ip-input').value = '';
    caricaIPBans();
  } else {
    const d = await r.json();
    toast(d.error || 'Errore ban IP');
  }
}
