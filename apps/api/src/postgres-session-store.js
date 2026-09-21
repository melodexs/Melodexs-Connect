const session = require("express-session");
const { pool } = require("./postgres");

class PostgresSessionStore extends session.Store {
    constructor(options = {}) {
        super();

        this.cleanupIntervalMs =
            options.cleanupIntervalMs || 15 * 60 * 1000;

        this.ready = this.initialize();

        this.cleanupTimer = setInterval(() => {
            this.cleanupExpired();
        }, this.cleanupIntervalMs);

        this.cleanupTimer.unref();
    }

    async initialize() {
        await pool.query(`
            CREATE TABLE IF NOT EXISTS sessions (
                sid TEXT PRIMARY KEY,
                sess TEXT NOT NULL,
                expire BIGINT NOT NULL
            )
        `);

        await pool.query(`
            CREATE INDEX IF NOT EXISTS idx_sessions_expire
            ON sessions(expire)
        `);
    }

    async cleanupExpired() {
        try {
            await this.ready;

            await pool.query(`
                DELETE FROM sessions
                WHERE expire <= $1
            `, [Date.now()]);
        } catch (error) {
            console.error("PostgreSQL session cleanup error:", error);
        }
    }

    get(sid, callback) {
        this.ready
            .then(async () => {
                const result = await pool.query(`
                    SELECT sess, expire
                    FROM sessions
                    WHERE sid = $1
                `, [sid]);

                const row = result.rows[0];

                if (!row) {
                    return callback(null, null);
                }

                if (Number(row.expire) <= Date.now()) {
                    await pool.query(`
                        DELETE FROM sessions
                        WHERE sid = $1
                    `, [sid]);

                    return callback(null, null);
                }

                const sessionData = JSON.parse(row.sess);

                return callback(null, sessionData);
            })
            .catch(callback);
    }

    set(sid, sessionData, callback) {
        this.ready
            .then(async () => {
                const expire = this.getExpiry(sessionData);

                await pool.query(`
                    INSERT INTO sessions (sid, sess, expire)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (sid)
                    DO UPDATE SET
                        sess = EXCLUDED.sess,
                        expire = EXCLUDED.expire
                `, [
                    sid,
                    JSON.stringify(sessionData),
                    expire
                ]);

                callback(null);
            })
            .catch(callback);
    }

    destroy(sid, callback) {
        this.ready
            .then(async () => {
                await pool.query(`
                    DELETE FROM sessions
                    WHERE sid = $1
                `, [sid]);

                callback(null);
            })
            .catch(callback);
    }

    touch(sid, sessionData, callback) {
        this.ready
            .then(async () => {
                const expire = this.getExpiry(sessionData);

                await pool.query(`
                    UPDATE sessions
                    SET expire = $1
                    WHERE sid = $2
                `, [expire, sid]);

                callback(null);
            })
            .catch(callback);
    }

    clear(callback) {
        this.ready
            .then(async () => {
                await pool.query(`
                    DELETE FROM sessions
                `);

                callback(null);
            })
            .catch(callback);
    }

    length(callback) {
        this.ready
            .then(async () => {
                const result = await pool.query(`
                    SELECT COUNT(*)::INTEGER AS count
                    FROM sessions
                `);

                callback(null, result.rows[0].count);
            })
            .catch(callback);
    }

    all(callback) {
        this.ready
            .then(async () => {
                const result = await pool.query(`
                    SELECT sid, sess, expire
                    FROM sessions
                `);

                const sessions = {};

                for (const row of result.rows) {
                    if (Number(row.expire) <= Date.now()) {
                        continue;
                    }

                    sessions[row.sid] = JSON.parse(row.sess);
                }

                callback(null, sessions);
            })
            .catch(callback);
    }

    destroyUserSessions(userId, callback) {
        this.ready
            .then(async () => {
                const result = await pool.query(`
                    SELECT sid, sess
                    FROM sessions
                `);

                const sessionIds = [];

                for (const row of result.rows) {
                    try {
                        const sessionData = JSON.parse(row.sess);

                        if (
                            Number(sessionData.userId) ===
                            Number(userId)
                        ) {
                            sessionIds.push(row.sid);
                        }
                    } catch (error) {
                        console.error(
                            `Could not read session ${row.sid} while invalidating user sessions:`,
                            error
                        );
                    }
                }

                if (sessionIds.length > 0) {
                    await pool.query(`
                        DELETE FROM sessions
                        WHERE sid = ANY($1::text[])
                    `, [sessionIds]);
                }

                callback(null, sessionIds.length);
            })
            .catch(callback);
    }

    getExpiry(sessionData) {
        if (
            sessionData.cookie &&
            sessionData.cookie.expires
        ) {
            const expiry = new Date(
                sessionData.cookie.expires
            ).getTime();

            if (Number.isFinite(expiry)) {
                return expiry;
            }
        }

        return Date.now() + (1000 * 60 * 60 * 24);
    }
}

module.exports = PostgresSessionStore;
