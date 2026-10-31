"""Every CSS custom property used by the web app must be defined.

The landing page shipped `color: var(--bluegray)` in eleven rules while
`--bluegray` was never declared. An undefined custom property makes the
declaration invalid, so the text silently fell back to the inherited dark
ink colour - near-invisible paragraphs on the dark background.

This test fails if any `var(--token)` reference has no matching
`--token:` declaration anywhere in the shipped frontend.
"""
import re
from pathlib import Path

_WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
# A var() WITH a fallback value is safe on its own, so only bare references
# (no comma) need a definition.
_USE_RE = re.compile(r"var\(\s*--([A-Za-z0-9_-]+)\s*\)")
# Variables assigned from JavaScript (el.style.setProperty("--x", ...)).
_SET_RE = re.compile(r"""setProperty\(\s*["']--([A-Za-z0-9_-]+)""")
_DEF_RE = re.compile(r"--([A-Za-z0-9_-]+)\s*:")


def _frontend_files():
    return sorted(list(_WEB.glob("*.html")) + list(_WEB.glob("*.css")) + list(_WEB.glob("*.js")))


def test_every_css_variable_used_is_defined():
    used = {}
    defined = set()
    for path in _frontend_files():
        text = path.read_text(errors="ignore")
        for name in _USE_RE.findall(text):
            used.setdefault(name, set()).add(path.name)
        defined.update(_DEF_RE.findall(text))
        defined.update(_SET_RE.findall(text))

    # Runtime-set variables count as defined; var() calls that carry their
    # own fallback are excluded by _USE_RE.
    missing = {name: sorted(files) for name, files in used.items() if name not in defined}
    assert not missing, f"CSS custom properties used but never defined: {missing}"


def test_landing_body_text_uses_a_light_token():
    """The landing/phone surfaces are dark navy: body copy must not inherit
    the dark ink colour."""
    css = (_WEB / "styles.css").read_text()
    root = css[css.index(":root {"):css.index("}", css.index(":root {"))]
    assert "--bluegray: #C7D1DD" in root.replace("  ", " "), (
        "the landing body-copy token must stay a light colour"
    )
    hero = css[css.index(".landing-hero h1 {"):]
    hero_rule = hero[:hero.index("}")]
    assert "color: var(--white)" in hero_rule, "the hero headline must not inherit the dark ink colour"
