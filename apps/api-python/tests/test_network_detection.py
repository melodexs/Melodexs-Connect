"""Network auto-detect from a Nigerian number's prefix.

The prefix table comes from the NCC Mobile Number Allocation Table (Nov 2024).
A wrong entry would auto-select the wrong network and buy the wrong product, so
every prefix is pinned, and the behaviour around ported numbers is pinned too.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
MODULE = WEB / "network-detect.js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

# The authoritative NCC allocation for the four networks the app sells.
NCC = {
    "MTN": "0803 0806 0810 0813 0814 0816 0703 0704 0706 0707 0903 0906 0913 0916".split(),
    "Airtel": "0802 0808 0812 0701 0708 0901 0902 0904 0907 0911 0912".split(),
    "Glo": "0805 0807 0811 0815 0705 0905 0915".split(),
    "9mobile": "0809 0817 0818 0908 0909".split(),
}
# Allocated to someone else, withdrawn or reserved: must never pick a network.
NOT_OURS = ["0801", "0804", "0702", "0709", "0819", "0800", "0700", "0900", "0910", "0914", "0801"]


def detect(value):
    out = subprocess.run(
        [NODE, "-e", "const m=require(process.argv[1]);process.stdout.write(JSON.stringify(m.detectNetwork(JSON.parse(process.argv[2]))))",
         str(MODULE), json.dumps(value)], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


@needs_node
@pytest.mark.parametrize("network,prefixes", NCC.items())
def test_every_ncc_prefix_maps_to_its_network(network, prefixes):
    for prefix in prefixes:
        assert detect(prefix + "1234567") == network, f"{prefix} should be {network}"


@needs_node
def test_the_module_table_matches_the_ncc_table_exactly():
    out = subprocess.run([NODE, "-e", "process.stdout.write(JSON.stringify(require(process.argv[1]).PREFIXES))", str(MODULE)],
                         capture_output=True, text=True, timeout=30, check=True)
    table = json.loads(out.stdout)
    assert {k: sorted(v) for k, v in table.items()} == {k: sorted(v) for k, v in NCC.items()}


@needs_node
def test_no_prefix_belongs_to_two_networks():
    flat = [p for prefixes in NCC.values() for p in prefixes]
    assert len(flat) == len(set(flat)) == 37


@needs_node
@pytest.mark.parametrize("prefix", NOT_OURS)
def test_prefixes_we_do_not_sell_never_pick_a_network(prefix):
    assert detect(prefix + "1234567") is None


@needs_node
@pytest.mark.parametrize("typed", ["", "0", "08", "080", "+23", "234", "abc", "   "])
def test_nothing_is_guessed_from_fewer_than_four_digits(typed):
    assert detect(typed) is None


@needs_node
@pytest.mark.parametrize("typed,expected", [
    ("08031234567", "MTN"),
    ("0803 123 4567", "MTN"),
    ("0803-123-4567", "MTN"),
    ("+2348031234567", "MTN"),
    ("2348031234567", "MTN"),
    ("+234 805 123 4567", "Glo"),
    ("2349091234567", "9mobile"),
    ("0802", "Airtel"),
])
def test_international_and_formatted_numbers_are_understood(typed, expected):
    assert detect(typed) == expected


@needs_node
def test_a_partial_international_prefix_waits_for_enough_digits():
    assert detect("+23480") is None       # only "080" so far: too early to say
    assert detect("+234803") == "MTN"


@needs_node
@pytest.mark.parametrize("junk", [None, 0, 803, {}, []])
def test_odd_inputs_never_throw(junk):
    assert detect(junk) is None


# ---- page wiring --------------------------------------------------------

AIRTIME = (WEB / "buy-airtime.html").read_text()
DATA = (WEB / "buy-data.html").read_text()
MODULE_SRC = MODULE.read_text()


def test_both_buy_pages_load_the_detector_before_their_own_script():
    for name, page in (("buy-airtime", AIRTIME), ("buy-data", DATA)):
        assert 'src="network-detect.js"' in page, f"{name} must load network-detect.js"
        assert page.index('src="network-detect.js"') < page.index("<script>"), f"{name}: load order"


def test_both_pages_bind_detection_to_the_phone_field_and_the_network_chips():
    for name, page in (("buy-airtime", AIRTIME), ("buy-data", DATA)):
        assert "bindNetworkDetection(document.getElementById(\"phone\")" in page, name
        assert 'networkChips: document.getElementById("networks")' in page, name
        assert 'noteElement: document.getElementById("networkNote")' in page, name


def test_the_detected_network_is_always_announced_to_the_user():
    for name, page in (("buy-airtime", AIRTIME), ("buy-data", DATA)):
        assert 'id="networkNote"' in page, name
        assert 'role="status"' in page and 'aria-live="polite"' in page, f"{name}: screen readers should hear it"


def test_data_page_switches_through_selectNetwork_so_plans_reload():
    """A bare relabel would leave the previous network's plans on screen."""
    body = DATA[DATA.index("bindNetworkDetection("):DATA.index("networkChips:")]
    assert "selectNetwork(slug, btn)" in body


def test_saved_recipients_win_over_the_prefix_on_both_pages():
    for name, page in (("buy-airtime", AIRTIME), ("buy-data", DATA)):
        assert "networkDetection.pinCurrent()" in page, f"{name}: a ported number's saved network must stick"


def test_buy_again_links_keep_the_network_they_carry():
    assert "if (params.get(\"network\")) window.networkDetection.pinCurrent();" in DATA


def test_only_real_taps_count_as_a_manual_override():
    """Auto-detect clicks nothing itself, but favourites call .click(); only trusted taps override."""
    assert "e.isTrusted" in MODULE_SRC


def test_manual_choice_is_forgotten_when_the_prefix_changes():
    body = MODULE_SRC[MODULE_SRC.index("function onInput"):MODULE_SRC.index("if (options.networkChips)")]
    assert "manualFor = null" in body


def test_the_module_stays_free_of_network_and_storage_access():
    for forbidden in ("fetch(", "XMLHttpRequest", "localStorage", "eval(", "innerHTML"):
        assert forbidden not in MODULE_SRC, f"network-detect.js must stay pure: {forbidden}"


def test_the_service_worker_caches_scripts_so_detection_works_offline():
    """sw.js stores any same-origin *.js on first use, which covers network-detect.js."""
    sw = (WEB / "sw.js").read_text()
    assert "STATIC_ASSET" in sw and "js" in sw.split("STATIC_ASSET =")[1].split(";")[0]
    assert (WEB / "network-detect.js").exists()
