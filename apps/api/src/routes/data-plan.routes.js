const express = require("express");
const { requireAuth, requireAdmin } = require("../auth");
const {
    getDataPlans,
    getAdminDataPlans,
    createDataPlan,
    updateDataPlan
} = require("../controllers/data-plan.controller");

const router = express.Router();

router.get("/data-plans", getDataPlans);
router.get("/admin/data-plans", requireAuth, requireAdmin, getAdminDataPlans);
router.post("/admin/data-plans", requireAuth, requireAdmin, createDataPlan);
router.patch("/admin/data-plans/:id", requireAuth, requireAdmin, updateDataPlan);

module.exports = router;
