# Changelog

Notable changes, newest first. Dates are deployment dates.

## November 2026

### Google Search Console verification
* **Added**: the `google-site-verification` meta tag on the landing page so the owner can verify melodex.com.ng in Google Search Console (sitemap submission, indexing requests). The tag is public by design. `tests/test_search_console_verification.py` keeps exactly one in the page head.

### Site moves to melodex.com.ng
* **Changed**: on `https://melodex.com.ng` the app now calls `https://api.melodex.com.ng`. Because the site and API now share one registrable domain, the sign-in cookie is first-party, which is the more reliable setup on iPhones and Safari. The bearer-token fallback stays as a safety net.
* **Old address still works**: anyone on `melodexs-connect.onrender.com` (saved links, installed apps, the Android app) keeps using the old API unchanged. `api.js` picks the API from the page hostname, with an exact match on `melodex.com.ng` / `www.melodex.com.ng` only; look-alike hostnames fall back to the old API. A staging `<meta name="api-base-url">` and local development still win.
* **Security policy**: the Content-Security-Policy now lists both API addresses in `connect-src` (explicit, no wildcard); without it the browser would block calls to whichever one is missing.
* **Search and link previews**: sitemap, robots, social-preview tags and `security.txt` now name `melodex.com.ng`.
* **Still to do**: Render `CHEAPDATA_PUBLIC_URL` (password-reset and Paystack return links), the Paystack and ISQUAREDATA callbacks, the Android app address, and the redirect from the old link. `tests/test_domain_switch.py` executes `api.js` for each hostname to pin all of the above.

### API accepts the new domain (melodex.com.ng)
* **Changed**: the API now accepts requests from `https://melodex.com.ng` and `https://www.melodex.com.ng` as well as the old `melodexs-connect.onrender.com` address. Before this, anyone opening the site on the new domain could browse but sign-in, registration and purchases were refused (HTTP 403).
* **Safe by design**: the allowed list is one exact set of three addresses (`KNOWN_SITE_ORIGINS`), used by both origin checks. Look-alikes (`melodex.com.ng.evil.example`, `evil-melodex.com.ng`, `http://`, other subdomains, `null`) stay blocked, and a blocked request still runs no handler code. `api.melodex.com.ng` is deliberately not on the list because pages are never loaded from it.
* **Not changed yet**: the site still talks to the old API address, and Google sign-in, Paystack and the ISQUAREDATA callback still use the old links. Each moves in its own step. `tests/test_custom_domain_origins.py` pins all of this.

### Renamed to MELODEX
* **Changed**: the product is now called **MELODEX** (was MELODEXS CONNECT). Customers see it on every page title, the logo, headings, the sidebar, the installed app name on a phone's home screen (web and Android), the offline page, receipts' wording, the Help and Privacy pages, the WhatsApp and email help messages, and the password-reset email subject and sender name.
* **Deliberately unchanged**: the live web addresses (`melodexs-connect.onrender.com` and the API), the Render service names, the GitHub repository, the Android package id, the session cookie and its signing salt, saved settings keys and the internal code names. Customers never read these, and changing them would sign everyone out, stop Android installs updating, or point people at addresses that do not exist. `tests/test_brand_name.py` pins both halves.
* **Domain**: when a MELODEX domain is bought, the address, sitemap, social-preview tags, security contact, Google sign-in origin and Paystack callback move together as a separate step.
* **Old records**: past transactions, runbooks and earlier changelog entries keep the name that was true when they were written.

### Admin: customer detail
* **Added**: a **View** button on every row of Registered Users opens that customer: wallet balance, total topped up, total spent (successful purchases only), pending and failed counts, and their full transaction history, newest first, with the supplier and supplier reference. Search the history by reference, description or supplier, filter by status, and load older rows 100 at a time. Support can now answer "my purchase did not arrive" in one click.
* **Read-only**: it shows data and changes nothing. There are no refund or balance buttons. Passwords, purchase PINs and reset tokens are never sent to the page.
* **Admin only**: the new `GET /api/admin/users/{id}` endpoint rejects signed-out visitors and ordinary customers.

### Admin dashboard: see what needs you first
* **Needs attention strip** at the top: pending purchases (customers waiting), failed transactions in recent activity, today's activity with the value of completed purchases, and customers with a N0 wallet. Each card jumps to the section where you act on it.
* **Section menu** that stays at the top while you scroll (Overview, Pricing, Providers, Pending, Users, Transactions), with a count badge on Pending. On a phone it scrolls sideways inside itself.
* **Search and filters**: find a customer by name, email, phone or ID, and filter by N0 wallet, has balance or admin. Find a transaction by reference, customer or description, and filter by status and type. Each shows "X of Y".
* **One broken section no longer blanks the page**: if statistics or transactions fail to load, the rest still show and a message names what failed.
* **Honest wording**: the button now says "Synchronize catalog plans", and the providers note no longer claims every purchase goes through WiseSub.
* No change to what any admin action does, no new endpoints, no database change.

### Create account page matches Login
* **Fixed**: on a laptop or desktop the Create Account form stretched across the whole screen while Login sat in a neat centred card. Login, Create Account, Forgot password and Reset password now share one centred column of the same width, with the heading centred above it and the brand name highlighted in lime. Phones are unchanged in width (the card still fills the screen with a small margin).

### Deposit fee is now impossible to miss
* **Fixed**: a customer topped up without seeing that a fee is deducted. The Top Up page now shows a fee notice at the top (for example: 3% is deducted, pay ₦1,000 and ₦970 is added). The Continue button stays off until the fee has loaded, and retries once if the server is waking up. If the fee still cannot load, the page says so and offers Retry instead of letting you pay blind. Before going to Paystack, a confirmation lists what you pay, the fee, and what reaches your wallet.

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
