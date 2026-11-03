"""Common provider interface for data fulfillment.

Every fulfillment provider (WiseSub today, additional suppliers later)
implements ProviderAdapter so the platform can:

- fetch and normalize a provider catalog,
- submit data and airtime purchases idempotently,
- requery transaction status,
- check the provider wallet balance where supported,
- normalize timeouts and provider errors into well-defined outcomes.

Outcome model
-------------
SUCCESSFUL      The provider confirmed a completed, delivered purchase.
PENDING         The request was accepted but the final outcome is not yet
                known (provider or network delay). The wallet debit stays
                held until reconciliation.
UNCERTAIN       The platform could not establish the outcome (timeout,
                HTTP 4xx/5xx, malformed response). Never auto-failed;
                always reconciled before any retry or fallback decision.
FAILED_FINAL    The provider confirmed the purchase failed AND documented
                that the wallet was refunded. Only adapters whose provider
                documents automatic refunds may emit this from a purchase
                response; WiseSub never does (its failures are resolved
                through the gated reconciliation flow).

Provider-specific authentication, request formats and response parsing live
inside the adapters; nothing else in the codebase may depend on a
particular provider's wire format.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class PurchaseOutcome(str, Enum):
    SUCCESSFUL = "successful"
    PENDING = "pending"
    UNCERTAIN = "uncertain"
    FAILED_FINAL = "failed_final"


@dataclass(frozen=True)
class PurchaseResult:
    outcome: PurchaseOutcome
    provider_reference: str | None = None
    message: str = ""
    raw: dict | None = None


@dataclass(frozen=True)
class StatusResult:
    """Normalized transaction status from a provider requery.

    recognized values: "successful", "failed", "pending".
    Anything else is surfaced as unrecognized=True, which callers must
    treat as uncertain (never as success or failure).
    """
    recognized: bool
    status: str | None = None
    message: str = ""


@dataclass(frozen=True)
class BalanceResult:
    supported: bool
    balance: Decimal | None = None
    currency: str | None = None
    message: str = ""
    # Provider-reported wallet mode (e.g. MELE DATA "live"/"test") and its
    # livemode flag. Used by sandbox-mode guards; None when the provider
    # does not report a mode (WiseSub, VTpass balance endpoint).
    mode: str | None = None
    livemode: bool | None = None


@dataclass(frozen=True)
class CatalogPackage:
    """A normalized provider catalog entry.

    network must be one of MTN, Airtel, Glo, 9mobile (display form).
    plan_type is the provider's own product family (e.g. SME, CG, gifting,
    standard) when the provider distinguishes one; None when unknown.
    Unknown plan_type makes a package ineligible for automatic equivalence
    matching (see app/package_matching.py).
    """
    code: str
    name: str
    network: str
    data_size: str | None
    validity: str | None
    plan_type: str | None
    cost: Decimal


class ProviderAdapter(ABC):
    """Contract every fulfillment provider must satisfy."""

    #: stable lowercase slug used in providers.slug and transactions.provider
    slug: str = ""
    #: human-readable name for the admin panel
    display_name: str = ""
    #: True when the provider documented automatic refunds for failed
    #: purchases (may emit FAILED_FINAL from purchase responses)
    auto_refunds_on_failure: bool = False
    #: True when a failed requery status is authoritative enough to refund
    #: without an extra admin confirmation gate (kept conservative: the
    #: WiseSub-style confirmation flag still applies unless documented)
    failure_status_is_final: bool = False
    #: True when the provider is deliberately EXCLUDED from selection
    #: (routing, fallback and the admin provider-selection UI) while its
    #: adapter code stays for compatibility (tests, historical
    #: reconciliation). Excluded adapters can never fulfill a purchase.
    selection_excluded: bool = False
    capabilities: tuple[str, ...] = ()

    @abstractmethod
    def is_configured(self) -> bool:
        """True when the required credentials/configuration are present."""

    @abstractmethod
    async def fetch_catalog(self) -> list[CatalogPackage]:
        """Fetch and normalize the provider's live data-plan catalog.

        Raises on transport/auth errors; must not return partial silent
        results."""

    @abstractmethod
    async def submit_data_purchase(self, *, network: str, package_code: str,
                                   phone: str, reference: str) -> PurchaseResult:
        """Submit a data purchase for the provider's package code.

        network is the display form (MTN, Airtel, Glo, 9mobile); each
        adapter maps it to its own provider value."""

    @abstractmethod
    async def submit_airtime_purchase(self, *, network: str,
                                      phone: str, amount: Decimal,
                                      reference: str) -> PurchaseResult:
        """Submit an airtime purchase (providers without airtime support
        should raise NotImplementedError at construction time rather than
        silently accepting)."""

    @abstractmethod
    async def transaction_status(self, reference: str) -> StatusResult:
        """Requery a previously submitted purchase by its provider
        reference."""

    async def account_balance(self) -> BalanceResult:
        """Providers without a documented balance endpoint report
        supported=False."""
        return BalanceResult(supported=False,
                             message="This provider does not document a balance endpoint.")

    async def health_check(self) -> BalanceResult:
        """Default health probe: the balance endpoint when supported."""
        return await self.account_balance()

    def describe(self) -> dict:
        return {
            "slug": self.slug,
            "name": self.display_name,
            "configured": self.is_configured(),
            "auto_refunds_on_failure": self.auto_refunds_on_failure,
            "capabilities": list(self.capabilities),
        }
