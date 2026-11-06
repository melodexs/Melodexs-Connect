"""The customer detail dialog in admin.html.

The behaviour was exercised in a real browser: open, close (button, Escape,
backdrop), focus return, a focus trap, hostile text, an unknown customer,
paging, a slow response racing a newer one, and a 390px phone. These pin the
structure so a later edit cannot quietly undo those guarantees.
"""
import re
from pathlib import Path

ADMIN = (Path(__file__).resolve().parents[3] / "apps" / "web" / "admin.html").read_text(encoding="utf-8")


def _block(start_marker, end_marker):
    start = ADMIN.index(start_marker)
    return ADMIN[start:ADMIN.index(end_marker, start)]


DIALOG_JS = _block("// CUSTOMER DETAIL DIALOG", "// Highlight the section being read.")


def test_every_user_row_gets_a_view_button_with_the_numeric_id():
    assert 'class="view-btn" data-customer="${escapeHtml(user.id)}"' in ADMIN
    assert 'aria-label="View details for ${escapeHtml(user.name)}"' in ADMIN


def test_the_users_table_header_and_empty_rows_account_for_the_extra_column():
    header = _block('<tbody id="usersTable">', "</tbody>")
    assert 'colspan="8"' in header
    assert 'colspan="7" class="empty">${adminData.users' not in ADMIN, "empty-row colspan must match the 8 columns"
    users_head = ADMIN[ADMIN.index('id="usersSection"'):ADMIN.index('<tbody id="usersTable">')]
    assert len(re.findall(r"<th[ >]", users_head)) == 8


def test_the_dialog_is_a_real_modal_with_a_name_and_a_close_button():
    markup = _block('<div class="cust-backdrop"', "<script>")
    assert 'role="dialog"' in markup and 'aria-modal="true"' in markup
    assert 'aria-labelledby="custName"' in markup and 'id="custName"' in markup
    assert 'id="custClose"' in markup and 'aria-label="Close customer details"' in markup


def test_visibility_is_one_class_so_it_cannot_be_half_hidden():
    """The install-button bug was a hidden attribute fighting a hidden class.
    The dialog must be controlled by exactly one thing: .open."""
    css = _block(".cust-backdrop {", ".cust-panel {")
    assert ".cust-backdrop { display: none;" in css and ".cust-backdrop.open { display: flex; }" in css
    assert 'class="cust-backdrop"' in ADMIN and 'class="cust-backdrop hidden"' not in ADMIN
    assert not re.search(r'id="custBackdrop"[^>]*\bhidden\b', ADMIN)
    assert 'classList.add("open")' in DIALOG_JS and 'classList.remove("open")' in DIALOG_JS


def test_it_closes_with_the_button_the_backdrop_and_escape_and_returns_focus():
    assert 'custEl("custClose").addEventListener("click", closeCustomerDialog)' in DIALOG_JS
    assert "event.target === custEl(\"custBackdrop\")" in DIALOG_JS
    assert 'event.key === "Escape"' in DIALOG_JS
    assert "cust.opener.focus()" in DIALOG_JS
    assert 'event.key === "Tab"' in DIALOG_JS, "keyboard focus must stay inside the open dialog"


def test_the_page_behind_stops_scrolling_while_open_and_recovers():
    assert "body.cust-open { overflow: hidden; }" in ADMIN
    assert 'classList.add("cust-open")' in DIALOG_JS and 'classList.remove("cust-open")' in DIALOG_JS


def test_a_slow_response_cannot_overwrite_a_newer_customer():
    """Opening Sam (slow) then closing and opening Ada must end on Ada."""
    assert "cust.token++" in DIALOG_JS, "closing must invalidate in-flight requests"
    assert DIALOG_JS.count("token !== cust.token") >= 2
    assert "const token = ++cust.token" in DIALOG_JS


def test_customer_text_is_never_put_into_the_page_unescaped():
    bare = re.findall(r"\$\{\s*(?:c|t|sm)\.[A-Za-z_]+\s*\}", DIALOG_JS)
    assert not bare, f"unescaped field in the dialog: {bare}"
    assert "Number(sm.purchases)" in DIALOG_JS, "counts are coerced to numbers where they are built"
    assert 'custEl("custName").textContent' in DIALOG_JS, "the name goes in as text, not HTML"
    # Every customer-controlled field must be wrapped, wherever it appears.
    for field in ("c.email", "c.phone", "c.created_at", "c.virtual_account_number", "c.virtual_bank_name",
                  "t.created_at", "t.type", "t.reference", "t.provider", "t.provider_reference", "t.description"):
        uses = re.findall(r"[^\w.]" + re.escape(field) + r"\b(?!\s*\))", DIALOG_JS)
        wrapped = re.findall(r"escapeHtml\(\s*" + re.escape(field) + r"\b", DIALOG_JS)
        assert wrapped, f"{field} is never escaped"
        for match in re.finditer(r"\$\{[^}]*\b" + re.escape(field) + r"\b[^}]*\}", DIALOG_JS):
            assert "escapeHtml(" in match.group(0) or "formatMoney(" in match.group(0) or "statusBadge(" in match.group(0), match.group(0)


def test_the_id_is_url_encoded_when_requested():
    assert "/api/admin/users/${encodeURIComponent(id)}" in DIALOG_JS


def test_it_loads_older_history_in_pages_and_says_when_it_is_complete():
    assert "limit=100&offset=${offset}" in DIALOG_JS
    assert "loadMoreCustomerRows" in DIALOG_JS and "hasMore" in DIALOG_JS
    assert "That is the full history." in DIALOG_JS


def test_an_error_is_shown_in_the_dialog_not_swallowed():
    assert "error.message || \"Could not load this customer.\"" in DIALOG_JS
    assert "Customer not found" not in DIALOG_JS, "the message comes from the server, not hard-coded"


def test_the_dialog_is_read_only():
    """Nothing in the dialog may change money or data."""
    assert not re.search(r"method:\s*[\"'](?:POST|PUT|PATCH|DELETE)", DIALOG_JS, re.I)
    for word in ("refund", "adjust", "credit the", "reverse", "delete"):
        assert word not in DIALOG_JS.lower(), word


def test_the_actions_header_cell_does_not_use_a_positioned_hidden_span():
    """Regression: a position:absolute .sr-only span inside a table header was
    not clipped by the scroll container, so on a 390px phone the whole page
    scrolled sideways (document 902px wide). Name the empty header with
    aria-label instead."""
    users_head = ADMIN[ADMIN.index('id="usersSection"'):ADMIN.index('<tbody id="usersTable">')]
    assert '<th aria-label="Actions"></th>' in users_head
    assert "<th><span" not in users_head
    for table_head in re.findall(r"<thead>.*?</thead>", ADMIN, re.S):
        assert 'class="sr-only"' not in table_head, "no positioned hidden element inside any table header"


def test_the_panel_and_close_button_are_phone_friendly():
    panel = _block(".cust-panel {", ".cust-head {")
    assert "max-width: 980px" in panel and "width: 100%" in panel
    close = _block(".cust-close {", ".cust-close:hover")
    assert "min-width: 44px" in close and "min-height: 44px" in close
    assert ".cust-backdrop { display: none; position: fixed; inset: 0;" in ADMIN
    assert "overflow-y: auto" in _block(".cust-backdrop {", ".cust-backdrop.open")
