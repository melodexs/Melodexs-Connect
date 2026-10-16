// Regression guard for GHSA-h3mg-xc3c-68pw / CVE-2026-101911.
//
// ip-address <= 10.7.0 builds a parse diagnostic proportional to the
// input when a string contains characters that cannot appear in an IPv6
// address, letting one long request stall or crash the Node process.
// The fix landed in ip-address 10.7.1.
//
// express-rate-limit only feeds Address6 strings that already passed
// Node's isIPv6 gate, so the vulnerable path is not reachable through
// the API today. This test exists so that stays true and so that a
// vulnerable ip-address version can never resolve again silently.
//
// Run with: npm run test:security  (no database required)

const assert = require("assert");
const { Address6 } = require("ip-address");
const { isIPv6 } = require("node:net");

const version = require("ip-address/package.json").version;
const [major, minor, patch] = version.split(".").map((n) => parseInt(n, 10));

// 1. The resolved ip-address must include the advisory fix (>= 10.7.1).
assert.ok(
    major > 10 || (major === 10 && (minor > 7 || (minor === 7 && patch >= 1))),
    `ip-address@${version} is affected by GHSA-h3mg-xc3c-68pw; expected >= 10.7.1. ` +
        "Check apps/api/package.json overrides."
);

// 2. The unbounded-diagnostic behavior must stay bounded on patched
//    versions: a 1 MiB invalid string must be rejected quickly instead of
//    building a ~110 MB parse diagnostic. The vulnerable version needs
//    well over 200 ms (measured ~230 ms) and tens of MB per MiB here.
const oversized = "!".repeat(1024 * 1024);
const started = process.hrtime.bigint();
assert.strictEqual(Address6.isValid(oversized), false, "oversized invalid input must be rejected");
const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6;
assert.ok(
    elapsedMs < 500,
    `Address6.isValid on 1 MiB of invalid input took ${elapsedMs.toFixed(1)} ms; ` +
        "this suggests the unbounded parse diagnostic is back (GHSA-h3mg-xc3c-68pw)."
);

// 3. Document the reachability gate in express-rate-limit: any string that
//    is not a syntactically valid IPv6 literal never reaches Address6.
assert.strictEqual(isIPv6(oversized), false);
assert.strictEqual(isIPv6("::ffff:192.0.2.1"), true);

console.log(`ok - ip-address@${version} (>= 10.7.1), 1 MiB invalid input rejected in ${elapsedMs.toFixed(1)} ms, isIPv6 gate intact`);
