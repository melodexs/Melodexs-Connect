const express = require("express");
const { requireAuth } = require("../auth");
const {
    fundWallet,
    paystackWebhook,
    verifyFundWallet
} = require("../controllers/paystack.controller");

const router = express.Router();
const webhookRouter = express.Router();

webhookRouter.post(
    "/paystack/webhook",
    express.raw({ type: "application/json" }),
    paystackWebhook
);

router.post("/fund-wallet", requireAuth, fundWallet);
router.post("/fund-wallet/verify", requireAuth, verifyFundWallet);

module.exports = {
    router,
    webhookRouter
};
