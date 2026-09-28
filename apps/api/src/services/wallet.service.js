const { pool } = require("../postgres");

async function reserveDebitAndCreateTransaction({
    userId,
    amount,
    reference,
    description
}) {
    const client = await pool.connect();

    try {
        await client.query("BEGIN");

        const debitResult = await client.query(`
            UPDATE users
            SET balance = balance - $1
            WHERE id = $2
              AND balance >= $1
            RETURNING id, balance
        `, [
            amount,
            userId
        ]);

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
        `, [
            userId,
            "debit",
            amount,
            "pending",
            reference,
            description
        ]);

        await client.query("COMMIT");

        return {
            ok: true,
            amount,
            reference
        };
    } catch (transactionError) {
        try {
            await client.query("ROLLBACK");
        } catch (rollbackError) {
            console.error(
                "Wallet reservation rollback error:",
                rollbackError
            );
        }

        throw transactionError;
    } finally {
        client.release();
    }
}

async function refundWalletAndUpdateTransaction({
    userId,
    amount,
    reference,
    description
}) {
    const client = await pool.connect();

    try {
        await client.query("BEGIN");

        const refundResult = await client.query(`
            UPDATE users
            SET balance = balance + $1
            WHERE id = $2
            RETURNING id, balance
        `, [
            amount,
            userId
        ]);

        if (refundResult.rowCount !== 1) {
            throw new Error("Wallet refund failed");
        }

        const updateResult = await client.query(`
            UPDATE transactions
            SET
                status = $1,
                description = $2
            WHERE reference = $3
              AND user_id = $4
              AND status = 'pending'
        `, [
            "failed",
            description,
            reference,
            userId
        ]);

        if (updateResult.rowCount !== 1) {
            throw new Error("Transaction status update failed");
        }

        await client.query("COMMIT");

        return {
            ok: true,
            amount,
            reference
        };
    } catch (transactionError) {
        try {
            await client.query("ROLLBACK");
        } catch (rollbackError) {
            console.error(
                "Wallet refund rollback error:",
                rollbackError
            );
        }

        throw transactionError;
    } finally {
        client.release();
    }
}

async function markTransactionSuccessful({
    userId,
    reference,
    description
}) {
    const client = await pool.connect();

    try {
        await client.query("BEGIN");

        const updateResult = await client.query(`
            UPDATE transactions
            SET
                status = $1,
                description = $2
            WHERE reference = $3
              AND user_id = $4
              AND status = 'pending'
        `, [
            "successful",
            description,
            reference,
            userId
        ]);

        if (updateResult.rowCount !== 1) {
            throw new Error("Pending transaction could not be completed");
        }

        await client.query("COMMIT");

        return {
            ok: true,
            reference
        };
    } catch (transactionError) {
        try {
            await client.query("ROLLBACK");
        } catch (rollbackError) {
            console.error(
                "Mark successful rollback error:",
                rollbackError
            );
        }

        throw transactionError;
    } finally {
        client.release();
    }
}

module.exports = {
    reserveDebitAndCreateTransaction,
    refundWalletAndUpdateTransaction,
    markTransactionSuccessful
};
