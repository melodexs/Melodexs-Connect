const express = require("express");
const { requireAuth } = require("../auth");
const {
    getTransactionsByUser
} = require("../controllers/transaction.controller");

const router = express.Router();

router.get("/transactions/:userId", requireAuth, getTransactionsByUser);

module.exports = router;
