require("dotenv").config();
const { getServices } = require("../src/services/wisesub.service");

async function testWiseSub() {
    try {
        const response = await getServices({
            baseUrl: process.env.WISESUB_BASE_URL,
            defaultEnvironment: false,
            emptyMissingCredentials: false
        });

        console.log("✅ WiseSub connection successful!");
        console.log(JSON.stringify(response.data, null, 2));

    } catch (error) {
        console.log("❌ WiseSub connection failed!");

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

testWiseSub();