const crypto = require("crypto");

function generateReference(prefix) {
    const now = new Date();

    const lagos = new Date(
        now.toLocaleString("en-US", {
            timeZone: "Africa/Lagos"
        })
    );

    const pad = (n) => String(n).padStart(2, "0");

    const YYYY = lagos.getFullYear();
    const MM = pad(lagos.getMonth() + 1);
    const DD = pad(lagos.getDate());
    const HH = pad(lagos.getHours());
    const II = pad(lagos.getMinutes());

    const suffix = Math.random()
        .toString(36)
        .substring(2, 12);

    // Preserve the original behaviour: timestamp + suffix.
    // An optional prefix argument is accepted for future use but
    // not required by existing code.
    return `${YYYY}${MM}${DD}${HH}${II}${suffix}`;
}

module.exports = {
    generateReference
};
