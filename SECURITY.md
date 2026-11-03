# Security policy

## Reporting

Email **okohmelody30@gmail.com** with steps to reproduce. Please do not open a
public issue for a vulnerability, and give us a reasonable window to fix it
before disclosing.

`/.well-known/security.txt` carries the same contact with an expiry date.

## In scope

* Authentication and session handling (`/api/login`, `/api/bootstrap`, cookies and
  bearer tokens).
* Money paths: purchases, refunds, wallet funding, purchase-PIN enforcement.
* Authorisation: any way for one account to read or act on another's data.
* Webhook signature verification.
* Injection, XSS, CSRF and header hardening on both deployables.

## Out of scope

* Denial of service by volume.
* Reports that only exist on outdated browsers.
* Findings that require the victim's device or mail account to be compromised.

## How the platform is hardened

* Passwords are bcrypt hashes (cost 10); purchase PINs are stored hashed and
  required for every spend.
* Sessions are server-side rows. The cookie is `HttpOnly`, `Secure` and
  `SameSite=None`; browsers that block it use the same signed value as a bearer
  token instead.
* Every response carries CSP, `X-Frame-Options: DENY`, a referrer policy and a
  restrictive permissions policy. Cross-origin calls are allow-listed by origin.
* Supplier webhooks are verified with an HMAC-SHA512 signature over the raw body.
* The API refuses to start if the PostgreSQL schema drifts from the reviewed
  expectation.
