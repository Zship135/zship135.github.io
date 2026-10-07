# Plight

Plight is a persistent, shared-world text RPG. The repository contains a runnable browser/server vertical slice: email/password accounts, character creation, an authored world, natural-language command resolution, per-character combat stats and shared enemy populations, loot and XP, player levels, branching multi-step quests with quest-gated exits, persistent chat, and live events.

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

The studio edits `plight_server/world_content.json`, the versioned server-side source for locations, exits, starting areas, NPCs, enemies, items, weapons, furniture, objects, resources, crafting recipes, and quests. Location exits can be gated by a quest; gates unlock for each character after that character completes the quest. Build quests in the **Quests** section with a giver, collect/kill/talk/visit objectives, branching steps, explicit player choices, and item or XP rewards. Players complete each step, choose a branch in the quest tracker, and return to the giver to claim final rewards. Existing fetch quests load as one-step quests and preserve saved player status. In the location editor, choose a quest as an exit requirement. NPCs have an authored race selected from a broad catalog of classic fantasy peoples, folkloric beings, elementals, constructed beings, beastfolk, undead, and otherworldly ancestries; they also have a list of player races that can see them and branching dialogue nodes with player-choice buttons. This NPC catalog does not change the two playable character species. Enemies have health, attack, defense, authored experience, loot-table entries with drop chances and quantity ranges, an authored attack die (D2–D100), a respawn chance percentage, a combat behavior, and an aggressive outside-combat hit chance. Respawn chance is rolled once per 15 seconds for each enemy type assigned to a location; its default is 0% until configured. Aggressive hit chance is rolled independently for each aggressive enemy instance and online player every 15 seconds; its default is 0%, disabling these attacks until configured. Each location has a maximum living-enemy population; assigned enemy types seed the initial population, duplicate instances can respawn, and the cap is enforced separately for each solo character and party. Passive enemies never retaliate, while neutral and aggressive enemies respond immediately to combat actions; only the character who acted is targeted. Conversations start at the configured opening node each time. While a player is in an area, the atmosphere panel runs a rolling feed of ambient lines, adding a new line every five seconds and fading each line over 18 seconds. The **Locations** editor accepts one looping MP3 background track per location; the **Audio** section assigns a shared MP3 effect to each recognized player action. Players can enable or mute game audio and adjust its volume. Audio files (up to 25 MiB each) are stored in `plight_server/audio_assets`, separately from the world JSON, and are served by the game API. Back up that directory along with the world JSON and database. **Save to active world** atomically publishes changes; the server immediately uses updated location descriptions and exits, and world snapshots include authored encounters and ambience lines. Content changes do not require a database migration. Back up the JSON file before major edits, and include intentional content changes in source control.

Content references are checked before a save is accepted. Locations cannot be removed while characters are still there, and stale editor sessions must reload instead of overwriting a newer save. The player view shows the current area's description, exits, NPCs, living enemy instances, objects, resources, level/XP, and a quest tracker with objective progress and branch choices. Quests must be accepted and finally turned in while with their giver; collection objectives consume required items at final turn-in, and completion/rewards apply only to that character. Kill, talk, and visit objectives progress from their corresponding in-game actions. Exits show a reason when a required quest is incomplete, and the server enforces the gate even for typed travel commands. The fixed-height activity panel appends confirmed results at the bottom, supports scrollback, clears on location changes, deduplicates HTTP and live-event results, and does not expose parser interpretations. NPC dialogue is orange, enemy text red, ambient world information dark green, player text green, and party-channel player text yellow. Player combat stats are persistent and per-character. Enemy populations and instance health are shared within a party encounter or kept separate for each solo character; different parties and solo players do not affect each other's enemy instances. Players start with 100 health, 3 attack, 1 defense, and 10 speed, and a fist in each hand. Enemy defeats award authored XP and roll authored loot tables. Each level requires 100 times the current level in additional XP; leveling grants +1 attack and +10 maximum/current health. Attacks use only the right-hand equipment slot; an equipped weapon adds its authored damage to the player's base attack. Passive enemies never retaliate; neutral and aggressive enemies respond to combat actions, rolling their authored die and targeting only the character who acted. Defend halves damage from each enemy response. A defeated player returns to their species' starting location at full health and keeps their inventory; defeating an enemy removes that instance for the current solo or party encounter until a later spawn roll succeeds. Party members can create a party, invite and accept members, leave or be removed, and use party chat. Combat resolves immediately in sentence order. For each attack, the player's action-adjusted Speed (light ×1.05, normal ×1.0, heavy ×0.95) is compared independently with each engaged non-passive enemy's Speed; the faster actor acts first. A tie pauses for a player-triggered D20 roll, and tied D20s require another click to reroll. Enemies acting first strike before the player's attack, which is cancelled if the player is defeated; enemies acting after the player retaliate after the attack. Defend and wait do not use initiative. The Roll button also supports standalone D20 rolls; dice and attack sound effects respect the audio toggle and volume. All online party members in the encounter area can participate, but only the current actor receives that exchange's enemy response. A defeated enemy gives each online party member in the area independent XP and loot rolls. `observe my inventory`, `look in my inventory`, and `what am I carrying?` open the inventory/equipment menu; `observe armor` opens Armor, while `observe hands` and `observe weapons` open the shared Hands view. The menu and the canonical `equip_item` / `unequip_item` commands use server-validated owned items and equipment slots. The current content defines weapon equipment only for the two hand slots; other item types explicitly report that they have no equipment definition. A co-located player's `observe` profile shows equipped gear but never their inventory. Migration `0006_equipment_slots` adds all armor, hand, ring, and necklace slots; `0008_enemy_populations` stores scoped enemy instances; `0009_parties_and_combat` adds party and combat state. NPC inventories, recipes, and other entity attributes remain content data; shop, crafting, gathering, and player-trade handlers are not implemented.

The API defaults to `sqlite:///./plight.db`. Set `PLIGHT_DATABASE_URL` to change it. Set `PLIGHT_UI_ORIGIN` to the deployed browser origin; the API allows that origin alongside the localhost development origins so the local Content Studio can still reach the API. Do not put tunnel credentials, passwords, signing keys, or database files in the browser build.

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
- `GET`/`POST /api/v1/party`, `POST /api/v1/party/invitations`, `PATCH /api/v1/party/invitations/{invitation_id}`, `DELETE /api/v1/party/members/{member_account_id}`, `DELETE /api/v1/party/membership`, and `DELETE /api/v1/party`
- `GET /api/v1/content/permission`, `GET`/`PUT /api/v1/content`, and `POST /api/v1/content/audio` for configured world-content editors; uploaded audio is publicly served from `GET /api/v1/content/audio/{asset_id}`
- `POST /api/v1/commands`, `GET /api/v1/commands/{request_id}`
- `POST /api/v1/chat/messages`, `GET /api/v1/chat/{channel_id}/messages`
- `WS /api/v1/live`

Account registration collects only email and password. On first sign-in, accounts without a character are directed to character creation, where they choose a globally unique name, human or goblin species, and cosmetic appearance. Background, past, heritage, and religion are deferred. Bearer tokens are random opaque values; only their SHA-256 hashes are stored in the database. Passwords use Argon2id. Sessions expire after 12 hours. Chat history is paginated at no more than 50 messages and expired messages are removed by the running server. Global, participant-authorized private, and party chat channels are available; party-channel access is checked against current membership.

Profiles store optional pronouns, up to 2,000 characters of lore, and a sanitized profile picture. Picture uploads accept PNG, JPEG, or WebP request bodies up to 512 KiB and four million pixels; the server decodes and re-encodes accepted images as PNG. Profile metadata and image delivery require an authenticated bearer session. Profile fields are shown to authenticated players in search results. Search uses partial, case-insensitive character-name matches. Friend requests remain pending until their recipient explicitly accepts; request, friend, search, and profile APIs are authenticated.

`PUT /api/v1/profile` accepts `{"pronouns": "they/them", "lore": "..."}`. Upload to `PUT /api/v1/profile/picture` as the raw image body with its `image/png`, `image/jpeg`, or `image/webp` content type; use `DELETE` on that path to remove it. `GET /api/v1/players?q=ash` returns at most 50 case-insensitive partial name matches with `account_id`, `name`, `species`, `area_name`, `pronouns`, `lore`, `profile_picture_url`, and `friend_status`. The picture URL itself also requires a bearer token. Send `POST /api/v1/friend-requests` with `{"recipient_account_id": "<account UUID>"}`; only that request's recipient can respond with `PATCH /api/v1/friend-requests/{request_id}` and `{"status": "accepted"}` or `{"status": "rejected"}`.

Command submissions use a client UUID and a database uniqueness constraint. Commands use the repository's deterministic local action catalog and return `200` with a completed result. Supported effects include observation, travel, talk, inventory inspection, wait, defend, attack variants, and equipping an owned weapon in either hand. Combat actions and their enemy responses resolve immediately; selected actions in a sentence retain their order, and new commands do not enter a combat queue. `observe` with no target describes the current area, while a target resolves against present world entities or players in the same area; observing a player opens that character's profile. Missing or ambiguous targets return an in-world clarification/failure. Other recognized actions return an in-world unavailable response rather than changing state. Gathering, crafting, trading, and marketplace handlers are not implemented.

## Database and operation

Use Alembic for schema changes. Make a consistent SQLite online backup before migrations or deployments and test restores before inviting external players. The six-hour encrypted off-device backup and retention process, operational monitoring, and outage/recovery runbook remain deployment work; this initial code does not claim to provide those facilities. SQLite and the in-process live-event hub are intentionally single-process components.

## Tests

```powershell
python -m pytest
```

The browser's focused profile-state tests and production build can be run with `cd web; npm test; npm run build`.

The API validates exact browser origins and rejects unauthorized subscriptions. It uses in-process rate limits suitable only for the documented single-server MVP; add a durable/shared limiter before scaling beyond one worker.
