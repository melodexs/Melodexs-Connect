const crypto = require("crypto");

async function validateWebhookSignature({ secretKey, rawBody, signature }) {
    if (!signature) {
        return false;
    }

    if (!secretKey) {
        return false;
    }

    const expectedSignature = crypto
        .createHmac("sha512", secretKey)
        .update(rawBody)
        .digest("hex");

    const receivedBuffer = Buffer.from(String(signature), "utf8");
    const expectedBuffer = Buffer.from(expectedSignature, "utf8");

    return (
        receivedBuffer.length === expectedBuffer.length &&
        crypto.timingSafeEqual(receivedBuffer, expectedBuffer)
    );
}

async function initializeWalletFunding({
    secretKey,
    email,
    amount,
    reference,
    callbackUrl,
    userId
}) {
    const response = await fetch(
        "https://api.paystack.co/transaction/initialize",
        {
            method: "POST",
            headers: {
                Authorization: `Bearer ${secretKey}`,
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                email,
                amount: String(amount * 100),
                currency: "NGN",
                reference,
                callback_url: callbackUrl,
                metadata: {
                    user_id: String(userId),
                    purpose: "wallet_funding"
                }
            })
        }
    );

    return response;
}

async function verifyWalletFunding({ secretKey, reference }) {
    const response = await fetch(
        `https://api.paystack.co/transaction/verify/${encodeURIComponent(reference)}`,
        {
            method: "GET",
            headers: {
                Authorization: `Bearer ${secretKey}`
            }
        }
    );

    return response;
}

module.exports = {
    validateWebhookSignature,
    initializeWalletFunding,
    verifyWalletFunding
};
