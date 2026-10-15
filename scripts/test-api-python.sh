#!/usr/bin/env bash
# Run the Python API test suite against a fresh external scratch SQLite
# database. Never uses or creates a database inside the repository, and never
# contacts PostgreSQL or production.
#
# PostgreSQL integration tests are skipped by default; they require the
# explicit opt-in gate documented in apps/api-python/MIGRATION-STAGING.md.
set -euo pipefail

SCRATCH_DIR="${TMPDIR:-/tmp}/melodexs-python-tests"
mkdir -p "$SCRATCH_DIR"
SCRATCH_DB="$SCRATCH_DIR/scratch-$(date +%Y%m%d%H%M%S).db"

cd "$(dirname "$0")/../apps/api-python"

PYTHON_TEST_DATABASE_URL="sqlite:///$SCRATCH_DB" python3 -m pytest tests/ -q "$@"

rm -f "$SCRATCH_DB"
