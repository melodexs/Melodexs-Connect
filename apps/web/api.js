(function () {
    /*
     * MELODEXS CONNECT API configuration
     *
     * The API origin is resolved in one place, in this order:
     *   1. The per-page <meta name="api-base-url"> tag (staging/preview).
     *   2. The production API URL below (the deployed backend service).
     *   3. The page origin, for local development where the static site and
     *      the API are served from the same host.
     *
     * Cutover complete (2026-10-16): the Python/FastAPI backend is the
     * production API, so API_TARGET_IS_PYTHON is true and the frontend
     * enables the categorized catalog and purchase/reconciliation UI
     * that only the Python API provides. The Node backend (apps/api)
     * is retained in Git for rollback only; see
     * apps/api-python/CUTOVER-CHECKLIST.md and ROLLBACK-RUNBOOK.md.
     */

    // Cutover switch: false = Node backend (rollback path), true = Python (production).
    const API_TARGET_IS_PYTHON = true;
    const PRODUCTION_API_URL = "https://melodexs-connect-api.onrender.com";

    // Staging/preview can set this meta value to a specific API origin.
    const configuredApiOrigin = document.querySelector('meta[name="api-base-url"]')?.content.trim().replace(/\/+$/, "");

    // Never let a hosted page talk to a developer machine.
    const pageIsLocal = ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);
    const originIsLocal = configuredApiOrigin && /^(https?:\/\/)?(localhost|127\.0\.0\.1)(:|\/|$)/.test(configuredApiOrigin);
    const safeConfiguredOrigin = pageIsLocal || !originIsLocal ? configuredApiOrigin : "";

    const API_BASE_URL = safeConfiguredOrigin || (pageIsLocal ? "" : PRODUCTION_API_URL);
    window.MELODEXS_CATEGORIZED_CATALOG = Boolean(safeConfiguredOrigin) || API_TARGET_IS_PYTHON;

    const originalFetch = window.fetch.bind(window);

    window.fetch = function (input, init) {
        let requestInput = input;

        if (
            typeof input === "string" &&
            input.startsWith("/api/")
        ) {
            const baseUrl =
                API_BASE_URL || window.location.origin;

            requestInput = baseUrl + input;
        }

        const requestInit = {
            ...(init || {}),
            credentials: "include"
        };

        return originalFetch(requestInput, requestInit);
    };
})();
