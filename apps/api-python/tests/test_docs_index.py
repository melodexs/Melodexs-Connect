"""An index nobody updates is a trap: it looks like the whole picture.

Every document must appear in docs/README.md, so a new guide cannot be written
and forgotten.
"""
from pathlib import Path

DOCS = Path(__file__).resolve().parents[3] / "docs"
INDEX = (DOCS / "README.md").read_text()


def test_every_document_is_indexed():
    missing = [p.name for p in sorted(DOCS.glob("*.md"))
               if p.name != "README.md" and f"({p.name})" not in INDEX]
    assert not missing, f"documents missing from the index: {missing}"


def test_every_decision_record_is_indexed():
    missing = [p.name for p in sorted((DOCS / "adr").glob("*.md"))
               if f"adr/{p.name}" not in INDEX]
    assert not missing, f"decision records missing from the index: {missing}"


def test_the_index_links_resolve():
    import re

    for target in re.findall(r"\((\.\.?/[^)]+)\)", INDEX):
        assert (DOCS / target).resolve().exists(), f"index link is broken: {target}"
