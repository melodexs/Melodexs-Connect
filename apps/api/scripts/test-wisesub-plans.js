const path = require("path");
const dotenv = require("dotenv");

// Always load the .env file from the MELODEXS CONNECT project root.
dotenv.config({
    path: path.resolve(__dirname, "../../../.env")
});

const { getDataPackages } = require("../src/services/wisesub.service");

const BASE_URL = process.env.WISESUB_BASE_URL;
const API_KEY = process.env.WISESUB_API_KEY;
const API_SECRET = process.env.WISESUB_API_SECRET;
const ENVIRONMENT = process.env.WISESUB_ENVIRONMENT || "test";

if (!BASE_URL) {
    console.error("❌ WISESUB_BASE_URL is missing from .env");
    process.exit(1);
}

if (!API_KEY || !API_SECRET) {
    console.error("❌ WiseSub API credentials are missing from .env");
    process.exit(1);
}

async function getPlans(network) {
    try {
        const response = await getDataPackages(network, {
            baseUrl: BASE_URL,
            timeout: 15000
        });

        console.log(`\n================ ${network.toUpperCase()} ================`);

        const packages = response.data?.data?.packages || [];

        console.log(`Found ${packages.length} packages.\n`);

        packages.forEach((pkg, index) => {
            console.log(
                `${index + 1}. ${pkg.package_name || "Unknown"}`
            );
            console.log(`   Code: ${pkg.package_code || "N/A"}`);
            console.log(`   Price: ₦${pkg.price ?? "N/A"}`);
        });

    } catch (error) {
        console.log(`\n❌ Failed to get ${network} plans`);

        if (error.response) {
            console.log("Status:", error.response.status);
            console.log(
                "Response:",
                JSON.stringify(error.response.data, null, 2)
            );
        } else {
            console.log("Error:", error.message);
        }
    }
}

async function testWiseSubPlans() {
    console.log("🚀 Checking WiseSub data plans...\n");
    console.log(`Environment: ${ENVIRONMENT}`);
    console.log(`Base URL: ${BASE_URL}`);

    await getPlans("mtn");
    await getPlans("glo");
    await getPlans("airtel");
    await getPlans("9mobile");
}

testWiseSubPlans();
