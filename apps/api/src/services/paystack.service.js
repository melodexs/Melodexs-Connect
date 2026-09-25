const crypto = require("crypto");
const fetch = globalThis.fetch || require("node-fetch");

function verifyWebhookSignature(rawBodyBuffer, signature) {
    if (!signature) return false;

    if (!process.env.PAYSTACK_SECRET_KEY) return false;

    const expectedSignature = crypto
        .createHmac("sha512", process.env.PAYSTACK_SECRET_KEY)
        .update(rawBodyBuffer)
        .digest("hex");

    try {
        const receivedBuffer = Buffer.from(String(signature), "utf8");
        const expectedBuffer = Buffer.from(expectedSignature, "utf8");

        if (
            receivedBuffer.length !== expectedBuffer.length ||
            !crypto.timingSafeEqual(receivedBuffer, expectedBuffer)
        ) {
            return false;
        }

        return true;
    } catch (e) {
        return false;
    }
}

async function initializeTransaction({ email, amountInKobo, reference, callbackUrl, metadata }) {
    const res = await fetch("https://api.paystack.co/transaction/initialize", {
        method: "POST",
        headers: {
            Authorization: `Bearer ${process.env.PAYSTACK_SECRET_KEY}`,
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            email,
            amount: String(amountInKobo),
            currency: "NGN",
            reference,
            callback_url: callbackUrl,
            metadata
        })
    });

    const data = await res.json().catch(() => null);

    return { ok: res.ok, status: res.status, data };
}

async function verifyTransaction(reference) {
    const res = await fetch(`https://api.paystack.co/transaction/verify/${encodeURIComponent(reference)}`, {
        method: "GET",
        headers: {
            Authorization: `Bearer ${process.env.PAYSTACK_SECRET_KEY}`
        }
    });

    const data = await res.json().catch(() => null);

    return { ok: res.ok, status: res.status, data };
}

module.exports = {
    verifyWebhookSignature,
    initializeTransaction,
    verifyTransaction
};
