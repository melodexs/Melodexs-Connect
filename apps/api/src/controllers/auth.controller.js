const { pool } = require("../postgres");
const bcrypt = require("bcryptjs");
const crypto = require("crypto");
const PostgresSessionStore = require("../postgres-session-store");
const { sendBrevoEmail } = require("../utils/email");
const { isValidNigerianPhone } = require("../utils/validation");

const sessionStore = new PostgresSessionStore();

async function sessionCheck(req, res) {
    res.setHeader("Cache-Control", "no-store, no-cache, must-revalidate, proxy-revalidate");
    res.setHeader("Pragma", "no-cache");
    res.setHeader("Expires", "0");

    try {
        if (!req.session || !req.session.userId) {
            return res.json({ success: true, loggedIn: false, user: null, has_purchase_pin: false });
        }

        const user = await require("../auth").getUserById(req.session.userId);

        if (!user) {
            req.session.destroy(() => {});

            return res.json({ success: true, loggedIn: false, user: null, has_purchase_pin: false });
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
                virtual_account_number: user.virtual_account_number,
                virtual_bank_name: user.virtual_bank_name,
                kyc_status: user.kyc_status,
                is_admin: user.is_admin,
                has_purchase_pin: Boolean(user.purchase_pin),
                created_at: user.created_at
            },
            has_purchase_pin: Boolean(user.purchase_pin)
        });
    } catch (error) {
        console.error("Session check error:", error);

        return res.status(500).json({ success: false, loggedIn: false, user: null, message: "Unable to check session" });
    }
}

async function getUser(req, res) {
    try {
        const requestedUserId = Number(req.params.id);
        const sessionUserId = Number(req.session.userId);

        if (!Number.isInteger(requestedUserId) || requestedUserId <= 0) {
            return res.status(400).json({ success: false, message: "Invalid user ID" });
        }

        if (requestedUserId !== sessionUserId) {
            return res.status(403).json({ success: false, message: "Access denied" });
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

            return res.status(404).json({ success: false, message: "User not found" });
        }

        const hasPurchasePin = Boolean(user.purchase_pin);

        delete user.purchase_pin;

        return res.json({ success: true, user, has_purchase_pin: hasPurchasePin });

    } catch (error) {
        console.error("Get user error:", error);

        return res.status(500).json({ success: false, message: "Could not retrieve user" });
    }
}

// REGISTER
async function register(req, res) {
    try {
        const { name, email, phone, password } = req.body;

        if (!name || !email || !phone || !password) {
            return res.status(400).json({ success: false, message: "Please fill in all fields" });
        }

        if (!isValidNigerianPhone(phone)) {
            return res.status(400).json({ success: false, message: "Please enter a valid Nigerian phone number" });
        }

        if (password.length < 8) {
            return res.status(400).json({ success: false, message: "Password must be at least 8 characters" });
        }

        const normalizedEmail = String(email).trim().toLowerCase();
        const normalizedPhone = String(phone).trim();

        const existingResult = await pool.query(`
            SELECT id
            FROM users
            WHERE email = $1
               OR phone = $2
            LIMIT 1
        `, [normalizedEmail, normalizedPhone]);

        if (existingResult.rows.length > 0) {
            return res.status(400).json({ success: false, message: "Email or phone number already exists" });
        }

        const hashedPassword = await bcrypt.hash(password, 10);

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
        `, [name, normalizedEmail, normalizedPhone, hashedPassword]);

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
            return res.status(500).json({ success: false, message: "Account was created but could not be loaded" });
        }

        const hasPurchasePin = Boolean(user.purchase_pin);

        delete user.purchase_pin;

        req.session.regenerate((err) => {
            if (err) {
                console.error("Registration session error:", err);

                return res.status(500).json({ success: false, message: "Account created but automatic login failed" });
            }

            req.session.userId = user.id;

            return res.json({ success: true, message: "Account created successfully", user: { ...user, has_purchase_pin: hasPurchasePin } });
        });

    } catch (error) {
        console.error("Registration error:", error);

        if (error.code === "23505") {
            return res.status(400).json({ success: false, message: "Email or phone number already exists" });
        }

        return res.status(500).json({ success: false, message: "Registration failed" });
    }
}

// LOGIN
async function login(req, res) {
    try {
        const { email, password } = req.body;

        if (!email || !password) {
            return res.status(400).json({ success: false, message: "Email and password are required" });
        }

        const normalizedEmail = String(email).trim().toLowerCase();

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
            return res.status(401).json({ success: false, message: "Invalid email or password" });
        }

        const passwordMatch = await bcrypt.compare(password, user.password);

        if (!passwordMatch) {
            return res.status(401).json({ success: false, message: "Invalid email or password" });
        }

        req.session.regenerate((err) => {
            if (err) {
                console.error("Session regenerate error:", err);

                return res.status(500).json({ success: false, message: "Login failed" });
            }

            req.session.userId = user.id;

            return res.json({ success: true, message: "Login successful", user: {
                id: user.id,
                name: user.name,
                email: user.email,
                phone: user.phone,
                balance: user.balance,
                virtual_account_number: user.virtual_account_number,
                virtual_bank_name: user.virtual_bank_name,
                kyc_status: user.kyc_status,
                is_admin: user.is_admin,
                has_purchase_pin: Boolean(user.purchase_pin),
                created_at: user.created_at
            }});
        });

    } catch (error) {
        console.error("Login error:", error);

        return res.status(500).json({ success: false, message: "Login failed" });
    }
}

// LOGOUT
function logout(req, res) {
    req.session.destroy((err) => {
        if (err) {
            console.error("Logout error:", err);
            return res.status(500).json({ success: false, message: "Logout failed" });
        }

        res.clearCookie("connect.sid");
        res.json({ success: true, message: "Logged out" });
    });
}

// PURCHASE PIN: set, change, verify
async function setPurchasePin(req, res) {
    try {
        const userId = req.session.userId;
        const { pin } = req.body;

        if (pin === undefined) {
            return res.status(400).json({ success: false, message: "PIN is required" });
        }

        const pinString = String(pin);

        if (!/^\d{4}$/.test(pinString)) {
            return res.status(400).json({ success: false, message: "Purchase PIN must be exactly 4 digits" });
        }

        const userResult = await pool.query(`SELECT id, purchase_pin FROM users WHERE id = $1`, [userId]);
        const user = userResult.rows[0];

        if (!user) {
            return res.status(404).json({ success: false, message: "User not found" });
        }

        if (user.purchase_pin) {
            return res.status(400).json({ success: false, message: "Purchase PIN has already been set" });
        }

        const hashedPin = await bcrypt.hash(pinString, 10);

        await pool.query(`UPDATE users SET purchase_pin = $1 WHERE id = $2`, [hashedPin, userId]);

        res.json({ success: true, message: "Purchase PIN created successfully" });

    } catch (error) {
        console.error("Set Purchase PIN error:", error);
        res.status(500).json({ success: false, message: "Could not create Purchase PIN" });
    }
}

async function changePurchasePin(req, res) {
    try {
        const userId = req.session.userId;
        const { currentPin, newPin } = req.body;

        if (currentPin === undefined || newPin === undefined) {
            return res.status(400).json({ success: false, message: "All PIN fields are required" });
        }

        const currentPinString = String(currentPin);
        const newPinString = String(newPin);

        if (!/^\d{4}$/.test(currentPinString)) {
            return res.status(400).json({ success: false, message: "Current PIN must be exactly 4 digits" });
        }

        if (!/^\d{4}$/.test(newPinString)) {
            return res.status(400).json({ success: false, message: "New PIN must be exactly 4 digits" });
        }

        if (currentPinString === newPinString) {
            return res.status(400).json({ success: false, message: "New PIN must be different from current PIN" });
        }

        const userResult = await pool.query(`SELECT id, purchase_pin FROM users WHERE id = $1`, [userId]);
        const user = userResult.rows[0];

        if (!user) {
            return res.status(404).json({ success: false, message: "User not found" });
        }

        if (!user.purchase_pin) {
            return res.status(400).json({ success: false, message: "Purchase PIN has not been set" });
        }

        const pinCorrect = await bcrypt.compare(currentPinString, user.purchase_pin);

        if (!pinCorrect) {
            return res.status(401).json({ success: false, message: "Current Purchase PIN is incorrect" });
        }

        const hashedNewPin = await bcrypt.hash(newPinString, 10);

        await pool.query(`UPDATE users SET purchase_pin = $1 WHERE id = $2`, [hashedNewPin, userId]);

        res.json({ success: true, message: "Purchase PIN changed successfully" });

    } catch (error) {
        console.error("Change Purchase PIN error:", error);
        res.status(500).json({ success: false, message: "Could not change Purchase PIN" });
    }
}

async function verifyPurchasePin(req, res) {
    try {
        const userId = req.session.userId;
        const { pin } = req.body;

        if (pin === undefined) {
            return res.status(400).json({ success: false, message: "PIN is required" });
        }

        const pinString = String(pin);

        if (!/^\d{4}$/.test(pinString)) {
            return res.status(400).json({ success: false, message: "Purchase PIN must be exactly 4 digits" });
        }

        const userResult = await pool.query(`SELECT id, purchase_pin FROM users WHERE id = $1`, [userId]);
        const user = userResult.rows[0];

        if (!user) {
            return res.status(404).json({ success: false, message: "User not found" });
        }

        if (!user.purchase_pin) {
            return res.status(400).json({ success: false, message: "Purchase PIN has not been set" });
        }

        const pinCorrect = await bcrypt.compare(pinString, user.purchase_pin);

        if (!pinCorrect) {
            return res.status(401).json({ success: false, message: "Incorrect Purchase PIN" });
        }

        res.json({ success: true, message: "Purchase PIN verified" });

    } catch (error) {
        console.error("Verify Purchase PIN error:", error);
        res.status(500).json({ success: false, message: "Could not verify Purchase PIN" });
    }
}

// FORGOT / RESET PASSWORD
async function forgotPassword(req, res) {
    try {
        const email = String(req.body.email || "").trim().toLowerCase();

        if (!email) {
            return res.status(400).json({ success: false, message: "Please enter your email address." });
        }

        const userResult = await pool.query(`SELECT id, email FROM users WHERE LOWER(email) = $1 LIMIT 1`, [email]);
        const user = userResult.rows[0];

        if (!user) {
            return res.json({ success: true, message: "If an account exists with that email, password reset instructions will be provided." });
        }

        const resetToken = crypto.randomBytes(32).toString("hex");
        const resetTokenHash = crypto.createHash("sha256").update(resetToken).digest("hex");
        const expiresAt = Date.now() + (15 * 60 * 1000);

        await pool.query(`UPDATE users SET reset_token_hash = $1, reset_token_expires_at = $2 WHERE id = $3`, [resetTokenHash, expiresAt, user.id]);

        const resetUrl = `${process.env.CHEAPDATA_PUBLIC_URL || `${req.protocol}://${req.get("host")}`}/reset-password.html?token=${resetToken}`;

        if (process.env.NODE_ENV !== "production") {
            console.log("");
            console.log("======================================");
            console.log("PASSWORD RESET REQUEST");
            console.log("======================================");
            console.log(`Email: ${user.email}`);
            console.log(`Reset link: ${resetUrl}`);
            console.log("Expires in: 15 minutes");
            console.log("======================================");
            console.log("");
        } else {
            try {
                await sendBrevoEmail({ to: user.email, subject: "MELODEXS CONNECT Password Reset", htmlContent: `
                    <div style="font-family: Arial, sans-serif; line-height: 1.6;">
                        <h2>Reset your MELODEXS CONNECT password</h2>

                        <p>We received a request to reset your MELODEXS CONNECT password.</p>

                        <p>
                            Click the button below to choose a new password:
                        </p>

                        <p>
                            <a
                                href="${resetUrl}"
                                style="
                                    display:inline-block;
                                    padding:12px 20px;
                                    background:#0251B0;
                                    color:#ffffff;
                                    text-decoration:none;
                                    border-radius:6px;
                                "
                            >
                                Reset Password
                            </a>
                        </p>

                        <p>
                            This link will expire in <strong>15 minutes</strong>.
                        </p>

                        <p>
                            If you did not request a password reset, you can safely
                            ignore this email.
                        </p>

                        <p>— MELODEXS CONNECT</p>
                    </div>
                `});
            } catch (emailError) {
                console.error("Password reset email failed:", emailError.message);

                await pool.query(`UPDATE users SET reset_token_hash = NULL, reset_token_expires_at = NULL WHERE id = $1`, [user.id]);

                throw new Error("Password reset email could not be sent.");
            }
        }

        return res.json({ success: true, message: "If an account exists with that email, password reset instructions will be provided." });

    } catch (error) {
        console.error("Forgot password error:", error);
        return res.status(500).json({ success: false, message: "Something went wrong. Please try again." });
    }
}

async function resetPassword(req, res) {
    try {
        const { token, newPassword } = req.body;

        if (!token || !newPassword) {
            return res.status(400).json({ success: false, message: "Reset token and new password are required." });
        }

        if (newPassword.length < 8) {
            return res.status(400).json({ success: false, message: "Password must be at least 8 characters." });
        }

        const tokenHash = crypto.createHash("sha256").update(token).digest("hex");

        const userResult = await pool.query(`SELECT id, reset_token_hash, reset_token_expires_at FROM users WHERE reset_token_hash = $1 LIMIT 1`, [tokenHash]);
        const user = userResult.rows[0];

        if (!user) {
            return res.status(400).json({ success: false, message: "This password reset link is invalid or has already been used." });
        }

        if (!user.reset_token_expires_at || Date.now() > Number(user.reset_token_expires_at)) {
            return res.status(400).json({ success: false, message: "This password reset link has expired. Please request a new one." });
        }

        const hashedPassword = await bcrypt.hash(newPassword, 10);

        await pool.query(`UPDATE users SET password = $1, reset_token_hash = NULL, reset_token_expires_at = NULL WHERE id = $2`, [hashedPassword, user.id]);

        await new Promise((resolve, reject) => {
            sessionStore.destroyUserSessions(user.id, (error) => {
                if (error) return reject(error);
                resolve();
            });
        });

        return res.json({ success: true, message: "Password reset successfully. You can now log in." });

    } catch (error) {
        console.error("Reset password error:", error);
        return res.status(500).json({ success: false, message: "Something went wrong. Please try again." });
    }
}

module.exports = {
    sessionCheck,
    getUser,
    register,
    login,
    logout,
    setPurchasePin,
    changePurchasePin,
    verifyPurchasePin,
    forgotPassword,
    resetPassword
};
