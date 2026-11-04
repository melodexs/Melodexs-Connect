/* Theme: light, dark, or follow the phone.
 *
 * Loaded synchronously in <head> so the saved choice is applied before the
 * first paint; otherwise dark-mode users would see a white flash on every
 * page. The choice is stored under "melodexsTheme" ("light" | "dark"); no
 * stored value means "follow the system".
 */
(function (root) {
    "use strict";
    var KEY = "melodexsTheme";
    var LIGHT_BAR = "#0251B0";   // electric-blue app surface
    var DARK_BAR = "#050B1C";    // deep-navy app surface

    function stored() {
        try {
            var v = root.localStorage.getItem(KEY);
            return v === "light" || v === "dark" ? v : null;
        } catch (e) { return null; }
    }

    function systemPrefersDark() {
        return !!(root.matchMedia && root.matchMedia("(prefers-color-scheme: dark)").matches);
    }

    function effective() {
        return stored() || (systemPrefersDark() ? "dark" : "light");
    }

    function paintBar(theme) {
        var meta = root.document && root.document.querySelector('meta[name="theme-color"]');
        if (meta) meta.setAttribute("content", theme === "dark" ? DARK_BAR : LIGHT_BAR);
    }

    function apply() {
        var choice = stored();
        var el = root.document.documentElement;
        if (choice) el.setAttribute("data-theme", choice); else el.removeAttribute("data-theme");
        paintBar(effective());
        return effective();
    }

    // choice: "light" | "dark" | "system"
    function set(choice) {
        try {
            if (choice === "light" || choice === "dark") root.localStorage.setItem(KEY, choice);
            else root.localStorage.removeItem(KEY);
        } catch (e) { /* private mode: the choice just won't persist */ }
        return apply();
    }

    var api = { get: stored, effective: effective, set: set, apply: apply, KEY: KEY };
    root.MELODEXS_THEME = api;
    apply();
    // Keep following the phone when the user has not chosen explicitly.
    if (root.matchMedia) {
        var mq = root.matchMedia("(prefers-color-scheme: dark)");
        var onChange = function () { if (!stored()) apply(); };
        if (mq.addEventListener) mq.addEventListener("change", onChange);
        else if (mq.addListener) mq.addListener(onChange);
    }
})(window);
