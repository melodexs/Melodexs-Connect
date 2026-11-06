# Operations

## Purchases that stay pending

A purchase is only marked successful when the supplier confirms it. Anything else
is held as `pending` rather than guessed, because a wrong "failed" would refund a
bundle the customer actually received.

1. `/api/status` is pinged every few minutes by the keep-alive workflow. Each ping
   schedules a sweep of ISQUAREDATA purchases pending longer than ten minutes
   (rate limited to one sweep every three minutes, 25 rows per batch).
2. A sweep requeries the supplier. A confirmed success finalises the transaction
   with the same effects as the webhook.
3. Still unknown stays pending. There are no automatic refunds.

## Reconciling by hand

The admin page (`apps/web/admin.html`) opens with a **Needs attention** strip: pending
purchases, failed transactions among the latest 100, today's activity (Africa/Lagos
day) and customers with a N0 wallet. Pending is the one to clear first; the nav badge
shows the same count. Users and Transactions are searchable in the browser from the rows
already loaded, so a search makes no extra request. Transactions are the latest 100, so
older ones need the database or a statement export.

```
GET  /api/admin/purchases/pending          # what is stuck
POST /api/admin/purchases/reconcile        # requery a batch
POST /api/admin/purchases/{id}/resolve     # finalise as successful or failed
```

Resolving as failed refunds the wallet using the same conditional-update style as
the rest of the money path; it is safe to retry.

## Webhooks

`POST /api/webhooks/isquaredata` verifies `x-isquare-signature`, an HMAC-SHA512 of
the raw body keyed by the profile UUID. Unknown references are logged and ignored,
and replays never double-apply. If supplier callbacks never arrive, the sweep
above is what keeps purchases moving; setting the callback URL on the ISQUAREDATA
dashboard is a manual step.

## Catalogue synchronisation

```
POST /api/admin/data-plans/synchronize     # fetch, price, upsert
GET  /api/admin/data-plans/synchronization # last runs
```

Selling price is `ceil(cost * 1.02)`. Rows with a manual override keep it. Runs are
audited in `data_plan_sync_runs`.

## Monitoring

* `GET /api/status` is the health probe. It also touches the database, so a
  failing database surfaces here first.
* Keep-alive: `.github/workflows/keepalive.yml` pings the API every five minutes.
* Provider health: `POST /api/admin/providers/{slug}/health-check`.
