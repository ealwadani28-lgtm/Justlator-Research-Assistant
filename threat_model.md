# Threat Model

## Project Overview

Justlator is a single-page Translation Studies research assistant served by a small Flask backend. The production surface is a static `index.html` frontend plus four Flask routes in `server.py` that proxy requests to Anthropic for text humanization, paper writing, and similarity analysis. The application has no user-account system; the primary sensitive assets are Anthropic API keys, user research text, generated papers, and any internal project files that become web-reachable.

Production assumptions for this scan:
- Only production-reachable code is in scope.
- Mock or sandbox-only paths are out of scope unless production reachability is demonstrated.
- `NODE_ENV` is assumed to be `production` when deployed.
- TLS is provided by the platform.

## Assets

- **Server-side Anthropic API key** — if `ANTHROPIC_API_KEY` is configured on the server, abuse of the backend can spend the operator's credits and act as the application's paid AI identity.
- **User-provided Anthropic API keys** — users can provide their own Claude key through the frontend, so the client runtime handles credential material that must not be exposed to unrelated parties.
- **User research content** — topics, notes, source metadata, similarity inputs, and generated papers may contain unpublished academic work or sensitive research data.
- **Repository and operational files** — source code, `.replit`, `replit.md`, task files, and other hidden project artifacts reveal architecture and internal operations if exposed over HTTP.

## Trust Boundaries

- **Browser to Flask API** — all `/api/*` requests cross from an untrusted client into server-side code that can invoke a paid Anthropic account.
- **Flask to Anthropic API** — the backend uses either a trusted server secret or an untrusted client-supplied key to call Anthropic.
- **Public web to static file serving** — requests for `/` and static assets cross into Flask's static-file handler; the server must not expose non-public repo files.
- **User input to model prompts** — arbitrary text from users is interpolated into prompts sent to Anthropic, so endpoints must enforce size, access, and abuse controls even if prompt injection is not a classic server compromise.
- **Client runtime to browser storage** — drafts, preferences, glossary content, and optionally user-provided keys are persisted in browser storage and should be treated as sensitive client-side state.

## Scan Anchors

- **Production entry points:** `server.py` and `index.html`
- **Highest-risk backend area:** Flask route handlers and app initialization in `server.py`
- **Public surface:** `/`, `/api/config`, `/api/humanize`, `/api/write`, `/api/similarity`, and Flask static file routes rooted at `.`
- **Client-side sensitive handling:** Claude key handling plus draft/source persistence in `index.html`
- **Usually ignorable dev-only areas:** `.agents/`, `.local/skills/`, attached screenshots, and helper scripts unless they become web-reachable through server configuration

## Threat Categories

### Spoofing

This project does not have end-user login, but the backend can still be abused as the application's AI identity when a server-side Anthropic key is configured. Public AI endpoints MUST ensure only intended callers can spend server-billed credits, and any future privileged automation or webhooks MUST be authenticated explicitly.

### Tampering

The client is fully untrusted. Requests to AI endpoints, storage-backed glossary imports, and research source metadata MUST be validated for shape and reasonable size, and server-side business controls MUST not rely on the frontend to decide who may invoke expensive model operations.

### Information Disclosure

The server serves both the application UI and static files, so deployment MUST ensure only intended public assets are web-accessible. Internal repo files, operational metadata, source code, and hidden directories such as `.local/` MUST NOT be exposed through Flask static-file configuration. Error responses should remain generic, and secrets must stay in environment variables rather than files under the web root.

### Denial of Service

AI endpoints are cost-amplifying and computationally expensive. Public requests MUST be authenticated or otherwise constrained with quotas, rate limits, and request-size limits so attackers cannot drive excessive Anthropic spend or tie up the service with oversized prompts.

### Elevation of Privilege

There is no role system today, but the main privilege boundary is between anonymous internet users and the server's ability to use a trusted Anthropic credential and access local files. Anonymous callers MUST NOT inherit server-side capabilities they do not already possess, including paid API access or file retrieval outside the intended public UI.
