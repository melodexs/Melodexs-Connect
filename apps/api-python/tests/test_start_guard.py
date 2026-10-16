"""Tests for the guarded Python start script (scripts/start-python-guarded.sh).

The guard's job is fail-closed behavior: NODE_ENV=production without the
explicit ALLOW_PYTHON_PRODUCTION=1 opt-in must refuse to start (exit 1);
with the opt-in (or outside production mode) it must proceed to uvicorn.

Pass-through cases must never actually serve: the test pre-binds the
target port so uvicorn fails to bind and exits quickly, proving control
left the guard without leaving a listening server behind.
"""
import os
import socket
import subprocess
import unittest

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "start-python-guarded.sh"
STRIPPED = ("NODE_ENV", "ALLOW_PYTHON_PRODUCTION", "PORT", "DATABASE_URL",
            "PYTHON_TEST_DATABASE_URL")


class _BusyPort:
    """Occupy an ephemeral TCP port so uvicorn's bind fails fast."""

    def __init__(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        self._sock.bind(("127.0.0.1", 0))
        self.port = self._sock.getsockname()[1]
        self._sock.listen(1)

    def close(self):
        self._sock.close()


def run_guard(env_overrides, timeout=30):
    env = {k: v for k, v in os.environ.items() if k not in STRIPPED}
    env.update(env_overrides)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class StartGuardTest(unittest.TestCase):
    def test_production_without_optin_refuses(self):
        result = run_guard({"NODE_ENV": "production"})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("refusing to start", result.stderr)
        self.assertIn("ALLOW_PYTHON_PRODUCTION=1", result.stderr)

    def test_production_with_optin_passes_through_to_uvicorn(self):
        busy = _BusyPort()
        try:
            result = run_guard({"NODE_ENV": "production", "ALLOW_PYTHON_PRODUCTION": "1",
                                "PORT": str(busy.port),
                                "DATABASE_URL": "sqlite:////tmp/mcx-guard-probe.db"})
        finally:
            busy.close()
        out = result.stderr + result.stdout
        self.assertNotIn("refusing to start", out)
        # Pass-through proof: control left the guard and reached Python
        # (uvicorn/app config), which then failed for environment reasons
        # (here: production env validation, since this env sets no
        # WISESUB/SESSION_SECRET/DATABASE_URL) - never the guard message.
        self.assertTrue("runtimeerror" in out.lower() or "address already in use" in out.lower(), out[:300])

    def test_non_production_ignores_guard(self):
        busy = _BusyPort()
        try:
            result = run_guard({"NODE_ENV": "test", "PORT": str(busy.port),
                                "DATABASE_URL": "sqlite:////tmp/mcx-guard-probe.db"})
        finally:
            busy.close()
        out = result.stderr + result.stdout
        self.assertNotIn("refusing to start", out)
        self.assertIn("started server process", out.lower())
        self.assertIn("address already in use", out.lower())


if __name__ == "__main__":
    unittest.main()
