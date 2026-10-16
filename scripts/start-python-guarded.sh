#!/usr/bin/env bash
# Guarded start for the Python backend (MELODEXS CONNECT migration).
#
# Production traffic is served by the Node backend (apps/api), which Render
# selects via the service's rootDir setting. The repository root's start
# script launches the PYTHON backend. If a Render service ever points at
# the repository root in production mode without an explicit opt-in, this
# guard refuses to boot rather than silently replacing the Node API.
#
# Failure mode is deliberate: crash-loop, do not serve.
#
# Opt-in: ALLOW_PYTHON_PRODUCTION=1 must be set explicitly on the
# environment that is intentionally allowed to run the Python backend in
# production mode (staging sets this; production never does).
set -euo pipefail

if [ "${NODE_ENV:-}" = "production" ] && [ "${ALLOW_PYTHON_PRODUCTION:-}" != "1" ]; then
    echo "ERROR: refusing to start the Python backend with NODE_ENV=production." >&2
    echo "       Production traffic must stay on the Node backend (apps/api) until" >&2
    echo "       cutover is explicitly authorized. If this environment is intended" >&2
    echo "       to run Python in production mode (e.g. staging), set" >&2
    echo "       ALLOW_PYTHON_PRODUCTION=1 explicitly." >&2
    exit 1
fi

exec python3 -m uvicorn app.main:app --app-dir apps/api-python \
    --host 0.0.0.0 --port "${PORT:-3000}" \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}"
