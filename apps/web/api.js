(function () {
    /*
     * MELODEXS CONNECT API configuration
     *
     * LOCAL DEVELOPMENT:
     * Leave API_BASE_URL empty to use the same origin.
     *
     * RENDER:
     * Replace the empty string with your Render API URL.
     *
     * Example:
     * const API_BASE_URL = "https://melodexs-connect-api.onrender.com"\;
     */

    const API_BASE_URL = "";

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
