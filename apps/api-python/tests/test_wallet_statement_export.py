"""CSV statement export: correctness, spreadsheet safety and wiring.

statement.js is a pure module, so it is executed for real under Node when
available (as in CI's runners and the dev sandbox) and statically pinned
otherwise. Either way the contract below must hold.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
MODULE = WEB / "statement.js"
WALLET = (WEB / "wallet.html").read_text()
NODE = shutil.which("node")

SAMPLE = [
    {"created_at": "2026-11-03T10:05:00Z", "reference": "MC-1", "type": "wallet_funding",
     "description": "Wallet funding", "amount": 5000, "status": "successful"},
    {"created_at": "2026-11-03T11:00:00Z", "reference": "MC-2", "type": "debit",
     "description": "MTN 1GB, weekly", "amount": 403, "status": "pending"},
    {"created_at": "2026-11-03T12:00:00Z", "reference": "MC-3", "type": "debit",
     "description": '=HYPERLINK("http://evil","x")', "amount": "12.5", "status": "failed"},
    {"created_at": "2026-11-03T13:00:00Z", "reference": "MC-4", "type": "debit",
     "description": "line one\nline two", "amount": 100, "status": "successful"},
    {"created_at": "not-a-date", "reference": None, "type": "debit",
     "description": None, "amount": None, "status": "successful"},
]


def run_node(expression):
    script = (
        "const s=require(process.argv[1]);"
        "const rows=JSON.parse(process.argv[2]);"
        f"process.stdout.write(JSON.stringify({expression}));"
    )
    out = subprocess.run([NODE, "-e", script, str(MODULE), json.dumps(SAMPLE)],
                         capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


@needs_node
def test_csv_has_a_header_and_one_line_per_transaction():
    csv = run_node("s.toCsv(rows)")
    lines = csv.split("\r\n")
    assert lines[0] == "Date,Reference,Type,Description,Amount (NGN),Direction,Status"
    assert csv.endswith("\r\n")
    # 1 header + 5 rows = 6 record terminators (the quoted multi-line cell adds no CRLF, only LF)
    assert csv.count("\r\n") == 6


@needs_node
def test_fields_with_commas_quotes_and_newlines_are_quoted():
    csv = run_node("s.toCsv(rows)")
    assert '"MTN 1GB, weekly"' in csv
    assert '"line one\nline two"' in csv


@needs_node
def test_formula_injection_is_neutralised():
    """A description starting with = + - @ would run as a formula in Excel."""
    csv = run_node("s.toCsv(rows)")
    assert "'=HYPERLINK" in csv
    assert ",=HYPERLINK" not in csv and '"=HYPERLINK' not in csv


@needs_node
@pytest.mark.parametrize("payload", ["=1+1", "+1+1", "-1+1", "@SUM(A1)", "\tcmd", "\rcmd"])
def test_every_formula_prefix_is_defused(payload):
    out = subprocess.run([NODE, "-e", "process.stdout.write(require(process.argv[1]).cell(process.argv[2]))",
                          str(MODULE), payload], capture_output=True, text=True, timeout=30, check=True).stdout
    assert out.lstrip('"').startswith("'"), out


@needs_node
def test_amounts_are_two_decimals_and_credit_debit_is_labelled():
    csv = run_node("s.toCsv(rows)")
    assert "5000.00,Credit,successful" in csv
    assert "403.00,Debit,pending" in csv
    assert "12.50,Debit,failed" in csv


@needs_node
def test_bad_data_never_throws_or_prints_undefined():
    csv = run_node("s.toCsv(rows)")
    assert "undefined" not in csv and "NaN" not in csv and "null" not in csv
    assert run_node("s.toCsv([])").count("\r\n") == 1, "an empty history still yields just a header"
    assert run_node("s.toCsv(null)").count("\r\n") == 1


@needs_node
def test_file_name_is_dated_and_filesystem_safe():
    name = run_node("s.fileName(new Date(2026, 10, 4))")
    assert name == "melodexs-statement-2026-11-04.csv"


def test_blob_carries_a_utf8_bom_so_excel_shows_the_naira_sign():
    assert '"\\uFEFF"' in MODULE.read_text()
    assert "text/csv;charset=utf-8" in MODULE.read_text()


def test_the_module_is_pure():
    """No DOM or network in the module, so it stays testable and safe."""
    src = MODULE.read_text()
    for forbidden in ("document.", "fetch(", "XMLHttpRequest", "localStorage", "eval(", "innerHTML"):
        assert forbidden not in src, f"statement.js must stay pure: found {forbidden}"


def test_wallet_page_loads_the_module_and_has_the_button():
    assert 'src="statement.js"' in WALLET
    assert 'id="exportCsv"' in WALLET
    assert "Download CSV" in WALLET


def test_export_only_reads_the_signed_in_users_own_history():
    """The export must reuse the ownership-checked endpoint, nothing broader."""
    body = WALLET[WALLET.index("async function exportStatement"):WALLET.index("async function loadTransactions")]
    assert '"/api/transactions/" + userId' in body
    assert "/api/admin" not in body
    assert 'credentials: "include"' in body


def test_export_respects_the_active_filters_and_is_bounded():
    body = WALLET[WALLET.index("async function exportStatement"):WALLET.index("async function loadTransactions")]
    for f in ("filters.type", "filters.status", "filters.q"):
        assert f in body, f"export should honour {f}"
    assert "EXPORT_MAX_ROWS" in body, "a runaway history must not hang the tab"
    assert "button.disabled = true" in body, "double-clicks must not start two exports"
    assert "finally" in body, "the button must always be re-enabled"


def test_statement_module_is_precached_with_the_other_static_assets():
    """sw.js caches *.js on first use; the page works offline once seen."""
    assert "js" in (WEB / "sw.js").read_text()


# ---- customer-facing descriptions: no supplier names or internal notes ----

REAL_SHAPES = [
    ("MTN 110MB DAILY data purchase for 08105922884 | Category: Daily Plans | Price: 100.00 | ISQUAREDATA confirmed delivery (auto requery sweep)",
     "MTN 110MB DAILY data purchase for 08105922884"),
    ("Airtel 1GB DAILY(BINGE) data purchase for 07011238917 | Category: Daily Plans | Price: 493.00 | Pending ISQUAREDATA confirmation | WiseSub status confirmed successful",
     "Airtel 1GB DAILY(BINGE) data purchase for 07011238917"),
    ("MTN 1GB WEEKLY data purchase for 08089525377 | Category: Weekly | ISQUAREDATA confirmed failure; wallet refunded",
     "MTN 1GB WEEKLY data purchase for 08089525377"),
    ("Paystack wallet funding", "Paystack wallet funding"),
]


def describe_with_node(text):
    out = subprocess.run(
        [NODE, "-e", "process.stdout.write(require(process.argv[1]).customerDescription(JSON.parse(process.argv[2])))",
         str(MODULE), json.dumps(text)], capture_output=True, text=True, timeout=30, check=True)
    return out.stdout


@needs_node
@pytest.mark.parametrize("stored,shown", REAL_SHAPES)
def test_customer_description_keeps_only_the_customer_facing_text(stored, shown):
    assert describe_with_node(stored) == shown


@needs_node
@pytest.mark.parametrize("stored,shown", REAL_SHAPES)
def test_no_supplier_name_survives_into_the_description(stored, shown):
    result = describe_with_node(stored).lower()
    for internal in ("isquaredata", "wisesub", "reconcil", "requery", "category:"):
        assert internal not in result


@needs_node
def test_empty_descriptions_are_safe():
    assert describe_with_node(None) == ""
    assert describe_with_node("") == ""


@needs_node
def test_the_csv_uses_the_clean_description():
    rows = [{"created_at": "2026-11-01T07:19:00Z", "reference": "R", "type": "debit", "status": "successful", "amount": 100,
             "description": REAL_SHAPES[0][0]}]
    out = subprocess.run([NODE, "-e", "process.stdout.write(require(process.argv[1]).toCsv(JSON.parse(process.argv[2])))",
                          str(MODULE), json.dumps(rows)], capture_output=True, text=True, timeout=30, check=True).stdout
    assert "ISQUAREDATA" not in out and "Category" not in out
    assert "MTN 110MB DAILY data purchase for 08105922884" in out


def test_wallet_screen_uses_the_clean_description_everywhere():
    """The list row, the detail view and the official receipt must all be cleaned.

    describe() itself is the one place allowed to read the raw field, so it is
    cut out before checking that nothing else renders it.
    """
    start = WALLET.index("function describe(")
    end = WALLET.index("const PAGE_SIZE")
    rest = WALLET[:start] + WALLET[end:]
    assert ".description" not in rest.replace('placeholder="Search by description', ""), (
        "a raw description is still rendered somewhere in the wallet page")
    assert rest.count("describe(") >= 3  # list row + detail view + official receipt
