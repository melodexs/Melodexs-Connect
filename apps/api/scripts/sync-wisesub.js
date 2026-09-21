const axios = require("axios");
const { pool } = require("../src/postgres");
require("dotenv").config();

const BASE_URL =
    process.env.WISESUB_BASE_URL ||
    "https://app.wisesub.com.ng/api/partner/v1";

const NETWORKS = [
    { name: "MTN", code: "mtn" },
    { name: "Airtel", code: "airtel" },
    { name: "Glo", code: "glo" },
    { name: "9mobile", code: "9mobile" }
];

function getHeaders() {
    return {
        Authorization: `Bearer ${process.env.WISESUB_API_KEY || ""}`,
        "X-API-Secret": process.env.WISESUB_API_SECRET || "",
        "X-Environment":
            process.env.WISESUB_ENVIRONMENT || "test",
        Accept: "application/json"
    };
}

/*
 * MELODEXS CONNECT pricing:
 *
 * WiseSub cost + markup
 *
 * Round UP to the next whole naira.
 */
function calculateSellingPrice(providerCost) {
    const markupPercent = Number(
        process.env.CHEAPDATA_MARKUP_PERCENT || 2
    );

    const cost = Number(providerCost);

    if (!Number.isFinite(cost) || cost <= 0) {
        return 0;
    }

    const markedUpPrice =
        cost * (1 + markupPercent / 100);

    return Math.ceil(markedUpPrice);
}

/*
 * Only allow actual data bundles.
 *
 * Exclude airtime, voice, social and
 * entertainment-type packages.
 */
function isValidDataPackage(packageName) {
    const name = String(packageName || "")
        .toLowerCase()
        .trim();

    const excludedWords = [
        "xtratalk",
        "xtra talk",
        "xtradata",
        "xtra data",
        "voice",
        "airtime",
        "tv",
        "vod",
        "telegram",
        "instagram",
        "tiktok",
        "youtube",
        "opera",
        "social",
        "myg",
        "wtf"
    ];

    if (
        excludedWords.some(word =>
            name.includes(word)
        )
    ) {
        return false;
    }

    return (
        name.includes("kb") ||
        name.includes("mb") ||
        name.includes("gb") ||
        name.includes("tb")
    );
}

/*
 * Clean package name shown to customers.
 */
function cleanPlanName(packageName) {
    let name = String(packageName || "").trim();

    name = name
        .replace(/^N[\d,]+\s*/i, "")
        .trim();

    return name || String(packageName || "").trim();
}

/*
 * Extract data size.
 */
function extractDataSize(planName) {
    const match = String(planName || "").match(
        /(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)/i
    );

    return match ? match[0] : "";
}

/*
 * Extract validity.
 */
function extractValidity(planName) {
    const match = String(planName || "").match(
        /(\d+)\s*(hour|hours|hr|hrs|day|days|week|weeks|month|months|year|years)/i
    );

    return match ? match[0] : "";
}

/*
 * Deactivate packages that should not appear
 * in the MELODEXS CONNECT customer catalog.
 */
async function deactivateInvalidPackages(client, networkName) {
    const storedPlansResult = await client.query(`
        SELECT
            id,
            plan,
            provider_package_name
        FROM data_plans
        WHERE network = $1
          AND source = 'wisesub'
          AND active = 1
    `, [networkName]);

    let deactivated = 0;

    for (const plan of storedPlansResult.rows) {
        const packageName =
            plan.provider_package_name ||
            plan.plan ||
            "";

        if (!isValidDataPackage(packageName)) {
            const updateResult = await client.query(`
                UPDATE data_plans
                SET
                    active = 0,
                    updated_at = NOW()
                WHERE id = $1
            `, [plan.id]);

            deactivated += updateResult.rowCount;
        }
    }

    return deactivated;
}

async function syncNetwork(network) {
    console.log(
        `\n================ ${network.name} ================`
    );

    try {
        const response = await axios.get(
            `${BASE_URL}/packages`,
            {
                params: {
                    service_type: "data",
                    provider_code: network.code
                },
                headers: getHeaders(),
                timeout: 15000
            }
        );

        const packages =
            response.data?.data?.packages || [];

        console.log(
            `WiseSub packages received: ${packages.length}`
        );

        if (!Array.isArray(packages)) {
            console.log(
                "❌ Invalid package response from WiseSub."
            );

            return {
                added: 0,
                updated: 0,
                skipped: 0,
                deactivated: 0,
                failed: 1
            };
        }

        let added = 0;
        let updated = 0;
        let skipped = 0;

        /*
         * Keep track of valid packages returned
         * by WiseSub during this successful sync.
         */
        const validPackageCodes = new Set();

        const client = await pool.connect();

        try {
            await client.query("BEGIN");

            for (const pkg of packages) {
                const packageCode = String(
                    pkg.package_code || ""
                ).trim();

                const packageName = String(
                    pkg.package_name || ""
                ).trim();

                const providerCost = Number(pkg.price);

                if (
                    !packageCode ||
                    !packageName ||
                    !Number.isFinite(providerCost) ||
                    providerCost <= 0
                ) {
                    skipped++;
                    continue;
                }

                if (!isValidDataPackage(packageName)) {
                    skipped++;
                    continue;
                }

                validPackageCodes.add(packageCode);

                const sellingPrice =
                    calculateSellingPrice(providerCost);

                const cleanName =
                    cleanPlanName(packageName);

                const dataSize =
                    extractDataSize(cleanName);

                const validity =
                    extractValidity(cleanName);

                /*
                 * First check by WiseSub package code.
                 */
                const existingByCodeResult =
                    await client.query(`
                        SELECT id
                        FROM data_plans
                        WHERE network = $1
                          AND provider_package_code = $2
                        LIMIT 1
                    `, [
                        network.name,
                        packageCode
                    ]);

                const existingByCode =
                    existingByCodeResult.rows[0];

                if (existingByCode) {
                    await client.query(`
                        UPDATE data_plans
                        SET
                            plan = $1,
                            data_size = $2,
                            provider_cost = $3,
                            selling_price = $4,
                            active = 1,
                            provider = 'wisesub',
                            provider_code = $5,
                            provider_package_code = $6,
                            provider_package_name = $7,
                            validity = $8,
                            source = 'wisesub',
                            last_synced_at = NOW(),
                            updated_at = NOW()
                        WHERE id = $9
                    `, [
                        cleanName,
                        dataSize,
                        providerCost,
                        sellingPrice,
                        network.code,
                        packageCode,
                        packageName,
                        validity,
                        existingByCode.id
                    ]);

                    updated++;
                    continue;
                }

                /*
                 * Check by network + plan name.
                 *
                 * This prevents duplicate plans.
                 */
                const existingByNameResult =
                    await client.query(`
                        SELECT id
                        FROM data_plans
                        WHERE network = $1
                          AND plan = $2
                        LIMIT 1
                    `, [
                        network.name,
                        cleanName
                    ]);

                const existingByName =
                    existingByNameResult.rows[0];

                if (existingByName) {
                    await client.query(`
                        UPDATE data_plans
                        SET
                            data_size = $1,
                            provider_cost = $2,
                            selling_price = $3,
                            active = 1,
                            provider = 'wisesub',
                            provider_code = $4,
                            provider_package_code = $5,
                            provider_package_name = $6,
                            validity = $7,
                            source = 'wisesub',
                            last_synced_at = NOW(),
                            updated_at = NOW()
                        WHERE id = $8
                    `, [
                        dataSize,
                        providerCost,
                        sellingPrice,
                        network.code,
                        packageCode,
                        packageName,
                        validity,
                        existingByName.id
                    ]);

                    updated++;
                    continue;
                }

                /*
                 * Brand-new WiseSub package.
                 */
                await client.query(`
                    INSERT INTO data_plans (
                        network,
                        plan,
                        data_size,
                        provider_cost,
                        selling_price,
                        active,
                        provider,
                        provider_code,
                        provider_package_code,
                        provider_package_name,
                        validity,
                        source,
                        last_synced_at,
                        updated_at
                    )
                    VALUES (
                        $1,
                        $2,
                        $3,
                        $4,
                        $5,
                        1,
                        'wisesub',
                        $6,
                        $7,
                        $8,
                        $9,
                        'wisesub',
                        NOW(),
                        NOW()
                    )
                `, [
                    network.name,
                    cleanName,
                    dataSize,
                    providerCost,
                    sellingPrice,
                    network.code,
                    packageCode,
                    packageName,
                    validity
                ]);

                added++;
            }

            /*
             * Remove invalid packages that may have been
             * stored during an earlier synchronization.
             */
            const deactivated =
                await deactivateInvalidPackages(
                    client,
                    network.name
                );

            await client.query("COMMIT");

            console.log(`Added:        ${added}`);
            console.log(`Updated:      ${updated}`);
            console.log(`Skipped:      ${skipped}`);
            console.log(`Deactivated:  ${deactivated}`);

            return {
                added,
                updated,
                skipped,
                deactivated,
                failed: 0
            };

        } catch (databaseError) {
            try {
                await client.query("ROLLBACK");
            } catch (rollbackError) {
                console.error(
                    "WiseSub sync rollback error:",
                    rollbackError
                );
            }

            throw databaseError;

        } finally {
            client.release();
        }

    } catch (error) {
        console.log(
            `❌ ${network.name} sync failed`
        );

        if (error.response) {
            console.log(
                "HTTP Status:",
                error.response.status
            );

            console.log(
                "Response:",
                JSON.stringify(
                    error.response.data,
                    null,
                    2
                )
            );
        } else {
            console.log(
                "Error:",
                error.message
            );
        }

        return {
            added: 0,
            updated: 0,
            skipped: 0,
            deactivated: 0,
            failed: 1
        };
    }
}

async function main() {
    console.log(
        "🚀 MELODEXS CONNECT WiseSub Data Plan Sync"
    );

    console.log(
        "===================================="
    );

    if (!process.env.DATABASE_URL) {
        console.error(
            "❌ DATABASE_URL is missing from .env"
        );

        process.exitCode = 1;
        return;
    }

    if (!process.env.WISESUB_API_KEY) {
        console.error(
            "❌ WISESUB_API_KEY is missing from .env"
        );

        process.exitCode = 1;
        return;
    }

    if (!process.env.WISESUB_API_SECRET) {
        console.error(
            "❌ WISESUB_API_SECRET is missing from .env"
        );

        process.exitCode = 1;
        return;
    }

    const markupPercent = Number(
        process.env.CHEAPDATA_MARKUP_PERCENT || 2
    );

    console.log(
        "Environment:",
        process.env.WISESUB_ENVIRONMENT || "test"
    );

    console.log(
        "Base URL:",
        BASE_URL
    );

    console.log(
        "MELODEXS CONNECT markup:",
        `${markupPercent}%`
    );

    console.log(
        "Pricing:",
        "Markup + round UP to whole naira"
    );

    const totals = {
        added: 0,
        updated: 0,
        skipped: 0,
        deactivated: 0,
        failed: 0
    };

    for (const network of NETWORKS) {
        const result =
            await syncNetwork(network);

        totals.added += result.added;
        totals.updated += result.updated;
        totals.skipped += result.skipped;
        totals.deactivated +=
            result.deactivated;
        totals.failed += result.failed;
    }

    console.log(
        "\n===================================="
    );

    console.log(
        "✅ SYNC FINISHED"
    );

    console.log(
        "===================================="
    );

    console.log(
        "Added:        ",
        totals.added
    );

    console.log(
        "Updated:      ",
        totals.updated
    );

    console.log(
        "Skipped:      ",
        totals.skipped
    );

    console.log(
        "Deactivated:  ",
        totals.deactivated
    );

    console.log(
        "Failed:       ",
        totals.failed
    );

    /*
     * Show active WiseSub plans.
     */
    const plansResult = await pool.query(`
        SELECT
            id,
            network,
            plan,
            provider_cost,
            selling_price,
            provider_package_code
        FROM data_plans
        WHERE source = 'wisesub'
          AND active = 1
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

    const plans = plansResult.rows;

    console.log(
        "\n📦 ACTIVE WISESUB PLANS IN MELODEXS CONNECT"
    );

    console.log(
        "===================================="
    );

    if (plans.length === 0) {
        console.log(
            "No active WiseSub plans were found."
        );
    } else {
        for (const plan of plans) {
            console.log(
                `${plan.network} | ${plan.plan} | Provider ₦${plan.provider_cost} | Sell ₦${plan.selling_price} | ${plan.provider_package_code}`
            );
        }
    }

    if (totals.failed > 0) {
        process.exitCode = 1;
    }
}

main()
    .catch(error => {
        console.error(
            "❌ Sync crashed:"
        );

        console.error(error);

        process.exitCode = 1;
    })
    .finally(async () => {
        await pool.end();
    });
