const express = require("express");
const { requireAuth, requireAdmin } = require("../auth");
const {
    getAdminStats,
    getAdminUsers,
    getAdminTransactions
} = require("../controllers/admin.controller");

const router = express.Router();

router.get("/admin/stats", requireAuth, requireAdmin, getAdminStats);
router.get("/admin/users", requireAuth, requireAdmin, getAdminUsers);
router.get("/admin/transactions", requireAuth, requireAdmin, getAdminTransactions);

module.exports = router;
