// Lista della spesa (v2.2.0): da comprare per reparto, suggeriti (finiti in dispensa), carrello.
// Dipende da app.js: apiFetch, API_BASE, esc, jsArg, toast, toastUndo.

let _spesa = null;            // ultima risposta di /api/spesa
let _sugEspansi = false;      // elenco dei suggeriti aperto fino in fondo
const SUG_VISIBILI = 5;
let _cercaTimer = null;
let _cercaSeq = 0;

function _iconaPosizione(p) { return p === 'Frigo' ? '🧊' : p === 'Freezer' ? '❄️' : '🗄️'; }

async function caricaListaSpesa() {
  try {
    const r = await apiFetch(`${API_BASE()}/api/spesa`);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    _spesa = await r.json();
    renderSpesa();
    aggiornaBadgeSpesa(_spesa.conteggi.da_comprare);
  } catch (e) {
    document.getElementById('spesa-da-comprare').innerHTML =
      '<div class="card"><div class="empty"><div class="empty-icon">⚠️</div><div>Backend non raggiungibile.</div></div></div>';
  }
}

// Numero di voci da comprare sull'icona della scheda; senza numero lo chiede al server
async function aggiornaBadgeSpesa(n) {
  const badge = document.getElementById('badge-spesa');
  if (!badge) return;
  if (typeof n !== 'number') {
    try {
      const r = await apiFetch(`${API_BASE()}/api/spesa/conteggi`);
      if (!r.ok) return;
      n = (await r.json()).da_comprare;
    } catch (e) { return; }
  }
  badge.textContent = n > 99 ? '99+' : String(n);
  badge.style.display = n > 0 ? '' : 'none';
  badge.setAttribute('aria-label', n + ' da comprare');
}

function renderSpesa() {
  if (!_spesa) return;
  renderDaComprare(_spesa.da_comprare, _spesa.suggeriti.length);
  renderSuggeriti(_spesa.suggeriti);
  renderCarrello(_spesa.carrello);
}

function _metaVoce(v) {
  const parti = [];
  if (v.marca) parti.push(esc(v.marca));
  if (v.origine === 'alexa') parti.push('🎤 Alexa');
  else if (v.origine === 'widget') parti.push('📱 dal telefono');
  else if (v.aggiunto_da) parti.push('di ' + esc(v.aggiunto_da));
  let html = parti.length ? `<div class="spesa-meta">${parti.join(' · ')}</div>` : '';
  if (v.in_dispensa && v.in_dispensa.length) {
    const d = v.in_dispensa[0];
    const stesso = String(d.nome).toLowerCase() === String(v.nome).toLowerCase();
    html += `<div class="spesa-meta"><span class="spesa-chip">📦 ${stesso ? 'ne hai già' : 'hai già ' + esc(d.nome)} ×${esc(d.quantita)} ${_iconaPosizione(d.posizione)}</span></div>`;
  }
  return html;
}

function renderDaComprare(voci, nSuggeriti) {
  const el = document.getElementById('spesa-da-comprare');
  let html = `<div class="spesa-titolo">Da comprare <span class="spesa-n">${voci.length}</span></div>`;
  if (!voci.length) {
    html += `<div class="card"><div class="empty"><div class="empty-icon">🛒</div><div>Niente da comprare</div>` +
      (nSuggeriti ? `<div style="font-size:13px;margin-top:6px;">Guarda i prodotti finiti qui sotto</div>` : '') + `</div></div>`;
    el.innerHTML = html;
    return;
  }
  html += '<div class="card">';
  let reparto = null;
  voci.forEach(v => {
    if (v.reparto !== reparto) {
      reparto = v.reparto;
      html += `<div class="spesa-reparto">${esc(v.reparto_etichetta)}</div>`;
    }
    html += `<div class="spesa-item">
      <div class="spesa-check" role="checkbox" aria-checked="false" aria-label="Segna come comprato: ${esc(v.nome)}" tabindex="0" onclick="spuntaVoce(${v.id})"></div>
      <div class="spesa-info"><div class="spesa-nome">${esc(v.nome)}</div>${_metaVoce(v)}</div>
      <div class="spesa-qty">
        <div class="quick-btn" role="button" aria-label="Meno" onclick="qtaVoce(${v.id}, -1)">−</div>
        <span>${esc(v.quantita)}</span>
        <div class="quick-btn" role="button" aria-label="Più" onclick="qtaVoce(${v.id}, 1)">+</div>
      </div>
      <div class="spesa-del" role="button" aria-label="Rimuovi ${esc(v.nome)}" onclick="eliminaVoce(${v.id})">✕</div>
    </div>`;
  });
  el.innerHTML = html + '</div>';
}

function renderSuggeriti(sugg) {
  const el = document.getElementById('spesa-suggeriti');
  if (!sugg.length) { el.innerHTML = ''; return; }
  const mostrati = _sugEspansi ? sugg : sugg.slice(0, SUG_VISIBILI);
  let html = `<div class="spesa-titolo">💡 Finiti in dispensa <span class="spesa-n">${sugg.length}</span>
      <button type="button" class="spesa-link" onclick="aggiungiTuttiSuggeriti()">Aggiungi tutti</button></div>
    <div class="spesa-nota">Non sono in lista: scegli quali ricomprare.</div><div class="card">`;
  mostrati.forEach(s => {
    const quando = s.giorni == null ? '' : s.giorni === 0 ? ' · finito oggi' : s.giorni === 1 ? ' · finito ieri' : ` · finito da ${s.giorni} giorni`;
    html += `<div class="spesa-item sug-item">
      <div class="spesa-info"><div class="spesa-nome">${esc(s.nome)}</div>
        <div class="spesa-meta">${s.marca ? esc(s.marca) + ' · ' : ''}${_iconaPosizione(s.posizione)} ${esc(s.posizione)}${esc(quando)}</div></div>
      <button type="button" class="sug-btn" aria-label="Non serve: ${esc(s.nome)}" title="Non serve" onclick="ignoraSuggerito(${s.prodotto_id})">✕</button>
      <button type="button" class="sug-btn add" aria-label="Aggiungi alla lista: ${esc(s.nome)}" title="Aggiungi alla lista" onclick="aggiungiSuggerito(${s.prodotto_id})">+</button>
    </div>`;
  });
  html += '</div>';
  if (sugg.length > SUG_VISIBILI) {
    html += `<button type="button" class="spesa-altri" onclick="alternaSuggeriti()">${_sugEspansi ? 'Mostra meno' : 'Mostra tutti (' + sugg.length + ')'}</button>`;
  }
  const vecchi = sugg.filter(s => s.giorni != null && s.giorni >= 90).length;
  if (vecchi) {
    html += `<button type="button" class="spesa-altri spesa-altri-grigio" onclick="nascondiVecchi(${vecchi})">Nascondi i ${vecchi} finiti da più di 3 mesi</button>`;
  }
  el.innerHTML = html;
}

function renderCarrello(voci) {
  const el = document.getElementById('spesa-carrello');
  if (!voci.length) { el.innerHTML = ''; return; }
  let html = `<div class="spesa-titolo">🛒 Nel carrello <span class="spesa-n">${voci.length}</span>
      <button type="button" class="spesa-link" onclick="svuotaCompletati()">Svuota</button></div><div class="card">`;
  voci.forEach(v => {
    html += `<div class="spesa-item">
      <div class="spesa-check done" role="checkbox" aria-checked="true" aria-label="Rimetti in lista: ${esc(v.nome)}" tabindex="0" onclick="rimettiVoce(${v.id})"></div>
      <div class="spesa-info"><div class="spesa-nome done">${esc(v.nome)}${v.quantita > 1 ? ' ×' + esc(v.quantita) : ''}</div></div>
      <div class="spesa-del" role="button" aria-label="Rimuovi ${esc(v.nome)}" onclick="eliminaVoce(${v.id})">✕</div>
    </div>`;
  });
  el.innerHTML = html + '</div>';
}

function _voce(id) {
  if (!_spesa) return null;
  return _spesa.da_comprare.find(v => v.id === id) || _spesa.carrello.find(v => v.id === id) || null;
}

async function _put(id, corpo) {
  const r = await apiFetch(`${API_BASE()}/api/lista-spesa/${id}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo),
  });
  if (!r.ok) throw new Error('HTTP ' + r.status);
}

async function spuntaVoce(id) {
  const v = _voce(id);
  try {
    await _put(id, { completato: 1 });
  } catch (e) { toast('Errore, riprova'); return; }
  await caricaListaSpesa();
  toastUndo(v ? `Nel carrello: ${v.nome}` : 'Nel carrello', async () => { await _put(id, { completato: 0 }); caricaListaSpesa(); });
}

async function rimettiVoce(id) {
  try { await _put(id, { completato: 0 }); } catch (e) { toast('Errore, riprova'); return; }
  caricaListaSpesa();
}

async function qtaVoce(id, delta) {
  const v = _voce(id);
  if (!v) return;
  const nuova = v.quantita + delta;
  if (nuova < 1) { eliminaVoce(id); return; }
  if (nuova > 99) return;
  try { await _put(id, { quantita: nuova }); } catch (e) { toast('Errore, riprova'); return; }
  caricaListaSpesa();
}

async function eliminaVoce(id) {
  const v = _voce(id);
  try {
    const r = await apiFetch(`${API_BASE()}/api/lista-spesa/${id}`, { method: 'DELETE' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
  } catch (e) { toast('Errore, riprova'); return; }
  await caricaListaSpesa();
  if (v) toastUndo(`Rimosso: ${v.nome}`, async () => { await _aggiungi(v.nome, v.quantita); caricaListaSpesa(); });
}

async function svuotaCompletati() {
  await apiFetch(`${API_BASE()}/api/lista-spesa/svuota-completati`, { method: 'DELETE' });
  toast('Carrello svuotato');
  caricaListaSpesa();
}

async function _aggiungi(nome, quantita) {
  const r = await apiFetch(`${API_BASE()}/api/lista-spesa`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(quantita ? { nome, quantita } : { nome }),
  });
  return { ok: r.ok, dati: await r.json().catch(() => ({})) };
}

function _messaggioAggiunta(d, prefisso) {
  let m = d.riattivata ? `Rimesso in lista: ${d.nome}` : d.unita ? `Già in lista: ${d.nome}` : `${prefisso || 'Aggiunto'}: ${d.nome}`;
  if (d.in_dispensa && d.in_dispensa.length) {
    const x = d.in_dispensa[0];
    m += ` · in dispensa hai ${x.nome} ×${x.quantita} (${x.posizione})`;
  }
  return m;
}

async function aggiungiNome(testo) {
  const nome = String(testo || '').trim();
  if (!nome) return;
  try {
    const { ok, dati } = await _aggiungi(nome);
    if (!ok) { toast(dati.error || 'Errore, riprova'); return; }
    toast(_messaggioAggiunta(dati), dati.in_dispensa && dati.in_dispensa.length ? 4500 : 2500);
  } catch (e) { toast('Errore, riprova'); return; }
  const campo = document.getElementById('spesa-input');
  if (campo) campo.value = '';
  nascondiCompletamento();
  caricaListaSpesa();
}

function aggiungiDaCampo(ev) {
  ev.preventDefault();
  aggiungiNome(document.getElementById('spesa-input').value);
}

// Completamento mentre si scrive: voci usate spesso e prodotti conosciuti
function spesaCompleta(testo) {
  if (_cercaTimer) clearTimeout(_cercaTimer);
  const q = String(testo || '').trim();
  if (q.length < 2) { nascondiCompletamento(); return; }
  _cercaTimer = setTimeout(async () => {
    const mio = ++_cercaSeq;
    try {
      const r = await apiFetch(`${API_BASE()}/api/spesa/cerca?q=${encodeURIComponent(q)}`);
      if (!r.ok || mio !== _cercaSeq) return;
      const voci = await r.json();
      const box = document.getElementById('spesa-completa');
      if (!voci.length) { nascondiCompletamento(); return; }
      box.innerHTML = voci.map(v =>
        `<button type="button" onmousedown="event.preventDefault()" onclick="aggiungiNome(${jsArg(v.nome)})">${esc(v.nome)}` +
        `<small>${v.fonte === 'frequente' ? '↻ spesso' : '📦 dispensa'}</small></button>`).join('');
      box.style.display = 'block';
    } catch (e) { nascondiCompletamento(); }
  }, 180);
}

function nascondiCompletamento() {
  _cercaSeq++;
  const box = document.getElementById('spesa-completa');
  if (box) { box.style.display = 'none'; box.innerHTML = ''; }
}

async function aggiungiSuggerito(pid) {
  const s = _spesa && _spesa.suggeriti.find(x => x.prodotto_id === pid);
  try {
    const r = await apiFetch(`${API_BASE()}/api/spesa/suggeriti/${pid}/aggiungi`, { method: 'POST' });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { toast(d.error || 'Errore, riprova'); return; }
    toast(_messaggioAggiunta(d));
  } catch (e) { toast('Errore, riprova'); return; }
  caricaListaSpesa();
  void s;
}

async function ignoraSuggerito(pid) {
  try {
    const r = await apiFetch(`${API_BASE()}/api/spesa/suggeriti/${pid}/ignora`, { method: 'POST' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
  } catch (e) { toast('Errore, riprova'); return; }
  toast('Nascosto: ricompare quando lo finisci di nuovo', 3500);
  caricaListaSpesa();
}

async function aggiungiTuttiSuggeriti() {
  const n = _spesa ? _spesa.suggeriti.length : 0;
  if (!n || !confirm(`Aggiungere alla lista tutti i ${n} prodotti finiti?`)) return;
  try {
    const r = await apiFetch(`${API_BASE()}/api/spesa/suggeriti/aggiungi-tutti`, { method: 'POST' });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { toast(d.error || 'Errore, riprova'); return; }
    toast(`Aggiunti ${d.aggiunti} prodotti`);
  } catch (e) { toast('Errore, riprova'); return; }
  caricaListaSpesa();
}

async function nascondiVecchi(n) {
  if (!confirm(`Nascondere i ${n} prodotti finiti da più di 3 mesi? Ricompariranno solo se li finisci di nuovo.`)) return;
  try {
    const r = await apiFetch(`${API_BASE()}/api/spesa/suggeriti/ignora-vecchi?giorni=90`, { method: 'POST' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    toast(`Nascosti ${d.nascosti} prodotti`);
  } catch (e) { toast('Errore, riprova'); return; }
  caricaListaSpesa();
}

function alternaSuggeriti() {
  _sugEspansi = !_sugEspansi;
  if (_spesa) renderSuggeriti(_spesa.suggeriti);
}

async function inviaListaSpesaTelegram() {
  const r = await apiFetch(`${API_BASE()}/api/lista-spesa/invia-telegram`);
  const data = await r.json();
  toast(data.ok ? '📤 Lista inviata su Telegram!' : '⚠️ ' + (data.errore || 'Errore'));
}

// ── Pannello Admin: stato della lista condivisa con Home Assistant ───────────
function _descriviSync(w) {
  if (!w || !w.entity) return '⚪ Non configurata: indica una lista in «Impostazioni sistema».';
  if (!w.attivo) return '⏸️ In pausa (sincronizzazione disattivata nelle impostazioni).';
  const quando = w.ultimo_ok ? new Date(w.ultimo_ok).toLocaleTimeString('it-IT') : null;
  if (w.ok === false) {
    let m = '⚠️ ' + esc(w.errore || 'errore');
    if (/(400|404)|not found|inatteso/i.test(w.errore || '')) {
      m += '<br><span style="color:var(--muted);">La lista <b>' + esc(w.entity) + '</b> non esiste ancora: in Home Assistant crea «Local To-do» con nome «Lista della spesa».</span>';
    }
    return m + (quando ? '<br><span style="color:var(--muted);">Ultimo scambio riuscito: ' + esc(quando) + '</span>' : '');
  }
  if (w.ok === true) {
    const r = w.risultato || {};
    const mosse = (r.locali_aggiunte || 0) + (r.locali_aggiornate || 0) + (r.locali_rimosse || 0) + (r.remote_aggiunte || 0) + (r.remote_aggiornate || 0) + (r.remote_rimosse || 0);
    return '✅ Collegata a <b>' + esc(w.entity) + '</b> · ' + esc(w.voci_collegate) + ' voci collegate<br><span style="color:var(--muted);">Ultimo scambio ' + esc(quando) + (mosse ? ' (' + mosse + ' modifiche)' : ' (nessuna differenza)') + '</span>';
  }
  return '⏳ In attesa del primo scambio (parte entro 30 secondi dall\'avvio).<br><span style="color:var(--muted);">Lista: ' + esc(w.entity) + ' · ' + esc(w.voci_collegate) + ' voci collegate</span>';
}

async function caricaSpesaSync() {
  const el = document.getElementById('spesa-sync-stato');
  if (!el) return;
  try {
    const r = await apiFetch(`${API_BASE()}/api/admin/spesa-sync`);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    el.innerHTML = _descriviSync((await r.json()).widget);
  } catch (e) { el.textContent = 'Stato non disponibile.'; }
}

async function sincronizzaOra() {
  const el = document.getElementById('spesa-sync-stato');
  if (el) el.textContent = '🔄 Sincronizzazione in corso…';
  try {
    const r = await apiFetch(`${API_BASE()}/api/admin/spesa-sync/ora`, { method: 'POST' });
    const d = await r.json();
    if (!r.ok) { if (el) el.textContent = '⚠️ ' + (d.error || 'Errore'); return; }
    if (el) el.innerHTML = _descriviSync(d.widget);
  } catch (e) { if (el) el.textContent = 'Errore di rete.'; }
}

// Spazio/Invio sulle caselle da spuntare (tastiera e lettori di schermo)
document.addEventListener('keydown', (e) => {
  const c = e.target && e.target.closest ? e.target.closest('.spesa-check') : null;
  if (c && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); c.click(); }
});
