const bcrypt = require("bcryptjs");
const { pool } = require("../postgres");

async function setPurchasePin(req, res) {
    try {
        const userId = req.session.userId;
        const { pin } = req.body;

        if (pin === undefined) {
            return res.status(400).json({
                success: false,
                message: "PIN is required"
            });
        }

        const pinString = String(pin);

        if (!/^\d{4}$/.test(pinString)) {
            return res.status(400).json({
                success: false,
                message: "Purchase PIN must be exactly 4 digits"
            });
        }

        const userResult = await pool.query(`
            SELECT
                id,
                purchase_pin
            FROM users
            WHERE id = $1
        `, [userId]);

        const user = userResult.rows[0];

        if (!user) {
            return res.status(404).json({
                success: false,
                message: "User not found"
            });
        }

        if (user.purchase_pin) {
            return res.status(400).json({
                success: false,
                message: "Purchase PIN has already been set"
            });
        }

        const hashedPin = await bcrypt.hash(
            pinString,
            10
        );

        await pool.query(`
            UPDATE users
            SET purchase_pin = $1
            WHERE id = $2
        `, [
            hashedPin,
            userId
        ]);

        res.json({
            success: true,
            message: "Purchase PIN created successfully"
        });

    } catch (error) {
        console.error(
            "Set Purchase PIN error:",
            error
        );

        res.status(500).json({
            success: false,
            message: "Could not create Purchase PIN"
        });
    }
}

async function changePurchasePin(req, res) {
    try {
        const userId = req.session.userId;
        const {
            currentPin,
            newPin
        } = req.body;

        if (
            currentPin === undefined ||
            newPin === undefined
        ) {
            return res.status(400).json({
                success: false,
                message: "All PIN fields are required"
            });
        }

        const currentPinString =
            String(currentPin);

        const newPinString =
            String(newPin);

        if (!/^\d{4}$/.test(currentPinString)) {
            return res.status(400).json({
                success: false,
                message: "Current PIN must be exactly 4 digits"
            });
        }

        if (!/^\d{4}$/.test(newPinString)) {
            return res.status(400).json({
                success: false,
                message: "New PIN must be exactly 4 digits"
            });
        }

        if (currentPinString === newPinString) {
            return res.status(400).json({
                success: false,
                message: "New PIN must be different from current PIN"
            });
        }

        const userResult = await pool.query(`
            SELECT
                id,
                purchase_pin
            FROM users
            WHERE id = $1
        `, [userId]);

        const user = userResult.rows[0];

        if (!user) {
            return res.status(404).json({
                success: false,
                message: "User not found"
            });
        }

        if (!user.purchase_pin) {
            return res.status(400).json({
                success: false,
                message: "Purchase PIN has not been set"
            });
        }

        const pinCorrect = await bcrypt.compare(
            currentPinString,
            user.purchase_pin
        );

        if (!pinCorrect) {
            return res.status(401).json({
                success: false,
                message: "Current Purchase PIN is incorrect"
            });
        }

        const hashedNewPin = await bcrypt.hash(
            newPinString,
            10
        );

        await pool.query(`
            UPDATE users
            SET purchase_pin = $1
            WHERE id = $2
        `, [
            hashedNewPin,
            userId
        ]);

        res.json({
            success: true,
            message: "Purchase PIN changed successfully"
        });

    } catch (error) {
        console.error(
            "Change Purchase PIN error:",
            error
        );

        res.status(500).json({
            success: false,
            message: "Could not change Purchase PIN"
        });
    }
}

async function verifyPurchasePin(req, res) {
    try {
        const userId = req.session.userId;
        const { pin } = req.body;

        if (pin === undefined) {
            return res.status(400).json({
                success: false,
                message: "PIN is required"
            });
        }

        const pinString = String(pin);

        if (!/^\d{4}$/.test(pinString)) {
            return res.status(400).json({
                success: false,
                message: "Purchase PIN must be exactly 4 digits"
            });
        }

        const userResult = await pool.query(`
            SELECT
                id,
                purchase_pin
            FROM users
            WHERE id = $1
        `, [userId]);

        const user = userResult.rows[0];

        if (!user) {
            return res.status(404).json({
                success: false,
                message: "User not found"
            });
        }

        if (!user.purchase_pin) {
            return res.status(400).json({
                success: false,
                message: "Purchase PIN has not been set"
            });
        }

        const pinCorrect = await bcrypt.compare(
            pinString,
            user.purchase_pin
        );

        if (!pinCorrect) {
            return res.status(401).json({
                success: false,
                message: "Incorrect Purchase PIN"
            });
        }

        res.json({
            success: true,
            message: "Purchase PIN verified"
        });

    } catch (error) {
        console.error(
            "Verify Purchase PIN error:",
            error
        );

        res.status(500).json({
            success: false,
            message: "Could not verify Purchase PIN"
        });
    }
}

module.exports = {
    setPurchasePin,
    changePurchasePin,
    verifyPurchasePin
};
