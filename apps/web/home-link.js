/* "Back to home" on the public pages (Help, Prices, Privacy).
 *
 * These pages are open to everyone, so their link defaults to the welcome
 * page ("/"). A signed-in customer expects their own home, the dashboard, so
 * when a saved sign-in is present the link is pointed there instead. Anything
 * that goes wrong (storage blocked, no sign-in) just leaves the default. The
 * dashboard bounces to sign-in by itself if the session has since expired.
 */
(function () {
    try {
        var signedIn = localStorage.getItem("cheapdataToken") || localStorage.getItem("cheapdataUser");
        if (!signedIn) return;
        var links = document.querySelectorAll("[data-home-link]");
        for (var i = 0; i < links.length; i++) links[i].setAttribute("href", "/dashboard.html");
    } catch (error) { /* storage blocked: keep the welcome page link */ }
})();
