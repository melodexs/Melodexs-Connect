"""Documentation rots fastest at its links.

A dead relative link is how a new contributor ends up with no idea where the
provider contract lives, so every markdown link is resolved against the file
system.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOC_DIRS = [ROOT / "docs", ROOT]
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _markdown_files():
    files = list((ROOT / "docs").rglob("*.md"))
    files += [ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "SECURITY.md",
              ROOT / "CHANGELOG.md"]
    return [f for f in files if f.exists()]


def test_every_relative_link_resolves():
    broken = {}
    for path in _markdown_files():
        for target in LINK.findall(path.read_text(errors="ignore")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            clean = target.split("#", 1)[0]
            if not clean:
                continue
            resolved = (path.parent / clean).resolve()
            if not resolved.exists():
                broken.setdefault(str(path.relative_to(ROOT)), []).append(target)
    assert not broken, f"broken documentation links: {broken}"


def test_the_entry_points_exist():
    for name in ("README.md", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md"):
        assert (ROOT / name).exists(), f"{name} is missing"


def test_every_adr_is_indexed_by_number():
    adrs = sorted((ROOT / "docs" / "adr").glob("*.md"))
    assert adrs, "at least one architecture decision belongs in the record"
    for adr in adrs:
        assert re.match(r"\d{4}-[a-z0-9-]+\.md$", adr.name), f"{adr.name} is not numbered"
