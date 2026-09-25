const { requireAuth } = require("../middleware/auth.middleware");
const { fundWallet, verifyFundWallet } = require("../controllers/wallet.controller");

function registerWalletRoutes(app) {
    app.post("/api/fund-wallet", requireAuth, fundWallet);
    app.post("/api/fund-wallet/verify", requireAuth, verifyFundWallet);
}

module.exports = {
    registerWalletRoutes
};
