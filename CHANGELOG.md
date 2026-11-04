# Changelog

Notable changes, newest first. Dates are deployment dates.

## November 2026

### Install button on Profile
* **Fixed**: on a phone where the browser cannot show its own install prompt (app already installed, an in-app browser such as Instagram or Facebook, or a browser menu install), tapping "How to install" now shows the steps. Before, the steps were written but stayed hidden, so the button looked dead. iPhone steps and the one-tap Install button are unchanged.

### Wallet deposit fee
* **Added**: a 3% fee is kept from each wallet deposit. A customer who pays N1,000 gets N970 in their wallet. The fund page shows the fee live before they pay; the Wallet detail and receipt show the amount paid, the fee and what was added. Set `DEPOSIT_FEE_PERCENT` to change the rate (`0` turns it off). Deposits already in progress, and every older deposit, are credited exactly as before.

### Quality pass
* **Search**: every page now has a description, and sign-in, account and money pages are marked `noindex` so they stay out of search results even if linked.
* **Accessibility**: the add-plan and per-row inputs in Admin have real labels, and the current-PIN field is marked for password managers. The purchase PIN field still never autofills.
* **Code health**: ESLint is clean with zero warnings (unused `catch` bindings removed). New tests cover the error envelope, security helpers, rate limits, package matching and supplier comparison. Three new decision records (0003 to 0005) explain the bearer token, WiseSub-only airtime and the deposit fee.

### Cleaner desktop sidebar
* **Changed**: the desktop sidebar no longer lists a separate Profile item. Your photo, name and phone number at the bottom of the sidebar open Profile, and that card is highlighted while you are on the Profile page. Phones are unchanged: the bottom bar still has a Profile tab.

### Back to home
* **Fixed**: on the Help, Privacy and Prices pages, "Back to home" now takes a signed-in customer to their dashboard instead of the welcome page. Visitors who are not signed in still go to the welcome page.

### Sign-up with +234 and first-time setup
* **Sign-up accepts +234**: `+234 806 834 7514`, `2348068347514`, and numbers with spaces or dashes all work. They are stored as the local `0806...` form, so the same person cannot register twice under two spellings.
* **First-time setup**: after creating an account and a Purchase PIN, new users are asked to add a profile picture (or skip), then land on the home page. Existing users changing their PIN are not affected.

### Profile alignment
* **Fixed**: on the Profile page the welcome text ("Hello, ...", "Welcome to MELODEXS CONNECT") now starts exactly where the card text does, and the cards no longer touch the screen edge on a phone.

### Dark mode, recipient nicknames and network auto-detect
* **Network auto-detect**: on Buy Data and Buy Airtime the network is picked
  from the number as you type (prefixes from the NCC Mobile Number Allocation
  Table), and the page says what it picked. Tapping another network keeps your
  choice for that number, because ported numbers keep their old prefix. Saved
  recipients and "buy again" links keep the network they were saved with.
* **Recipient nicknames**: saving a number asks for an optional name.
* **Dark mode**: Light, Dark or follow-my-phone on the Profile page, applied
  before first paint so there is no flash.
* **Fixed**: saving a recipient only worked for MTN; Airtel, Glo and 9mobile
  failed with "Invalid network". All four now save.
* **Fixed**: page titles and subtitles on the blue background were dark text
  (contrast 2.5:1 and 1.2:1); now light.

### Help centre, price list and statement download
* **Help & Support** (`/help.html`): WhatsApp, call and email buttons plus an
  8-question FAQ covering pending and failed purchases, funding that has not
  credited, wrong numbers, the purchase PIN and password reset. Linked from the
  landing footer, Profile and the Wallet pending-purchase note; the offline page
  shows a tap-to-call line.
* **Public price list** (`/prices.html`): today's MTN, Airtel, Glo and 9mobile
  prices with network tabs and search, readable before signing up.
* **Wallet statement**: a Download CSV button exports the signed-in user's own
  history (respecting the active filter). The file opens correctly in Excel,
  and cells that could run as spreadsheet formulas are neutralised.
* **Privacy fix**: the Wallet list, detail view, receipt and export no longer
  show internal supplier notes that were stored after the first `|` in a
  transaction description.
* **Speed**: electricity, TV and education menus are cached for 5 minutes
  (stale copy served if the supplier is down), static assets carry browser cache
  headers, and the API is kept awake by the platform scheduler.
* **CI**: web-only changes now run the test suite, and Node is installed so the
  browser-module tests can never skip silently.
* **Repository**: removed four stale backup archives and blocked `*.zip`.

### Documentation and guard rails
* Added the guides that were living in people's heads: architecture, frontend,
  API, database, providers, operations, deployment, testing and local setup, plus
  an index and two decision records.
* Added correctness-only lint (CI and pre-commit), a Makefile that forces a
  scratch test database, an `.editorconfig`, Dependabot for pip and Actions, and
  a pull-request template that asks for evidence.
* New tests cover the user payload (no credential leaks), Nigerian phone
  validation, the 2% markup rounding, session cookie flags, safe configuration
  defaults, page/asset wiring, the PWA manifest, the service worker, the
  navigation contract, the desktop shell layout, `security.txt`, the crawl files,
  provider capabilities, the health and error contracts and repository hygiene
  (no committed secrets or database files).
* Fixed two real defects the new tests found: `privacy.html` pointed at two icons
  that do not exist, and `security.txt` had no `Policy` line.
* Accessibility: keyboard focus is now visible on every control, the desktop
  shell honours `prefers-reduced-motion`, and receipts print without the chrome.

### Database moved next to the application
Production PostgreSQL moved from London to `us-west-2`, the same region as the
API. Login went from ~1.8s to ~0.67s, page boot to 0.14s and catalogue reads to
0.24s. The London project is retained as a rollback copy.

### Faster sign-in
* Removed a fixed 700ms (login) and 900ms (registration) wait before redirecting.
* `/api/bootstrap` and `/api/session` resolve the session owner and profile in a
  single statement.
* Sign-in pages warm the database while the visitor types.

### Desktop shell
A fixed sidebar lists every feature with its icons, the content column widens and
the dashboard uses two columns. Phones keep the bottom bar.

### Providers
* RizPay adapter corrected to the supplier's documented contract (still retired).
* GN Data adapter prepared and registered, disabled without credentials.

## October 2026

### iOS sign-in fixed
`onrender.com` is a public suffix, so the site and the API are different sites and
Safari blocks the session cookie as third-party. Sign-in now also returns a session
token that the app sends as a bearer credential.

### Landing page
Defined the missing `--bluegray` token that made body copy render dark-on-dark,
and added a test that fails when a colour token is used but never declared.

### Billers, PWA, security headers
Electricity, TV and education result PINs; installable PWA with an offline page;
CSP and companion headers on both deployables.

### Provider platform
ISQUAREDATA activated as the primary provider with a 2% markup, WiseSub retained,
airtime pinned to WiseSub, mixed catalogue and automatic requery for pending
purchases.
