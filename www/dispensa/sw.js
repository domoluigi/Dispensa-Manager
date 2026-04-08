const CACHE = 'dispensa-v2';
const STATIC_ASSETS = [
  '/local/dispensa/',
  '/local/dispensa/index.html',
  'https://unpkg.com/@zxing/library@0.19.1/umd/index.min.js',
  'https://unpkg.com/tesseract.js@5/dist/tesseract.min.js',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => {
      // addAll with individual try/catch so CDN failures don't break the SW
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

  // API calls: network first, cache fallback (per uso offline)
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

  // Altre API: network only (scritture non vanno messe in cache)
  if (url.includes('/api/')) {
    return;
  }

  // Asset statici: cache first, poi rete
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request))
  );
});
