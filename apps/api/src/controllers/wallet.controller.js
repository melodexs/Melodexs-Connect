const { pool } = require("../postgres");
const crypto = require("crypto");
const { initializeTransaction, verifyTransaction } = require("../services/paystack.service");

async function fundWallet(req, res) {
    let reference = null;

    try {
        const { amount } = req.body;

        const numericUserId = req.session.userId;
        const fundingAmount = Number(amount);

        // Validate amount
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

        const { createPendingTransaction } = require("../services/wallet.service");

        await createPendingTransaction({
            userId: user.id,
            type: "wallet_funding",
            amount: fundingAmount,
            reference,
            description: "Paystack wallet funding"
        });

        const amountInKobo = fundingAmount * 100;

        const callbackUrl = `${process.env.CHEAPDATA_PUBLIC_URL || `${req.protocol}://${req.get("host")}`}/fund-wallet.html`;

        const init = await initializeTransaction({
            email: user.email,
            amountInKobo,
            reference,
            callbackUrl,
            metadata: { user_id: String(user.id), purpose: "wallet_funding" }
        });

        if (!init.ok || !init.data || !init.data.status || !init.data.data) {
            console.error("Paystack initialization failed:", init.data);

            await pool.query(`
                UPDATE transactions
                SET status = $1, description = $2
                WHERE reference = $3 AND user_id = $4 AND type = $5 AND status = $6
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
                message: init.data && init.data.message ? init.data.message : "Unable to initialize payment."
            });
        }

        if (!init.data.data.reference || init.data.data.reference !== reference) {
            console.error("Paystack returned an unexpected transaction reference:", { expected: reference, received: init.data.data.reference });

            return res.status(502).json({
                success: false,
                message: "Payment initialization could not be verified. Please try again later."
            });
        }

        return res.json({
            success: true,
            message: "Payment initialized successfully.",
            authorization_url: init.data.data.authorization_url,
            access_code: init.data.data.access_code,
            reference: reference
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

        const { getTransactionByReference, creditPendingTransaction } = require("../services/wallet.service");

        const transaction = await getTransactionByReference(reference, req.session.userId);

        if (!transaction) {
            return res.status(404).json({ success: false, message: "Funding transaction not found." });
        }

        if (transaction.status === "successful") {
            const userResult = await pool.query(`SELECT balance FROM users WHERE id = $1`, [req.session.userId]);
            const user = userResult.rows[0];
            return res.json({ success: true, message: "Payment has already been credited.", balance: user.balance, reference });
        }

        const verification = await verifyTransaction(reference);

        if (!verification.ok || !verification.data || !verification.data.status || !verification.data.data) {
            return res.status(400).json({ success: false, message: verification.data && verification.data.message ? verification.data.message : "Unable to verify payment." });
        }

        const payment = verification.data.data;
        const expectedAmount = Math.round(Number(transaction.amount) * 100);
        const paidAmount = Number(payment.amount);
        const metadataUserId = String((payment.metadata && payment.metadata.user_id) || "");

        if (payment.status !== "success" || payment.currency !== "NGN" || paidAmount !== expectedAmount || metadataUserId !== String(req.session.userId) || String(payment.reference) !== reference) {
            return res.status(400).json({ success: false, message: "Payment could not be verified as a valid MELODEXS CONNECT wallet funding." });
        }

        let creditedResult;

        try {
            creditedResult = await creditPendingTransaction(transaction.id);
        } catch (creditError) {
            console.error("Paystack verification credit error:", creditError);
            return res.status(500).json({ success: false, message: "Unable to verify payment right now. Please try again." });
        }

        const userResult = await pool.query(`SELECT balance FROM users WHERE id = $1`, [req.session.userId]);
        const user = userResult.rows[0];

        return res.json({ success: true, message: creditedResult.credited ? "Payment verified and wallet credited successfully." : "Payment has already been credited.", balance: user.balance, amount: transaction.amount, reference });

    } catch (error) {
        console.error("Paystack verification error:", error);
        return res.status(500).json({ success: false, message: "Unable to verify payment right now. Please try again." });
    }
}

module.exports = {
    fundWallet,
    verifyFundWallet
};
