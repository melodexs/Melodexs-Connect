const { Pool } = require("pg");

if (!process.env.DATABASE_URL) {
    throw new Error(
        "DATABASE_URL is not configured. PostgreSQL connection cannot start."
    );
}

const pool = new Pool({
    connectionString: process.env.DATABASE_URL,
    ssl: {
        rejectUnauthorized: false
    },
    max: 10,
    idleTimeoutMillis: 30000,
    connectionTimeoutMillis: 30000
});

pool.on("error", (error) => {
    console.error("Unexpected PostgreSQL pool error:", error);
});

async function testPostgresConnection() {
    const result = await pool.query(`
        SELECT
            current_database() AS database,
            version() AS version
    `);

    console.log(
        `PostgreSQL connected to database: ${result.rows[0].database}`
    );

    return result.rows[0];
}

module.exports = {
    pool,
    testPostgresConnection
};
