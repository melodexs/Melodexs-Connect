const STATIC_CACHE = "melodexs-static-v3";
const PAGES_CACHE = "melodexs-pages-v3";
const STATIC_ASSET = /\.(?:css|js|png|svg|webmanifest|woff2?)$/i;
const OFFLINE_URL = "/offline.html";

self.addEventListener("install", event => {
    // The offline fallback must be in the cache from the very first install,
    // otherwise an installed app opened offline would show a browser error.
    event.waitUntil((async () => {
        const cache = await caches.open(STATIC_CACHE);
        await cache.add(OFFLINE_URL);
        await self.skipWaiting();
    })());
});

self.addEventListener("activate", event => {
    event.waitUntil((async () => {
        const cacheNames = await caches.keys();
        await Promise.all(
            cacheNames
                .filter(name => (name.startsWith("melodexs-static-") || name.startsWith("melodexs-pages-")) &&
                                 name !== STATIC_CACHE && name !== PAGES_CACHE)
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
        url.pathname === "/sw.js"
    ) {
        return;
    }

    // Page navigations: network-first so users always get fresh content,
    // cached copy when offline, branded offline page as the last resort.
    if (request.mode === "navigate") {
        event.respondWith((async () => {
            try {
                const response = await fetch(request);
                if (response.ok && response.type === "basic") {
                    const cache = await caches.open(PAGES_CACHE);
                    await cache.put(request, response.clone());
                }
                return response;
            } catch (error) {
                const pages = await caches.open(PAGES_CACHE);
                const cached = await pages.match(request, { ignoreSearch: true });
                if (cached) return cached;
                const statics = await caches.open(STATIC_CACHE);
                const offline = await statics.match(OFFLINE_URL);
                if (offline) return offline;
                throw error;
            }
        })());
        return;
    }

    if (!STATIC_ASSET.test(url.pathname)) {
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
