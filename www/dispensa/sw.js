const CACHE = 'dispensa-v3';

// Solo librerie CDN con versione fissa nell'URL — queste non cambiano mai
const STATIC_ASSETS = [
  'https://unpkg.com/@zxing/library@0.19.1/umd/index.min.js',
  'https://unpkg.com/tesseract.js@5/dist/tesseract.min.js',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => {
      return Promise.allSettled(STATIC_ASSETS.map(url => c.add(url).catch(() => {})));
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const url = e.request.url;

  // API GET prodotti: network first, cache fallback offline
  if (url.includes('/api/prodotti') && e.request.method === 'GET') {
    e.respondWith(
      fetch(e.request)
        .then(r => {
          const clone = r.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
          return r;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  // Altre API: network only (scritture non in cache)
  if (url.includes('/api/')) {
    return;
  }

  // index.html e root dispensa: network first — sempre aggiornato, cache solo offline
  if (url.includes('index.html') || url.includes('/local/dispensa/')) {
    e.respondWith(
      fetch(e.request)
        .then(r => {
          const clone = r.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
          return r;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  // CDN libraries con versione fissa: cache first (non cambiano mai)
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request))
  );
});
