const express = require("express");
const { rateLimit } = require("express-rate-limit");
const {
    getSession,
    register,
    login
} = require("../controllers/auth.controller");

const router = express.Router();

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

router.get("/session", getSession);
router.post("/register", registerLimiter, register);
router.post("/login", loginLimiter, login);

module.exports = router;
