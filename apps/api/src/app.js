const express = require("express");
const helmet = require("helmet");
// rateLimit is used in auth routes
const axios = require("axios");
const session = require("express-session");
const PostgresSessionStore = require("./postgres-session-store");
const crypto = require("crypto");
const bcrypt = require("bcryptjs");
const { WEB_PUBLIC_DIR } = require("./config");
const { pool } = require("./postgres");
const { requireAuth, requireAdmin, getAdmin } = require("./auth");

// Brevo email sending is provided by `utils/email.js`.

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
// =========================
// PURCHASE DATA
// Moved to `routes/purchase.routes.js` -> `controllers/purchase.controller.js`
// (preserves wallet reservation, WiseSub calls, and refund behavior)
                                localReference
                        // =========================
                        // PURCHASE AIRTIME
                        // Moved to `routes/purchase.routes.js` -> `controllers/purchase.controller.js`
                        // (preserves wallet reservation, WiseSub calls, and refund behavior)
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
// DATA PLANS (public)
// Moved to `routes/purchase.routes.js` -> `controllers/purchase.controller.js`

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

// Forgot password endpoint moved to `routes/auth.routes.js`

// =========================
// RESET PASSWORD
// =========================

// Reset password endpoint moved to `routes/auth.routes.js`

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
