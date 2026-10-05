# Plight

Plight is a persistent, shared-world text RPG. The repository now contains its first runnable browser/server vertical slice: email/password accounts, separate character creation, an authenticated two-area world, natural-language command resolution, persistent global/private chat, and live chat events.

## Local development

Use Python 3.11 or newer and Node.js 20 or newer.

1. Install backend dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. Apply the database migration:

   ```powershell
   alembic upgrade head
   ```

3. Start the API and browser app together:

   ```powershell
   .\start-plight.ps1
   ```

   Enter the email address of your creator account when prompted. The launcher starts the API and Vite in separate PowerShell windows, selects an available browser port, configures the matching local CORS origin, and opens the browser when both services are ready. It restarts an existing Plight API only after confirmation and refuses to stop unrelated processes. Close the two service windows to stop the app. The client uses tab-scoped `sessionStorage`; closing the browser tab ends that client-side session.

## World content studio

The authenticated browser app includes a content studio for the configured creator account. Set `PLIGHT_CONTENT_EDITOR_EMAIL` to the email address of an existing game account before starting the API, then sign in to the browser with that account and choose **Content studio**. Other players can read neither edit nor publish world definitions through the content API.

The studio edits `plight_server/world_content.json`, the versioned server-side source for locations, exits, starting areas, NPCs, enemies, items, weapons, furniture, objects, resources, and crafting recipes. Locations, NPCs, and enemies can each have ambience text blocks. NPCs have an authored race, a list of player races that can see them, and branching dialogue nodes with player-choice buttons. Enemies have health, attack, defense, and an authored attack die (D2–D100); their retaliation rolls an integer from 1 through the die's sides and adds it to base attack. Conversations start at the configured opening node each time. While a player is in an area, the atmosphere panel runs a rolling feed of ambient lines, adding a new line every five seconds and fading each line over 18 seconds. **Save to active world** atomically publishes changes; the server immediately uses updated location descriptions and exits, and world snapshots include authored encounters and ambience lines. Content changes do not require a database migration. Back up the JSON file before major edits, and include intentional content changes in source control.

Content references are checked before a save is accepted. Locations cannot be removed while characters are still there, and stale editor sessions must reload instead of overwriting a newer save. The player view shows the current area's description, exits, NPCs, enemies, objects, and resources. Players can travel between directly connected exits and open NPC dialogue from the area panel or command input. The fixed-height activity panel appends confirmed results at the bottom, supports scrollback, clears on location changes, deduplicates HTTP and live-event results, and does not expose parser interpretations. NPC dialogue is orange, enemy text red, ambient world information dark green, player text green, and party-channel player text yellow. Combat is a persistent per-character encounter: players start with 100 health, 3 attack, 1 defense, and 10 speed, and a fist in each hand. Attacks use only the right-hand equipment slot; an equipped weapon adds its authored damage to the player's base attack. Living enemies retaliate after an attack, rolling their authored die and adding the result to base attack. A defended strike deals half damage, rounded down. A defeated player returns to their species' starting location at full health, keeps their inventory, and resets the current enemy; enemies also reset for that character when they leave the area. `observe my inventory`, `look in my inventory`, and `what am I carrying?` open the inventory/equipment menu; `observe armor`, `observe hands`, and `observe weapons` select menu views. The menu and the canonical `equip_item` / `unequip_item` commands use server-validated owned items and equipment slots. The current content defines weapon equipment only for the two hand slots; other item types explicitly report that they have no equipment definition. A co-located player's `observe` profile shows equipped gear but never their inventory. Migration `0006_equipment_slots` adds all armor, hand, ring, and necklace slots while preserving previously equipped hand items. NPC inventories, recipes, and other entity attributes remain content data; shop, crafting, gathering, and player-trade handlers are not implemented.

The API defaults to `sqlite:///./plight.db`. Set `PLIGHT_DATABASE_URL` to change it. Set `PLIGHT_UI_ORIGIN` to the one deployed browser origin when running outside local development; when set, that origin replaces the localhost development allow-list. Do not put tunnel credentials, passwords, signing keys, or database files in the browser build.

## Public browser publishing and laptop server

The browser UI is published at `https://zship135.github.io/` from the `Zship135/zship135.github.io` repository. GitHub Pages hosts only the static browser UI. The game API, live WebSocket, and SQLite database run on the developer's laptop; an ngrok agent creates the public HTTPS/WSS route to the API. This lets anyone reach the UI and register an account while the laptop and tunnel are online. It is an early alpha, not an always-available production service.

### One-time GitHub and ngrok setup

1. In `Zship135/zship135.github.io`, set **Settings → Pages → Build and deployment → Source** to **GitHub Actions**. This publishes Plight at the site root without deleting the repository's previous source files.
2. Install the ngrok agent on the laptop and configure its auth token locally using ngrok's instructions. Never add the ngrok auth token to this repository or the browser build.
3. Apply database migrations after taking a consistent backup:

   ```powershell
   python -m alembic upgrade head
   ```

4. Start the laptop API and tunnel:

   ```powershell
   .\start-plight-public.ps1
   ```

   The script uses the HTTPS hostname assigned by ngrok and prints the public API origin. If you have a specific assigned domain, optionally add `-NgrokDomain "your-assigned-name.ngrok-free.app"`. Add `-CreatorEmail "you@example.com"` if this account should edit world content.

The startup script checks the local API, launches ngrok, verifies the public `/health` endpoint, configures the API to allow only the supplied Pages origin, and binds Uvicorn to `127.0.0.1` with one worker. It uses this project's Pages origin and assigned ngrok hostname by default; if both services are already healthy, rerunning it verifies them without starting duplicates. Copy the printed public API origin into the repository variable `PLIGHT_API_BASE_URL` at **Settings → Secrets and variables → Actions → Variables**. Keep both windows running; do not expose port 8000 on the router or bind Uvicorn to a public interface. The default database remains `plight.db` in the project folder.

The root `.github/workflows/pages.yml` workflow builds and deploys only the static Plight UI at the site root. It runs on pushes to `main` that change the Plight project or workflow, and can also be started manually from **Actions → Publish Plight browser UI → Run workflow**. The build validates that `PLIGHT_API_BASE_URL` is an HTTPS origin. After deployment, open `https://zship135.github.io/` and test account registration, sign-in, a game command, chat, and the live connection. The site is publicly reachable, but the laptop, network, ngrok service, and free-plan limits determine availability. Set up and test encrypted off-device database backups before inviting players.

The browser client sends `ngrok-skip-browser-warning: true` on API requests to bypass ngrok's free-tier browser warning. The API explicitly permits this header in CORS; keep both settings when using the tunnel.

## Implemented API surface

- `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`
- `POST /api/v1/characters` to create the account's one persistent character
- `GET /api/v1/me`, `GET /api/v1/world/snapshot`, `GET /api/v1/players`
- `GET`/`PUT /api/v1/profile`, `PUT`/`DELETE /api/v1/profile/picture`
- `GET /api/v1/players?q={partial-name}` for partial character-name search and `GET /api/v1/players/{account_id}/profile`
- `GET /api/v1/friends`, `GET /api/v1/friend-requests`, `POST /api/v1/friend-requests`, and `PATCH /api/v1/friend-requests/{request_id}`
- `GET /api/v1/content/permission`, `GET /api/v1/content`, and `PUT /api/v1/content` for configured world-content editors
- `POST /api/v1/commands`, `GET /api/v1/commands/{request_id}`
- `POST /api/v1/chat/messages`, `GET /api/v1/chat/{channel_id}/messages`
- `WS /api/v1/live`

Account registration collects only email and password. On first sign-in, accounts without a character are directed to character creation, where they choose a globally unique name, human or goblin species, and cosmetic appearance. Background, past, heritage, and religion are deferred. Bearer tokens are random opaque values; only their SHA-256 hashes are stored in the database. Passwords use Argon2id. Sessions expire after 12 hours. Chat history is paginated at no more than 50 messages and expired messages are removed by the running server. Global and participant-authorized private channels are available; party membership and party chat are not implemented yet.

Profiles store optional pronouns, up to 2,000 characters of lore, and a sanitized profile picture. Picture uploads accept PNG, JPEG, or WebP request bodies up to 512 KiB and four million pixels; the server decodes and re-encodes accepted images as PNG. Profile metadata and image delivery require an authenticated bearer session. Profile fields are shown to authenticated players in search results. Search uses partial, case-insensitive character-name matches. Friend requests remain pending until their recipient explicitly accepts; request, friend, search, and profile APIs are authenticated.

`PUT /api/v1/profile` accepts `{"pronouns": "they/them", "lore": "..."}`. Upload to `PUT /api/v1/profile/picture` as the raw image body with its `image/png`, `image/jpeg`, or `image/webp` content type; use `DELETE` on that path to remove it. `GET /api/v1/players?q=ash` returns at most 50 case-insensitive partial name matches with `account_id`, `name`, `species`, `area_name`, `pronouns`, `lore`, `profile_picture_url`, and `friend_status`. The picture URL itself also requires a bearer token. Send `POST /api/v1/friend-requests` with `{"recipient_account_id": "<account UUID>"}`; only that request's recipient can respond with `PATCH /api/v1/friend-requests/{request_id}` and `{"status": "accepted"}` or `{"status": "rejected"}`.

Command submissions use a client UUID and a database uniqueness constraint. The first vertical slice parses with the repository's deterministic local action catalog and immediately persists the result before returning `202`; supported effects include observation, travel, talk, inventory inspection, wait, defend, attack variants, and equipping an owned weapon in either hand. `observe` with no target describes the current area, while a target resolves against present world entities or players in the same area; observing a player opens that character's profile. Missing or ambiguous targets return an in-world clarification/failure. Other recognized actions return an in-world unavailable response rather than changing state. This is not yet the full queued combat, gathering, crafting, trading, marketplace, or character-progression MVP.

## Database and operation

Use Alembic for schema changes. Make a consistent SQLite online backup before migrations or deployments and test restores before inviting external players. The six-hour encrypted off-device backup and retention process, operational monitoring, and outage/recovery runbook remain deployment work; this initial code does not claim to provide those facilities. SQLite and the in-process live-event hub are intentionally single-process components.

## Tests

```powershell
python -m pytest
```

The browser's focused profile-state tests and production build can be run with `cd web; npm test; npm run build`.

The API validates exact browser origins and rejects unauthorized subscriptions. It uses in-process rate limits suitable only for the documented single-server MVP; add a durable/shared limiter before scaling beyond one worker.
