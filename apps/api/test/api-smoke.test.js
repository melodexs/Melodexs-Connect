const assert = require("assert");
const http = require("http");
const path = require("path");
const dotenv = require("dotenv");

// Load the project's .env BEFORE importing the application.
dotenv.config({
    path: path.join(__dirname, "../../../.env")
});

process.env.NODE_ENV = "test";
process.env.SESSION_SECRET = "test-only-session-secret";

const { app, sessionStore } = require("../src/app");
const { pool } = require("../src/postgres");

function request(server, requestPath) {
    return new Promise((resolve, reject) => {
        const address = server.address();

        const host =
            address.address === "::"
                ? "localhost"
                : address.address;

        const request = http.get(
            `http://${host}:${address.port}${requestPath}`,
            response => {
                let body = "";

                response.setEncoding("utf8");

                response.on(
                    "data",
                    chunk => {
                        body += chunk;
                    }
                );

                response.on(
                    "end",
                    () => {
                        resolve({
                            statusCode: response.statusCode,
                            body
                        });
                    }
                );
            }
        );

        request.on("error", reject);
    });
}

async function run() {
    const server = app.listen(0);

    try {
    // Wait for the PostgreSQL session store
    // to finish creating its required tables.
    await sessionStore.ready;

    // Verify PostgreSQL is available.
    await pool.query("SELECT 1");

        const status = await request(
            server,
            "/api/status"
        );

        assert.strictEqual(
            status.statusCode,
            200
        );

        assert.strictEqual(
            JSON.parse(status.body).success,
            true
        );

        const page = await request(
            server,
            "/index.html"
        );

        assert.strictEqual(
            page.statusCode,
            200
        );

        assert.match(
            page.body,
            /MELODEXS CONNECT/i
        );

        console.log(
            "API PostgreSQL test environment smoke test passed"
        );

    } finally {
        await new Promise(
            resolve => server.close(resolve)
        );

        await pool.end();
    }
}

run().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
