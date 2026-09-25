const axios = require("axios");

async function purchaseWithWiseSub({ baseUrl, apiKey, apiSecret, environment, body }) {
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
    purchaseWithWiseSub
};
