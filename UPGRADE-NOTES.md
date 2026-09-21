# MELODEXS CONNECT Upgrade Notes

This package is a clean replacement copy of the current MELODEXS CONNECT project.

## Added

- Server-side Paystack wallet funding verification.
- Pending wallet-funding transactions are created before checkout.
- Wallet credit occurs only after Paystack confirms the exact reference, amount, NGN currency, successful status, and matching user metadata.
- Verification is idempotent so the same payment cannot credit the wallet twice.
- Fund-wallet page automatically verifies a Paystack callback reference.
- SQLite data-plan schema now contains the provider metadata required by the WiseSub sync script.
- WiseSub sync script was aligned with the current `data_plans` schema (`plan` / `active`).
- Airtime wallet debit now has the same atomic balance guard as data purchases.
- JSON and URL-encoded request body limits were added.
- Proxy trust is enabled for hosted HTTPS deployments.
- Accidental Markdown code fences were removed from HTML files.

## Important

- `.env` is intentionally NOT included. Keep your existing `.env` file.
- The SQLite database is intentionally NOT included. Keep your existing database.
- `node_modules` is intentionally NOT included. Run `npm install` after replacing the project files.
- The old duplicate `pricing-upgrade` copy and nested ZIP were removed from this replacement package.

## Current limitation

Data and airtime purchase routes still perform local wallet debits and record the transaction. They do not yet call WiseSub to fulfill the purchase. That should be the next major integration: provider request -> pending transaction -> provider result -> successful/failed state -> automatic refund on a failed fulfillment.
