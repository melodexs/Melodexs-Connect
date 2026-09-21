const path = require("path");

// Always load the root MELODEXS CONNECT .env file.
// config.js is located at: apps/api/src/config.js
require("dotenv").config({
    path: path.resolve(__dirname, "../../../.env")
});

if (!process.env.SESSION_SECRET) {
    if (process.env.NODE_ENV === "production") {
        console.error(
            "SESSION_SECRET is not set. Refusing to start in production without it."
        );
        process.exit(1);
    }

    console.warn(
        "SESSION_SECRET is not set. Using an insecure development-only fallback."
    );
}

const DB_PATH =
    process.env.DB_PATH ||
    path.join(__dirname, "../data/cheapdata.db");

const WEB_PUBLIC_DIR = path.join(__dirname, "../../web");

module.exports = {
    DB_PATH,
    WEB_PUBLIC_DIR,
    PORT: Number(process.env.PORT || 3000),
    SESSION_SECRET:
        process.env.SESSION_SECRET || "dev-only-insecure-secret"
};
