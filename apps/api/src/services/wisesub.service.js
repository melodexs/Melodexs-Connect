const axios = require("axios");

function _getConfigFromEnv() {
    const baseUrl = process.env.WISESUB_BASE_URL;
    const apiKey = process.env.WISESUB_API_KEY;
    const apiSecret = process.env.WISESUB_API_SECRET;
    const environment = process.env.WISESUB_ENVIRONMENT || "test";

    return { baseUrl, apiKey, apiSecret, environment };
}

async function purchaseData({ reference, provider_code, package_code, recipient }) {
    const { baseUrl, apiKey, apiSecret, environment } = _getConfigFromEnv();

    const body = {
        service_type: "data",
        reference,
        provider_code,
        package_code,
        recipient
    };

    const res = await axios.post(
        `${baseUrl}/purchase`,
        body,
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

    return res;
}

async function purchaseAirtime({ reference, provider_code, recipient, amount }) {
    const { baseUrl, apiKey, apiSecret, environment } = _getConfigFromEnv();

    const body = {
        service_type: "airtime",
        reference,
        provider_code,
        recipient,
        amount
    };

    const res = await axios.post(
        `${baseUrl}/purchase`,
        body,
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

    return res;
}

module.exports = {
    purchaseData,
    purchaseAirtime
};
