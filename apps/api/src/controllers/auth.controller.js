const bcrypt = require("bcryptjs");
const { pool } = require("../postgres");
const { getUserById } = require("../auth");

function isValidNigerianPhone(phone) {
    return /^0[7-9][0-1][0-9]{8}$/.test(phone);
}

async function getSession(req, res) {
    // Authentication/session responses must never be cached.
    res.setHeader(
        "Cache-Control",
        "no-store, no-cache, must-revalidate, proxy-revalidate"
    );
    res.setHeader("Pragma", "no-cache");
    res.setHeader("Expires", "0");

    try {
        if (!req.session || !req.session.userId) {
            return res.json({
                success: true,
                loggedIn: false,
                user: null,
                has_purchase_pin: false
            });
        }

        const user = await getUserById(req.session.userId);

        if (!user) {
            req.session.destroy(() => {});

            return res.json({
                success: true,
                loggedIn: false,
                user: null,
                has_purchase_pin: false
            });
        }

        return res.json({
            success: true,
            loggedIn: true,
            user: {
                id: user.id,
                name: user.name,
                email: user.email,
                phone: user.phone,
                balance: user.balance,
                virtual_account_number:
                    user.virtual_account_number,
                virtual_bank_name:
                    user.virtual_bank_name,
                kyc_status:
                    user.kyc_status,
                is_admin:
                    user.is_admin,
                has_purchase_pin:
                    Boolean(user.purchase_pin),
                created_at:
                    user.created_at
            },
            has_purchase_pin:
                Boolean(user.purchase_pin)
        });
    } catch (error) {
        console.error("Session check error:", error);

        return res.status(500).json({
            success: false,
            loggedIn: false,
            user: null,
            message: "Unable to check session"
        });
    }
}

async function register(req, res) {
    try {
        const {
            name,
            email,
            phone,
            password
        } = req.body;

        if (!name || !email || !phone || !password) {
            return res.status(400).json({
                success: false,
                message: "Please fill in all fields"
            });
        }

        if (!isValidNigerianPhone(phone)) {
            return res.status(400).json({
                success: false,
                message: "Please enter a valid Nigerian phone number"
            });
        }

        if (password.length < 8) {
            return res.status(400).json({
                success: false,
                message: "Password must be at least 8 characters"
            });
        }

        const normalizedEmail = String(email)
            .trim()
            .toLowerCase();

        const normalizedPhone = String(phone).trim();

        const existingResult = await pool.query(`
            SELECT id
            FROM users
            WHERE email = $1
               OR phone = $2
            LIMIT 1
        `, [
            normalizedEmail,
            normalizedPhone
        ]);

        if (existingResult.rows.length > 0) {
            return res.status(400).json({
                success: false,
                message: "Email or phone number already exists"
            });
        }

        const hashedPassword = await bcrypt.hash(
            password,
            10
        );

        const insertResult = await pool.query(`
            INSERT INTO users (
                name,
                email,
                phone,
                password,
                purchase_pin,
                balance,
                kyc_status,
                is_admin
            )
            VALUES (
                $1,
                $2,
                $3,
                $4,
                NULL,
                0,
                'pending',
                0
            )
            RETURNING id
        `, [
            name,
            normalizedEmail,
            normalizedPhone,
            hashedPassword
        ]);

        const newUserId = insertResult.rows[0].id;

        const userResult = await pool.query(`
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
        `, [newUserId]);

        const user = userResult.rows[0];

        if (!user) {
            return res.status(500).json({
                success: false,
                message: "Account was created but could not be loaded"
            });
        }

        const hasPurchasePin = Boolean(user.purchase_pin);

        delete user.purchase_pin;

        req.session.regenerate((err) => {
            if (err) {
                console.error(
                    "Registration session error:",
                    err
                );

                return res.status(500).json({
                    success: false,
                    message:
                        "Account created but automatic login failed"
                });
            }

            req.session.userId = user.id;

            return res.json({
                success: true,
                message: "Account created successfully",
                user: {
                    ...user,
                    has_purchase_pin: hasPurchasePin
                }
            });
        });
    } catch (error) {
        console.error("Registration error:", error);

        if (error.code === "23505") {
            return res.status(400).json({
                success: false,
                message: "Email or phone number already exists"
            });
        }

        return res.status(500).json({
            success: false,
            message: "Registration failed"
        });
    }
}

async function login(req, res) {
    try {
        const {
            email,
            password
        } = req.body;

        if (!email || !password) {
            return res.status(400).json({
                success: false,
                message: "Email and password are required"
            });
        }

        const normalizedEmail = String(email)
            .trim()
            .toLowerCase();

        const result = await pool.query(`
            SELECT
                id,
                name,
                email,
                phone,
                password,
                balance,
                virtual_account_number,
                virtual_bank_name,
                kyc_status,
                is_admin,
                purchase_pin,
                created_at
            FROM users
            WHERE LOWER(email) = $1
            LIMIT 1
        `, [normalizedEmail]);

        const user = result.rows[0];

        if (!user) {
            return res.status(401).json({
                success: false,
                message: "Invalid email or password"
            });
        }

        const passwordMatch = await bcrypt.compare(
            password,
            user.password
        );

        if (!passwordMatch) {
            return res.status(401).json({
                success: false,
                message: "Invalid email or password"
            });
        }

        req.session.regenerate((err) => {
            if (err) {
                console.error(
                    "Session regenerate error:",
                    err
                );

                return res.status(500).json({
                    success: false,
                    message: "Login failed"
                });
            }

            req.session.userId = user.id;

            return res.json({
                success: true,
                message: "Login successful",
                user: {
                    id: user.id,
                    name: user.name,
                    email: user.email,
                    phone: user.phone,
                    balance: user.balance,
                    virtual_account_number:
                        user.virtual_account_number,
                    virtual_bank_name:
                        user.virtual_bank_name,
                    kyc_status:
                        user.kyc_status,
                    is_admin:
                        user.is_admin,
                    has_purchase_pin:
                        Boolean(user.purchase_pin),
                    created_at:
                        user.created_at
                }
            });
        });
    } catch (error) {
        console.error("Login error:", error);

        return res.status(500).json({
            success: false,
            message: "Login failed"
        });
    }
}

module.exports = {
    getSession,
    register,
    login
};
