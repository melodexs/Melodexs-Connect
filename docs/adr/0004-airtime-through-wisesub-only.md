# ADR 0004: airtime is fulfilled through WiseSub only

## Context

ISQUAREDATA is the primary provider and serves data. For airtime the owner
decided to keep using WiseSub. An earlier design let airtime fall back to
WiseSub only when ISQUAREDATA was unavailable, which left two code paths for one
product.

## Decision

Airtime purchases always go through WiseSub. `_airtime_wisesub_ready()` (the
provider is configured, enabled and not excluded) gates every airtime purchase,
independent of `MULTI_PROVIDER_ROUTING_ENABLED`. When WiseSub is not ready the
request is refused with a clean 503 **before** any debit, so no wallet movement
and no transaction row exist.

## Consequences

* One path to reason about for airtime; the old fallback was removed.
* If WiseSub is down, airtime is down. That is deliberate and visible.
* Data is unaffected and still follows ISQUAREDATA-primary routing.
* WiseSub has no balance endpoint, so there is no supplier pre-check for it; an
  unfunded WiseSub purchase stays pending until an admin reconciles it.
