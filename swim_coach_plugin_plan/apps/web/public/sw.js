const CACHE = "swim-coach-safe-offline-v1";
const SHELL = ["/", "/manifest.webmanifest"];
const SAFE_API = /^\/api\/v1\/workouts(?:\/[0-9a-f-]+)?$/i;
const NEVER_CACHE = /\/(actions|proposals|approve|reject|publish|schedule)(?:\/|$)/i;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || NEVER_CACHE.test(url.pathname)) return;
  if (SAFE_API.test(url.pathname)) {
    event.respondWith(networkFirst(request));
    return;
  }
  if (request.mode === "navigate" || url.pathname.startsWith("/assets/")) {
    event.respondWith(cacheFirst(request));
  }
});

async function networkFirst(request) {
  const cache = await caches.open(CACHE);
  try {
    const response = await fetch(request);
    if (response.ok) await cache.put(request, response.clone());
    return response;
  } catch (error) {
    const cached = await cache.match(request);
    if (!cached) throw error;
    const headers = new Headers(cached.headers);
    headers.set("X-Swim-Coach-Offline", "stale");
    notifyClients();
    return new Response(await cached.blob(), { status: cached.status, headers });
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) await cache.put(request, response.clone());
  return response;
}

async function notifyClients() {
  const clients = await self.clients.matchAll({ type: "window" });
  clients.forEach((client) => client.postMessage({ type: "SWIM_COACH_STALE_DATA" }));
}
