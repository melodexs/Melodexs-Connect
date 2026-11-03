"""What must never reach a public repository.

The repo is public. A committed .env, database dump or private key is a live
secret, and the history keeps it long after the file is deleted.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

SECRET_FILES = {".env", "local.db", "tests/test_suite.db", "id_rsa", "id_ed25519"}
SECRET_PATTERNS = [
    (re.compile(r"sk_live_[0-9a-zA-Z]{10,}"), "Stripe live key"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "private key"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key"),
    (re.compile(r"ghp_[0-9a-zA-Z]{30,}"), "GitHub token"),
]
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "android", "dist"}


def _tracked_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix in {".png", ".jpg", ".jpeg", ".webp", ".ico", ".zip", ".db", ".pyc"}:
            continue
        yield path


def test_no_secret_files_are_committed():
    found = [str(p.relative_to(ROOT)) for p in _tracked_files() if p.name in SECRET_FILES]
    assert not found, f"secret or database files present: {found}"


def test_no_live_credentials_in_source():
    hits = []
    for path in _tracked_files():
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for pattern, label in SECRET_PATTERNS:
            if pattern.search(text):
                hits.append(f"{path.relative_to(ROOT)}: {label}")
    assert not hits, f"possible live credentials: {hits}"


def test_no_backup_archives_are_committed():
    """Zipped snapshots bloat a public repo and can hide anything inside them."""
    zips = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*.zip")
            if not any(part in SKIP_DIRS for part in p.parts)]
    assert not zips, f"archives committed to the repository: {zips}"


def test_gitignore_covers_build_and_runtime_artifacts():
    ignore = (ROOT / ".gitignore").read_text()
    for pattern in ("*.db", ".env", "__pycache__", "node_modules", "*.zip"):
        assert pattern in ignore, f"{pattern} must be ignored"
