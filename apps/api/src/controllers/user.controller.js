const { pool } = require("../postgres");

async function getStatus(req, res) {
    res.json({
        success: true,
        message: "MELODEXS CONNECT API is running"
    });
}

async function getUserProfile(req, res) {
    try {
        const requestedUserId = Number(req.params.id);
        const sessionUserId = Number(req.session.userId);

        if (
            !Number.isInteger(requestedUserId) ||
            requestedUserId <= 0
        ) {
            return res.status(400).json({
                success: false,
                message: "Invalid user ID"
            });
        }

        if (requestedUserId !== sessionUserId) {
            return res.status(403).json({
                success: false,
                message: "Access denied"
            });
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
        `, [sessionUserId]);

        const user = result.rows[0];

        if (!user) {
            req.session.destroy(() => {});

            return res.status(404).json({
                success: false,
                message: "User not found"
            });
        }

        const hasPurchasePin = Boolean(user.purchase_pin);

        delete user.purchase_pin;

        return res.json({
            success: true,
            user,
            has_purchase_pin: hasPurchasePin
        });

    } catch (error) {
        console.error("Get user error:", error);

        return res.status(500).json({
            success: false,
            message: "Could not retrieve user"
        });
    }
}

module.exports = {
    getStatus,
    getUserProfile
};
