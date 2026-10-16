"""Tests for the guarded Python start script (scripts/start-python-guarded.sh).

The guard's job is fail-closed behavior: NODE_ENV=production without the
explicit ALLOW_PYTHON_PRODUCTION=1 opt-in must refuse to start (exit 1);
with the opt-in (or outside production mode) it must proceed to uvicorn.
These tests execute the real script with controlled environments.
"""
import os
import subprocess
import unittest

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "start-python-guarded.sh"


def run_guard(env_overrides):
    env = {k: v for k, v in os.environ.items() if k not in ("NODE_ENV", "ALLOW_PYTHON_PRODUCTION", "PORT")}
    env.update(env_overrides)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


class StartGuardTest(unittest.TestCase):
    def test_production_without_optin_refuses(self):
        result = run_guard({"NODE_ENV": "production"})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("refusing to start", result.stderr)
        self.assertIn("ALLOW_PYTHON_PRODUCTION=1", result.stderr)

    def test_production_with_optin_attempts_boot(self):
        # With the opt-in the guard execs uvicorn; uvicorn then fails for
        # environment reasons (no DATABASE_URL here) but NOT with the
        # guard message, proving the guard passed control through.
        result = run_guard({"NODE_ENV": "production", "ALLOW_PYTHON_PRODUCTION": "1"})
        out = result.stderr + result.stdout
        self.assertNotIn("refusing to start", out)
        # Control reached uvicorn/app config, which fails here on
        # environment grounds - that is the pass-through proof.
        self.assertIn("uvicorn", out.lower())

    def test_non_production_ignores_guard(self):
        result = run_guard({"NODE_ENV": "test"})
        self.assertNotIn("refusing to start", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
