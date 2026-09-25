const { pool } = require("../postgres");
const bcrypt = require("bcryptjs");
const { generateReference } = require("../utils/references");
const { isValidNigerianPhone } = require("../utils/validation");
const { purchaseWithWiseSub } = require("../services/wisesub.service");

async function purchaseData(req, res) {
    try {
        const userId = req.session.userId;

        const { network, phone, plan, pin } = req.body;

        if (!network || !phone || !plan || pin === undefined) {
            return res.status(400).json({ success: false, message: "Please provide all purchase details including your Purchase PIN" });
        }

        const pinString = String(pin);

        if (!/^\d{4}$/.test(pinString)) {
            return res.status(400).json({ success: false, message: "Purchase PIN must be exactly 4 digits" });
        }

        if (!isValidNigerianPhone(phone)) {
            return res.status(400).json({ success: false, message: "Please enter a valid Nigerian phone number" });
        }

        const allowedNetworks = ["MTN","Airtel","Glo","9mobile"];

        if (!allowedNetworks.includes(network)) {
            return res.status(400).json({ success: false, message: "Invalid network" });
        }

        const selectedPlanResult = await pool.query(`
            SELECT id, network, plan, provider_cost, selling_price, active, provider, provider_code, provider_package_code, provider_package_name, source
            FROM data_plans
            WHERE network = $1 AND plan = $2 AND active = 1 AND source = 'wisesub'
            LIMIT 1
        `, [network, plan]);

        const selectedPlan = selectedPlanResult.rows[0];

        if (!selectedPlan) {
            return res.status(400).json({ success: false, message: "That data plan is not currently available" });
        }

        if (!selectedPlan.provider_package_code || !selectedPlan.provider_code) {
            console.error("Missing WiseSub package information:", selectedPlan);
            return res.status(500).json({ success: false, message: "This data plan is not properly configured. Please try another plan." });
        }

        const sellingPrice = Number(selectedPlan.selling_price);

        if (!Number.isFinite(sellingPrice) || sellingPrice <= 0) {
            return res.status(500).json({ success: false, message: "Invalid data plan price" });
        }

        const userResult = await pool.query(`SELECT id, balance, purchase_pin FROM users WHERE id = $1`, [userId]);
        const user = userResult.rows[0];

        if (!user) return res.status(404).json({ success: false, message: "User not found" });

        if (!user.purchase_pin) return res.status(400).json({ success: false, message: "Please create a Purchase PIN before buying data" });

        const pinCorrect = await bcrypt.compare(pinString, user.purchase_pin);

        if (!pinCorrect) return res.status(401).json({ success: false, message: "Incorrect Purchase PIN" });

        const baseUrl = process.env.WISESUB_BASE_URL;
        const apiKey = process.env.WISESUB_API_KEY;
        const apiSecret = process.env.WISESUB_API_SECRET;
        const environment = process.env.WISESUB_ENVIRONMENT || "test";

        if (!baseUrl || !apiKey || !apiSecret) {
            console.error("WiseSub configuration is incomplete.");
            return res.status(500).json({ success: false, message: "Data service is temporarily unavailable" });
        }

        const localReference = generateReference("DATA");

        try {
            const client = await pool.connect();
            try {
                await client.query("BEGIN");

                const debitResult = await client.query(`UPDATE users SET balance = balance - $1 WHERE id = $2 AND balance >= $1 RETURNING id, balance`, [sellingPrice, userId]);

                if (debitResult.rowCount !== 1) throw new Error("INSUFFICIENT_BALANCE");

                await client.query(`INSERT INTO transactions (user_id, type, amount, status, reference, description) VALUES ($1,$2,$3,$4,$5,$6)`, [userId, "debit", sellingPrice, "pending", localReference, `${network} ${plan} data purchase for ${phone} | Pending WiseSub confirmation`]);

                await client.query("COMMIT");
            } catch (transactionError) {
                try { await client.query("ROLLBACK"); } catch (rollbackError) { console.error("Data purchase reservation rollback error:", rollbackError); }
                throw transactionError;
            } finally { client.release(); }
        } catch (reserveError) {
            if (reserveError.message === "INSUFFICIENT_BALANCE") return res.status(400).json({ success: false, message: "Insufficient wallet balance" });
            console.error("Could not reserve wallet for data purchase:", reserveError);
            return res.status(500).json({ success: false, message: "Could not start the data purchase. Please try again." });
        }

        const providerRecipient = environment === "test" ? "08011111111" : phone;

        let wiseSubResponse;

        try {
            wiseSubResponse = await purchaseWithWiseSub({
                baseUrl,
                apiKey,
                apiSecret,
                environment,
                body: {
                    service_type: "data",
                    reference: localReference,
                    provider_code: selectedPlan.provider_code,
                    package_code: selectedPlan.provider_package_code,
                    recipient: providerRecipient
                }
            });
        } catch (providerError) {
            console.error("WiseSub data purchase request failed.");

            if (providerError.response) {
                console.error("WiseSub status:", providerError.response.status);
                console.error("WiseSub response:", JSON.stringify(providerError.response.data, null, 2));

                if (providerError.response.status >= 400 && providerError.response.status < 500) {
                    try {
                        const client = await pool.connect();
                        try {
                            await client.query("BEGIN");
                            const refundResult = await client.query(`UPDATE users SET balance = balance + $1 WHERE id = $2 RETURNING id, balance`, [sellingPrice, userId]);
                            if (refundResult.rowCount !== 1) throw new Error("Wallet refund failed");
                            const updateResult = await client.query(`UPDATE transactions SET status = $1, description = $2 WHERE reference = $3 AND user_id = $4 AND status = 'pending'`, ["failed", `${network} ${plan} data purchase for ${phone} | WiseSub rejected the purchase`, localReference, userId]);
                            if (updateResult.rowCount !== 1) throw new Error("Transaction status update failed");
                            await client.query("COMMIT");
                        } catch (transactionError) {
                            try { await client.query("ROLLBACK"); } catch (rollbackError) { console.error("Data purchase refund rollback error:", rollbackError); }
                            throw transactionError;
                        } finally { client.release(); }
                    } catch (refundError) {
                        console.error("CRITICAL: WiseSub rejected data purchase but wallet refund failed.", refundError);
                        return res.status(500).json({ success: false, message: "The data provider rejected the purchase, but we could not complete the wallet refund automatically. Please contact support.", reference: localReference });
                    }

                    return res.status(502).json({ success: false, message: "Data purchase was rejected by the provider. Your wallet has been refunded.", reference: localReference });
                }

                return res.status(202).json({ success: false, pending: true, message: "Your data purchase is being verified with the provider. Please do not retry this purchase.", reference: localReference });
            }

            console.error("WiseSub data request error:", providerError.message);

            return res.status(202).json({ success: false, pending: true, message: "We could not immediately confirm your data purchase. Please do not retry this purchase.", reference: localReference });
        }

        const providerData = wiseSubResponse.data;

        if (!providerData || providerData.success !== true) {
            console.error("WiseSub returned an unsuccessful data response:", JSON.stringify(providerData, null, 2));

            try {
                const client = await pool.connect();
                try {
                    await client.query("BEGIN");
                    const refundResult = await client.query(`UPDATE users SET balance = balance + $1 WHERE id = $2 RETURNING id, balance`, [sellingPrice, userId]);
                    if (refundResult.rowCount !== 1) throw new Error("Wallet refund failed");
                    const updateResult = await client.query(`UPDATE transactions SET status = $1, description = $2 WHERE reference = $3 AND user_id = $4 AND status = 'pending'`, ["failed", `${network} ${plan} data purchase for ${phone} | WiseSub did not complete the purchase`, localReference, userId]);
                    if (updateResult.rowCount !== 1) throw new Error("Transaction status update failed");
                    await client.query("COMMIT");
                } catch (transactionError) {
                    try { await client.query("ROLLBACK"); } catch (rollbackError) { console.error("Data purchase refund rollback error:", rollbackError); }
                    throw transactionError;
                } finally { client.release(); }
            } catch (refundError) {
                console.error("CRITICAL: WiseSub data purchase failed but wallet refund failed.", refundError);
                return res.status(500).json({ success: false, message: "The data purchase failed, but we could not complete the wallet refund automatically. Please contact support.", reference: localReference });
            }

            return res.status(502).json({ success: false, message: "Data purchase was not completed. Your wallet has been refunded.", reference: localReference });
        }

        const wiseSubReference = providerData.data?.reference || null;

        if (!wiseSubReference) {
            console.error("CRITICAL: WiseSub reported success but returned no reference.", JSON.stringify(providerData, null, 2));
            return res.status(202).json({ success: false, pending: true, message: "Your data purchase was accepted by the provider but could not yet be fully confirmed. Please do not retry this purchase.", reference: localReference });
        }

        try {
            const client = await pool.connect();
            try {
                await client.query("BEGIN");
                const updateResult = await client.query(`UPDATE transactions SET status = $1, description = $2 WHERE reference = $3 AND user_id = $4 AND status = 'pending'`, ["successful", `${network} ${plan} data purchase for ${phone} | WiseSub reference: ${wiseSubReference}`, localReference, userId]);
                if (updateResult.rowCount !== 1) throw new Error("Pending transaction could not be completed");
                await client.query("COMMIT");
            } catch (transactionError) {
                try { await client.query("ROLLBACK"); } catch (rollbackError) { console.error("Data purchase completion rollback error:", rollbackError); }
                throw transactionError;
            } finally { client.release(); }
        } catch (completionError) {
            console.error("CRITICAL: WiseSub data purchase succeeded but MELODEXS CONNECT could not mark the transaction successful.", completionError);
            return res.status(500).json({ success: false, message: "Your data purchase was processed by the provider, but we could not complete the transaction record automatically. Please contact support before trying again.", reference: localReference, providerReference: wiseSubReference });
        }

        const updatedUserResult = await pool.query(`SELECT balance FROM users WHERE id = $1`, [userId]);
        const updatedUser = updatedUserResult.rows[0];

        return res.json({ success: true, message: "Data purchase successful", network, plan, phone, amount: sellingPrice, balance: updatedUser.balance, reference: localReference, providerReference: wiseSubReference });

    } catch (error) {
        console.error("Data purchase error:", error);
        return res.status(500).json({ success: false, message: "Data purchase failed" });
    }
}

async function purchaseAirtime(req, res) {
    try {
        const userId = req.session.userId;
        const { network, phone, amount, pin } = req.body;
        const airtimeAmount = Number(amount);

        if (!network || !phone || amount === undefined || pin === undefined) return res.status(400).json({ success: false, message: "Please provide all purchase details including your Purchase PIN" });

        const pinString = String(pin);
        if (!/^\d{4}$/.test(pinString)) return res.status(400).json({ success: false, message: "Purchase PIN must be exactly 4 digits" });

        const allowedNetworks = ["MTN","Airtel","Glo","9mobile"];
        if (!allowedNetworks.includes(network)) return res.status(400).json({ success: false, message: "Invalid network" });

        if (!isValidNigerianPhone(phone)) return res.status(400).json({ success: false, message: "Please enter a valid Nigerian phone number" });

        if (!Number.isFinite(airtimeAmount) || !Number.isInteger(airtimeAmount) || airtimeAmount < 50 || airtimeAmount > 50000) {
            return res.status(400).json({ success: false, message: "Airtime amount must be between ₦50 and ₦50,000" });
        }

        const userResult = await pool.query(`SELECT id, balance, purchase_pin FROM users WHERE id = $1`, [userId]);
        const user = userResult.rows[0];
        if (!user) return res.status(404).json({ success: false, message: "User not found" });
        if (!user.purchase_pin) return res.status(400).json({ success: false, message: "Please create a Purchase PIN before buying airtime" });

        const pinCorrect = await bcrypt.compare(pinString, user.purchase_pin);
        if (!pinCorrect) return res.status(401).json({ success: false, message: "Incorrect Purchase PIN" });

        const baseUrl = process.env.WISESUB_BASE_URL;
        const apiKey = process.env.WISESUB_API_KEY;
        const apiSecret = process.env.WISESUB_API_SECRET;
        const environment = process.env.WISESUB_ENVIRONMENT || "test";

        if (!baseUrl || !apiKey || !apiSecret) {
            console.error("WiseSub configuration is incomplete.");
            return res.status(500).json({ success: false, message: "Airtime service is temporarily unavailable" });
        }

        const providerCodes = { MTN: "mtn", Airtel: "airtel", Glo: "glo", "9mobile": "9mobile" };
        const providerCode = providerCodes[network];
        if (!providerCode) return res.status(400).json({ success: false, message: "Could not determine the airtime provider" });

        const localReference = generateReference("AIRTIME");

        try {
            const client = await pool.connect();
            try {
                await client.query("BEGIN");
                const debitResult = await client.query(`UPDATE users SET balance = balance - $1 WHERE id = $2 AND balance >= $1 RETURNING id, balance`, [airtimeAmount, userId]);
                if (debitResult.rowCount !== 1) throw new Error("INSUFFICIENT_BALANCE");
                await client.query(`INSERT INTO transactions (user_id, type, amount, status, reference, description) VALUES ($1,$2,$3,$4,$5,$6)`, [userId, "debit", airtimeAmount, "pending", localReference, `${network} airtime purchase for ${phone} | Pending WiseSub confirmation`]);
                await client.query("COMMIT");
            } catch (transactionError) {
                try { await client.query("ROLLBACK"); } catch (rollbackError) { console.error("Airtime wallet reservation rollback error:", rollbackError); }
                throw transactionError;
            } finally { client.release(); }
        } catch (reserveError) {
            if (reserveError.message === "INSUFFICIENT_BALANCE") return res.status(400).json({ success: false, message: "Insufficient wallet balance" });
            console.error("Could not reserve wallet for airtime purchase:", reserveError);
            return res.status(500).json({ success: false, message: "Could not start the airtime purchase. Please try again." });
        }

        const providerRecipient = environment === "test" ? "08011111111" : phone;

        let wiseSubResponse;

        try {
            wiseSubResponse = await purchaseWithWiseSub({ baseUrl, apiKey, apiSecret, environment, body: { service_type: "airtime", reference: localReference, provider_code: providerCode, recipient: providerRecipient, amount: airtimeAmount } });
        } catch (providerError) {
            console.error("WiseSub airtime purchase request failed.");
            if (providerError.response) {
                console.error("WiseSub status:", providerError.response.status);
                console.error("WiseSub response:", JSON.stringify(providerError.response.data, null, 2));

                if (providerError.response.status >= 400 && providerError.response.status < 500) {
                    try {
                        const client = await pool.connect();
                        try {
                            await client.query("BEGIN");
                            const refundResult = await client.query(`UPDATE users SET balance = balance + $1 WHERE id = $2 RETURNING id, balance`, [airtimeAmount, userId]);
                            if (refundResult.rowCount !== 1) throw new Error("Wallet refund failed");
                            const updateResult = await client.query(`UPDATE transactions SET status = $1, description = $2 WHERE reference = $3 AND user_id = $4 AND status = 'pending'`, ["failed", `${network} airtime purchase for ${phone} | WiseSub rejected the purchase`, localReference, userId]);
                            if (updateResult.rowCount !== 1) throw new Error("Transaction status update failed");
                            await client.query("COMMIT");
                        } catch (transactionError) {
                            try { await client.query("ROLLBACK"); } catch (rollbackError) { console.error("Airtime purchase refund rollback error:", rollbackError); }
                            throw transactionError;
                        } finally { client.release(); }
                    } catch (refundError) {
                        console.error("CRITICAL: WiseSub rejected airtime purchase but wallet refund failed.", refundError);
                        return res.status(500).json({ success: false, message: "The airtime provider rejected the purchase, but we could not complete the wallet refund automatically. Please contact support.", reference: localReference });
                    }

                    return res.status(502).json({ success: false, message: "Airtime purchase was rejected by the provider. Your wallet has been refunded.", reference: localReference });
                }

                return res.status(202).json({ success: false, pending: true, message: "Your airtime purchase is being verified with the provider. Please do not retry this purchase.", reference: localReference });
            }

            console.error("WiseSub airtime request error:", providerError.message);
            return res.status(202).json({ success: false, pending: true, message: "We could not immediately confirm your airtime purchase. Please do not retry this purchase.", reference: localReference });
        }

        const providerData = wiseSubResponse.data;

        if (!providerData || providerData.success !== true) {
            console.error("WiseSub returned an unsuccessful airtime response:", JSON.stringify(providerData, null, 2));
            try {
                const client = await pool.connect();
                try {
                    await client.query("BEGIN");
                    const refundResult = await client.query(`UPDATE users SET balance = balance + $1 WHERE id = $2 RETURNING id, balance`, [airtimeAmount, userId]);
                    if (refundResult.rowCount !== 1) throw new Error("Wallet refund failed");
                    const updateResult = await client.query(`UPDATE transactions SET status = $1, description = $2 WHERE reference = $3 AND user_id = $4 AND status = 'pending'`, ["failed", `${network} airtime purchase for ${phone} | WiseSub did not complete the purchase`, localReference, userId]);
                    if (updateResult.rowCount !== 1) throw new Error("Transaction status update failed");
                    await client.query("COMMIT");
                } catch (transactionError) {
                    try { await client.query("ROLLBACK"); } catch (rollbackError) { console.error("Airtime purchase refund rollback error:", rollbackError); }
                    throw transactionError;
                } finally { client.release(); }
            } catch (refundError) {
                console.error("CRITICAL: WiseSub airtime purchase failed but wallet refund failed.", refundError);
                return res.status(500).json({ success: false, message: "The airtime purchase failed, but we could not complete the wallet refund automatically. Please contact support.", reference: localReference });
            }

            return res.status(502).json({ success: false, message: "Airtime purchase was not completed. Your wallet has been refunded.", reference: localReference });
        }

        const wiseSubReference = providerData.data?.reference || null;
        if (!wiseSubReference) {
            console.error("CRITICAL: WiseSub reported airtime success but returned no reference.", JSON.stringify(providerData, null, 2));
            return res.status(202).json({ success: false, pending: true, message: "Your airtime purchase was accepted by the provider but could not yet be fully confirmed. Please do not retry this purchase.", reference: localReference });
        }

        try {
            const client = await pool.connect();
            try {
                await client.query("BEGIN");
                const updateResult = await client.query(`UPDATE transactions SET status = $1, description = $2 WHERE reference = $3 AND user_id = $4 AND status = 'pending'`, ["successful", `${network} airtime purchase for ${phone} | WiseSub reference: ${wiseSubReference}`, localReference, userId]);
                if (updateResult.rowCount !== 1) throw new Error("Pending transaction could not be completed");
                await client.query("COMMIT");
            } catch (transactionError) {
                try { await client.query("ROLLBACK"); } catch (rollbackError) { console.error("Airtime completion rollback error:", rollbackError); }
                throw transactionError;
            } finally { client.release(); }
        } catch (completionError) {
            console.error("CRITICAL: WiseSub airtime purchase succeeded but MELODEXS CONNECT could not mark the transaction successful.", completionError);
            return res.status(500).json({ success: false, message: "Your airtime purchase was processed by the provider, but we could not complete the transaction record automatically. Please contact support before trying again.", reference: localReference, providerReference: wiseSubReference });
        }

        const updatedUserResult = await pool.query(`SELECT balance FROM users WHERE id = $1`, [userId]);
        const updatedUser = updatedUserResult.rows[0];

        return res.json({ success: true, message: "Airtime purchase successful", network, phone, amount: airtimeAmount, balance: updatedUser.balance, reference: localReference, providerReference: wiseSubReference });

    } catch (error) {
        console.error("Airtime purchase error:", error);
        return res.status(500).json({ success: false, message: "Airtime purchase failed" });
    }
}

async function getDataPlans(req, res) {
    try {
        const result = await pool.query(`
            SELECT id, network, plan, selling_price, data_size, validity
            FROM data_plans
            WHERE active = 1 AND LOWER(TRIM(source)) = 'wisesub'
            ORDER BY CASE LOWER(network) WHEN 'mtn' THEN 1 WHEN 'airtel' THEN 2 WHEN 'glo' THEN 3 WHEN '9mobile' THEN 4 ELSE 5 END, selling_price ASC, id ASC
        `);

        return res.json({ success: true, plans: result.rows });
    } catch (error) {
        console.error("Data plans error:", error);
        return res.status(500).json({ success: false, message: "Could not load data plans" });
    }
}

module.exports = {
    purchaseData,
    purchaseAirtime,
    getDataPlans
};
