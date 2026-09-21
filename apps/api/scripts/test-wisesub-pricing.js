require("dotenv").config();
const axios = require("axios");

const networks = [
    {
        name: "MTN",
        code: "mtn"
    },
    {
        name: "Airtel",
        code: "airtel"
    },
    {
        name: "Glo",
        code: "glo"
    },
    {
        name: "9mobile",
        code: "9mobile"
    }
];

async function getPackages(network) {
    try {
        const response = await axios.get(
            `${process.env.WISESUB_BASE_URL}/packages`,
            {
                params: {
                    service_type: "data",
                    provider_code: network.code
                },
                headers: {
                    Authorization:
                        `Bearer ${process.env.WISESUB_API_KEY}`,

                    "X-API-Secret":
                        process.env.WISESUB_API_SECRET,

                    "X-Environment":
                        process.env.WISESUB_ENVIRONMENT,

                    Accept: "application/json"
                }
            }
        );

        return response.data?.data?.packages || [];
    } catch (error) {
        console.log(
            `❌ Failed to load ${network.name}`
        );

        if (error.response) {
            console.log(
                JSON.stringify(
                    error.response.data,
                    null,
                    2
                )
            );
        } else {
            console.log(error.message);
        }

        return [];
    }
}

function suggestedPrice(providerCost) {
    /*
     * MELODEXS CONNECT markup.
     *
     * Change this later when we decide
     * exactly how much profit to make.
     */

    const markup = 0.05;

    return Math.ceil(
        providerCost * (1 + markup)
    );
}

async function main() {
    console.log("");
    console.log(
        "=========================================="
    );
    console.log(
        "       CHEAPDATA WISESUB PRICING"
    );
    console.log(
        "=========================================="
    );
    console.log("");

    for (const network of networks) {
        console.log(
            `\n================ ${network.name} ================`
        );

        const packages =
            await getPackages(network);

        if (!packages.length) {
            console.log(
                "No packages found."
            );
            continue;
        }

        for (const plan of packages) {
            const providerCost =
                Number(plan.price);

            if (
                !Number.isFinite(
                    providerCost
                )
            ) {
                continue;
            }

            const sellingPrice =
                suggestedPrice(
                    providerCost
                );

            const profit =
                sellingPrice -
                providerCost;

            console.log("");
            console.log(
                `Plan: ${plan.package_name}`
            );
            console.log(
                `Code: ${plan.package_code}`
            );
            console.log(
                `WiseSub cost: ₦${providerCost.toFixed(2)}`
            );
            console.log(
                `Suggested price: ₦${sellingPrice.toFixed(2)}`
            );
            console.log(
                `MELODEXS CONNECT profit: ₦${profit.toFixed(2)}`
            );
        }
    }

    console.log("");
    console.log(
        "=========================================="
    );
    console.log(
        "             PRICING COMPLETE"
    );
    console.log(
        "=========================================="
    );
}

main();