# ADR 0001: one adapter per supplier, registered centrally

## Context

The platform needs to buy data, airtime and bill payments from different VTU
suppliers. Each supplier has a different catalogue shape, error vocabulary and
idea of what "failed" means. Prices and routing decisions must stay consistent
regardless of who fulfils an order.

## Decision

Every supplier implements the same adapter interface and is registered in
`app/provider_registry.py`. Adapters declare capabilities, whether they are
configured, and how conservative their failure semantics are. Routing rules and
money handling live in the platform, never inside an adapter.

A supplier that is replaced stays registered with `selection_excluded = True`
instead of being deleted, so historical transactions still resolve.

## Consequences

* Adding a supplier cannot change customer-visible behaviour until it is enabled
  and configured.
* Each adapter is testable with mocked HTTP; no test calls a live supplier.
* Some duplication between adapters is accepted in exchange for isolation: a bug
  in one cannot corrupt another's catalogue.
* Retired adapters keep a maintenance cost, which is the price of keeping old
  transactions explainable.
