const crypto = require("crypto");
const { pool } = require("../postgres");
const {
    initializeWalletFunding,
    validateWebhookSignature,
    verifyWalletFunding
} = require("../services/paystack.service");

async function fundWallet(req, res) {
    let reference = null;

    try {
        const { amount } = req.body;
        const numericUserId = req.session.userId;
        const fundingAmount = Number(amount);

        if (
            !Number.isInteger(fundingAmount) ||
            fundingAmount < 100 ||
            fundingAmount > 500000
        ) {
            return res.status(400).json({
                success: false,
                message: "Funding amount must be between ₦100 and ₦500,000."
            });
        }

        const userResult = await pool.query(`
            SELECT id, email
            FROM users
            WHERE id = $1
        `, [numericUserId]);
        const user = userResult.rows[0];

        if (!user) {
            return res.status(404).json({
                success: false,
                message: "User account not found."
            });
        }

        if (!process.env.PAYSTACK_SECRET_KEY) {
            console.error("PAYSTACK_SECRET_KEY is missing.");
            return res.status(500).json({
                success: false,
                message: "Payment system is not configured yet."
            });
        }

        reference = `CD-${Date.now()}-${crypto.randomBytes(6).toString("hex")}`;

        await pool.query(`
            INSERT INTO transactions (
                user_id,
                type,
                amount,
                status,
                reference,
                description
            )
            VALUES ($1, $2, $3, $4, $5, $6)
        `, [
            user.id,
            "wallet_funding",
            fundingAmount,
            "pending",
            reference,
            "Paystack wallet funding"
        ]);

        const callbackUrl =
            `${process.env.CHEAPDATA_PUBLIC_URL || `${req.protocol}://${req.get("host")}`}/fund-wallet.html`;
        let paystackResponse;

        try {
            paystackResponse = await initializeWalletFunding({
                secretKey: process.env.PAYSTACK_SECRET_KEY,
                email: user.email,
                amount: fundingAmount,
                reference,
                callbackUrl,
                userId: user.id
            });
        } catch (error) {
            console.error("Paystack initialization network error:", error);
            return res.status(500).json({
                success: false,
                message:
                    "Unable to confirm payment initialization right now. Please try again later."
            });
        }

        let paystackData;
        try {
            paystackData = await paystackResponse.json();
        } catch (error) {
            console.error(
                "Invalid response from Paystack during initialization:",
                error
            );
            return res.status(502).json({
                success: false,
                message:
                    "Payment initialization could not be confirmed. Please try again later."
            });
        }

        if (
            !paystackResponse.ok ||
            !paystackData.status ||
            !paystackData.data
        ) {
            console.error("Paystack initialization failed:", paystackData);
            await pool.query(`
                UPDATE transactions
                SET
                    status = $1,
                    description = $2
                WHERE reference = $3
                  AND user_id = $4
                  AND type = $5
                  AND status = $6
            `, [
                "failed",
                "Paystack wallet funding initialization failed",
                reference,
                user.id,
                "wallet_funding",
                "pending"
            ]);

            return res.status(400).json({
                success: false,
                message:
                    paystackData.message || "Unable to initialize payment."
            });
        }

        if (
            !paystackData.data.reference ||
            paystackData.data.reference !== reference
        ) {
            console.error(
                "Paystack returned an unexpected transaction reference:",
                {
                    expected: reference,
                    received: paystackData.data.reference
                }
            );
            return res.status(502).json({
                success: false,
                message:
                    "Payment initialization could not be verified. Please try again later."
            });
        }

        return res.json({
            success: true,
            message: "Payment initialized successfully.",
            authorization_url: paystackData.data.authorization_url,
            access_code: paystackData.data.access_code,
            reference
        });
    } catch (error) {
        console.error("Fund wallet error:", error);
        return res.status(500).json({
            success: false,
            message: "Unable to initialize payment. Please try again."
        });
    }
}

async function verifyFundWallet(req, res) {
    try {
        const reference = String(req.body.reference || "").trim();

        if (!reference || reference.length > 100) {
            return res.status(400).json({
                success: false,
                message: "A valid payment reference is required."
            });
        }

        if (!process.env.PAYSTACK_SECRET_KEY) {
            return res.status(500).json({
                success: false,
                message: "Payment system is not configured yet."
            });
        }

        const transactionResult = await pool.query(`
            SELECT id, user_id, amount, status, reference
            FROM transactions
            WHERE reference = $1
              AND type = 'wallet_funding'
              AND user_id = $2
            LIMIT 1
        `, [reference, req.session.userId]);
        const transaction = transactionResult.rows[0];

        if (!transaction) {
            return res.status(404).json({
                success: false,
                message: "Funding transaction not found."
            });
        }

        if (transaction.status === "successful") {
            const userResult = await pool.query(`
                SELECT balance
                FROM users
                WHERE id = $1
            `, [req.session.userId]);
            const user = userResult.rows[0];
            return res.json({
                success: true,
                message: "Payment has already been credited.",
                balance: user.balance,
                reference
            });
        }

        const paystackResponse = await verifyWalletFunding({
            secretKey: process.env.PAYSTACK_SECRET_KEY,
            reference
        });
        const paystackData = await paystackResponse.json();

        if (!paystackResponse.ok || !paystackData.status || !paystackData.data) {
            return res.status(400).json({
                success: false,
                message: paystackData.message || "Unable to verify payment."
            });
        }

        const payment = paystackData.data;
        const expectedAmount = Math.round(Number(transaction.amount) * 100);
        const paidAmount = Number(payment.amount);
        const metadataUserId = String(
            payment.metadata && payment.metadata.user_id || ""
        );

        if (
            payment.status !== "success" ||
            payment.currency !== "NGN" ||
            paidAmount !== expectedAmount ||
            metadataUserId !== String(req.session.userId) ||
            String(payment.reference) !== reference
        ) {
            return res.status(400).json({
                success: false,
                message:
                    "Payment could not be verified as a valid MELODEXS CONNECT wallet funding."
            });
        }

        let credited = false;
        const client = await pool.connect();

        try {
            await client.query("BEGIN");
            const currentResult = await client.query(`
                SELECT status, user_id, amount
                FROM transactions
                WHERE id = $1
                FOR UPDATE
            `, [transaction.id]);
            const current = currentResult.rows[0];

            if (!current) {
                throw new Error("Funding transaction could not be found.");
            }

            if (current.status === "successful") {
                await client.query("COMMIT");
            } else {
                const walletUpdate = await client.query(`
                    UPDATE users
                    SET balance = balance + $1
                    WHERE id = $2
                    RETURNING id, balance
                `, [current.amount, current.user_id]);

                if (walletUpdate.rowCount !== 1) {
                    throw new Error("Wallet could not be updated.");
                }

                const transactionUpdate = await client.query(`
                    UPDATE transactions
                    SET
                        status = 'successful',
                        description = $1
                    WHERE id = $2
                      AND status <> 'successful'
                `, ["Verified Paystack wallet funding", transaction.id]);

                if (transactionUpdate.rowCount !== 1) {
                    throw new Error("Funding transaction could not be completed.");
                }

                await client.query("COMMIT");
                credited = true;
            }
        } catch (creditError) {
            try {
                await client.query("ROLLBACK");
            } catch (rollbackError) {
                console.error("Paystack wallet credit rollback error:", rollbackError);
            }
            throw creditError;
        } finally {
            client.release();
        }

        const userResult = await pool.query(`
            SELECT balance
            FROM users
            WHERE id = $1
        `, [req.session.userId]);
        const user = userResult.rows[0];

        return res.json({
            success: true,
            message: credited
                ? "Payment verified and wallet credited successfully."
                : "Payment has already been credited.",
            balance: user.balance,
            amount: transaction.amount,
            reference
        });
    } catch (error) {
        console.error("Paystack verification error:", error);
        return res.status(500).json({
            success: false,
            message: "Unable to verify payment right now. Please try again."
        });
    }
}

async function paystackWebhook(req, res) {
    try {
        const signature = req.headers["x-paystack-signature"];

        if (!signature) {
            return res.status(401).send("Missing signature");
        }

        if (!process.env.PAYSTACK_SECRET_KEY) {
            console.error("PAYSTACK_SECRET_KEY is missing.");
            return res.status(500).send("Webhook not configured");
        }

        const signatureIsValid = await validateWebhookSignature({
            secretKey: process.env.PAYSTACK_SECRET_KEY,
            rawBody: req.body,
            signature
        });

        if (!signatureIsValid) {
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
            SELECT
                id,
                user_id,
                amount,
                status,
                reference
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
        const metadataUserId = String(
            payment.metadata && payment.metadata.user_id || ""
        );

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
                SELECT
                    id,
                    status,
                    user_id,
                    amount
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
                SET
                    status = 'successful',
                    description = $1
                WHERE id = $2
            `, ["Paystack webhook wallet funding", current.id]);

            await client.query("COMMIT");
            credited = true;
        } catch (error) {
            try {
                await client.query("ROLLBACK");
            } catch (rollbackError) {
                console.error("Paystack webhook rollback error:", rollbackError);
            }
            throw error;
        } finally {
            client.release();
        }

        console.log(
            credited
                ? `Paystack webhook: ₦${transaction.amount} credited successfully.`
                : "Paystack webhook: payment was already processed."
        );
        return res.status(200).send("Webhook processed");
    } catch (error) {
        console.error("Paystack webhook error:", error);
        return res.status(500).send("Webhook processing failed");
    }
}

module.exports = {
    fundWallet,
    paystackWebhook,
    verifyFundWallet
};
