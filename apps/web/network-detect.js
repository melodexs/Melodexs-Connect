/* Detect the mobile network from a Nigerian phone number's prefix.
 *
 * Source: the NCC "Mobile Number Allocation Table" (ncc.gov.ng, updated
 * Nov 2024). Pure functions, no DOM, so they are unit-tested under Node.
 *
 * IMPORTANT: since Mobile Number Portability (2013) a person can keep their
 * number when they switch network, so a prefix is a strong HINT and not proof.
 * Callers must show what was detected and leave the user free to override it.
 */
(function (root) {
    "use strict";

    // 4-digit local prefix (0803...) -> network slug used by the app.
    var PREFIXES = {
        MTN: ["0803", "0806", "0810", "0813", "0814", "0816", "0703", "0704", "0706", "0707", "0903", "0906", "0913", "0916"],
        Airtel: ["0802", "0808", "0812", "0701", "0708", "0901", "0902", "0904", "0907", "0911", "0912"],
        Glo: ["0805", "0807", "0811", "0815", "0705", "0905", "0915"],
        "9mobile": ["0809", "0817", "0818", "0908", "0909"]
    };

    var LOOKUP = {};
    Object.keys(PREFIXES).forEach(function (network) {
        PREFIXES[network].forEach(function (prefix) { LOOKUP[prefix] = network; });
    });

    // Accepts 0803..., 234803..., +234803..., with spaces or dashes. Returns the
    // local form's digits so far ("0803123"), or "" if it is not a Nigerian number.
    function toLocalDigits(input) {
        var digits = String(input == null ? "" : input).replace(/[^\d+]/g, "");
        if (digits.indexOf("+234") === 0) digits = "0" + digits.slice(4);
        else if (digits.indexOf("234") === 0 && digits.length > 3) digits = "0" + digits.slice(3);
        digits = digits.replace(/\+/g, "");
        return digits.charAt(0) === "0" ? digits : "";
    }

    // Returns the network slug once four digits are typed, else null.
    // Never guesses from fewer digits, and returns null for prefixes that do not
    // belong to one of the four supported networks (e.g. 0804 M-Tel, 0702 Smile).
    function detectNetwork(input) {
        var local = toLocalDigits(input);
        if (local.length < 4) return null;
        return LOOKUP[local.slice(0, 4)] || null;
    }

    // Wires a phone <input> to a page's network selector.
    //   options.getNetwork()   -> the network currently selected
    //   options.setNetwork(n)  -> switch the page to network n (n is a slug)
    //   options.noteElement    -> element that shows "Detected Glo" feedback
    //   options.networkChips   -> element holding the manual network buttons
    //
    // Rules: switch once a 4-digit prefix identifies a network; always say so;
    // and once the user picks a network by hand, stop overriding them for the
    // current number (a ported number legitimately differs from its prefix).
    // Typing a different prefix, or clearing the field, resets that choice.
    function bindNetworkDetection(input, options) {
        var manualFor = null;       // the 4-digit prefix the user overrode by hand
        var lastPrefix = "";

        function say(text) {
            var el = options.noteElement;
            if (!el) return;
            el.textContent = text || "";
            el.hidden = !text;
        }

        function onInput() {
            var local = toLocalDigits(input.value);
            var prefix = local.length >= 4 ? local.slice(0, 4) : "";
            if (prefix !== lastPrefix) {
                // a different prefix (or cleared field) is a fresh number
                if (manualFor && prefix !== manualFor) manualFor = null;
                lastPrefix = prefix;
            }
            if (!prefix) { say(""); return; }

            var detected = LOOKUP[prefix] || null;
            if (!detected) { say(""); return; }
            if (manualFor === prefix) {
                // user chose differently on purpose; just remind them what the prefix says
                if (detected !== options.getNetwork()) say("This number starts like " + detected + ", but you chose " + options.getNetwork() + ".");
                else say("");
                return;
            }
            if (detected !== options.getNetwork()) options.setNetwork(detected);
            say("Detected " + detected + " from the number. Tap another network if this number has moved.");
        }

        if (options.networkChips) {
            // a real tap on a network chip is a deliberate override of the current prefix
            options.networkChips.addEventListener("click", function (e) {
                if (!e.isTrusted) return;
                var chip = e.target.closest && e.target.closest("[data-network]");
                if (!chip || !lastPrefix) return;
                manualFor = lastPrefix;
                onInput();
            });
        }
        input.addEventListener("input", onInput);
        return {
            refresh: onInput,
            // Treat the network that is selected right now as the user's own choice
            // for the number currently in the field (used for saved recipients).
            pinCurrent: function () {
                var local = toLocalDigits(input.value);
                lastPrefix = local.length >= 4 ? local.slice(0, 4) : "";
                manualFor = lastPrefix || null;
                onInput();
            }
        };
    }

    var api = { PREFIXES: PREFIXES, detectNetwork: detectNetwork, toLocalDigits: toLocalDigits, bindNetworkDetection: bindNetworkDetection };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    root.MELODEXS_NETWORK = api;
})(typeof window !== "undefined" ? window : globalThis);
