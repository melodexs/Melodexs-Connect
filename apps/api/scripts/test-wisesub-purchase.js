const path = require("path");
const axios = require("axios");
const dotenv = require("dotenv");

// Always load the .env file from the MELODEXS CONNECT project root.
dotenv.config({
    path: path.resolve(__dirname, "../../../.env")
});

const BASE_URL = process.env.WISESUB_BASE_URL;
const API_KEY = process.env.WISESUB_API_KEY;
const API_SECRET = process.env.WISESUB_API_SECRET;
const ENVIRONMENT = process.env.WISESUB_ENVIRONMENT || "test";

async function testPurchase() {
    console.log("🚀 Testing WiseSub sandbox purchase...");
    console.log("====================================");
    console.log("Environment:", ENVIRONMENT);
    console.log("Base URL:", BASE_URL);
    console.log("");

    if (!BASE_URL) {
        console.error("❌ WISESUB_BASE_URL is missing from .env");
        process.exit(1);
    }

    if (!API_KEY || !API_SECRET) {
        console.error("❌ WiseSub API credentials are missing from .env");
        process.exit(1);
    }

    try {
        const response = await axios.post(
            `${BASE_URL}/purchase`,
            {
                service_type: "data",
                provider_code: "mtn",
                package_code: "mtn-10mb-100",
                recipient: "08011111111"
            },
            {
                headers: {
                    Authorization: `Bearer ${API_KEY}`,
                    "X-API-Secret": API_SECRET,
                    "X-Environment": ENVIRONMENT,
                    Accept: "application/json",
                    "Content-Type": "application/json"
                },
                timeout: 30000
            }
        );

        console.log("✅ WiseSub purchase request completed");
        console.log("HTTP status:", response.status);
        console.log("");
        console.log("WiseSub response:");
        console.log(JSON.stringify(response.data, null, 2));

    } catch (error) {
        console.error("❌ WiseSub purchase request failed");

        if (error.response) {
            console.error("HTTP status:", error.response.status);
            console.error("");
            console.error(
                "WiseSub response:",
                JSON.stringify(error.response.data, null, 2)
            );
        } else {
            console.error("Error:", error.message);
        }

        process.exit(1);
    }
}

testPurchase();
