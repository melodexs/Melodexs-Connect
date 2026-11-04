# ADR 0005: the wallet deposit fee is fixed when the deposit is created

## Context

A percentage (default 3%) is kept from each Paystack deposit: pay N1,000, the
wallet receives N970. The rate can change at any time through
`DEPOSIT_FEE_PERCENT`, and deposits take a moment to confirm, so a deposit can
be created at one rate and confirmed after the rate changed. Paystack also
validates the amount charged against what we asked for.

## Decision

* The customer is charged the **full** amount, so Paystack's amount check is
  unchanged.
* The fee is computed once, in whole kobo with round-half-up, when the deposit
  is created, and written to the transaction description after the
  customer-visible first segment (`... | deposit_fee_kobo=3000 | credit_kobo=97000`).
* Crediting reads the stored figure, never the live rate.
* A deposit with no marker (every one made before this shipped) is credited in
  full. A marker whose two figures do not add up to the amount paid is ignored
  and the full amount is credited, so tampering can never short-change a customer.
* No schema change and no migration.

## Consequences

* Changing the rate never alters a deposit already in flight.
* Customers only ever see the first segment of a description
  (`customerDescription`), so the markers stay internal.
* If this ever needs reporting, a dedicated `fee` column plus a reviewed
  migration would be cleaner than parsing the description. That was avoided here
  to keep the change migration-free.
