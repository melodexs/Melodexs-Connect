const express = require("express");
const helmet = require("helmet");
const session = require("express-session");
const PostgresSessionStore = require("./postgres-session-store");
const bcrypt = require("bcryptjs");
const { WEB_PUBLIC_DIR } = require("./config");
const { pool } = require("./postgres");
const { requireAuth, requireAdmin } = require("./auth");
const authRoutes = require("./routes/auth.routes");
const userRoutes = require("./routes/user.routes");
const transactionRoutes = require("./routes/transaction.routes");
const dataPlanRoutes = require("./routes/data-plan.routes");
const purchaseRoutes = require("./routes/purchase.routes");
const paystackRoutes = require("./routes/paystack.routes");

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



// Preserve the raw request body for Paystack signature verification.
app.use("/api", paystackRoutes.webhookRouter);
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
app.use("/api", transactionRoutes);
app.use("/api", dataPlanRoutes);
app.use("/api", purchaseRoutes);
app.use("/api", paystackRoutes.router);

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


module.exports = {
    app,
    sessionStore
};
