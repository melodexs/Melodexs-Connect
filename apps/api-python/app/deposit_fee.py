"""Wallet deposit fee.

A customer pays the full amount they typed to Paystack. A percentage is kept
as a fee and only the rest is credited to their wallet:

    pay N1,000 at 3%  ->  fee N30  ->  wallet receives N970

Design rules, each of which protects money:

* The fee is worked out ONCE, when the deposit is created, and written onto the
  transaction. Crediting later reads that stored figure, never the live rate, so
  changing the rate cannot alter a deposit that is already in flight.
* Deposits created before this feature existed carry no fee marker and are
  credited in full, exactly as they always were.
* Arithmetic is done in whole kobo (integers) with round-half-up, so there is
  no floating point drift.
* No schema change: the figures ride in the transaction description after the
  customer-visible first segment (customers only ever see that first segment).
"""
from __future__ import annotations

import re

# Marker written after the customer-visible text, e.g.
#   "Wallet funding: N1,000 paid, N30 fee | deposit_fee_kobo=3000 | credit_kobo=97000"
_FEE_RE = re.compile(r"\|\s*deposit_fee_kobo=(\d+)\s*\|\s*credit_kobo=(\d+)")


def _kobo(naira: float) -> int:
    return int(round(float(naira) * 100))


def fee_for(amount_naira: float, percent: float) -> float:
    """Fee in naira for a deposit, rounded half-up to the nearest kobo."""
    percent = max(0.0, float(percent or 0))
    paid_kobo = _kobo(amount_naira)
    # integer math: kobo * percent / 100, half-up
    fee_kobo = int((paid_kobo * int(round(percent * 1000)) + 50_000) // 100_000)
    fee_kobo = min(fee_kobo, paid_kobo)  # never more than the deposit itself
    return fee_kobo / 100


def split(amount_naira: float, percent: float) -> dict:
    """Return {'paid', 'fee', 'credit'} in naira."""
    paid = _kobo(amount_naira)
    fee = _kobo(fee_for(amount_naira, percent))
    return {"paid": paid / 100, "fee": fee / 100, "credit": (paid - fee) / 100}


def _money(n: float) -> str:
    return f"N{n:,.0f}" if float(n).is_integer() else f"N{n:,.2f}"


def describe(amount_naira: float, percent: float) -> str:
    """Description stored on a NEW deposit: customer text first, machine fields after."""
    s = split(amount_naira, percent)
    if s["fee"] <= 0:
        return "Paystack wallet funding"
    return (f"Wallet funding: {_money(s['paid'])} paid, {_money(s['fee'])} fee"
            f" | deposit_fee_kobo={_kobo(s['fee'])} | credit_kobo={_kobo(s['credit'])}")


def credit_for(description: str | None, paid_naira: float) -> float:
    """Naira to credit for a stored deposit.

    A description with a fee marker credits the stored figure. Anything else
    (deposits made before this feature, or fee-free ones) credits the full
    amount paid.
    """
    match = _FEE_RE.search(description or "")
    if not match:
        return float(paid_naira)
    fee_kobo, credit_kobo = int(match.group(1)), int(match.group(2))
    # Self-check: the stored figures must add up to what was paid. If they do
    # not, something has been altered; fall back to the safe, larger-credit
    # reading rather than silently short-changing a customer.
    if fee_kobo + credit_kobo != _kobo(paid_naira):
        return float(paid_naira)
    return credit_kobo / 100


def fee_of(description: str | None) -> float:
    match = _FEE_RE.search(description or "")
    return int(match.group(1)) / 100 if match else 0.0
