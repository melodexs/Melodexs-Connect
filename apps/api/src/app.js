const express = require("express");
const helmet = require("helmet");
const { rateLimit } = require("express-rate-limit");
const axios = require("axios");
const session = require("express-session");
const PostgresSessionStore = require("./postgres-session-store");
const crypto = require("crypto");
const bcrypt = require("bcryptjs");
const { WEB_PUBLIC_DIR } = require("./config");
const { pool } = require("./postgres");
const { requireAuth, requireAdmin, getAdmin } = require("./auth");

// =========================
// BREVO EMAIL
// =========================

async function sendBrevoEmail({ to, subject, htmlContent }) {
    if (
        !process.env.BREVO_API_KEY ||
        !process.env.BREVO_FROM_EMAIL
    ) {
        throw new Error("Brevo email configuration is missing.");
    }

    const response = await axios.post(
        "https://api.brevo.com/v3/smtp/email",
        {
            sender: {
                name: process.env.BREVO_FROM_NAME || "MELODEXS CONNECT",
                email: process.env.BREVO_FROM_EMAIL
            },
            to: [
                {
                    email: to
                }
            ],
            subject,
            htmlContent
        },
        {
            headers: {
                "api-key": process.env.BREVO_API_KEY,
                "Content-Type": "application/json",
                Accept: "application/json"
            },
            timeout: 10000
        }
    );

    return response.data;
}

const app = express();

// =========================
// PRODUCTION SECURITY CHECKS
// =========================

const sessionSecret = process.env.SESSION_SECRET;

if (process.env.NODE_ENV === "production") {
    if (!sessionSecret) {
        console.error(
            "SESSION_SECRET is required when NODE_ENV=production."
        );
        process.exit(1);
    }

    if (sessionSecret.length < 32) {
        console.error(
            "SESSION_SECRET must be at least 32 characters in production."
        );
        process.exit(1);
    }
} else if (!sessionSecret) {
    console.warn(
        "SESSION_SECRET is not set. Using an insecure development-only fallback."
    );
}

// =========================
// MIDDLEWARE
// =========================

app.set("trust proxy", 1);
// =========================
// RATE LIMITING
// =========================

const loginLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  limit: 10,
  standardHeaders: "draft-8",
  legacyHeaders: false,
  message: {
    success: false,
    message: "Too many login attempts. Please try again later."
  }
});

const registerLimiter = rateLimit({
  windowMs: 60 * 60 * 1000,
  limit: 10,
  standardHeaders: "draft-8",
  legacyHeaders: false,
  message: {
    success: false,
    message: "Too many registration attempts. Please try again later."
  }
});

const forgotPasswordLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  limit: 5,
  standardHeaders: "draft-8",
  legacyHeaders: false,
  message: {
    success: false,
    message: "Too many password reset requests. Please try again later."
  }
});

const resetPasswordLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  limit: 10,
  standardHeaders: "draft-8",
  legacyHeaders: false,
  message: {
    success: false,
    message: "Too many password reset attempts. Please try again later."
  }
});
// Security headers.
// CSP is intentionally not enabled yet because the frontend currently
// uses inline <script> and <style> blocks.
app.use(helmet({
  contentSecurityPolicy: false
}));



// =========================
// PAYSTACK WEBHOOK
// =========================
// Must be registered BEFORE express.json()
// so we can verify Paystack's original request body.

app.post(
    "/api/paystack/webhook",
    express.raw({ type: "application/json" }),
    async (req, res) => {
        try {
            const signature = req.headers["x-paystack-signature"];

            if (!signature) {
                return res.status(401).send("Missing signature");
            }

            if (!process.env.PAYSTACK_SECRET_KEY) {
                console.error("PAYSTACK_SECRET_KEY is missing.");
                return res.status(500).send("Webhook not configured");
            }

            const expectedSignature = crypto
                .createHmac(
                    "sha512",
                    process.env.PAYSTACK_SECRET_KEY
                )
                .update(req.body)
                .digest("hex");

            const receivedBuffer =
                Buffer.from(String(signature), "utf8");

            const expectedBuffer =
                Buffer.from(expectedSignature, "utf8");

            if (
                receivedBuffer.length !== expectedBuffer.length ||
                !crypto.timingSafeEqual(
                    receivedBuffer,
                    expectedBuffer
                )
            ) {
                console.error("Invalid Paystack webhook signature.");
                return res.status(401).send("Invalid signature");
            }

            const event = JSON.parse(
                req.body.toString("utf8")
            );

            console.log(
                "Paystack webhook received:",
                event.event
            );

            if (event.event !== "charge.success") {
                return res.status(200).send("Event received");
            }

            const payment = event.data;

            if (!payment) {
                return res.status(400).send("Invalid payment data");
            }

            const reference =
                String(payment.reference || "").trim();

            if (!reference) {
                return res.status(400).send(
                    "Missing payment reference"
                );
            }

            const transactionResult = await pool.query(`
                SELECT
                    id,
                    user_id,
                    amount,
                    status,
                    reference
                FROM transactions
                WHERE reference = $1
                  AND type = 'wallet_funding'
                LIMIT 1
            `, [reference]);

            const transaction = transactionResult.rows[0];

            if (!transaction) {
                console.warn(
                    "Paystack webhook transaction not found:",
                    reference
                );

                return res.status(200).send(
                    "Transaction not found"
                );
            }

            const expectedAmount =
                Math.round(Number(transaction.amount) * 100);

            const paidAmount =
                Number(payment.amount);

            const currency =
                String(payment.currency || "").toUpperCase();

            const metadataUserId =
                String(
                    payment.metadata &&
                    payment.metadata.user_id ||
                    ""
                );

            if (
                payment.status !== "success" ||
                currency !== "NGN" ||
                paidAmount !== expectedAmount ||
                metadataUserId !== String(transaction.user_id) ||
                String(payment.reference) !== reference
            ) {
                console.error(
                    "Paystack webhook payment validation failed:",
                    {
                        reference,
                        paymentStatus: payment.status,
                        currency,
                        paidAmount,
                        expectedAmount,
                        metadataUserId,
                        transactionUserId: transaction.user_id
                    }
                );

                return res.status(400).send(
                    "Payment validation failed"
                );
            }

            const client = await pool.connect();

            let credited = false;

            try {
                await client.query("BEGIN");

                const currentResult = await client.query(`
                    SELECT
                        id,
                        status,
                        user_id,
                        amount
                    FROM transactions
                    WHERE id = $1
                    FOR UPDATE
                `, [transaction.id]);

                const current = currentResult.rows[0];

                if (
                    !current ||
                    current.status === "successful"
                ) {
                    await client.query("ROLLBACK");

                    console.log(
                        "Paystack webhook: payment was already processed."
                    );

                    return res.status(200).send(
                        "Already processed"
                    );
                }

                const walletResult = await client.query(`
                    UPDATE users
                    SET balance = balance + $1
                    WHERE id = $2
                    RETURNING id, balance
                `, [
                    current.amount,
                    current.user_id
                ]);

                if (walletResult.rowCount !== 1) {
                    throw new Error(
                        "User wallet could not be updated."
                    );
                }

                await client.query(`
                    UPDATE transactions
                    SET
                        status = 'successful',
                        description = $1
                    WHERE id = $2
                `, [
                    "Paystack webhook wallet funding",
                    current.id
                ]);

                await client.query("COMMIT");

                credited = true;

            } catch (error) {
                try {
                    await client.query("ROLLBACK");
                } catch (rollbackError) {
                    console.error(
                        "Paystack webhook rollback error:",
                        rollbackError
                    );
                }

                throw error;

            } finally {
                client.release();
            }

            console.log(
                credited
                    ? `Paystack webhook: ₦${transaction.amount} credited successfully.`
                    : "Paystack webhook: payment was already processed."
            );

            return res.status(200).send(
                "Webhook processed"
            );

        } catch (error) {
            console.error(
                "Paystack webhook error:",
                error
            );

            return res.status(500).send(
                "Webhook processing failed"
            );
        }
    }
);

// =========================
// PAYSTACK WEBHOOK
// =========================
// IMPORTANT:
// This must come BEFORE express.json() because Paystack's
app.use(express.json({ limit: "50kb" }));

app.use(express.urlencoded({
    extended: true,
    limit: "50kb"
}));
// =========================
// SESSION
// =========================

const sessionStore = new PostgresSessionStore();

app.use(
    session({
        store: sessionStore,

        secret:
            sessionSecret ||
            "dev-only-insecure-secret",

        resave: false,

        saveUninitialized: false,

        cookie: {
            httpOnly: true,
            sameSite: "lax",
            secure:
                process.env.NODE_ENV === "production",
            maxAge:
                1000 * 60 * 60 * 24
        }
    })
);

// =========================
// CSRF / ORIGIN PROTECTION
// =========================

app.use((req, res, next) => {
    const stateChangingMethods = [
        "POST",
        "PUT",
        "PATCH",
        "DELETE"
    ];

    if (
        !req.path.startsWith("/api/") ||
        !stateChangingMethods.includes(req.method)
    ) {
        return next();
    }

    // Paystack webhook is handled before this middleware.
    if (req.path === "/api/paystack/webhook") {
        return next();
    }

    const origin = req.get("Origin");

    // If the browser provides an Origin header,
    // it must match an allowed MELODEXS CONNECT origin.
    if (origin) {
        const configuredPublicUrl =
            process.env.CHEAPDATA_PUBLIC_URL;

        const configuredOrigin = configuredPublicUrl
            ? new URL(configuredPublicUrl).origin
            : null;

        const requestOrigin =
            `${req.protocol}://${req.get("host")}`;

        // Development may use localhost or the configured
        // Codespaces/public origin.
        // Production requires the configured public origin.
        const allowedOrigins =
            process.env.NODE_ENV === "production"
                ? new Set(
                    configuredOrigin
                        ? [configuredOrigin]
                        : [requestOrigin]
                )
                : new Set(
                    [
                        requestOrigin,
                        configuredOrigin
                    ].filter(Boolean)
                );

        if (!allowedOrigins.has(origin)) {
            console.warn(
                `Blocked cross-origin ${req.method} request to ${req.path} from ${origin}`
            );

            return res.status(403).json({
                success: false,
                message: "Cross-origin request blocked."
            });
        }
    }

    next();
});

app.use(express.static(WEB_PUBLIC_DIR));
// =========================
// SESSION CHECK
// =========================
app.get("/api/session", async (req, res) => {
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
});

// =========================
// HELPER FUNCTIONS
// =========================

function generateReference(prefix) {
    return `${prefix}-${Date.now()}-${Math.floor(
        Math.random() * 10000
    )}`;
}

function isValidNigerianPhone(phone) {
    return /^0[7-9][0-1][0-9]{8}$/.test(phone);
}

// =========================
// API STATUS
// =========================

app.get("/api/status", (req, res) => {
    res.json({
        success: true,
        message: "MELODEXS CONNECT API is running"
    });
});

// =========================
// REGISTER
// =========================

app.post("/api/register", registerLimiter, async (req, res) => {
    try {
        const {
            name,
            email,
            phone,
            password
        } = req.body;

        // =========================
        // VALIDATION
        // =========================

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

        const normalizedPhone = String(phone)
            .trim();

        // =========================
        // CHECK EXISTING USER
        // =========================

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

        // =========================
        // HASH PASSWORD
        // =========================

        const hashedPassword = await bcrypt.hash(
            password,
            10
        );

        // =========================
        // CREATE USER
        // =========================

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

        // =========================
        // GET NEW USER
        // =========================

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

        const hasPurchasePin = Boolean(
            user.purchase_pin
        );

        delete user.purchase_pin;

        // =========================
        // CREATE LOGIN SESSION
        // =========================

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
        console.error(
            "Registration error:",
            error
        );

        // PostgreSQL unique constraints can also catch
        // simultaneous duplicate registrations.
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
});

// =========================
// LOGIN
// =========================

app.post("/api/login", loginLimiter, async (req, res) => {
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
        console.error(
            "Login error:",
            error
        );

        return res.status(500).json({
            success: false,
            message: "Login failed"
        });
    }
});

// =========================
// PURCHASE PIN
// =========================


// =========================

// SET PURCHASE PIN

app.post("/api/purchase-pin/set", requireAuth, async (req, res) => {
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
});

// CHANGE PURCHASE PIN

app.post("/api/purchase-pin/change", requireAuth, async (req, res) => {
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
});

// VERIFY PURCHASE PIN

app.post("/api/purchase-pin/verify", requireAuth, async (req, res) => {
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
});

// =========================
// PURCHASE DATA
// =========================

app.post("/api/purchase-data", requireAuth, async (req, res) => {
    try {
        const userId = req.session.userId;

        const {
            network,
            phone,
            plan,
            pin
        } = req.body;

        // =========================
        // BASIC VALIDATION
        // =========================

        if (
            !network ||
            !phone ||
            !plan ||
            pin === undefined
        ) {
            return res.status(400).json({
                success: false,
                message:
                    "Please provide all purchase details including your Purchase PIN"
            });
        }

        const pinString = String(pin);

        if (!/^\d{4}$/.test(pinString)) {
            return res.status(400).json({
                success: false,
                message: "Purchase PIN must be exactly 4 digits"
            });
        }

        if (!isValidNigerianPhone(phone)) {
            return res.status(400).json({
                success: false,
                message: "Please enter a valid Nigerian phone number"
            });
        }

        const allowedNetworks = [
            "MTN",
            "Airtel",
            "Glo",
            "9mobile"
        ];

        if (!allowedNetworks.includes(network)) {
            return res.status(400).json({
                success: false,
                message: "Invalid network"
            });
        }

        // =========================
        // FIND WISESUB PLAN
        // =========================

        const selectedPlanResult = await pool.query(`
            SELECT
                id,
                network,
                plan,
                provider_cost,
                selling_price,
                active,
                provider,
                provider_code,
                provider_package_code,
                provider_package_name,
                source
            FROM data_plans
            WHERE network = $1
              AND plan = $2
              AND active = 1
              AND source = 'wisesub'
            LIMIT 1
        `, [
            network,
            plan
        ]);

        const selectedPlan =
            selectedPlanResult.rows[0];

        if (!selectedPlan) {
            return res.status(400).json({
                success: false,
                message:
                    "That data plan is not currently available"
            });
        }

        // =========================
        // VERIFY PROVIDER DETAILS
        // =========================

        if (
            !selectedPlan.provider_package_code ||
            !selectedPlan.provider_code
        ) {
            console.error(
                "Missing WiseSub package information:",
                selectedPlan
            );

            return res.status(500).json({
                success: false,
                message:
                    "This data plan is not properly configured. Please try another plan."
            });
        }

        const sellingPrice =
            Number(selectedPlan.selling_price);

        if (
            !Number.isFinite(sellingPrice) ||
            sellingPrice <= 0
        ) {
            return res.status(500).json({
                success: false,
                message: "Invalid data plan price"
            });
        }

        // =========================
        // GET USER
        // =========================

        const userResult = await pool.query(`
            SELECT
                id,
                balance,
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

        // =========================
        // VERIFY PURCHASE PIN
        // =========================

        if (!user.purchase_pin) {
            return res.status(400).json({
                success: false,
                message:
                    "Please create a Purchase PIN before buying data"
            });
        }

        const pinCorrect =
            await bcrypt.compare(
                pinString,
                user.purchase_pin
            );

        if (!pinCorrect) {
            return res.status(401).json({
                success: false,
                message: "Incorrect Purchase PIN"
            });
        }

        // =========================
        // WISESUB CONFIG
        // =========================

        const baseUrl =
            process.env.WISESUB_BASE_URL;

        const apiKey =
            process.env.WISESUB_API_KEY;

        const apiSecret =
            process.env.WISESUB_API_SECRET;

        const environment =
            process.env.WISESUB_ENVIRONMENT || "test";

        if (!baseUrl || !apiKey || !apiSecret) {
            console.error(
                "WiseSub configuration is incomplete."
            );

            return res.status(500).json({
                success: false,
                message:
                    "Data service is temporarily unavailable"
            });
        }

        // =========================
        // GENERATE LOCAL REFERENCE
        // =========================

        const localReference =
            generateReference("DATA");

        // =========================
        // RESERVE WALLET + CREATE
        // PENDING TRANSACTION
        // =========================
        //
        // IMPORTANT:
        // The wallet is deducted BEFORE calling WiseSub.
        //
        // This prevents two simultaneous requests from
        // spending the same wallet balance.
        //
        // The transaction remains "pending" until WiseSub
        // confirms success or a confirmed provider failure
        // allows us to refund it.
        //

        try {
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
                    sellingPrice,
                    userId
                ]);

                if (debitResult.rowCount !== 1) {
                    throw new Error(
                        "INSUFFICIENT_BALANCE"
                    );
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
                    sellingPrice,
                    "pending",
                    localReference,
                    `${network} ${plan} data purchase for ${phone} | Pending WiseSub confirmation`
                ]);

                await client.query("COMMIT");

            } catch (transactionError) {

                try {
                    await client.query("ROLLBACK");
                } catch (rollbackError) {
                    console.error(
                        "Data purchase reservation rollback error:",
                        rollbackError
                    );
                }

                throw transactionError;

            } finally {
                client.release();
            }

        } catch (reserveError) {

            if (
                reserveError.message ===
                "INSUFFICIENT_BALANCE"
            ) {
                return res.status(400).json({
                    success: false,
                    message: "Insufficient wallet balance"
                });
            }

            console.error(
                "Could not reserve wallet for data purchase:",
                reserveError
            );

            return res.status(500).json({
                success: false,
                message:
                    "Could not start the data purchase. Please try again."
            });
        }

        // =========================
        // CALL WISESUB
        // =========================

        const providerRecipient =
            environment === "test"
                ? "08011111111"
                : phone;

        let wiseSubResponse;

        try {

            wiseSubResponse =
                await axios.post(
                    `${baseUrl}/purchase`,
                    {
                        service_type: "data",

                        provider_code:
                            selectedPlan.provider_code,

                        package_code:
                            selectedPlan.provider_package_code,

                        recipient:
                            providerRecipient
                    },
                    {
                        headers: {
                            Authorization:
                                `Bearer ${apiKey}`,

                            "X-API-Secret":
                                apiSecret,

                            "X-Environment":
                                environment,

                            Accept:
                                "application/json",

                            "Content-Type":
                                "application/json"
                        },

                        timeout: 30000
                    }
                );

        } catch (providerError) {

            console.error(
                "WiseSub data purchase request failed."
            );

            if (providerError.response) {

                console.error(
                    "WiseSub status:",
                    providerError.response.status
                );

                console.error(
                    "WiseSub response:",
                    JSON.stringify(
                        providerError.response.data,
                        null,
                        2
                    )
                );

                // =========================
                // CONFIRMED CLIENT-SIDE
                // PROVIDER FAILURE
                // =========================
                //
                // A 4xx response means WiseSub rejected
                // the request before completing it.
                //
                // Safe to refund the reserved amount.
                //

                if (
                    providerError.response.status >= 400 &&
                    providerError.response.status < 500
                ) {

                    try {

                        const client = await pool.connect();

                        try {
                            await client.query("BEGIN");

                            const refundResult = await client.query(`
                                UPDATE users
                                SET balance = balance + $1
                                WHERE id = $2
                                RETURNING id, balance
                            `, [
                                sellingPrice,
                                userId
                            ]);

                            if (refundResult.rowCount !== 1) {
                                throw new Error(
                                    "Wallet refund failed"
                                );
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
                                `${network} ${plan} data purchase for ${phone} | WiseSub rejected the purchase`,
                                localReference,
                                userId
                            ]);

                            if (updateResult.rowCount !== 1) {
                                throw new Error(
                                    "Transaction status update failed"
                                );
                            }

                            await client.query("COMMIT");

                        } catch (transactionError) {

                            try {
                                await client.query("ROLLBACK");
                            } catch (rollbackError) {
                                console.error(
                                    "Data purchase refund rollback error:",
                                    rollbackError
                                );
                            }

                            throw transactionError;

                        } finally {
                            client.release();
                        }

                    } catch (refundError) {

                        console.error(
                            "CRITICAL: WiseSub rejected data purchase but wallet refund failed.",
                            refundError
                        );

                        return res.status(500).json({
                            success: false,
                            message:
                                "The data provider rejected the purchase, but we could not complete the wallet refund automatically. Please contact support.",
                            reference:
                                localReference
                        });
                    }

                    return res.status(502).json({
                        success: false,
                        message:
                            "Data purchase was rejected by the provider. Your wallet has been refunded.",
                        reference:
                            localReference
                    });
                }

                // =========================
                // 5xx = AMBIGUOUS
                // =========================
                //
                // DO NOT refund automatically.
                //
                // WiseSub may have processed the purchase even
                // though MELODEXS CONNECT received a server error.
                //

                return res.status(202).json({
                    success: false,
                    pending: true,
                    message:
                        "Your data purchase is being verified with the provider. Please do not retry this purchase.",
                    reference:
                        localReference
                });
            }

            // =========================
            // NETWORK / TIMEOUT ERROR
            // =========================
            //
            // We cannot know whether WiseSub processed the
            // purchase. Therefore the wallet remains reserved
            // and the transaction remains pending.
            //

            console.error(
                "WiseSub data request error:",
                providerError.message
            );

            return res.status(202).json({
                success: false,
                pending: true,
                message:
                    "We could not immediately confirm your data purchase. Please do not retry this purchase.",
                reference:
                    localReference
            });
        }

        // =========================
        // CHECK WISESUB RESULT
        // =========================

        const providerData =
            wiseSubResponse.data;

        if (
            !providerData ||
            providerData.success !== true
        ) {

            console.error(
                "WiseSub returned an unsuccessful data response:",
                JSON.stringify(
                    providerData,
                    null,
                    2
                )
            );

            // WiseSub explicitly returned a normal API response
            // saying the purchase was unsuccessful.
            //
            // Refund the wallet because this is not an ambiguous
            // network/server failure.

            try {

                const client = await pool.connect();

                try {
                    await client.query("BEGIN");

                    const refundResult = await client.query(`
                        UPDATE users
                        SET balance = balance + $1
                        WHERE id = $2
                        RETURNING id, balance
                    `, [
                        sellingPrice,
                        userId
                    ]);

                    if (refundResult.rowCount !== 1) {
                        throw new Error(
                            "Wallet refund failed"
                        );
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
                        `${network} ${plan} data purchase for ${phone} | WiseSub did not complete the purchase`,
                        localReference,
                        userId
                    ]);

                    if (updateResult.rowCount !== 1) {
                        throw new Error(
                            "Transaction status update failed"
                        );
                    }

                    await client.query("COMMIT");

                } catch (transactionError) {

                    try {
                        await client.query("ROLLBACK");
                    } catch (rollbackError) {
                        console.error(
                            "Data purchase refund rollback error:",
                            rollbackError
                        );
                    }

                    throw transactionError;

                } finally {
                    client.release();
                }

            } catch (refundError) {

                console.error(
                    "CRITICAL: WiseSub data purchase failed but wallet refund failed.",
                    refundError
                );

                return res.status(500).json({
                    success: false,
                    message:
                        "The data purchase failed, but we could not complete the wallet refund automatically. Please contact support.",
                    reference:
                        localReference
                });
            }

            return res.status(502).json({
                success: false,
                message:
                    "Data purchase was not completed. Your wallet has been refunded.",
                reference:
                    localReference
            });
        }

        // =========================
        // GET WISESUB REFERENCE
        // =========================

        const wiseSubReference =
            providerData.data?.reference || null;

        // =========================
        // SUCCESS MUST HAVE
        // PROVIDER REFERENCE
        // =========================
        //
        // The reference is required for future reconciliation.
        //

        if (!wiseSubReference) {

            console.error(
                "CRITICAL: WiseSub reported success but returned no reference.",
                JSON.stringify(
                    providerData,
                    null,
                    2
                )
            );

            return res.status(202).json({
                success: false,
                pending: true,
                message:
                    "Your data purchase was accepted by the provider but could not yet be fully confirmed. Please do not retry this purchase.",
                reference:
                    localReference
            });
        }

        // =========================
        // MARK TRANSACTION SUCCESSFUL
        // =========================

        try {
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
            `${network} ${plan} data purchase for ${phone} | WiseSub reference: ${wiseSubReference}`,
            localReference,
            userId
        ]);

        if (updateResult.rowCount !== 1) {
            throw new Error(
                "Pending transaction could not be completed"
            );
        }

        await client.query("COMMIT");

    } catch (transactionError) {
        try {
            await client.query("ROLLBACK");
        } catch (rollbackError) {
            console.error(
                "Data purchase completion rollback error:",
                rollbackError
            );
        }

        throw transactionError;

    } finally {
        client.release();
    }

} catch (completionError) {

            console.error(
                "CRITICAL: WiseSub data purchase succeeded but MELODEXS CONNECT could not mark the transaction successful.",
                completionError
            );

            return res.status(500).json({
                success: false,
                message:
                    "Your data purchase was processed by the provider, but we could not complete the transaction record automatically. Please contact support before trying again.",
                reference:
                    localReference,
                providerReference:
                    wiseSubReference
            });
        }

        // =========================
        // GET UPDATED BALANCE
        // =========================

const updatedUserResult = await pool.query(`
    SELECT balance
    FROM users
    WHERE id = $1
`, [userId]);

const updatedUser = updatedUserResult.rows[0];

        // =========================
        // SUCCESS
        // =========================

        return res.json({
            success: true,
            message: "Data purchase successful",

            network,
            plan,
            phone,

            amount:
                sellingPrice,

            balance:
                updatedUser.balance,

            reference:
                localReference,

            providerReference:
                wiseSubReference
        });

    } catch (error) {

        console.error(
            "Data purchase error:",
            error
        );

        return res.status(500).json({
            success: false,
            message:
                "Data purchase failed"
        });
    }
});


// =========================
// PURCHASE AIRTIME
// =========================

app.post("/api/purchase-airtime", requireAuth, async (req, res) => {
    try {
        const userId = req.session.userId;

        const {
            network,
            phone,
            amount,
            pin
        } = req.body;

        const airtimeAmount =
            Number(amount);

        // =========================
        // VALIDATION
        // =========================

        if (
            !network ||
            !phone ||
            amount === undefined ||
            pin === undefined
        ) {
            return res.status(400).json({
                success: false,
                message:
                    "Please provide all purchase details including your Purchase PIN"
            });
        }

        const pinString =
            String(pin);

        if (!/^\d{4}$/.test(pinString)) {
            return res.status(400).json({
                success: false,
                message:
                    "Purchase PIN must be exactly 4 digits"
            });
        }

        const allowedNetworks = [
            "MTN",
            "Airtel",
            "Glo",
            "9mobile"
        ];

        if (!allowedNetworks.includes(network)) {
            return res.status(400).json({
                success: false,
                message:
                    "Invalid network"
            });
        }

        if (!isValidNigerianPhone(phone)) {
            return res.status(400).json({
                success: false,
                message:
                    "Please enter a valid Nigerian phone number"
            });
        }

        if (
            !Number.isFinite(airtimeAmount) ||
            !Number.isInteger(airtimeAmount) ||
            airtimeAmount < 50 ||
            airtimeAmount > 50000
        ) {
            return res.status(400).json({
                success: false,
                message:
                    "Airtime amount must be between ₦50 and ₦50,000"
            });
        }

        // =========================
        // GET USER
        // =========================

const userResult = await pool.query(`
    SELECT id, balance, purchase_pin
    FROM users
    WHERE id = $1
`, [userId]);

const user = userResult.rows[0];

        if (!user) {
            return res.status(404).json({
                success: false,
                message:
                    "User not found"
            });
        }

        if (!user.purchase_pin) {
            return res.status(400).json({
                success: false,
                message:
                    "Please create a Purchase PIN before buying airtime"
            });
        }

        // =========================
        // VERIFY PURCHASE PIN
        // =========================

        const pinCorrect =
            await bcrypt.compare(
                pinString,
                user.purchase_pin
            );

        if (!pinCorrect) {
            return res.status(401).json({
                success: false,
                message:
                    "Incorrect Purchase PIN"
            });
        }

        // =========================
        // WISESUB CONFIGURATION
        // =========================

        const baseUrl =
            process.env.WISESUB_BASE_URL;

        const apiKey =
            process.env.WISESUB_API_KEY;

        const apiSecret =
            process.env.WISESUB_API_SECRET;

        const environment =
            process.env.WISESUB_ENVIRONMENT || "test";

        if (!baseUrl || !apiKey || !apiSecret) {
            console.error(
                "WiseSub configuration is incomplete."
            );

            return res.status(500).json({
                success: false,
                message:
                    "Airtime service is temporarily unavailable"
            });
        }

        // =========================
        // NETWORK → WISESUB PROVIDER
        // =========================

        const providerCodes = {
            MTN: "mtn",
            Airtel: "airtel",
            Glo: "glo",
            "9mobile": "9mobile"
        };

        const providerCode =
            providerCodes[network];

        if (!providerCode) {
            return res.status(400).json({
                success: false,
                message:
                    "Could not determine the airtime provider"
            });
        }

        // =========================
        // GENERATE LOCAL REFERENCE
        // =========================

        const localReference =
            generateReference("AIRTIME");

        // =========================
        // RESERVE WALLET + CREATE
        // PENDING TRANSACTION
        // =========================

        try {

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
        airtimeAmount,
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
        airtimeAmount,
        "pending",
        localReference,
        `${network} airtime purchase for ${phone} | Pending WiseSub confirmation`
    ]);

    await client.query("COMMIT");

} catch (transactionError) {
    try {
        await client.query("ROLLBACK");
    } catch (rollbackError) {
        console.error(
            "Airtime wallet reservation rollback error:",
            rollbackError
        );
    }

    throw transactionError;

} finally {
    client.release();
}

        } catch (reserveError) {

            if (
                reserveError.message ===
                "INSUFFICIENT_BALANCE"
            ) {
                return res.status(400).json({
                    success: false,
                    message:
                        "Insufficient wallet balance"
                });
            }

            console.error(
                "Could not reserve wallet for airtime purchase:",
                reserveError
            );

            return res.status(500).json({
                success: false,
                message:
                    "Could not start the airtime purchase. Please try again."
            });
        }

        // =========================
        // TEST/SANDBOX RECIPIENT
        // =========================

        const providerRecipient =
            environment === "test"
                ? "08011111111"
                : phone;

        // =========================
        // CALL WISESUB
        // =========================

        let wiseSubResponse;

        try {

            wiseSubResponse =
                await axios.post(
                    `${baseUrl}/purchase`,
                    {
                        service_type: "airtime",

                        provider_code:
                            providerCode,

                        recipient:
                            providerRecipient,

                        amount:
                            airtimeAmount
                    },
                    {
                        headers: {
                            Authorization:
                                `Bearer ${apiKey}`,

                            "X-API-Secret":
                                apiSecret,

                            "X-Environment":
                                environment,

                            Accept:
                                "application/json",

                            "Content-Type":
                                "application/json"
                        },

                        timeout: 30000
                    }
                );

        } catch (providerError) {

            console.error(
                "WiseSub airtime purchase request failed."
            );

            if (providerError.response) {

                console.error(
                    "WiseSub status:",
                    providerError.response.status
                );

                console.error(
                    "WiseSub response:",
                    JSON.stringify(
                        providerError.response.data,
                        null,
                        2
                    )
                );

                // =========================
                // CONFIRMED 4xx FAILURE
                // =========================

                if (
                    providerError.response.status >= 400 &&
                    providerError.response.status < 500
                ) {

                    try {

 const client = await pool.connect();

try {
    await client.query("BEGIN");

    const refundResult = await client.query(`
        UPDATE users
        SET balance = balance + $1
        WHERE id = $2
        RETURNING id, balance
    `, [
        airtimeAmount,
        userId
    ]);

    if (refundResult.rowCount !== 1) {
        throw new Error(
            "Wallet refund failed"
        );
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
        `${network} airtime purchase for ${phone} | WiseSub rejected the purchase`,
        localReference,
        userId
    ]);

    if (updateResult.rowCount !== 1) {
        throw new Error(
            "Transaction status update failed"
        );
    }

    await client.query("COMMIT");

} catch (transactionError) {

    try {
        await client.query("ROLLBACK");
    } catch (rollbackError) {
        console.error(
            "Airtime purchase refund rollback error:",
            rollbackError
        );
    }

    throw transactionError;

} finally {
    client.release();
}

                    } catch (refundError) {

                        console.error(
                            "CRITICAL: WiseSub rejected airtime purchase but wallet refund failed.",
                            refundError
                        );

                        return res.status(500).json({
                            success: false,
                            message:
                                "The airtime provider rejected the purchase, but we could not complete the wallet refund automatically. Please contact support.",
                            reference:
                                localReference
                        });
                    }

                    return res.status(502).json({
                        success: false,
                        message:
                            "Airtime purchase was rejected by the provider. Your wallet has been refunded.",
                        reference:
                            localReference
                    });
                }

                // =========================
                // 5xx = AMBIGUOUS
                // =========================

                return res.status(202).json({
                    success: false,
                    pending: true,
                    message:
                        "Your airtime purchase is being verified with the provider. Please do not retry this purchase.",
                    reference:
                        localReference
                });
            }

            // =========================
            // NETWORK / TIMEOUT ERROR
            // =========================

            console.error(
                "WiseSub airtime request error:",
                providerError.message
            );

            return res.status(202).json({
                success: false,
                pending: true,
                message:
                    "We could not immediately confirm your airtime purchase. Please do not retry this purchase.",
                reference:
                    localReference
            });
        }

        // =========================
        // CHECK WISESUB RESPONSE
        // =========================

        const providerData =
            wiseSubResponse.data;

        if (
            !providerData ||
            providerData.success !== true
        ) {

            console.error(
                "WiseSub returned an unsuccessful airtime response:",
                JSON.stringify(
                    providerData,
                    null,
                    2
                )
            );

            // =========================
            // REFUND CONFIRMED FAILURE
            // =========================

            try {

const client = await pool.connect();

try {
    await client.query("BEGIN");

    const refundResult = await client.query(`
        UPDATE users
        SET balance = balance + $1
        WHERE id = $2
        RETURNING id, balance
    `, [
        airtimeAmount,
        userId
    ]);

    if (refundResult.rowCount !== 1) {
        throw new Error(
            "Wallet refund failed"
        );
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
        `${network} airtime purchase for ${phone} | WiseSub did not complete the purchase`,
        localReference,
        userId
    ]);

    if (updateResult.rowCount !== 1) {
        throw new Error(
            "Transaction status update failed"
        );
    }

    await client.query("COMMIT");

} catch (transactionError) {

    try {
        await client.query("ROLLBACK");
    } catch (rollbackError) {
        console.error(
            "Airtime purchase refund rollback error:",
            rollbackError
        );
    }

    throw transactionError;

} finally {
    client.release();
}

            } catch (refundError) {

                console.error(
                    "CRITICAL: WiseSub airtime purchase failed but wallet refund failed.",
                    refundError
                );

                return res.status(500).json({
                    success: false,
                    message:
                        "The airtime purchase failed, but we could not complete the wallet refund automatically. Please contact support.",
                    reference:
                        localReference
                });
            }

            return res.status(502).json({
                success: false,
                message:
                    "Airtime purchase was not completed. Your wallet has been refunded.",
                reference:
                    localReference
            });
        }

        // =========================
        // GET WISESUB REFERENCE
        // =========================

        const wiseSubReference =
            providerData.data?.reference || null;

        // =========================
        // SUCCESS MUST HAVE
        // PROVIDER REFERENCE
        // =========================

        if (!wiseSubReference) {

            console.error(
                "CRITICAL: WiseSub reported airtime success but returned no reference.",
                JSON.stringify(
                    providerData,
                    null,
                    2
                )
            );

            return res.status(202).json({
                success: false,
                pending: true,
                message:
                    "Your airtime purchase was accepted by the provider but could not yet be fully confirmed. Please do not retry this purchase.",
                reference:
                    localReference
            });
        }

        // =========================
        // MARK TRANSACTION SUCCESSFUL
        // =========================

try {

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
            `${network} airtime purchase for ${phone} | WiseSub reference: ${wiseSubReference}`,
            localReference,
            userId
        ]);

        if (updateResult.rowCount !== 1) {
            throw new Error(
                "Pending transaction could not be completed"
            );
        }

        await client.query("COMMIT");

    } catch (transactionError) {

        try {
            await client.query("ROLLBACK");
        } catch (rollbackError) {
            console.error(
                "Airtime completion rollback error:",
                rollbackError
            );
        }

        throw transactionError;

    } finally {
        client.release();
    }

} catch (completionError) {


            console.error(
                "CRITICAL: WiseSub airtime purchase succeeded but MELODEXS CONNECT could not mark the transaction successful.",
                completionError
            );

            return res.status(500).json({
                success: false,
                message:
                    "Your airtime purchase was processed by the provider, but we could not complete the transaction record automatically. Please contact support before trying again.",
                reference:
                    localReference,
                providerReference:
                    wiseSubReference
            });
        }

        // =========================
        // GET UPDATED BALANCE
        // =========================

        const updatedUserResult = await pool.query(`
            SELECT balance
            FROM users
            WHERE id = $1
        `, [userId]);

        const updatedUser = updatedUserResult.rows[0];

        // =========================
        // SUCCESS
        // =========================

        return res.json({
            success: true,

            message:
                "Airtime purchase successful",

            network,

            phone,

            amount:
                airtimeAmount,

            balance:
                updatedUser.balance,

            reference:
                localReference,

            providerReference:
                wiseSubReference
        });

    } catch (error) {

        console.error(
            "Airtime purchase error:",
            error
        );

        return res.status(500).json({
            success: false,
            message:
                "Airtime purchase failed"
        });
    }
});

// =========================
// USER TRANSACTIONS
// =========================

app.get("/api/transactions/:userId", requireAuth, async (req, res) => {
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
});

// =========================
// DATA PLANS
// =========================

// Public: customer-facing active WiseSub plans.
app.get("/api/data-plans", async (req, res) => {
    try {
        const result = await pool.query(`
            SELECT
                id,
                network,
                plan,
                selling_price,
                data_size,
                validity
            FROM data_plans
            WHERE active = 1
              AND LOWER(TRIM(source)) = 'wisesub'
            ORDER BY
                CASE LOWER(network)
                    WHEN 'mtn' THEN 1
                    WHEN 'airtel' THEN 2
                    WHEN 'glo' THEN 3
                    WHEN '9mobile' THEN 4
                    ELSE 5
                END,
                selling_price ASC,
                id ASC
        `);

        return res.json({
            success: true,
            plans: result.rows
        });

    } catch (error) {
        console.error("Data plans error:", error);

        return res.status(500).json({
            success: false,
            message: "Could not load data plans"
        });
    }
});

// Admin: active WiseSub plans only.
app.get("/api/admin/data-plans", requireAuth, requireAdmin, async (req, res) => {
    try {
        const result = await pool.query(`
            SELECT
                id,
                network,
                plan,
                provider_cost,
                selling_price,
                (selling_price - provider_cost) AS margin,
                active,
                provider,
                provider_code,
                provider_package_code,
                provider_package_name,
                data_size,
                validity,
                source,
                last_synced_at,
                created_at,
                updated_at
            FROM data_plans
            WHERE active = 1
              AND source IS NOT NULL
              AND TRIM(source) <> ''
            ORDER BY
                CASE network
                    WHEN 'MTN' THEN 1
                    WHEN 'Airtel' THEN 2
                    WHEN 'Glo' THEN 3
                    WHEN '9mobile' THEN 4
                    ELSE 5
                END,
                selling_price ASC,
                id ASC
        `);

        return res.json({
            success: true,
            plans: result.rows
        });

    } catch (error) {
        console.error("Admin data plans error:", error);

        return res.status(500).json({
            success: false,
            message: "Could not load data plans"
        });
    }
});

app.post("/api/admin/data-plans", requireAuth, requireAdmin, async (req, res) => {
    try {
        const network = String(req.body.network || "").trim();
        const plan = String(req.body.plan || "").trim();
        const providerCost = Number(req.body.provider_cost);
        const sellingPrice = Number(req.body.selling_price);
        const active =
            req.body.active === undefined
                ? 1
                : (Number(req.body.active) ? 1 : 0);

        const allowedNetworks = [
            "MTN",
            "Airtel",
            "Glo",
            "9mobile"
        ];

        if (!allowedNetworks.includes(network)) {
            return res.status(400).json({
                success: false,
                message: "Invalid network"
            });
        }

        if (!/^\d+(?:\.\d+)?(?:MB|GB)$/i.test(plan)) {
            return res.status(400).json({
                success: false,
                message:
                    "Invalid plan format. Example: 1GB or 500MB"
            });
        }

        if (!Number.isFinite(providerCost) || providerCost < 0) {
            return res.status(400).json({
                success: false,
                message: "Provider cost must be 0 or greater"
            });
        }

        if (!Number.isFinite(sellingPrice) || sellingPrice <= 0) {
            return res.status(400).json({
                success: false,
                message: "Selling price must be greater than 0"
            });
        }

        if (sellingPrice < providerCost) {
            return res.status(400).json({
                success: false,
                message:
                    "Selling price cannot be below provider cost"
            });
        }

        const normalizedPlan = plan.toUpperCase();

        const result = await pool.query(`
            INSERT INTO data_plans (
                network,
                plan,
                provider_cost,
                selling_price,
                active,
                updated_at
            )
            VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
            ON CONFLICT(network, plan)
            DO UPDATE SET
                provider_cost = EXCLUDED.provider_cost,
                selling_price = EXCLUDED.selling_price,
                active = EXCLUDED.active,
                updated_at = CURRENT_TIMESTAMP
            RETURNING
                id,
                network,
                plan,
                provider_cost,
                selling_price,
                active,
                (selling_price - provider_cost) AS margin,
                updated_at
        `, [
            network,
            normalizedPlan,
            providerCost,
            sellingPrice,
            active
        ]);

        return res.json({
            success: true,
            message: "Data plan saved successfully",
            plan: result.rows[0]
        });

    } catch (error) {
        console.error("Save data plan error:", error);

        return res.status(500).json({
            success: false,
            message: "Could not save data plan"
        });
    }
});

app.patch("/api/admin/data-plans/:id", requireAuth, requireAdmin, async (req, res) => {
    try {
        const id = Number(req.params.id);

        if (!Number.isInteger(id) || id <= 0) {
            return res.status(400).json({
                success: false,
                message: "Invalid plan ID"
            });
        }

        const currentResult = await pool.query(`
            SELECT *
            FROM data_plans
            WHERE id = $1
        `, [id]);

        const current = currentResult.rows[0];

        if (!current) {
            return res.status(404).json({
                success: false,
                message: "Data plan not found"
            });
        }

        const providerCost =
            req.body.provider_cost === undefined
                ? Number(current.provider_cost)
                : Number(req.body.provider_cost);

        const sellingPrice =
            req.body.selling_price === undefined
                ? Number(current.selling_price)
                : Number(req.body.selling_price);

        const active =
            req.body.active === undefined
                ? Number(current.active)
                : (Number(req.body.active) ? 1 : 0);

        if (
            !Number.isFinite(providerCost) ||
            providerCost < 0 ||
            !Number.isFinite(sellingPrice) ||
            sellingPrice <= 0
        ) {
            return res.status(400).json({
                success: false,
                message: "Invalid pricing values"
            });
        }

        if (sellingPrice < providerCost) {
            return res.status(400).json({
                success: false,
                message:
                    "Selling price cannot be below provider cost"
            });
        }

        const result = await pool.query(`
            UPDATE data_plans
            SET
                provider_cost = $1,
                selling_price = $2,
                active = $3,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = $4
            RETURNING
                id,
                network,
                plan,
                provider_cost,
                selling_price,
                active,
                (selling_price - provider_cost) AS margin,
                updated_at
        `, [
            providerCost,
            sellingPrice,
            active,
            id
        ]);

        return res.json({
            success: true,
            message: "Data plan updated successfully",
            plan: result.rows[0]
        });

    } catch (error) {
        console.error("Update data plan error:", error);

        return res.status(500).json({
            success: false,
            message: "Could not update data plan"
        });
    }
});

// =========================
// ADMIN STATS
// =========================

app.get("/api/admin/stats", requireAuth, requireAdmin, async (req, res) => {
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
});

// =========================
// ADMIN USERS
// =========================

app.get("/api/admin/users", requireAuth, requireAdmin, async (req, res) => {
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
});

// =========================
// ADMIN TRANSACTIONS
// =========================

app.get("/api/admin/transactions", requireAuth, requireAdmin, async (req, res) => {
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
});

// =========================
// SERVER


// =========================

// =========================
// FORGOT PASSWORD
// =========================

app.post("/api/forgot-password", forgotPasswordLimiter, async (req, res) => {
    try {
        const email = String(req.body.email || "").trim().toLowerCase();

        if (!email) {
            return res.status(400).json({
                success: false,
                message: "Please enter your email address."
            });
        }

        const userResult = await pool.query(`
            SELECT id, email
            FROM users
            WHERE LOWER(email) = $1
            LIMIT 1
        `, [email]);

        const user = userResult.rows[0];

        // Always return the same message whether the email exists or not.
        // This helps prevent account enumeration.
        if (!user) {
            return res.json({
                success: true,
                message:
                    "If an account exists with that email, password reset instructions will be provided."
            });
        }

        // Generate a secure random reset token.
        const resetToken = crypto.randomBytes(32).toString("hex");

        // Store only the SHA-256 hash of the token.
        const resetTokenHash = crypto
            .createHash("sha256")
            .update(resetToken)
            .digest("hex");

        // Token expires in 15 minutes.
        const expiresAt = Date.now() + (15 * 60 * 1000);

        await pool.query(`
            UPDATE users
            SET reset_token_hash = $1,
                reset_token_expires_at = $2
            WHERE id = $3
        `, [
            resetTokenHash,
            expiresAt,
            user.id
        ]);

        const resetUrl =
            `${process.env.CHEAPDATA_PUBLIC_URL || `${req.protocol}://${req.get("host")}`}/reset-password.html?token=${resetToken}`;

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
                await sendBrevoEmail({
                    to: user.email,
                    subject: "MELODEXS CONNECT Password Reset",
                    htmlContent: `
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
                    `
                });
            } catch (emailError) {
                console.error(
                    "Password reset email failed:",
                    emailError.message
                );

                await pool.query(`
                    UPDATE users
                    SET reset_token_hash = NULL,
                        reset_token_expires_at = NULL
                    WHERE id = $1
                `, [user.id]);

                throw new Error("Password reset email could not be sent.");
            }
        }

        return res.json({
            success: true,
            message:
                "If an account exists with that email, password reset instructions will be provided."
        });

    } catch (error) {
        console.error("Forgot password error:", error);

        return res.status(500).json({
            success: false,
            message: "Something went wrong. Please try again."
        });
    }
});

// =========================
// RESET PASSWORD
// =========================

app.post("/api/reset-password", resetPasswordLimiter, async (req, res) => {
    try {
        const { token, newPassword } = req.body;

        if (!token || !newPassword) {
            return res.status(400).json({
                success: false,
                message: "Reset token and new password are required."
            });
        }

        if (newPassword.length < 8) {
            return res.status(400).json({
                success: false,
                message: "Password must be at least 8 characters."
            });
        }

        // Hash the token received from the reset link.
        const tokenHash = crypto
            .createHash("sha256")
            .update(token)
            .digest("hex");

        // Find a user with this token.
        const userResult = await pool.query(`
            SELECT
                id,
                reset_token_hash,
                reset_token_expires_at
            FROM users
            WHERE reset_token_hash = $1
            LIMIT 1
        `, [tokenHash]);

        const user = userResult.rows[0];

        if (!user) {
            return res.status(400).json({
                success: false,
                message:
                    "This password reset link is invalid or has already been used."
            });
        }

        // Check whether the token has expired.
        if (
            !user.reset_token_expires_at ||
            Date.now() > Number(user.reset_token_expires_at)
        ) {
            return res.status(400).json({
                success: false,
                message:
                    "This password reset link has expired. Please request a new one."
            });
        }

        // Hash the new password.
        const hashedPassword = await bcrypt.hash(newPassword, 10);

        // Save the new password and invalidate the reset token.
        await pool.query(`
            UPDATE users
            SET password = $1,
                reset_token_hash = NULL,
                reset_token_expires_at = NULL
            WHERE id = $2
        `, [
            hashedPassword,
            user.id
        ]);

        // Log the user out of all existing sessions.
        await new Promise((resolve, reject) => {
            sessionStore.destroyUserSessions(user.id, (error) => {
                if (error) {
                    return reject(error);
                }

                resolve();
            });
        });

        return res.json({
            success: true,
            message: "Password reset successfully. You can now log in."
        });

    } catch (error) {
        console.error("Reset password error:", error);

        return res.status(500).json({
            success: false,
            message: "Something went wrong. Please try again."
        });
    }
});

    // =========================
// FUND WALLET - PAYSTACK
// =========================

app.post("/api/fund-wallet", requireAuth, async (req, res) => {
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

        // Find the user from the database
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

        // Make sure Paystack secret key exists
        if (!process.env.PAYSTACK_SECRET_KEY) {
            console.error("PAYSTACK_SECRET_KEY is missing.");

            return res.status(500).json({
                success: false,
                message: "Payment system is not configured yet."
            });
        }

        // Generate the reference before creating the local transaction.
        // This exact reference is also sent to Paystack.
        reference =
            `CD-${Date.now()}-${crypto.randomBytes(6).toString("hex")}`;

        // Record the funding attempt FIRST.
        // The wallet is NOT credited here.
        // Credit happens only after server-side verification/webhook validation.
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
        `, [
            user.id,
            "wallet_funding",
            fundingAmount,
            "pending",
            reference,
            "Paystack wallet funding"
        ]);

        // Paystack expects the amount in kobo
        const amountInKobo = fundingAmount * 100;

        let paystackResponse;

        try {
            paystackResponse = await fetch(
                "https://api.paystack.co/transaction/initialize",
                {
                    method: "POST",

                    headers: {
                        "Authorization":
                            `Bearer ${process.env.PAYSTACK_SECRET_KEY}`,

                        "Content-Type": "application/json"
                    },

                    body: JSON.stringify({
                        email: user.email,
                        amount: String(amountInKobo),
                        currency: "NGN",
                        reference: reference,

                        callback_url:
                            `${process.env.CHEAPDATA_PUBLIC_URL || `${req.protocol}://${req.get("host")}`}/fund-wallet.html`,

                        metadata: {
                            user_id: String(user.id),
                            purpose: "wallet_funding"
                        }
                    })
                }
            );
        } catch (error) {
            // We cannot know whether Paystack received the request.
            // Keep the transaction pending so it can be reconciled safely.
            console.error(
                "Paystack initialization network error:",
                error
            );

            return res.status(500).json({
                success: false,
                message:
                    "Unable to confirm payment initialization right now. Please try again later."
            });
        }

        let paystackData;

        try {
            paystackData = await paystackResponse.json();
        } catch (error) {
            // The payment request reached Paystack, but the response could
            // not be interpreted. Keep the local transaction pending.
            console.error(
                "Invalid response from Paystack during initialization:",
                error
            );

            return res.status(502).json({
                success: false,
                message:
                    "Payment initialization could not be confirmed. Please try again later."
            });
        }

        // Paystack explicitly rejected the initialization.
        // Since we know the request was rejected, mark the local attempt failed.
        if (
            !paystackResponse.ok ||
            !paystackData.status ||
            !paystackData.data
        ) {
            console.error(
                "Paystack initialization failed:",
                paystackData
            );

            await pool.query(`
                UPDATE transactions
                SET
                    status = $1,
                    description = $2
                WHERE reference = $3
                  AND user_id = $4
                  AND type = $5
                  AND status = $6
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
                message:
                    paystackData.message ||
                    "Unable to initialize payment."
            });
        }

        // Paystack should return the same reference we supplied.
        // Reject an unexpected reference rather than creating an
        // authorization flow that cannot be matched safely.
        if (
            !paystackData.data.reference ||
            paystackData.data.reference !== reference
        ) {
            console.error(
                "Paystack returned an unexpected transaction reference:",
                {
                    expected: reference,
                    received: paystackData.data.reference
                }
            );

            return res.status(502).json({
                success: false,
                message:
                    "Payment initialization could not be verified. Please try again later."
            });
        }

        return res.json({
            success: true,
            message: "Payment initialized successfully.",

            authorization_url:
                paystackData.data.authorization_url,

            access_code:
                paystackData.data.access_code,

            reference:
                reference
        });

    } catch (error) {
        console.error(
            "Fund wallet error:",
            error
        );

        return res.status(500).json({
            success: false,
            message:
                "Unable to initialize payment. Please try again."
        });
    }
});

// =========================
// VERIFY PAYSTACK WALLET FUNDING
// =========================

app.post("/api/fund-wallet/verify", requireAuth, async (req, res) => {
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

        const transactionResult = await pool.query(`
            SELECT id, user_id, amount, status, reference
            FROM transactions
            WHERE reference = $1
              AND type = 'wallet_funding'
              AND user_id = $2
            LIMIT 1
        `, [reference, req.session.userId]);

        const transaction = transactionResult.rows[0];

        if (!transaction) {
            return res.status(404).json({
                success: false,
                message: "Funding transaction not found."
            });
        }

        // Idempotency: never credit an already-successful payment twice.
        if (transaction.status === "successful") {
            const userResult = await pool.query(`
                SELECT balance
                FROM users
                WHERE id = $1
            `, [req.session.userId]);

            const user = userResult.rows[0];
            return res.json({
                success: true,
                message: "Payment has already been credited.",
                balance: user.balance,
                reference
            });
        }

        const paystackResponse = await fetch(
            `https://api.paystack.co/transaction/verify/${encodeURIComponent(reference)}`,
            {
                method: "GET",
                headers: {
                    "Authorization": `Bearer ${process.env.PAYSTACK_SECRET_KEY}`
                }
            }
        );

        const paystackData = await paystackResponse.json();

        if (!paystackResponse.ok || !paystackData.status || !paystackData.data) {
            return res.status(400).json({
                success: false,
                message: paystackData.message || "Unable to verify payment."
            });
        }

        const payment = paystackData.data;
        const expectedAmount = Math.round(Number(transaction.amount) * 100);
        const paidAmount = Number(payment.amount);
        const metadataUserId = String(
            payment.metadata && payment.metadata.user_id || ""
        );

        if (
            payment.status !== "success" ||
            payment.currency !== "NGN" ||
            paidAmount !== expectedAmount ||
            metadataUserId !== String(req.session.userId) ||
            String(payment.reference) !== reference
        ) {
            return res.status(400).json({
                success: false,
                message: "Payment could not be verified as a valid MELODEXS CONNECT wallet funding."
            });
        }

        let credited = false;

        const client = await pool.connect();

        try {
            await client.query("BEGIN");

            const currentResult = await client.query(`
                SELECT status, user_id, amount
                FROM transactions
                WHERE id = $1
                FOR UPDATE
            `, [transaction.id]);

            const current = currentResult.rows[0];

            if (!current) {
                throw new Error("Funding transaction could not be found.");
            }

            if (current.status === "successful") {
                await client.query("COMMIT");
            } else {
                const walletUpdate = await client.query(`
                    UPDATE users
                    SET balance = balance + $1
                    WHERE id = $2
                    RETURNING id, balance
                `, [
                    current.amount,
                    current.user_id
                ]);

                if (walletUpdate.rowCount !== 1) {
                    throw new Error("Wallet could not be updated.");
                }

                const transactionUpdate = await client.query(`
                    UPDATE transactions
                    SET
                        status = 'successful',
                        description = $1
                    WHERE id = $2
                      AND status <> 'successful'
                `, [
                    "Verified Paystack wallet funding",
                    transaction.id
                ]);

                if (transactionUpdate.rowCount !== 1) {
                    throw new Error("Funding transaction could not be completed.");
                }

                await client.query("COMMIT");

                credited = true;
            }

        } catch (creditError) {
            try {
                await client.query("ROLLBACK");
            } catch (rollbackError) {
                console.error(
                    "Paystack wallet credit rollback error:",
                    rollbackError
                );
            }

            throw creditError;

        } finally {
            client.release();
        }

        const userResult = await pool.query(`
            SELECT balance
            FROM users
            WHERE id = $1
        `, [req.session.userId]);

        const user = userResult.rows[0];

        return res.json({
            success: true,
            message: credited
                ? "Payment verified and wallet credited successfully."
                : "Payment has already been credited.",
            balance: user.balance,
            amount: transaction.amount,
            reference
        });
    } catch (error) {
        console.error("Paystack verification error:", error);
        return res.status(500).json({
            success: false,
            message: "Unable to verify payment right now. Please try again."
        });
    }
});

module.exports = {
    app,
    sessionStore
};
