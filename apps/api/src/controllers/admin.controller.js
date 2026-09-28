const { pool } = require("../postgres");

async function getAdminStats(req, res) {
    try {
        const result = await pool.query(`
            SELECT
                (SELECT COUNT(*) FROM users) AS total_users,
                (SELECT COALESCE(SUM(balance), 0) FROM users) AS total_balance,
                (SELECT COUNT(*) FROM transactions) AS total_transactions,
                (
                    SELECT COUNT(*)
                    FROM transactions
                    WHERE type = 'debit'
                      AND status = 'successful'
                      AND description ILIKE '%data purchase%'
                ) AS data_purchases,
                (
                    SELECT COUNT(*)
                    FROM transactions
                    WHERE type = 'debit'
                      AND status = 'successful'
                      AND description ILIKE '%airtime purchase%'
                ) AS airtime_purchases,
                (
                    SELECT COALESCE(SUM(amount), 0)
                    FROM transactions
                    WHERE type = 'debit'
                      AND status = 'successful'
                      AND (
                          description ILIKE '%data purchase%'
                          OR description ILIKE '%airtime purchase%'
                      )
                ) AS total_revenue
        `);

        const stats = result.rows[0];

        return res.json({
            success: true,
            stats: {
                totalUsers: Number(stats.total_users),
                totalBalance: Number(stats.total_balance),
                totalTransactions: Number(stats.total_transactions),
                dataPurchases: Number(stats.data_purchases),
                airtimePurchases: Number(stats.airtime_purchases),
                totalRevenue: Number(stats.total_revenue)
            }
        });

    } catch (error) {
        console.error(
            "Admin stats error:",
            error
        );

        return res.status(500).json({
            success: false,
            message: "Could not load admin statistics"
        });
    }
}

async function getAdminUsers(req, res) {
    try {
        const result = await pool.query(`
            SELECT
                id,
                name,
                email,
                phone,
                balance,
                virtual_account_number,
                virtual_bank_name,
                kyc_status,
                is_admin,
                created_at
            FROM users
            ORDER BY id DESC
        `);

        return res.json({
            success: true,
            users: result.rows
        });

    } catch (error) {
        console.error(
            "Admin users error:",
            error
        );

        return res.status(500).json({
            success: false,
            message: "Could not load users"
        });
    }
}

async function getAdminTransactions(req, res) {
    try {
        const result = await pool.query(`
            SELECT
                transactions.id,
                users.name AS user_name,
                users.email AS user_email,
                transactions.type,
                transactions.amount,
                transactions.status,
                transactions.reference,
                transactions.description,
                transactions.created_at
            FROM transactions
            INNER JOIN users
                ON users.id = transactions.user_id
            ORDER BY transactions.id DESC
            LIMIT 100
        `);

        return res.json({
            success: true,
            transactions: result.rows
        });

    } catch (error) {
        console.error(
            "Admin transactions error:",
            error
        );

        return res.status(500).json({
            success: false,
            message: "Could not load admin transactions"
        });
    }
}

module.exports = {
    getAdminStats,
    getAdminUsers,
    getAdminTransactions
};
