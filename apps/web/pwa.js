(() => {
    const DISMISSED_KEY = "melodexs_pwa_install_dismissed";
    let installPrompt = null;
    let banner = null;

    function isStandalone() {
        return window.matchMedia("(display-mode: standalone)").matches ||
            window.navigator.standalone === true;
    }

    function isAppleMobile() {
        return /iPhone|iPad|iPod/.test(window.navigator.userAgent) ||
            (window.navigator.platform === "MacIntel" && window.navigator.maxTouchPoints > 1);
    }

    function wasDismissed() {
        try {
            return window.localStorage.getItem(DISMISSED_KEY) === "true";
        } catch (error) {
            return false;
        }
    }

    function dismissPermanently() {
        try {
            window.localStorage.setItem(DISMISSED_KEY, "true");
        } catch (error) {
            // The current page still hides the banner when storage is unavailable.
        }
        hideBanner();
    }

    function hideBanner() {
        if (banner) {
            banner.remove();
            banner = null;
        }
    }

    function showBanner(appleFallback = false) {
        if (isStandalone() || wasDismissed() || banner) {
            return;
        }

        banner = document.createElement("aside");
        banner.className = "melodexs-install-banner";
        banner.setAttribute("role", "region");
        banner.setAttribute("aria-label", "Install MELODEXS CONNECT");

        const message = document.createElement("p");
        message.textContent = "Install MELODEXS CONNECT on your phone for faster access.";
        banner.append(message);

        if (appleFallback) {
            const instructions = document.createElement("p");
            instructions.textContent = "On iPhone or iPad, tap Share → Add to Home Screen.";
            instructions.className = "melodexs-install-help";
            banner.append(instructions);
        } else {
            const installButton = document.createElement("button");
            installButton.type = "button";
            installButton.textContent = "Install MELODEXS CONNECT";
            installButton.addEventListener("click", async () => {
                if (!installPrompt) {
                    return;
                }
                installPrompt.prompt();
                const choice = await installPrompt.userChoice;
                installPrompt = null;
                if (choice && choice.outcome === "dismissed") {
                    dismissPermanently();
                } else {
                    hideBanner();
                }
            });
            banner.append(installButton);
        }

        const dismissButton = document.createElement("button");
        dismissButton.type = "button";
        dismissButton.className = "melodexs-install-dismiss";
        dismissButton.textContent = "Not now";
        dismissButton.setAttribute("aria-label", "Dismiss install message");
        dismissButton.addEventListener("click", dismissPermanently);
        banner.append(dismissButton);
        document.body.append(banner);
    }

    const style = document.createElement("style");
    style.textContent = `
        .melodexs-install-banner {
            position: fixed;
            z-index: 10000;
            inset: auto 16px max(16px, env(safe-area-inset-bottom)) 16px;
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 12px;
            padding: 16px;
            border: 1px solid #C7D1DD;
            border-radius: 14px;
            background: #fff;
            box-shadow: 0 8px 32px rgba(10, 35, 70, .2);
            color: #10243e;
            font: 500 14px/1.45 Arial, sans-serif;
        }
        .melodexs-install-banner p { flex: 1 1 220px; margin: 0; }
        .melodexs-install-banner .melodexs-install-help { flex-basis: 100%; color: #43566f; }
        .melodexs-install-banner button {
            border: 0;
            border-radius: 8px;
            padding: 10px 14px;
            background: #0251B0;
            color: #fff;
            font: 700 14px Arial, sans-serif;
            cursor: pointer;
        }
        .melodexs-install-banner .melodexs-install-dismiss {
            padding-inline: 8px;
            background: transparent;
            color: #43566f;
        }
    `;
    document.head.append(style);

    window.addEventListener("beforeinstallprompt", event => {
        event.preventDefault();
        installPrompt = event;
        showBanner(false);
    });

    window.addEventListener("appinstalled", () => {
        hideBanner();
        installPrompt = null;
    });

    if (isAppleMobile() && !isStandalone()) {
        showBanner(true);
    }

    if ("serviceWorker" in navigator && window.location.protocol.startsWith("http")) {
        window.addEventListener("load", () => {
            navigator.serviceWorker.register("/sw.js").catch(() => {});
        }, { once: true });
    }
})();
