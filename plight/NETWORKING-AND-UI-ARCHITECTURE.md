# Plight Networking and Browser UI

**Document status:** MVP architecture decisions  
**Audience:** Plight developer and implementation collaborators  
**Related design:** [PLIGHT-DESIGN-AND-DEVELOPMENT.md](./PLIGHT-DESIGN-AND-DEVELOPMENT.md)

This document records the networking and browser-UI direction discussed after reviewing the game design. The repository now includes an initial FastAPI/SQLite server and React/Vite browser slice; the decisions below remain the architecture baseline, not a claim that every listed MVP or operational feature is implemented.

## 1. Product context

Plight is a text-first, persistent, shared-world game. The Python server is authoritative for accounts, characters, world state, commands, and game outcomes. The browser client presents the activity stream, command entry, atmosphere, and chat in a responsive layout. Updates to chat and relevant shared-world activity should appear without a manual refresh.

The interface should feel like a readable text terminal or TUI, not a graphical game with text layered over it. On desktop it uses the activity/command area, an atmosphere panel, and chat panels; on phones those panels stack vertically. Interactive UI elements include chat tabs and player-profile views that players can open and close.

## 2. Decisions recorded

| Area | Direction | Status |
|---|---|---|
| Authoritative game server | Run the Python game server on the developer's laptop for the initial release. | Confirmed |
| Browser UI hosting | Publish the static browser UI on GitHub Pages. | Confirmed |
| Public hostname | Use a free tunnel-provided hostname initially rather than requiring a custom domain. | Confirmed |
| Public access from the internet to the laptop | Use the ngrok agent and its assigned free development domain for the publicly reachable early alpha. | Decided |
| Browser/server transport | HTTPS JSON API for request/response operations; secure WebSocket for pushed live events. | Decided |
| Authentication | Opaque, revocable bearer sessions; keep the token in tab-scoped `sessionStorage`; authenticate the WebSocket in its first message. | Decided |
| UI implementation | React with Vite, plain CSS, and minimal dependencies. | Decided |
| Python web framework | FastAPI with Pydantic request/response models. | Decided |
| Initial database | SQLite on the laptop, accessed through SQLAlchemy 2 and migrated with Alembic. One server process only. | Decided |
| Chat history | Persist messages for 90 days; load the latest 50 messages per conversation, with pagination for older retained messages. | Decided |
| Backups | Encrypted off-device database backup every six hours; RPO 6 hours, target RTO 4 hours. | Decided |

## 3. Recommended MVP architecture

```text
Player's browser
  ├── HTTPS: static UI assets from GitHub Pages
  └── HTTPS / secure WebSocket: game API and live events
              │
              ▼
      Public tunnel endpoint
              │ encrypted tunnel connection
              ▼
      Tunnel connector on developer laptop
              │ local connection
              ▼
      Python game server ─── local persistent database
```

GitHub Pages serves only the built client files. It does not run Python or hold authoritative game data. A tunnel connector running on the laptop initiates an outbound connection to the tunnel service and forwards authorized requests to the local game server. This avoids exposing a home router port directly and works with many dynamic home IP addresses or networks that do not permit inbound connections.

Use the ngrok command-line agent on the laptop and its assigned `*.ngrok-free.app` development hostname. This fits the no-custom-domain constraint and is simpler than home-router port forwarding. Keep the game server bound to localhost and let the agent establish the outbound tunnel; do not expose the Python server directly to the public network.

This is for development and a small publicly reachable alpha, not a production availability promise. Anyone with the Pages URL can attempt to register an account. The current ngrok free plan documents a 1 GB/month outbound transfer allowance, 20,000 HTTP requests/month, one development domain, and an interstitial warning for browser HTML traffic. Because GitHub Pages serves the HTML and ngrok serves only the API, validate actual browser `fetch` and WebSocket behavior through the assigned hostname; do not rely on assumptions about the warning page or free-tier behavior. Recheck quotas and terms before sharing the URL, monitor usage, and stop or upgrade before limits interrupt play. For comparison, Cloudflare Quick Tunnels provide temporary hostnames that change on restart and are explicitly intended for testing/development, so they are a poorer fit for a repeatable tester URL.

Official references: [ngrok free plan limits](https://ngrok.com/docs/pricing-limits/free-plan-limits/) and [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

### Service responsibilities

- **Browser client:** Render views and collect user input. Treat all client data as untrusted; do not decide game outcomes or keep the sole copy of game state.
- **Python game server:** Authenticate players, validate requests and game rules, resolve commands against current state, persist changes, and publish authorized events.
- **Database:** Store account and persistent character/world data on the server side. It must not be exposed to GitHub Pages or the browser.
- **Tunnel connector:** Provide encrypted public ingress to the local service. It is a network path, not an authentication or authorization system.
- **GitHub Pages:** Deliver versioned static assets. Never put passwords, signing keys, database files, or server credentials in the client bundle or repository's public UI configuration.

## 4. Browser-to-server communication

### Protocol split

Use HTTPS JSON requests for account/session operations, command submission, chat sends, and state/history reads. Use a secure WebSocket only for server-pushed events such as chat, activity updates, command outcomes, and atmosphere changes. Do not send state-changing commands over the WebSocket in the MVP.

This split keeps request validation, explicit errors, and idempotent writes straightforward while still providing low-latency delivery for events that arrive independently of a request. HTTPS endpoints should be versioned under `/api/v1`. Implement these MVP operations:

- `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, and `POST /api/v1/auth/logout`.
- `GET /api/v1/me` and `GET /api/v1/world/snapshot` for the authenticated character and current authoritative view.
- `POST /api/v1/commands`, with the player's raw text and a client-generated UUID request ID. The server derives the actor from the session, persists the request idempotently, and returns `202 Accepted` with the request ID and `queued` status. Return a stored result for a duplicate request ID instead of enqueuing it again.
- `GET /api/v1/commands/{request_id}` to recover the command's current status/result after a disconnect.
- `POST /api/v1/chat/messages` to submit a chat message, and `GET /api/v1/chat/{channel_id}/messages` to page through the latest 50 retained messages.

Return JSON errors using a consistent shape such as `{"error":{"code":"...","message":"...","request_id":"..."}}`; do not encode failures as success-shaped responses. Use explicit HTTP status codes for authentication, validation, conflict, rate-limit, and service-unavailable cases.

Connect to `/api/v1/live` using secure WebSocket (`wss`). Browser WebSocket APIs cannot set an Authorization header, so the client sends its bearer token in the first JSON frame—not in the URL—and the server must authenticate it before accepting subscriptions:

```json
{"type":"auth","token":"<session-token>"}
```

After authentication, messages use a versioned envelope. Server events include a monotonically increasing per-account `event_id`, `type`, `occurred_at`, and `payload`; for example:

```json
{"event_id":1842,"type":"chat.message","occurred_at":"2026-10-04T20:00:00Z","payload":{"channel_id":"global","message_id":"...","sender":"...","text":"..."}}
```

Authorize every channel subscription against the authenticated account and current party/area membership. Validate the exact GitHub Pages `Origin`, limit message sizes and rates, and never log bearer tokens or authentication frames. On reconnect, refresh the authoritative snapshot and command statuses; fetch chat history from its persisted API rather than relying on replay of an unbounded event log. WebSocket delivery is best-effort, not the durable record of game state.

### Connection behavior

- Establish the secure live connection after successful authentication and subscribe only to channels the authenticated player is allowed to receive.
- Reconnect after transient network loss with bounded backoff, show a visible disconnected/reconnecting state, and refresh authoritative state after reconnect. Do not imply that an unacknowledged command succeeded.
- Give consequential command submissions unique request IDs. The server should make retries idempotent so reconnects or timeouts cannot spend items, transfer goods, or enqueue the same action twice.
- Persist the server's authoritative results before publishing success events. Treat a lost event as recoverable by fetching current state or recent authorized activity after reconnect.
- Validate the WebSocket `Origin` against the deployed UI origin, authenticate the connection, and authorize every subscription and message. HTTPS/CORS configuration and WebSocket-origin validation are related but distinct controls.
- Return explicit authentication, validation, conflict, and service-unavailable errors. Never trust a client-supplied character/account identity or game state.

### Authentication and transport security

The existing game design calls for email/password accounts. Account creation and sign-in go to the Python backend over HTTPS. Hash passwords with Argon2id using a maintained library; never store reversible passwords or plain hashes. On successful login, issue a cryptographically random opaque bearer token, store only its hash in the server-side sessions table, and keep the token in tab-scoped `sessionStorage` so a page reload in the same tab does not force reauthentication. Do not use `localStorage`, URL parameters, or cookies for the session token. Set a 12-hour absolute session lifetime, revoke it on logout, and support server-side revocation.

Send the token in the HTTPS `Authorization: Bearer` header and in the first WebSocket authentication frame over TLS. Require reauthentication when the tab session is gone or expired. This is a deliberate MVP trade-off for a static GitHub Pages origin and a different API hostname; mitigate script-injection risk with a strict Content Security Policy, React's normal text escaping, no unsafe HTML rendering, and dependency minimization. Rate-limit sign-up and login attempts.

Because GitHub Pages and the game API have different origins, configure the API to allow only the deployed UI origin for browser requests. Configure the development UI origin separately rather than using a wildcard in production. Secrets required by the backend or tunnel connector belong on the laptop/server and must not be compiled into the UI.

## 5. Browser UI development and deployment

### Recommended implementation

Use a small React application built with Vite, plain CSS, and minimal additional dependencies. This is the selected MVP approach for interactive, stateful elements—chat tabs, open/closed profile panels, command status, and live event updates—without adopting a larger application framework or adding a graphical game engine. Keep the visual design text-first and use semantic HTML and keyboard-accessible controls.

Organize the client around a small number of focused areas: the command/activity stream, atmosphere panel, chat tabs and messages, and a player-profile view that can be opened and closed. Keep live-connection and authentication state separate from presentation where practical. Avoid building a complex client-side world model; render server-authoritative data and clearly distinguish pending actions from confirmed results.

Build one vertical slice before implementing every screen: sign-in, command/activity stream, chat, and a profile view that opens and closes. Keep the UI source in the repository and the output static. Use hash-based navigation if multiple client views require routes, avoiding reliance on server-side SPA fallback from GitHub Pages. Configure Vite's base path for the repository's GitHub Pages URL.

The current server uses FastAPI with Pydantic models and a native WebSocket endpoint, SQLAlchemy 2, and Alembic. HTTP database handlers are synchronous, and WebSocket database work is offloaded to worker threads. The current browser is a React/Vite application. The remaining recommendations in this document guide future expansion and deployment rather than describing an empty repository.

Use SQLite on the laptop for the initial playable MVP. It avoids a separate database service while the world, player population, and write volume are small. Enable foreign-key enforcement and WAL mode, use short explicit transactions, enforce unique constraints for idempotency, and back up through SQLite's online backup mechanism rather than copying a live database file. Run one application process/worker; SQLite write serialization and process-local coordination are not a multi-worker scaling strategy. Exercise simultaneous trades, queue updates, and duplicate requests in tests.

Move to PostgreSQL before broad public testing or any need for multiple server processes, higher write concurrency, or hosted deployment. Keep SQLAlchemy/Alembic migrations and database access behind repositories/services so the move does not require rewriting game rules.

### Build and publish

1. Keep the UI source code in the project repository, separate from backend secrets and persistent data.
2. Build static assets locally or in a GitHub Actions workflow.
3. Publish only the generated static assets to GitHub Pages.
4. Configure the client with the public game API hostname through a non-secret build setting. Do not include tunnel tokens or private credentials.
5. Configure the backend's allowed browser origin to the actual GitHub Pages origin.
6. Test the deployed page against the real secure API hostname; local development success alone does not verify the Pages origin, TLS, tunnel, or WebSocket path.

## 6. Operational limitations and safeguards

Laptop hosting is appropriate for an early prototype, but availability depends on the laptop being powered on, awake, connected to the internet, and running both the game server and tunnel connector. Restarting the laptop, home internet outages, tunnel-provider outages or limits, and network changes will disconnect players. The ngrok assigned development hostname is preferable to a new random hostname for repeatable testing, but the free plan's quotas and interstitial must be tested and monitored.

Before inviting players, add:

- A visible server availability/connection state in the client.
- Server health checks and useful logs that avoid recording passwords or session credentials.
- A tested backup and restore process: create a consistent SQLite online backup every six hours, encrypt it before sending it off-device, and retain 28 six-hourly backups plus four weekly checkpoints. Store the encryption recovery key separately from the laptop and backup destination.
- A controlled server startup/restart procedure and a way to apply updates without corrupting persistent data.
- Rate limits and request-size limits for public endpoints, plus authentication and authorization tests.
- A documented recovery procedure for a laptop, home-network, or tunnel outage.

The operational target is a maximum six-hour recovery point objective (RPO) and a four-hour recovery time objective (RTO) after a working replacement or repaired laptop is available. Make a backup before every schema or deployment change. Perform a restore drill at least monthly and before inviting external testers. The tunnel reduces inbound-network setup but does not make the server immune to abuse or downtime. The game server remains internet-facing through the tunnel and must validate all requests.

Persist global, party, and private chat messages for 90 days. Return at most 50 messages per history page and enforce channel membership on every history request. Delete expired messages through a scheduled server task. Keep ordinary application logs separate from chat content and credentials; retain only the operational logs needed to diagnose service behavior. Treat game state as authoritative and recover it from the database snapshot, not by replaying a permanent event stream.

## 7. Suggested implementation sequence

1. Prototype the Python server locally with a health endpoint and one authenticated request.
2. Install the ngrok agent on the laptop; verify its assigned HTTPS hostname, API requests, secure WebSocket behavior, cross-origin configuration, and current free-plan limits.
3. Build a small responsive UI slice: sign-in shell, command/activity area, chat panel, and open/close player profile.
4. Publish the static UI to GitHub Pages and verify the production origin can authenticate and connect securely.
5. Add the real-time channel, reconnect state, event authorization, and idempotent command handling.
6. Test with multiple browser sessions, a phone-sized viewport, laptop/server restart, temporary network loss, and duplicate command retries.
7. Add persistence backups, health monitoring, and operational documentation before a wider test.

## 8. Decision review and upgrade triggers

The initial MVP decisions are now set: ngrok free development domain; HTTPS JSON API plus secure WebSocket push; opaque bearer sessions; 90-day chat retention; React/Vite; FastAPI; SQLite with SQLAlchemy 2 and Alembic; six-hour encrypted off-device backups; six-hour RPO and four-hour RTO.

Revisit a decision only when evidence justifies it:

- **Tunnel:** Move off the free ngrok plan if quotas, browser interstitial behavior, provider terms, or availability interfere with tests. A public launch requires a stable supported hostname and a hosting/availability plan beyond a laptop.
- **Database:** Move from SQLite to PostgreSQL before multi-process deployment, broad public testing, or when measured write contention affects play.
- **Transport:** Keep commands on HTTPS and events on WebSocket unless the prototype demonstrates a concrete simplicity or reliability benefit from changing the contract.
- **UI:** Keep React/Vite unless the first vertical slice demonstrates that browser-native code is materially simpler to maintain for the required interactions.
- **Retention and recovery:** Revisit 90-day chat retention and backup objectives before public launch if moderation, privacy, or player expectations require a different policy.

The initial aim remains a working, low-cost browser experience with an authoritative server on the developer's laptop. These choices are intentionally sized for an early MVP and are not a claim of production-grade availability or scale.
