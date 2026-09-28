require("dotenv").config();
const { getDataPackages } = require("../src/services/wisesub.service");

async function testMTN() {
    try {
        console.log("🚀 Requesting MTN plans from WiseSub...\n");

        const response = await getDataPackages("mtn", {
            baseUrl: process.env.WISESUB_BASE_URL,
            defaultEnvironment: false,
            emptyMissingCredentials: false,
            timeout: null
        });

        console.log("✅ MTN request successful!\n");

        console.log(
            JSON.stringify(response.data, null, 2)
        );

    } catch (error) {
        console.log("❌ MTN request failed!");

        if (error.response) {
            console.log("Status:", error.response.status);
            console.log(
                JSON.stringify(error.response.data, null, 2)
            );
        } else {
            console.log(error.message);
        }
    }
}

testMTN();