const { requireAuth } = require("../middleware/auth.middleware");
const { purchaseData, purchaseAirtime, getDataPlans } = require("../controllers/purchase.controller");

function registerPurchaseRoutes(app) {
    app.post("/api/purchase-data", requireAuth, purchaseData);
    app.post("/api/purchase-airtime", requireAuth, purchaseAirtime);
    app.get("/api/data-plans", getDataPlans);
}

module.exports = {
    registerPurchaseRoutes
};
