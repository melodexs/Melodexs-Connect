const STATIC_CACHE = "melodexs-static-v1";
const STATIC_ASSET = /\.(?:css|js|png|svg|webmanifest|woff2?)$/i;

self.addEventListener("install", event => {
    event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", event => {
    event.waitUntil((async () => {
        const cacheNames = await caches.keys();
        await Promise.all(
            cacheNames
                .filter(name => name.startsWith("melodexs-static-") && name !== STATIC_CACHE)
                .map(name => caches.delete(name))
        );
        await self.clients.claim();
    })());
});

self.addEventListener("fetch", event => {
    const request = event.request;
    const url = new URL(request.url);

    if (
        request.method !== "GET" ||
        url.origin !== self.location.origin ||
        url.pathname.startsWith("/api/") ||
        url.pathname === "/sw.js" ||
        !STATIC_ASSET.test(url.pathname)
    ) {
        return;
    }

    event.respondWith((async () => {
        const cache = await caches.open(STATIC_CACHE);

        try {
            const response = await fetch(request);
            if (response.ok && response.type === "basic") {
                await cache.put(request, response.clone());
            }
            return response;
        } catch (error) {
            const cached = await cache.match(request);
            if (cached) {
                return cached;
            }
            throw error;
        }
    })());
});
