const CACHE = 'dispensa-v11';

const STATIC_ASSETS = [
  'https://unpkg.com/@zxing/library@0.19.1/umd/index.min.js',
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

  if (url.includes('/api/')) {
    return;
  }

  // Network-first per HTML, CSS e JS dell'app (no flash di vecchie versioni)
  const isAppAsset = url.endsWith('/') || url.includes('index.html')
    || url.endsWith('style.css') || url.includes('style.css?')
    || url.endsWith('app.js') || url.includes('app.js?');

  if (isAppAsset) {
    e.respondWith(
      fetch(e.request)
        .then(r => {
          const clone = r.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
          return r;
        })
        .catch(() => caches.match(e.request, { ignoreSearch: true }))
    );
    return;
  }

  // Cache-first per le altre risorse statiche (librerie CDN, immagini)
  e.respondWith(
    caches.match(e.request, { ignoreSearch: true }).then(r => r || fetch(e.request))
  );
});
