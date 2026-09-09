// 安冉的学习助手 - Service Worker (PWA 离线支持)
const CACHE_NAME = 'anran-learning-v21';
const ASSETS = [
  './',
  './index.html',
  './css/style.css?v=20260909c',
  './js/data.js?v=20260909c',
  './js/learning.js?v=20260909c',
  './js/storage.js?v=20260909c',
  './js/app.js?v=20260909c',
  './manifest.json',
  './icons/icon-192.png',
  './icons/icon-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // API 请求（POST 等）不经过 Service Worker，直接走网络
  if (url.pathname.startsWith('/api/')) {
    return;
  }
  // 对 HTML、JS、CSS 文件，优先从网络获取最新版本
  if (url.pathname.endsWith('.html') || url.pathname.endsWith('.js') || url.pathname.endsWith('.css')) {
    e.respondWith(
      fetch(e.request).then(res => {
        const clone = res.clone();
        caches.open(CACHE_NAME).then(c => c.put(e.request, clone)).catch(() => {});
        return res;
      }).catch(() => caches.match(e.request))
    );
  } else {
    e.respondWith(
      caches.match(e.request).then(cached => cached || fetch(e.request).then(res => {
        const clone = res.clone();
        caches.open(CACHE_NAME).then(c => c.put(e.request, clone)).catch(() => {});
        return res;
      }).catch(() => cached))
    );
  }
});
