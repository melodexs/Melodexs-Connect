const axios = require("axios");

async function sendBrevoEmail({ to, subject, htmlContent }) {
    if (
        !process.env.BREVO_API_KEY ||
        !process.env.BREVO_FROM_EMAIL
    ) {
        throw new Error("Brevo email configuration is missing.");
    }

    const response = await axios.post(
        "https://api.brevo.com/v3/smtp/email",
        {
            sender: {
                name: process.env.BREVO_FROM_NAME || "MELODEXS CONNECT",
                email: process.env.BREVO_FROM_EMAIL
            },
            to: [
                {
                    email: to
                }
            ],
            subject,
            htmlContent
        },
        {
            headers: {
                "api-key": process.env.BREVO_API_KEY,
                "Content-Type": "application/json",
                Accept: "application/json"
            },
            timeout: 10000
        }
    );

    return response.data;
}

module.exports = {
    sendBrevoEmail
};
