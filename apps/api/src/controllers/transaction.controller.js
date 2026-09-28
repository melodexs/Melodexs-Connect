const { pool } = require("../postgres");
const { getAdmin } = require("../auth");

async function getTransactionsByUser(req, res) {
    try {
        const requestedId = Number(req.params.userId);

        if (!Number.isInteger(requestedId) || requestedId <= 0) {
            return res.status(400).json({
                success: false,
                message: "Invalid user ID"
            });
        }

        if (requestedId !== req.session.userId) {
            const admin = await getAdmin(req.session.userId);

            if (!admin) {
                return res.status(403).json({
                    success: false,
                    message: "You can only view your own transactions"
                });
            }
        }

        const result = await pool.query(`
            SELECT
                id,
                type,
                amount,
                status,
                reference,
                description,
                created_at
            FROM transactions
            WHERE user_id = $1
            ORDER BY id DESC
        `, [requestedId]);

        return res.json({
            success: true,
            transactions: result.rows
        });

    } catch (error) {
        console.error(
            "Transactions error:",
            error
        );

        return res.status(500).json({
            success: false,
            message: "Could not load transactions"
        });
    }
}

module.exports = {
    getTransactionsByUser
};
