const { requireAuth } = require("../middleware/auth.middleware");
const { rateLimit } = require("express-rate-limit");
const {
    sessionCheck,
    getUser,
    register,
    login,
    logout,
    setPurchasePin,
    changePurchasePin,
    verifyPurchasePin,
    forgotPassword,
    resetPassword
} = require("../controllers/auth.controller");

function registerAuthRoutes(app) {
    app.get("/api/session", sessionCheck);

    app.get("/api/user/:id", requireAuth, getUser);

    const loginLimiter = rateLimit({
        windowMs: 15 * 60 * 1000,
        limit: 10,
        standardHeaders: "draft-8",
        legacyHeaders: false,
        message: {
            success: false,
            message: "Too many login attempts. Please try again later."
        }
    });

    const registerLimiter = rateLimit({
        windowMs: 60 * 60 * 1000,
        limit: 10,
        standardHeaders: "draft-8",
        legacyHeaders: false,
        message: {
            success: false,
            message: "Too many registration attempts. Please try again later."
        }
    });

    app.post("/api/register", registerLimiter, register);

    app.post("/api/login", loginLimiter, login);

    app.post("/api/logout", logout);

    app.post("/api/purchase-pin/set", requireAuth, setPurchasePin);
    app.post("/api/purchase-pin/change", requireAuth, changePurchasePin);
    app.post("/api/purchase-pin/verify", requireAuth, verifyPurchasePin);

    const forgotPasswordLimiter = rateLimit({
        windowMs: 15 * 60 * 1000,
        limit: 5,
        standardHeaders: "draft-8",
        legacyHeaders: false,
        message: {
            success: false,
            message: "Too many password reset requests. Please try again later."
        }
    });

    const resetPasswordLimiter = rateLimit({
        windowMs: 15 * 60 * 1000,
        limit: 10,
        standardHeaders: "draft-8",
        legacyHeaders: false,
        message: {
            success: false,
            message: "Too many password reset attempts. Please try again later."
        }
    });

    app.post("/api/forgot-password", forgotPasswordLimiter, forgotPassword);
    app.post("/api/reset-password", resetPasswordLimiter, resetPassword);
}

module.exports = {
    registerAuthRoutes
};
