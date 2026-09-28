const express = require("express");
const { requireAuth } = require("../auth");
const {
    purchaseData,
    purchaseAirtime
} = require("../controllers/purchase.controller");

const router = express.Router();

router.post("/purchase-data", requireAuth, purchaseData);
router.post("/purchase-airtime", requireAuth, purchaseAirtime);

module.exports = router;
