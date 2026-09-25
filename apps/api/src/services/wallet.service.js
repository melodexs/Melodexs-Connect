const { pool } = require("../postgres");

async function createPendingTransaction({ userId, type, amount, reference, description }) {
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
    `, [userId, type, amount, "pending", reference, description]);
}

async function getTransactionByReference(reference, userId) {
    const result = await pool.query(`
        SELECT id, user_id, amount, status, reference
        FROM transactions
        WHERE reference = $1
          AND type = 'wallet_funding'
          AND user_id = $2
        LIMIT 1
    `, [reference, userId]);

    return result.rows[0] || null;
}

async function creditPendingTransaction(transactionId, { successDescription = "Verified Paystack wallet funding" } = {}) {
    let credited = false;

    const client = await pool.connect();

    try {
        await client.query("BEGIN");

        const currentResult = await client.query(`
            SELECT status, user_id, amount
            FROM transactions
            WHERE id = $1
            FOR UPDATE
        `, [transactionId]);

        const current = currentResult.rows[0];

        if (!current) {
            throw new Error("Funding transaction could not be found.");
        }

        if (current.status === "successful") {
            await client.query("COMMIT");
            return { credited: false, userId: current.user_id, amount: current.amount };
        }

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
            SET status = 'successful', description = $1
            WHERE id = $2 AND status <> 'successful'
        `, [successDescription, transactionId]);

        if (transactionUpdate.rowCount !== 1) {
            throw new Error("Funding transaction could not be completed.");
        }

        await client.query("COMMIT");

        credited = true;

        return { credited, balance: walletUpdate.rows[0].balance, userId: current.user_id, amount: current.amount };

    } catch (err) {
        try { await client.query("ROLLBACK"); } catch (e) { console.error("Rollback error in creditPendingTransaction:", e); }
        throw err;
    } finally {
        client.release();
    }
}

async function reserveDebitAndCreateTransaction(userId, amount, referenceOrDescription, maybeDescription) {
    // Support two calling conventions for backward compatibility:
    // 1) (userId, amount, reference, descriptionText)
    // 2) (userId, amount, { reference, text })
    let reference = null;
    let descriptionText = "";

    if (referenceOrDescription && typeof referenceOrDescription === "object") {
        reference = referenceOrDescription.reference || null;
        descriptionText = referenceOrDescription.text || "";
    } else {
        reference = referenceOrDescription || null;
        descriptionText = maybeDescription || "";
    }

    const client = await pool.connect();
    try {
        await client.query("BEGIN");

        const debitResult = await client.query(`
            UPDATE users
            SET balance = balance - $1
            WHERE id = $2
              AND balance >= $1
            RETURNING id, balance
        `, [amount, userId]);

        if (debitResult.rowCount !== 1) {
            throw new Error("INSUFFICIENT_BALANCE");
        }

        await client.query(`
            INSERT INTO transactions (
                user_id,
                type,
                amount,
                status,
                reference,
                description
            )
            VALUES ($1, $2, $3, $4, $5, $6)
        `, [userId, "debit", amount, "pending", reference, descriptionText]);

        await client.query("COMMIT");
    } catch (err) {
        try { await client.query("ROLLBACK"); } catch (e) { console.error("Rollback error in reserveDebitAndCreateTransaction:", e); }
        throw err;
    } finally {
        client.release();
    }
}

module.exports = {
    createPendingTransaction,
    getTransactionByReference,
    creditPendingTransaction,
    reserveDebitAndCreateTransaction
};
