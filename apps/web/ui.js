/*
 * MELODEXS CONNECT — shared UI helpers (design-system edition).
 * Loaded on every authenticated page after api.js.
 */
(function () {
    const UI = {};

    /* ---------- Nigerian phone formatting ---------- */
    UI.formatPhone = function (phone) {
        const raw = String(phone || "").replace(/\D/g, "");
        if (/^0\d{10}$/.test(raw)) {
            const n = raw.slice(1); // 10 digits: 810 123 4567
            return "+234 " + n.slice(0, 3) + " " + n.slice(3, 6) + " " + n.slice(6);
        }
        if (/^234\d{10}$/.test(raw)) {
            const n = raw.slice(3);
            return "+234 " + n.slice(0, 3) + " " + n.slice(3, 6) + " " + n.slice(6);
        }
        return String(phone || "");
    };

    /* ---------- Naira formatting ---------- */
    UI.formatNaira = function (amount) {
        const n = Number(amount || 0);
        return "₦" + (Number.isInteger(n) ? n.toLocaleString("en-NG") : n.toLocaleString("en-NG", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
    };

    /* ---------- Session + user boot (ONE request per page) ----------
     * Every page used to boot with two sequential API calls (/api/session
     * then /api/user/{id}); each one costs a database round trip, which is
     * what made "Connecting to MELODEXS..." linger. /api/bootstrap returns
     * both in a single round trip, and the promise is memoized so pages
     * that call requireSession() and refreshUserCache() in sequence only
     * ever make one request. */
    let bootstrapPromise = null;
    UI.bootstrap = function () {
        if (!bootstrapPromise) {
            bootstrapPromise = fetch("/api/bootstrap", { credentials: "include" })
                .then(function (response) {
                    return response.ok ? response.json() : null;
                })
                .then(function (data) {
                    if (data && data.loggedIn && data.user) {
                        const cached = { ...data.user, has_purchase_pin: data.has_purchase_pin };
                        localStorage.setItem("cheapdataUser", JSON.stringify(cached));
                        return { ...data, user: cached };
                    }
                    return data;
                })
                .catch(function () { return null; });
        }
        return bootstrapPromise;
    };

    /* ---------- Session helper ---------- */
    UI.requireSession = async function () {
        const data = await UI.bootstrap();
        if (!data || !data.loggedIn) {
            localStorage.removeItem("cheapdataUser");
            localStorage.removeItem("cheapdataToken");
            window.location.href = "/login.html";
            return null;
        }
        return data;
    };

    UI.currentUser = function () {
        try { return JSON.parse(localStorage.getItem("cheapdataUser")); } catch { return null; }
    };

    UI.refreshUserCache = async function () {
        const data = await UI.bootstrap();
        if (data && data.loggedIn && data.user) return data.user;
        return null;
    };

    /* ---------- Toasts (in-app notifications) ---------- */
    let toastStack = null;
    UI.toast = function (message, kind, ms) {
        if (!toastStack) {
            toastStack = document.createElement("div");
            toastStack.className = "toast-stack";
            toastStack.setAttribute("role", "status");
            toastStack.setAttribute("aria-live", "polite");
            document.body.appendChild(toastStack);
        }
        const existing = Array.from(toastStack.children).find(t => t.dataset.msg === message && t.dataset.kind === (kind || "info"));
        if (existing) { clearTimeout(existing.timer); existing.timer = setTimeout(() => existing.remove(), ms || 4200); return; }
        const toast = document.createElement("div");
        toast.className = "toast " + (kind || "info");
        toast.dataset.msg = message;
        toast.dataset.kind = kind || "info";
        const icon = { success: "✓", error: "✕", pending: "⏳", info: "ℹ" }[kind] || "ℹ";
        toast.innerHTML = '<span aria-hidden="true">' + icon + '</span><span>' + UI.esc(message) + "</span>";
        toastStack.appendChild(toast);
        toast.timer = setTimeout(() => toast.remove(), ms || 4200);
    };

    /* ---------- Modal helper ---------- */
    UI.openModal = function (id) {
        const backdrop = document.getElementById(id);
        if (backdrop) backdrop.classList.add("open");
        document.body.style.overflow = "hidden";
    };
    UI.closeModal = function (id) {
        const backdrop = document.getElementById(id);
        if (backdrop) backdrop.classList.remove("open");
        document.body.style.overflow = "";
    };
    UI.confirm = function (title, message, confirmLabel) {
        return new Promise((resolve) => {
            const backdrop = document.getElementById("confirm-modal");
            if (!backdrop || !document.getElementById("confirm-title")) { resolve(window.confirm(message)); return; }
            document.getElementById("confirm-title").textContent = title;
            document.getElementById("confirm-message").textContent = message;
            const ok = document.getElementById("confirm-ok");
            const cancel = document.getElementById("confirm-cancel");
            ok.textContent = confirmLabel || "Confirm";
            const done = (answer) => {
                UI.closeModal("confirm-modal");
                ok.onclick = cancel.onclick = backdrop.onclick = null;
                resolve(answer);
            };
            ok.onclick = () => done(true);
            cancel.onclick = () => done(false);
            backdrop.onclick = (e) => { if (e.target === backdrop) done(false); };
            UI.openModal("confirm-modal");
        });
    };

    /* ---------- Text prompt (e.g. naming a saved recipient) ----------
       Builds its own markup on first use so no page has to ship modal HTML:
       an empty modal shell on a page once made UI.confirm() throw and
       silently killed purchases. Resolves to the trimmed text, "" when the
       user chooses to skip, or null when they cancel. */
    UI.promptText = function (title, message, options) {
        const opts = options || {};
        return new Promise((resolve) => {
            let backdrop = document.getElementById("prompt-modal");
            if (!backdrop) {
                backdrop = document.createElement("div");
                backdrop.className = "modal-backdrop";
                backdrop.id = "prompt-modal";
                backdrop.setAttribute("role", "dialog");
                backdrop.setAttribute("aria-modal", "true");
                backdrop.setAttribute("aria-labelledby", "prompt-title");
                backdrop.innerHTML = '<div class="modal"><div class="modal-head"><h3 id="prompt-title"></h3>' +
                    '<button type="button" class="modal-close" id="prompt-cancel" aria-label="Cancel">\u2715</button></div>' +
                    '<p class="muted" id="prompt-message" style="margin-bottom:12px"></p>' +
                    '<input class="input" id="prompt-input" type="text" autocomplete="off" style="margin-bottom:18px">' +
                    '<div class="row" style="justify-content:flex-end">' +
                    '<button type="button" class="btn btn-ghost" id="prompt-skip"></button>' +
                    '<button type="button" class="btn btn-primary" id="prompt-ok"></button></div></div>';
                document.body.appendChild(backdrop);
            }
            const input = document.getElementById("prompt-input");
            const ok = document.getElementById("prompt-ok");
            const skip = document.getElementById("prompt-skip");
            const cancel = document.getElementById("prompt-cancel");
            document.getElementById("prompt-title").textContent = title;
            document.getElementById("prompt-message").textContent = message || "";
            input.value = "";
            input.placeholder = opts.placeholder || "";
            input.maxLength = opts.maxLength || 60;
            ok.textContent = opts.okLabel || "Save";
            skip.textContent = opts.skipLabel || "Skip";
            skip.style.display = opts.allowSkip === false ? "none" : "";
            const done = (answer) => {
                UI.closeModal("prompt-modal");
                ok.onclick = skip.onclick = cancel.onclick = backdrop.onclick = null;
                document.removeEventListener("keydown", onKey, true);
                resolve(answer);
            };
            ok.onclick = () => done(input.value.trim());
            skip.onclick = () => done("");
            cancel.onclick = () => done(null);
            backdrop.onclick = (e) => { if (e.target === backdrop) done(null); };
            // Listen on the document while the dialog is open, not on the dialog:
            // tapping the card's text moves focus to <body>, and Escape must
            // still close it. The listener is removed in done().
            const onKey = (e) => {
                if (e.key === "Escape") { e.preventDefault(); done(null); }
                else if (e.key === "Enter" && e.target === input) { e.preventDefault(); done(input.value.trim()); }
            };
            document.addEventListener("keydown", onKey, true);
            UI.openModal("prompt-modal");
            input.focus();
            setTimeout(() => input.focus(), 50);
        });
    };

    /* ---------- HTML escaping ---------- */
    UI.esc = function (value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    };

    /* ---------- Shared page chrome (appbar + bottom nav + confirm modal) ---------- */
    UI.NETWORKS = [
        { slug: "MTN", color: "#ffcc00" },
        { slug: "Airtel", color: "#e40000" },
        { slug: "Glo", color: "#00a651" },
        { slug: "9mobile", color: "#006e51" }
    ];

    /* Which sidebar entry owns each page. Used when a page does not pass an
       explicit key, so the navigation is always correct and always present. */
    const PAGE_FEATURE = {
        "/dashboard.html": "home",
        "/buy-data.html": "data",
        "/buy-airtime.html": "airtime",
        "/buy-electricity.html": "electricity",
        "/buy-cable.html": "cable",
        "/buy-education.html": "education",
        "/wallet.html": "wallet",
        "/fund-wallet.html": "wallet",
        "/purchase-pin.html": "profile"
    };

    UI.activeFeature = function (active) {
        const key = active || PAGE_FEATURE[window.location.pathname] || "home";
        return { plans: "data", fund: "wallet" }[key] || key;
    };

    UI.mountChrome = function (active) {
        const user = UI.currentUser() || {};
        const initials = (user.name || "M").trim().split(/\s+/).map(w => w[0]).slice(0, 2).join("").toUpperCase();
        const appbar = document.getElementById("appbar");
        if (appbar) {
            const avatarInner = user.profile_image
                ? '<img class="avatar-photo" alt="Profile picture" src="' + user.profile_image + '">'
                : UI.esc(initials || "M");
            appbar.innerHTML =
                '<a class="appbar-user" href="/purchase-pin.html" aria-label="Account and profile">' +
                '<span class="appbar-avatar">' + avatarInner + '<span class="online-dot"></span></span>' +
                '<span class="appbar-phone" id="appbarPhone">' + UI.esc(UI.formatPhone(user.phone) || "Add phone number") +
                '<span class="chev">▾</span></span></a>' +
                '<div class="appbar-actions"><button class="icon-btn" id="logoutBtn" aria-label="Sign out" title="Sign out">' +
                '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg></button></div>';
            const logoutBtn = document.getElementById("logoutBtn");
            if (logoutBtn) logoutBtn.addEventListener("click", UI.logoutWithConfirm);
        }
        /* Every feature the app offers. Mobile shows the four primary
           destinations in the bottom bar; desktop shows ALL of them in the
           sidebar, each with its icon. */
        const ALL_FEATURES = [
            { key: "home", href: "/dashboard.html", label: "Home", icon: '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>' },
            { key: "data", href: "/buy-data.html", label: "Buy Data", icon: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>' },
            { key: "airtime", href: "/buy-airtime.html", label: "Buy Airtime", icon: '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.9.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z"/>' },
            { key: "electricity", href: "/buy-electricity.html", label: "Electricity", icon: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>' },
            { key: "cable", href: "/buy-cable.html", label: "TV Subscription", icon: '<rect x="2" y="7" width="20" height="15" rx="2"/><polyline points="17 2 12 7 7 2"/>' },
            { key: "education", href: "/buy-education.html", label: "Result PINs", icon: '<path d="M22 10L12 5 2 10l10 5 10-5z"/><path d="M6 12v5c0 1.7 2.7 3 6 3s6-1.3 6-3v-5"/>' },
            { key: "wallet", href: "/wallet.html", label: "Wallet", icon: '<path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4z"/>' },
            { key: "profile", href: "/purchase-pin.html", label: "Profile", icon: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>' }
        ];
        const activeFeature = UI.activeFeature(active);
        const bottomKey = ["airtime", "electricity", "cable", "education"].includes(activeFeature) ? "data" : activeFeature;
        const tabs = ALL_FEATURES.filter(f => ["home", "data", "wallet", "profile"].includes(f.key));
        const nav = document.getElementById("bottom-nav");
        if (nav) {
            nav.innerHTML = tabs.map(t =>
                '<a href="' + t.href + '" class="' + (t.key === bottomKey ? "active" : "") + '" aria-current="' + (t.key === bottomKey ? "page" : "false") + '">' +
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + t.icon + "</svg>" +
                "<span>" + t.label + "</span></a>").join("");
        }
        const desktop = document.getElementById("desktop-tabs");
        if (desktop) {
            desktop.innerHTML = tabs.map(t =>
                '<a href="' + t.href + '" class="' + (t.key === activeFeature ? "active" : "") + '">' + t.label + "</a>").join("");
        }

        /* Desktop sidebar: every feature, with icons. Built once per page. */
        if (!document.getElementById("app-sidebar")) {
            const sidebar = document.createElement("aside");
            sidebar.className = "app-sidebar";
            sidebar.id = "app-sidebar";
            sidebar.innerHTML =
                '<a class="sidebar-brand" href="/dashboard.html"><span class="logo-mark">M</span><span class="sidebar-brand-text">MELODEXS<small>CONNECT</small></span></a>' +
                '<nav class="sidebar-nav" aria-label="Sections">' +
                /* Profile is not listed here: the account chip below (photo,
                   name, phone) already opens it. Phones have no chip, so the
                   bottom bar keeps its Profile tab. */
                ALL_FEATURES.filter(f => f.key !== "profile").map(f =>
                    '<a href="' + f.href + '" class="' + (f.key === activeFeature ? "active" : "") + '"' +
                    (f.key === activeFeature ? ' aria-current="page"' : "") + '>' +
                    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + f.icon + "</svg>" +
                    '<span>' + f.label + '</span></a>').join("") +
                "</nav>" +
                '<div class="sidebar-foot">' +
                '<a class="sidebar-user' + (activeFeature === "profile" ? " active" : "") + '" href="/purchase-pin.html"' +
                (activeFeature === "profile" ? ' aria-current="page"' : "") + '>' +
                '<span class="appbar-avatar">' + (user.profile_image ? '<img class="avatar-photo" alt="" src="' + user.profile_image + '">' : UI.esc(initials || "M")) + '</span>' +
                '<span class="sidebar-user-text"><strong>' + UI.esc(user.name || "Your account") + '</strong><small>' + UI.esc(UI.formatPhone(user.phone) || "Add phone number") + '</small></span></a>' +
                '<button class="sidebar-signout" id="sidebarSignout" type="button">' +
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>' +
                "<span>Sign out</span></button></div>";
            document.body.appendChild(sidebar);
            document.body.classList.add("has-sidebar");
            const sidebarSignout = document.getElementById("sidebarSignout");
            if (sidebarSignout) sidebarSignout.addEventListener("click", UI.logoutWithConfirm);
        }
        if (!document.getElementById("confirm-modal")) {
            const modal = document.createElement("div");
            modal.className = "modal-backdrop";
            modal.id = "confirm-modal";
            modal.setAttribute("role", "dialog");
            modal.setAttribute("aria-modal", "true");
            modal.innerHTML = '<div class="modal"><div class="modal-head"><h3 id="confirm-title"></h3>' +
                '<button class="modal-close" id="confirm-cancel" aria-label="Cancel">✕</button></div>' +
                '<p class="muted" id="confirm-message" style="margin-bottom:18px"></p>' +
                '<div class="row" style="justify-content:flex-end"><button class="btn btn-ghost" id="confirm-cancel2">Cancel</button>' +
                '<button class="btn btn-primary" id="confirm-ok">Confirm</button></div></div>';
            document.body.appendChild(modal);
            modal.querySelector("#confirm-cancel2").addEventListener("click", () => UI.closeModal("confirm-modal"));
        }
    };

    /* Keep the sidebar present on every app page: if a page's own boot
       sequence fails, navigation must still work. mountChrome() is
       idempotent, so this is just an early first pass. */
    document.addEventListener("DOMContentLoaded", function () {
        if (!document.getElementById("app-sidebar") && document.getElementById("appbar")) {
            try { UI.mountChrome(); } catch (error) { /* page boot will retry */ }
        }
    });

    UI.logoutWithConfirm = async function () {
        const confirmed = await UI.confirm("Sign out?", "You will need to log in again to access your account.", "Sign out");
        if (!confirmed) return;
        try { await fetch("/api/logout", { method: "POST", credentials: "include" }); } catch (error) { /* network: still clear locally */ }
        localStorage.removeItem("cheapdataUser");
        localStorage.removeItem("cheapdataNewUserId");
        localStorage.removeItem("cheapdataToken");
        window.location.href = "/login.html";
    };

    /* ---------- Cold-start boot indicator ----------
       App pages render <div id="boot-loading"> while start() awaits the API.
       Pages call UI.bootDone() once interactive; a 25s safety timer guarantees
       the overlay can never get stuck over a working page. */
    UI.bootDone = function () {
        const el = document.getElementById("boot-loading");
        if (el) el.classList.add("hidden");
    };
    setTimeout(function () { UI.bootDone(); }, 25000);

    window.MELODEXS_UI = UI;
})();
