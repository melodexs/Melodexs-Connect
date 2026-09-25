const { pool } = require("../postgres");
const { verifyWebhookSignature } = require("../services/paystack.service");
const crypto = require("crypto");

async function webhookHandler(req, res) {
    try {
        const signature = req.headers["x-paystack-signature"];

        if (!signature) {
            return res.status(401).send("Missing signature");
        }

        if (!process.env.PAYSTACK_SECRET_KEY) {
            console.error("PAYSTACK_SECRET_KEY is missing.");
            return res.status(500).send("Webhook not configured");
        }

        const valid = verifyWebhookSignature(req.body, signature);

        if (!valid) {
            console.error("Invalid Paystack webhook signature.");
            return res.status(401).send("Invalid signature");
        }

        const event = JSON.parse(req.body.toString("utf8"));

        console.log("Paystack webhook received:", event.event);

        if (event.event !== "charge.success") {
            return res.status(200).send("Event received");
        }

        const payment = event.data;

        if (!payment) {
            return res.status(400).send("Invalid payment data");
        }

        const reference = String(payment.reference || "").trim();

        if (!reference) {
            return res.status(400).send("Missing payment reference");
        }

        const transactionResult = await pool.query(`
            SELECT id, user_id, amount, status, reference
            FROM transactions
            WHERE reference = $1
              AND type = 'wallet_funding'
            LIMIT 1
        `, [reference]);

        const transaction = transactionResult.rows[0];

        if (!transaction) {
            console.warn("Paystack webhook transaction not found:", reference);
            return res.status(200).send("Transaction not found");
        }

        const expectedAmount = Math.round(Number(transaction.amount) * 100);
        const paidAmount = Number(payment.amount);
        const currency = String(payment.currency || "").toUpperCase();
        const metadataUserId = String((payment.metadata && payment.metadata.user_id) || "");

        if (
            payment.status !== "success" ||
            currency !== "NGN" ||
            paidAmount !== expectedAmount ||
            metadataUserId !== String(transaction.user_id) ||
            String(payment.reference) !== reference
        ) {
            console.error("Paystack webhook payment validation failed:", {
                reference,
                paymentStatus: payment.status,
                currency,
                paidAmount,
                expectedAmount,
                metadataUserId,
                transactionUserId: transaction.user_id
            });

            return res.status(400).send("Payment validation failed");
        }

        const client = await pool.connect();
        let credited = false;

        try {
            await client.query("BEGIN");

            const currentResult = await client.query(`
                SELECT id, status, user_id, amount
                FROM transactions
                WHERE id = $1
                FOR UPDATE
            `, [transaction.id]);

            const current = currentResult.rows[0];

            if (!current || current.status === "successful") {
                await client.query("ROLLBACK");
                console.log("Paystack webhook: payment was already processed.");
                return res.status(200).send("Already processed");
            }

            const walletResult = await client.query(`
                UPDATE users
                SET balance = balance + $1
                WHERE id = $2
                RETURNING id, balance
            `, [current.amount, current.user_id]);

            if (walletResult.rowCount !== 1) {
                throw new Error("User wallet could not be updated.");
            }

            await client.query(`
                UPDATE transactions
                SET status = 'successful', description = $1
                WHERE id = $2
            `, ["Paystack webhook wallet funding", current.id]);

            await client.query("COMMIT");

            credited = true;

        } catch (error) {
            try { await client.query("ROLLBACK"); } catch (e) { console.error("Paystack webhook rollback error:", e); }
            throw error;
        } finally {
            client.release();
        }

        console.log(credited ? `Paystack webhook: ₦${transaction.amount} credited successfully.` : "Paystack webhook: payment was already processed.");

        return res.status(200).send("Webhook processed");

    } catch (error) {
        console.error("Paystack webhook error:", error);
        return res.status(500).send("Webhook processing failed");
    }
}

module.exports = {
    webhookHandler
};
