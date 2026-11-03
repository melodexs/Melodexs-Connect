# Providers

Every VTU supplier is an adapter in `apps/api-python/app/provider_*.py`, registered
in `app/provider_registry.py`. Adapters never talk to the database directly; they
translate the platform's vocabulary into the supplier's HTTP contract.

## Adapter contract

| Member | Meaning |
| --- | --- |
| `slug`, `display_name` | Identity used in the `providers` table and transactions. |
| `capabilities` | Tuple drawn from `catalog`, `data`, `airtime`, `status`, `balance`. The dispatcher only tries an adapter for a capability it declares. |
| `selection_excluded` | `True` retires an adapter: it stays importable for historical reconciliation but can never be routed to or enabled from the admin UI. |
| `is_configured()` | Whether the credentials for this adapter are present. An unconfigured adapter can never be routed to, even if its row is enabled. |
| `auto_refunds_on_failure`, `failure_status_is_final` | How conservatively a failed purchase may be treated. Both stay `False`/`True` only where the supplier documents the behaviour. |
| `fetch_catalog()`, `buy_*()`, `requery()`, `balance()` | Capability implementations, each returning a normalised result. |

## Current status

| Provider | Enabled | Role |
| --- | --- | --- |
| ISQUAREDATA | yes | Primary catalogue and fulfilment for data and every biller service. |
| WiseSub | yes | Retained fallback; the only supplier used for airtime. |
| MeleData | no | Retired (`selection_excluded`), kept for historical rows. |
| RizPay | no | Retired (`selection_excluded`), contract kept current for future use. |
| GN Data | no | Prepared adapter with no credentials; inert until they are supplied. |

## Routing rules

1. **Data** is routed to the provider that owns the plan row
   (`_plan_owner_provider`). A mixed catalogue therefore serves both suppliers
   without a routing flag.
2. **Airtime** always goes through WiseSub. If WiseSub is not ready the request
   is refused with a clean 503 *before* any wallet movement.
3. **Billers** (electricity, TV, education) are ISQUAREDATA only.
4. A `SupplierPreFlightRefusal` never debits the customer.

## Adding a provider

1. Implement the adapter and register it in `default_adapters()`.
2. Ship it disconfigured: no credentials, `enabled = 0` in the `providers` table.
3. Add contract tests with mocked HTTP; never call a live supplier from tests.
4. Validate a live purchase with the owner present before enabling it.
