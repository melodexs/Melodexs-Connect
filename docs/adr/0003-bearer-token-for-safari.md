# ADR 0003: accept a bearer token alongside the session cookie

## Context

The web app (`melodexs-connect.onrender.com`) and the API
(`melodexs-connect-api.onrender.com`) are different *sites*, because
`onrender.com` is on the public suffix list. Safari and every iOS browser block
third-party cookies by default, so the login cookie was discarded and every page
bounced back to the sign-in screen. Chrome only worked because it still allowed
those cookies.

## Decision

Login, register and Google sign-in also return the same signed value as
`session_token`. `session_id()` accepts `Authorization: Bearer <token>` when no
cookie is present. `api.js` attaches the token automatically and clears it on
logout or a failed boot. CORS allows the `Authorization` header.

## Consequences

* iOS users stay signed in.
* The token lives in `localStorage`, so unlike the `HttpOnly` cookie it is
  readable by script. The strict Content-Security-Policy is what makes that
  acceptable; keep it strict.
* When both are present the cookie wins.
* A permanent alternative is serving the app and API from one origin (the API
  can already serve `apps/web`), which removes the cross-site cookie entirely.
