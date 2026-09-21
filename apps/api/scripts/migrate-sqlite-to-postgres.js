const Database = require("better-sqlite3");
const { Client } = require("pg");
const path = require("path");
require("dotenv").config();

const PROJECT_ROOT = path.resolve(__dirname, "../../..");

const sqlitePath = path.join(
    PROJECT_ROOT,
    "apps/api/data/cheapdata.db"
);

const sqlite = new Database(sqlitePath, {
    readonly: true
});

const postgres = new Client({
    connectionString: process.env.DATABASE_URL,
    ssl: {
        rejectUnauthorized: false
    }
});

async function createTables() {
    await postgres.query(`
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            phone TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            purchase_pin TEXT,
            balance DOUBLE PRECISION NOT NULL DEFAULT 0,
            virtual_account_number TEXT,
            virtual_bank_name TEXT,
            kyc_status TEXT NOT NULL DEFAULT 'pending',
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reset_token_hash TEXT,
            reset_token_expires_at BIGINT
        )
    `);

    await postgres.query(`
        CREATE TABLE IF NOT EXISTS data_plans (
            id INTEGER PRIMARY KEY,
            network TEXT NOT NULL,
            plan_name TEXT,
            plan TEXT NOT NULL,
            data_size TEXT,
            provider_cost DOUBLE PRECISION NOT NULL DEFAULT 0,
            selling_price DOUBLE PRECISION NOT NULL,
            status TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            provider TEXT,
            provider_code TEXT,
            provider_package_code TEXT,
            provider_package_name TEXT,
            validity TEXT,
            source TEXT,
            last_synced_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(network, plan)
        )
    `);

    await postgres.query(`
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            amount DOUBLE PRECISION NOT NULL,
            status TEXT NOT NULL,
            reference TEXT,
            description TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    `);

    await postgres.query(`
        CREATE TABLE IF NOT EXISTS sessions (
            sid TEXT PRIMARY KEY,
            sess TEXT NOT NULL,
            expire BIGINT NOT NULL
        )
    `);

    await postgres.query(`
        CREATE INDEX IF NOT EXISTS idx_sessions_expire
        ON sessions(expire)
    `);
}

async function migrateUsers() {
    const users = sqlite.prepare(`
        SELECT
            id,
            name,
            email,
            phone,
            password,
            purchase_pin,
            balance,
            virtual_account_number,
            virtual_bank_name,
            kyc_status,
            is_admin,
            created_at,
            reset_token_hash,
            reset_token_expires_at
        FROM users
        ORDER BY id
    `).all();

    for (const user of users) {
        await postgres.query(
            `
            INSERT INTO users (
                id,
                name,
                email,
                phone,
                password,
                purchase_pin,
                balance,
                virtual_account_number,
                virtual_bank_name,
                kyc_status,
                is_admin,
                created_at,
                reset_token_hash,
                reset_token_expires_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8,
                $9, $10, $11, $12, $13, $14
            )
            ON CONFLICT (id)
            DO UPDATE SET
                name = EXCLUDED.name,
                email = EXCLUDED.email,
                phone = EXCLUDED.phone,
                password = EXCLUDED.password,
                purchase_pin = EXCLUDED.purchase_pin,
                balance = EXCLUDED.balance,
                virtual_account_number = EXCLUDED.virtual_account_number,
                virtual_bank_name = EXCLUDED.virtual_bank_name,
                kyc_status = EXCLUDED.kyc_status,
                is_admin = EXCLUDED.is_admin,
                created_at = EXCLUDED.created_at,
                reset_token_hash = EXCLUDED.reset_token_hash,
                reset_token_expires_at = EXCLUDED.reset_token_expires_at
            `,
            [
                user.id,
                user.name,
                user.email,
                user.phone,
                user.password,
                user.purchase_pin,
                user.balance,
                user.virtual_account_number,
                user.virtual_bank_name,
                user.kyc_status,
                user.is_admin,
                user.created_at,
                user.reset_token_hash,
                user.reset_token_expires_at
            ]
        );
    }

    return users.length;
}

async function migrateDataPlans() {
    const plans = sqlite.prepare(`
        SELECT
            id,
            network,
            plan_name,
            data_size,
            provider_cost,
            selling_price,
            status,
            created_at,
            provider,
            provider_code,
            provider_package_code,
            provider_package_name,
            validity,
            source,
            last_synced_at,
            plan,
            active,
            updated_at
        FROM data_plans
        ORDER BY id
    `).all();

    for (const plan of plans) {
        await postgres.query(
            `
            INSERT INTO data_plans (
                id,
                network,
                plan_name,
                plan,
                data_size,
                provider_cost,
                selling_price,
                status,
                created_at,
                provider,
                provider_code,
                provider_package_code,
                provider_package_name,
                validity,
                source,
                last_synced_at,
                active,
                updated_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8,
                $9, $10, $11, $12, $13, $14, $15,
                $16, $17, $18
            )
            ON CONFLICT (id)
            DO UPDATE SET
                network = EXCLUDED.network,
                plan_name = EXCLUDED.plan_name,
                plan = EXCLUDED.plan,
                data_size = EXCLUDED.data_size,
                provider_cost = EXCLUDED.provider_cost,
                selling_price = EXCLUDED.selling_price,
                status = EXCLUDED.status,
                created_at = EXCLUDED.created_at,
                provider = EXCLUDED.provider,
                provider_code = EXCLUDED.provider_code,
                provider_package_code = EXCLUDED.provider_package_code,
                provider_package_name = EXCLUDED.provider_package_name,
                validity = EXCLUDED.validity,
                source = EXCLUDED.source,
                last_synced_at = EXCLUDED.last_synced_at,
                active = EXCLUDED.active,
                updated_at = EXCLUDED.updated_at
            `,
            [
                plan.id,
                plan.network,
                plan.plan_name,
                plan.plan,
                plan.data_size,
                plan.provider_cost,
                plan.selling_price,
                plan.status,
                plan.created_at,
                plan.provider,
                plan.provider_code,
                plan.provider_package_code,
                plan.provider_package_name,
                plan.validity,
                plan.source,
                plan.last_synced_at,
                plan.active,
                plan.updated_at
            ]
        );
    }

    return plans.length;
}

async function migrateTransactions() {
    const transactions = sqlite.prepare(`
        SELECT
            id,
            user_id,
            type,
            amount,
            status,
            reference,
            description,
            created_at
        FROM transactions
        ORDER BY id
    `).all();

    for (const transaction of transactions) {
        await postgres.query(
            `
            INSERT INTO transactions (
                id,
                user_id,
                type,
                amount,
                status,
                reference,
                description,
                created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (id)
            DO UPDATE SET
                user_id = EXCLUDED.user_id,
                type = EXCLUDED.type,
                amount = EXCLUDED.amount,
                status = EXCLUDED.status,
                reference = EXCLUDED.reference,
                description = EXCLUDED.description,
                created_at = EXCLUDED.created_at
            `,
            [
                transaction.id,
                transaction.user_id,
                transaction.type,
                transaction.amount,
                transaction.status,
                transaction.reference,
                transaction.description,
                transaction.created_at
            ]
        );
    }

    return transactions.length;
}

async function migrateSessions() {
    const exists = sqlite.prepare(`
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        AND name = 'sessions'
    `).get();

    if (!exists) {
        return 0;
    }

    const sessions = sqlite.prepare(`
        SELECT sid, sess, expire
        FROM sessions
    `).all();

    for (const currentSession of sessions) {
        await postgres.query(
            `
            INSERT INTO sessions (
                sid,
                sess,
                expire
            )
            VALUES ($1, $2, $3)
            ON CONFLICT (sid)
            DO UPDATE SET
                sess = EXCLUDED.sess,
                expire = EXCLUDED.expire
            `,
            [
                currentSession.sid,
                currentSession.sess,
                currentSession.expire
            ]
        );
    }

    return sessions.length;
}

async function verifyMigration() {
    const users = await postgres.query(
        "SELECT COUNT(*)::int AS count FROM users"
    );

    const plans = await postgres.query(
        "SELECT COUNT(*)::int AS count FROM data_plans"
    );

    const transactions = await postgres.query(
        "SELECT COUNT(*)::int AS count FROM transactions"
    );

    const sessions = await postgres.query(
        "SELECT COUNT(*)::int AS count FROM sessions"
    );

    console.log("");
    console.log("POSTGRESQL VERIFICATION");
    console.log("------------------------");
    console.log("Users:", users.rows[0].count);
    console.log("Data plans:", plans.rows[0].count);
    console.log("Transactions:", transactions.rows[0].count);
    console.log("Sessions:", sessions.rows[0].count);
}

async function main() {
    console.log("Starting SQLite -> PostgreSQL migration...");
    console.log("SQLite source:", sqlitePath);

    await postgres.connect();

    console.log("PostgreSQL connection: SUCCESS");

    await createTables();

    console.log("PostgreSQL tables: READY");

    const users = await migrateUsers();
    console.log(`Users migrated: ${users}`);

    const plans = await migrateDataPlans();
    console.log(`Data plans migrated: ${plans}`);

    const transactions = await migrateTransactions();
    console.log(`Transactions migrated: ${transactions}`);

    const sessions = await migrateSessions();
    console.log(`Sessions migrated: ${sessions}`);

    await verifyMigration();

    console.log("");
    console.log("MIGRATION COMPLETED SUCCESSFULLY");
    console.log("SQLite database was NOT modified.");
}

main()
    .catch(error => {
        console.error("");
        console.error("MIGRATION FAILED");
        console.error(error);
        process.exitCode = 1;
    })
    .finally(async () => {
        sqlite.close();
        await postgres.end().catch(() => {});
    });