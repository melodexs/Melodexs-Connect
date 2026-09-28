const express = require("express");
const { requireAuth } = require("../auth");
const {
    setPurchasePin,
    changePurchasePin,
    verifyPurchasePin
} = require("../controllers/purchase-pin.controller");

const router = express.Router();

router.post("/purchase-pin/set", requireAuth, setPurchasePin);
router.post("/purchase-pin/change", requireAuth, changePurchasePin);
router.post("/purchase-pin/verify", requireAuth, verifyPurchasePin);

module.exports = router;
