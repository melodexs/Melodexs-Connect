const express = require("express");
const { webhookHandler } = require("../controllers/paystack.controller");

function registerPaystackRoutes(app) {
    // Must be registered before express.json() is used in app.js
    app.post(
        "/api/paystack/webhook",
        express.raw({ type: "application/json" }),
        webhookHandler
    );
}

module.exports = {
    registerPaystackRoutes
};
