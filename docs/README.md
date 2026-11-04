# Documentation

Start here. Everything below describes the system as it is deployed today.

| Document | Read it when |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | You need the shape of the system before changing it. |
| [FRONTEND.md](FRONTEND.md) | You are touching pages, CSS or the shared chrome. |
| [API.md](API.md) | You need an endpoint, its auth mode or its error contract. |
| [DATABASE.md](DATABASE.md) | You are changing schema, or wondering why the API refuses to boot. |
| [PROVIDERS.md](PROVIDERS.md) | You are adding or repairing a supplier integration. |
| [OPERATIONS.md](OPERATIONS.md) | A purchase is stuck pending, or a webhook never arrived. |
| [DEPLOYMENT.md](DEPLOYMENT.md) | You are deploying, changing environment variables or rolling back. |
| [TESTING.md](TESTING.md) | You are adding tests or running the suite. |
| [LOCAL-DEVELOPMENT.md](LOCAL-DEVELOPMENT.md) | You are setting the project up from scratch. |

## Decisions

Architecture decisions are recorded so the reasoning survives the people who made
them:

* [ADR 0001: one adapter per supplier](adr/0001-provider-adapter-pattern.md)
* [ADR 0002: database in the same region as the API](adr/0002-region-co-location.md)
* [ADR 0003: a bearer token backs up the session cookie](adr/0003-bearer-token-for-safari.md)
* [ADR 0004: airtime goes through WiseSub only](adr/0004-airtime-through-wisesub-only.md)
* [ADR 0005: the deposit fee is fixed at deposit creation](adr/0005-deposit-fee-stored-at-creation.md)

## Policies

* [CONTRIBUTING.md](../CONTRIBUTING.md) — how to propose and verify a change.
* [SECURITY.md](../SECURITY.md) — how to report a vulnerability.
* [CHANGELOG.md](../CHANGELOG.md) — what changed and when.
