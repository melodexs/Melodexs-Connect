/* MELODEXS CONNECT — premium 3D landing motion.
   Transform/opacity only, rAF-throttled, and fully disabled under
   prefers-reduced-motion. No dependencies. */
(function () {
    "use strict";

    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var finePointer = window.matchMedia("(hover: hover) and (pointer: fine)").matches;

    /* ---------- Scroll reveals ---------- */
    var revealEls = document.querySelectorAll(".reveal");
    if (revealEls.length) {
        if (reduce || !("IntersectionObserver" in window)) {
            revealEls.forEach(function (el) { el.classList.add("in"); });
        } else {
            var io = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting) {
                        var el = entry.target;
                        el.classList.add("in");
                        io.unobserve(el);
                        /* Once the entrance finishes, drop the reveal classes so
                           their 0.7s transform transition no longer slows down
                           pointer interactions (3D tilt). */
                        el.addEventListener("transitionend", function done(ev) {
                            if (ev.propertyName === "opacity") {
                                el.classList.remove("reveal", "in");
                                el.removeEventListener("transitionend", done);
                            }
                        });
                    }
                });
            }, { threshold: 0.18 });
            revealEls.forEach(function (el) { io.observe(el); });
        }
    }

    /* ---------- Sticky nav glass on scroll ---------- */
    var nav = document.getElementById("landingNav");
    var lastNavState = null;
    function updateNav() {
        var scrolled = window.scrollY > 24;
        if (scrolled !== lastNavState) {
            nav.classList.toggle("scrolled", scrolled);
            lastNavState = scrolled;
        }
    }
    window.addEventListener("scroll", updateNav, { passive: true });
    updateNav();

    /* ---------- Hero 3D scene parallax ---------- */
    var scene = document.getElementById("heroScene");
    var phone = document.getElementById("heroPhone");
    if (scene && phone && !reduce) {
        var layers = [{ el: scene, depth: 1 }, { el: phone, depth: 2.2 }];
        var chips = document.querySelectorAll(".float-chip");
        chips.forEach(function (chip, i) {
            layers.push({ el: chip, depth: 1.6 + (i % 2) * 0.7 });
        });

        var targetX = 0, targetY = 0;   // -1..1
        var curX = 0, curY = 0;
        var scrollTilt = 0;
        var raf = null;

        function schedule() {
            if (raf === null) raf = window.requestAnimationFrame(render);
        }

        function render() {
            raf = null;
            curX += (targetX - curX) * 0.08;
            curY += (targetY - curY) * 0.08;

            layers.forEach(function (layer) {
                var d = layer.depth;
                var el = layer.el;
                if (el === phone) {
                    el.style.transform =
                        "rotateY(" + (-13 + curX * 6.5 * d * 0.45).toFixed(2) + "deg)" +
                        " rotateX(" + (5 - curY * 5 * d * 0.45).toFixed(2) + "deg)" +
                        " translateX(" + (curX * 4).toFixed(1) + "px)" +
                        " translateY(" + (curY * 3 + scrollTilt * 6).toFixed(1) + "px)";
                } else if (el.classList.contains("float-chip")) {
                    /* chips keep their keyframe transform; add a small parallax
                       via margin so the animation is untouched */
                    el.style.marginLeft = (curX * 6 * d).toFixed(1) + "px";
                    el.style.marginTop = (curY * 4 * d).toFixed(1) + "px";
                } else {
                    el.style.transform =
                        "rotateY(" + (curX * 4).toFixed(2) + "deg)" +
                        " rotateX(" + (-curY * 3).toFixed(2) + "deg)" +
                        " translateY(" + (scrollTilt * 8).toFixed(1) + "px)";
                }
            });

            if (Math.abs(targetX - curX) + Math.abs(targetY - curY) > 0.002) schedule();
        }

        if (finePointer) {
            window.addEventListener("pointermove", function (e) {
                targetX = (e.clientX / window.innerWidth) * 2 - 1;
                targetY = (e.clientY / window.innerHeight) * 2 - 1;
                schedule();
            }, { passive: true });
        }

        var heroSection = document.querySelector(".landing-hero");
        window.addEventListener("scroll", function () {
            var rect = heroSection.getBoundingClientRect();
            if (rect.bottom > 0) {
                scrollTilt = Math.min(1, Math.max(0, -rect.top / (rect.height || 1)));
                schedule();
            }
        }, { passive: true });
    }

    /* ---------- 3D tilt feature cards ---------- */
    if (finePointer && !reduce) {
        document.querySelectorAll(".tilt").forEach(function (card) {
            card.addEventListener("pointermove", function (e) {
                var rect = card.getBoundingClientRect();
                var px = (e.clientX - rect.left) / rect.width;
                var py = (e.clientY - rect.top) / rect.height;
                var rx = (0.5 - py) * 9;
                var ry = (px - 0.5) * 11;
                card.style.transform = "rotateX(" + rx.toFixed(2) + "deg) rotateY(" + ry.toFixed(2) + "deg) translateY(-3px)";
                card.style.setProperty("--gx", (px * 100).toFixed(1) + "%");
                card.style.setProperty("--gy", (py * 100).toFixed(1) + "%");
            });
            card.addEventListener("pointerleave", function () {
                card.style.transform = "";
            });
        });
    }

    /* ---------- Cursor spotlight (desktop) ---------- */
    var spotlight = document.getElementById("spotlight");
    if (spotlight && finePointer && !reduce) {
        var sx = window.innerWidth / 2, sy = window.innerHeight * 0.35;
        var stx = sx, sty = sy;
        var sRaf = null;

        function renderSpot() {
            sRaf = null;
            sx += (stx - sx) * 0.12;
            sy += (sty - sy) * 0.12;
            spotlight.style.transform = "translate(" + (sx - 280) + "px," + (sy - 280) + "px)";
            if (Math.abs(stx - sx) + Math.abs(sty - sy) > 0.5) sRaf = window.requestAnimationFrame(renderSpot);
        }

        window.addEventListener("pointermove", function (e) {
            stx = e.clientX; sty = e.clientY;
            document.body.classList.add("spotlight-on");
            if (sRaf === null) sRaf = window.requestAnimationFrame(renderSpot);
        }, { passive: true });
    }

    /* ---------- Magnetic CTA buttons ---------- */
    if (finePointer && !reduce) {
        document.querySelectorAll(".magnetic").forEach(function (btn) {
            btn.addEventListener("pointermove", function (e) {
                var rect = btn.getBoundingClientRect();
                var dx = e.clientX - (rect.left + rect.width / 2);
                var dy = e.clientY - (rect.top + rect.height / 2);
                btn.style.transform = "translate(" + (dx * 0.18).toFixed(1) + "px," + (dy * 0.28).toFixed(1) + "px) translateY(-2px)";
            });
            btn.addEventListener("pointerleave", function () {
                btn.style.transform = "";
            });
        });
    }

    /* ---------- Stats count-up ---------- */
    var counters = document.querySelectorAll(".stat b[data-count]");
    if (counters.length) {
        var cio = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) return;
                var el = entry.target;
                cio.unobserve(el);
                if (reduce) return;
                var target = parseInt(el.getAttribute("data-count"), 10) || 0;
                var suffix = el.getAttribute("data-suffix") || "";
                var start = null;
                var dur = 1100;
                function tick(ts) {
                    if (start === null) start = ts;
                    var t = Math.min(1, (ts - start) / dur);
                    var eased = 1 - Math.pow(1 - t, 3);
                    el.textContent = Math.round(target * eased) + suffix;
                    if (t < 1) window.requestAnimationFrame(tick);
                }
                window.requestAnimationFrame(tick);
            });
        }, { threshold: 0.5 });
        counters.forEach(function (el) { cio.observe(el); });
    }

    /* ---------- Seamless marquee ---------- */
    var track = document.getElementById("marqueeTrack");
    if (track && !reduce) {
        var half = track.innerHTML;
        track.insertAdjacentHTML("beforeend", half);
    }
})();
