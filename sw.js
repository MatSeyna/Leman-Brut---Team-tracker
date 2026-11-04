// Network first, falls back to the last cached copy when offline.
var C = "leman-brut-v7";
self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(C).then(function (c) {
    return c.addAll(["./", "index.html", "manifest.webmanifest", "icon.svg", "hero.jpg"]);
  }));
  self.skipWaiting();
});
self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (ks) {
    return Promise.all(ks.filter(function (k) { return k !== C; }).map(function (k) { return caches.delete(k); }));
  }));
  self.clients.claim();
});
self.addEventListener("fetch", function (e) {
  if (e.request.method !== "GET" || new URL(e.request.url).origin !== location.origin) return;
  e.respondWith(
    fetch(e.request).then(function (r) {
      var copy = r.clone();
      caches.open(C).then(function (c) { c.put(e.request, copy); });
      return r;
    }).catch(function () { return caches.match(e.request); })
  );
});
