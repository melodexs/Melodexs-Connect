# Deployment

Two Render services and one Neon project.

| Resource | Value |
| --- | --- |
| API service | `srv-dap97sqd0e5s73f5hk70`, region `oregon` |
| Static site | `melodexs-connect.onrender.com` |
| Database | Neon project `silent-forest-89319786`, `us-west-2` |

## Environment

The API reads its configuration from Render environment variables. Nineteen are
in use, and every change is applied by reading the full list and writing it back,
so a single edit can never drop the others:

```
GET  https://api.render.com/v1/services/<id>/env-vars
PUT  https://api.render.com/v1/services/<id>/env-vars   # full list
```

Environment changes do **not** restart the running service by themselves. Trigger
a deploy afterwards or the old values stay in memory:

```
POST https://api.render.com/v1/services/<id>/deploys -d '{"clearCache":"do_not_clear"}'
```

## Deploying

1. Merge to `master`. CI runs the Python suite on a scratch SQLite database.
2. Web-only changes deploy automatically to the static site.
3. Backend changes need a deploy trigger on the API service; watch the deploy to
   `live` and then hit `/api/status`.

A failed API deploy does not take the site down: Render keeps the previous
instance serving until the new one reports healthy.

## Rollback

* **Application**: deploy the previous commit id.
* **Environment**: rewrite the env list with the previous values.
* **Database region**: the London project still holds a full copy. Point
  `DATABASE_URL` back at the old host, deploy, and the app runs on it unchanged.

## Post-deploy checklist

1. `GET /api/status` returns `success: true`.
2. Login works, and `/api/bootstrap` returns `loggedIn: true` with the bearer token.
3. Catalogue counts unchanged (`/api/data-plans?network=MTN`).
4. `providers` table unchanged: ISQUAREDATA enabled, others as expected.
5. Wallet totals unchanged for a sample user.
