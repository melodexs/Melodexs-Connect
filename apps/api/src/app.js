const express = require("express");
const helmet = require("helmet");
const session = require("express-session");
const PostgresSessionStore = require("./postgres-session-store");
const { WEB_PUBLIC_DIR } = require("./config");
const authRoutes = require("./routes/auth.routes");
const userRoutes = require("./routes/user.routes");
const transactionRoutes = require("./routes/transaction.routes");
const dataPlanRoutes = require("./routes/data-plan.routes");
const purchaseRoutes = require("./routes/purchase.routes");
const purchasePinRoutes = require("./routes/purchase-pin.routes");
const adminRoutes = require("./routes/admin.routes");
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

app.use(express.static(WEB_PUBLIC_DIR, {
    setHeaders: (res, filePath) => {
        if (filePath.endsWith(".webmanifest")) {
            res.setHeader(
                "Content-Type",
                "application/manifest+json"
            );
        }
    }
}));
app.use("/api", authRoutes);
app.use("/api", userRoutes);
app.use("/api", transactionRoutes);
app.use("/api", dataPlanRoutes);
app.use("/api", purchaseRoutes);
app.use("/api", purchasePinRoutes);
app.use("/api", adminRoutes);
app.use("/api", paystackRoutes.router);

module.exports = {
    app,
    sessionStore
};
