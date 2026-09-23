const { pool } = require("./postgres");

async function getUserById(userId) {
    if (!userId) {
        return null;
    }

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
            purchase_pin,
            created_at
        FROM users
        WHERE id = $1
        LIMIT 1
    `, [userId]);

    return result.rows[0] || null;
}

function requireAuth(req, res, next) {
    if (!req.session || !req.session.userId) {
        return res.status(401).json({
            success: false,
            message: "Please log in to continue"
        });
    }

    next();
}

async function getAdmin(userId) {
    if (!userId) {
        return null;
    }

    const result = await pool.query(`
        SELECT
            id,
            name,
            email,
            is_admin
        FROM users
        WHERE id = $1
        AND is_admin = 1
        LIMIT 1
    `, [userId]);

    return result.rows[0] || null;
}

async function requireAdmin(req, res, next) {
    try {
        const admin = await getAdmin(
            req.session && req.session.userId
        );

        if (!admin) {
            return res.status(403).json({
                success: false,
                message: "Admin access required"
            });
        }

        req.admin = admin;
        next();
    } catch (error) {
        console.error("Admin authentication error:", error);

        return res.status(500).json({
            success: false,
            message: "Could not verify admin access"
        });
    }
}

module.exports = {
    requireAuth,
    requireAdmin,
    getAdmin,
    getUserById
};
