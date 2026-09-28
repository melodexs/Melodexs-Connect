const express = require("express");
const helmet = require("helmet");
const axios = require("axios");
const session = require("express-session");
const PostgresSessionStore = require("./postgres-session-store");
const crypto = require("crypto");
const bcrypt = require("bcryptjs");
const { WEB_PUBLIC_DIR } = require("./config");
const { pool } = require("./postgres");
const { requireAuth, requireAdmin, getAdmin } = require("./auth");
const authRoutes = require("./routes/auth.routes");
const userRoutes = require("./routes/user.routes");
const purchaseRoutes = require("./routes/purchase.routes");

// =========================
// BREVO EMAIL
// =========================

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

            // The frontend and API are different origins.
            // Allow the session cookie to be sent with
            // cross-origin frontend requests in production.
            sameSite:
                process.env.NODE_ENV === "production"
                    ? "none"
                    : "lax",

            secure:
                process.env.NODE_ENV === "production",

            maxAge:
                1000 * 60 * 60 * 24
        }
    })
);

// =========================
// CORS
// =========================

app.use((req, res, next) => {
    const origin = req.get("Origin");

    // Requests without an Origin header do not need CORS handling.
    if (!origin) {
        return next();
    }

    const allowedOrigins = new Set([
        "https://melodexs-connect.onrender.com"
    ]);

    // Also allow the configured public/frontend URL.
    if (process.env.CHEAPDATA_PUBLIC_URL) {
        try {
            allowedOrigins.add(
                new URL(
                    process.env.CHEAPDATA_PUBLIC_URL
                ).origin
            );
        } catch (error) {
            console.error(
                "Invalid CHEAPDATA_PUBLIC_URL:",
                error.message
            );
        }
    }

    // Allow the local API origin during development.
    if (process.env.NODE_ENV !== "production") {
        allowedOrigins.add(
            `${req.protocol}://${req.get("host")}`
        );
    }

    if (!allowedOrigins.has(origin)) {
        console.warn(
            `CORS blocked request from origin: ${origin}`
        );

        return res.status(403).json({
            success: false,
            message: "CORS origin not allowed"
        });
    }

    res.setHeader(
        "Access-Control-Allow-Origin",
        origin
    );

    res.setHeader(
        "Access-Control-Allow-Credentials",
        "true"
    );

    res.setHeader(
        "Access-Control-Allow-Headers",
        "Content-Type, Accept"
    );

    res.setHeader(
        "Access-Control-Allow-Methods",
        "GET,POST,PUT,PATCH,DELETE,OPTIONS"
    );

    res.setHeader(
        "Vary",
        "Origin"
    );

    // Browser preflight request.
    if (req.method === "OPTIONS") {
        return res.sendStatus(204);
    }

    next();
});

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
app.use("/api", authRoutes);
app.use("/api", userRoutes);
app.use("/api", purchaseRoutes);

// =========================
// HELPER FUNCTIONS
// =========================

function generateReference() {
    const now = new Date();

    const lagos = new Date(
        now.toLocaleString("en-US", {
            timeZone: "Africa/Lagos"
        })
    );

    const pad = (n) => String(n).padStart(2, "0");

    const YYYY = lagos.getFullYear();
    const MM = pad(lagos.getMonth() + 1);
    const DD = pad(lagos.getDate());
    const HH = pad(lagos.getHours());
    const II = pad(lagos.getMinutes());

    const suffix = Math.random()
        .toString(36)
        .substring(2, 12);

    return `${YYYY}${MM}${DD}${HH}${II}${suffix}`;
}

function isValidNigerianPhone(phone) {
    return /^0[7-9][0-1][0-9]{8}$/.test(phone);
}

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
