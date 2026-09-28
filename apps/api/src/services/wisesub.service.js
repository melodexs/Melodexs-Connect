const axios = require("axios");

function getWiseSubBaseUrl() {
    return process.env.WISESUB_BASE_URL ||
        "https://app.wisesub.com.ng/api/partner/v1";
}

function getWiseSubHeaders({
    defaultEnvironment = true,
    emptyMissingCredentials = true
} = {}) {
    const environment = defaultEnvironment
        ? process.env.WISESUB_ENVIRONMENT || "test"
        : process.env.WISESUB_ENVIRONMENT;

    const apiKey = emptyMissingCredentials
        ? process.env.WISESUB_API_KEY || ""
        : process.env.WISESUB_API_KEY;
    const apiSecret = emptyMissingCredentials
        ? process.env.WISESUB_API_SECRET || ""
        : process.env.WISESUB_API_SECRET;

    return {
        Authorization: `Bearer ${apiKey}`,
        "X-API-Secret": apiSecret,
        "X-Environment": environment,
        Accept: "application/json"
    };
}

function getRequestBaseUrl(options) {
    return Object.prototype.hasOwnProperty.call(options, "baseUrl")
        ? options.baseUrl
        : getWiseSubBaseUrl();
}

async function getServices(options = {}) {
    return axios.get(
        `${getRequestBaseUrl(options)}/services`,
        {
            headers: getWiseSubHeaders(options)
        }
    );
}

async function getDataPackages(providerCode, options = {}) {
    const requestOptions = {
        params: {
            service_type: "data",
            provider_code: providerCode
        },
        headers: getWiseSubHeaders(options)
    };
    const timeout = Object.prototype.hasOwnProperty.call(options, "timeout")
        ? options.timeout
        : 15000;

    if (timeout !== null) {
        requestOptions.timeout = timeout;
    }

    return axios.get(
        `${getRequestBaseUrl(options)}/packages`,
        requestOptions
    );
}

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
    getWiseSubBaseUrl,
    getServices,
    getDataPackages,
    purchaseData,
    purchaseAirtime
};
