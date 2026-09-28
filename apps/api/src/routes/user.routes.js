const express = require("express");
const { requireAuth } = require("../auth");
const {
    getStatus,
    getUserProfile
} = require("../controllers/user.controller");

const router = express.Router();

router.get("/status", getStatus);
router.get("/user/:id", requireAuth, getUserProfile);

module.exports = router;
