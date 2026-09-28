const { pool } = require("../postgres");

async function getDataPlans(req, res) {
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
}

async function getAdminDataPlans(req, res) {
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
}

async function createDataPlan(req, res) {
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
}

async function updateDataPlan(req, res) {
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
}

module.exports = {
    getDataPlans,
    getAdminDataPlans,
    createDataPlan,
    updateDataPlan
};
