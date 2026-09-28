const axios = require("axios");

function getWiseSubConfig() {
    const baseUrl = process.env.WISESUB_BASE_URL;
    const apiKey = process.env.WISESUB_API_KEY;
    const apiSecret = process.env.WISESUB_API_SECRET;
    const environment = process.env.WISESUB_ENVIRONMENT || "test";

    if (!baseUrl || !apiKey || !apiSecret) {
        throw new Error("WiseSub configuration is incomplete.");
    }

    return {
        baseUrl,
        apiKey,
        apiSecret,
        environment
    };
}

async function purchaseData({
    reference,
    providerCode,
    packageCode,
    recipient
}) {
    const {
        baseUrl,
        apiKey,
        apiSecret,
        environment
    } = getWiseSubConfig();

    return axios.post(
        `${baseUrl}/purchase`,
        {
            service_type: "data",
            reference,
            provider_code: providerCode,
            package_code: packageCode,
            recipient
        },
        {
            headers: {
                Authorization: `Bearer ${apiKey}`,
                "X-API-Secret": apiSecret,
                "X-Environment": environment,
                Accept: "application/json",
                "Content-Type": "application/json"
            },
            timeout: 30000
        }
    );
}

async function purchaseAirtime({
    reference,
    providerCode,
    recipient,
    amount
}) {
    const {
        baseUrl,
        apiKey,
        apiSecret,
        environment
    } = getWiseSubConfig();

    return axios.post(
        `${baseUrl}/purchase`,
        {
            service_type: "airtime",
            reference,
            provider_code: providerCode,
            recipient,
            amount
        },
        {
            headers: {
                Authorization: `Bearer ${apiKey}`,
                "X-API-Secret": apiSecret,
                "X-Environment": environment,
                Accept: "application/json",
                "Content-Type": "application/json"
            },
            timeout: 30000
        }
    );
}

module.exports = {
    purchaseData,
    purchaseAirtime
};
