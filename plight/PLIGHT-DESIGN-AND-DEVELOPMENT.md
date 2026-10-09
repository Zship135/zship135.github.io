# Plight: Game Vision and Development Process

**Document status:** Interview synthesis and initial development guide  
**Audience:** The solo creator of Plight and AI-assisted development collaborators

This document records the decisions made during the initial design interview and turns them into a practical process for building Plight. It distinguishes agreed direction from questions that are intentionally left for implementation and playtesting. It is a living specification, not a claim that every system is fully designed.

## 1. Game vision

Plight is a **purely text-based, persistent, shared-world high-fantasy sandbox**. Players use natural-language text to act in the world, communicate with each other, and shape the conditions that future players encounter. There is no graphical game world: places, characters, combat, weather, and activity are conveyed through text and text-based interface panels.

The central experience is the freedom to decide what kind of life to pursue. A player might explore dangerous places with friends, fight, gather resources, craft, trade, or specialize in an economic role. There is no required central storyline; optional, authored NPC quests can offer personal goals and unlock content without funneling everyone through a single plot. The world supplies situations and events; players make their own adventures.

### Design principles

1. **Text is the whole game.** The browser interface should feel like a readable text terminal or TUI, not a graphical game with text added as a layer.
2. **Players express intent naturally.** Players should be able to type ordinary sentences rather than memorize a fixed command vocabulary.
3. **The game, not the parser, owns outcomes.** Language processing identifies intended canonical actions; game rules and current world state determine their effects.
4. **The world is shared and persistent.** Players inhabit the same world, and player characters and important world state persist across logins.
5. **Identity changes the experience.** A character's fixed species, background, heritage, and religion influence how the world and its inhabitants respond.
6. **Systems create stories.** Faction relations, local danger, trade, and events should produce emergent situations instead of funneling every player through a single plot.
7. **The interface is responsive and real-time.** Chat and relevant shared-world updates should appear without a manual refresh, on both desktop and phone.

## 2. Player experience and interface

### First session

A new player creates an account and one character, then enters a guided introduction with a wise old NPC. The introduction should teach the player by letting them type freely and see those sentences interpreted as actions. The tutorial is guided, but it should demonstrate the open-ended action model rather than teach a long list of fixed commands.

### Browser layout

The desktop layout is a text-focused, boxed interface:

- **Left side:** command entry and the main activity stream, including arrival descriptions, dialogue, action results, and combat.
- **Upper-right:** a read-only atmosphere panel for details such as weather, time of day, and sounds made by NPCs and enemies.
- **Lower-right:** chat tabs and a message input.
- **Chat tabs:** global chat, party chat, and one-to-one private chats opened from another player's profile. Players can open and close private-chat tabs.

On phones, stack the panels vertically rather than shrinking the desktop columns into an unusable layout. Keep the command field, activity stream, atmosphere, and chat practical to reach on a small screen.

## 3. Natural-language action system

### RPGNLP and canonical actions

RPGNLP is an existing, published, pip-installable Python package created by the game's developer. It currently parses sentences into structured data such as canonical actions, subjects, and objects. Plight will use RPGNLP as the local parsing base and extend it where the action tests require; the MVP will not require an external language-model service. English is the initial supported input language.

The developer-facing contract, expression semantics, starter action catalog, implementation sequence, and acceptance tests are specified in [NLP-ENGINE-DESIGN-AND-IMPLEMENTATION.md](./NLP-ENGINE-DESIGN-AND-IMPLEMENTATION.md).

The intended pipeline is:

1. Receive a player's English sentence.
2. Use RPGNLP and Plight's action catalog to produce and rank structured interpretations.
3. Map different phrasings—such as “walk,” “run,” and “travel”—to canonical action IDs such as `travel`.
4. Preserve ordered action occurrences and parse supported Boolean operators between them.
5. Ask for clarification only when the highest-ranked interpretations are tied, or when a live target reference matches multiple entities. Otherwise select the highest-ranked interpretation, even if its match is weak.
6. Queue and resolve actions against authoritative character, area, inventory, and world state. Record the selected interpretation and execution results so tests and production events can be reproduced.

The engine should execute its best interpretation without routinely stopping to ask what the player meant. If no strong match exists, it still selects the highest-ranked supported action; the game server validates that action and returns an ordinary failure if it cannot be performed. The developer intends to build a substantial hand-written test set and test the action system thoroughly.

### Action-chain behavior

Actions in a chain execute sequentially, not as one indivisible batch. The game re-evaluates the world after each selected action. Repeated mentions are distinct action occurrences; selected occurrences retain their sentence order. Combat responses happen between combat actions in the same sentence, and later actions resolve against the state at that time.

The MVP supports English Boolean operator words and phrases, including `not`, `and`, `or`, `xor`, `nand`, `nor`, `xnor`, implication, converse/“only if,” and equivalence/“if and only if”; symbolic forms are deferred. Each action occurrence is a Boolean variable. The server uniformly selects one satisfying assignment when the expression reaches execution, including an empty action set when valid. Selected actions then run sequentially in sentence order. The exact formal semantics and failed-action behavior are defined in the linked implementation document.

### Parser boundary

“The player can type anything” describes the input experience; it must not mean that arbitrary text can bypass game rules. RPGNLP may identify the closest intended action, but the game server must still determine whether the target exists, the player has the required item or tool, the action is possible in that location, and the character can afford its costs. A failed selected action is not rerolled: the server explains the failure and continues with the next selected action. A target that could refer to multiple present entities requires the player to choose; no action is executed until resolved.

## 4. World, characters, and social structure

### Areas and travel

The world is a graph of discrete, named areas connected by exits, not a grid of tiles. Travel moves a character between areas. A player can leave during combat; travel resolves in sentence order, and leaving the encounter area prevents that action's enemy response.

### Initial playable identities

The initial playable species are **human** and **goblin**. A character's species is fixed at creation; changing species or transforming into another playable creature is not part of the current design.

The smallest world premise is:

- A human city and a goblin town, connected as areas in the world.
- Humans begin in the human city; goblins begin in the goblin town.
- The two peoples begin with poor relations.
- Each city's relationship to the other species makes it a hostile dungeon-like place for that species, while functioning as a place to live, trade, and socialize for its own people.
- NPC attitude, hostility, access, and prices can differ according to the character's identity and changing relations.

### Character creation and development

Each account has one persistent character. Character creation should include:

- A name and species.
- An extensive but structured set of cosmetic appearance options. Appearance is descriptive and can be referenced in dialogue, but does not provide mechanical bonuses.
- Structured choices for background, past, heritage, and religion. These may affect aptitudes with magic or weapons and relations with relevant factions.
- “Inclinations” or similar character details, whose exact fields and mechanical role remain to be defined.

There are no fixed classes. Skills develop through use and are influenced by character background and species. The precise skill list, progression curve, and treatment of failed attempts are open for later design.

### Shared world and emergent events

The world has hidden global variables, including relations between peoples and economic conditions. Actions should contribute to gradual change; threshold crossings, rather than a single action instantly overturning the world, trigger broader consequences. Players should not see direct numerical meters for these variables. They should infer change from the world—for example, a shopkeeper becoming more hostile or charging a particular character more as relations worsen.

There is no central narrative. Dynamic events and authored events can both give players reasons to act. The simulation should continue while no players are online, although its clock, tick frequency, and offline update rules still need to be designed. Advanced economy and simulation work can follow the interaction-focused initial release.

## 5. Combat and parties

The live combat implementation uses immediate action-response combat and the party rules below.

### Party formation and lifetime

- A player can create a party and invite any character from that character's profile. An invitee must accept; friendship is not required. There is no fixed party-size cap.
- A character can belong to one party at a time. The creator is its leader. The leader can invite or remove members and disband the party; any member can leave.
- If the leader leaves, is removed, or disconnects while others remain online, leadership passes to the longest-serving online member. A former leader who reconnects returns as a regular member.
- The party and its outstanding invitations remain available while at least one member is online. They are removed when every member is offline; a party is not restored after a server restart.
- Party members share a real-time party-chat channel. The server checks membership when reading history, sending messages, and subscribing to live updates.

### Immediate combat

- Solo fighters have a personal encounter. A party has a separate encounter for each area in which its members are fighting. Players outside that party are not pulled into its encounter.
- Enemy populations are encounter-scoped rather than global: each solo character has its own living enemy instances and health, while members of one party share that party's instances and health. One solo player or party defeating an enemy does not remove it for another solo player or party. Each context has its own location population cap. A character's solo enemy state is preserved while they are in a party and resumes when they leave it; solo respawn rolls pause while that character is offline. Party enemy state is discarded when the party ends.
- A fight begins when an attack is submitted; it resolves immediately, and the command response includes the result. New commands complete synchronously rather than entering a combat queue or waiting for a timer.
- Selected action occurrences resolve in sentence order, with each action and its enemy response forming a separate exchange. One sentence can select up to eight actions; each is revalidated against the state produced by the previous action.
- All online party members in the area are eligible to participate in the party encounter; a member who enters during combat can act on their next command. Only the member whose action is resolving receives the enemy response. A member who leaves the fight no longer participates there. Other characters in the area remain outside the party fight.
- Combat rewards and party participation require a live connection and presence in the fight's area. A disconnected member takes no offline combat damage or rewards. The solo encounter ends if its only fighter disconnects.
- The encounter ends when its engaged enemies are defeated or no connected party fighters remain in that area. If a party splits across areas, each area has an independent encounter.

### Enemy turns and reinforcements

- Immediately after each combat action, every living, engaged non-passive enemy attacks only the member who just acted. Each enemy rolls separately; that character's defense reduces each hit. Defend adds the equipped shield's defense to every hit in its immediate response; a shield gives no defense otherwise.
- Passive enemies never attack or join a fight. Neutral enemies retaliate when attacked and may join an active fight. Aggressive enemies attack the acting member during combat; outside combat, each aggressive enemy instance independently rolls for each online player every 15 seconds using its Content Studio-configured 0–100% hit chance. The default chance is 0%, which disables these attacks.
- After each action exchange, every living, unengaged neutral or aggressive enemy assigned to the same area makes an independent join roll. Its chance is 10% for neutral or 20% for aggressive, plus 5 percentage points for each other active fighter, capped at 60%. A bystander retries after later action exchanges until it joins or the encounter ends. A successful join is announced immediately, but that enemy first attacks after the next combat action. Location spawn limits still cap the total living population. Helpful NPC combatants are deferred until their combat stats and behavior are separately designed.

### Environment interactions

- Furniture and objects may have one optional Content Studio interaction effect: fully restore the character's health, or save the current location as that character's respawn point.
- Players may activate an effect by using the object in its location; beds set persistent, per-character respawn locations, and a valid bed location overrides the species starting location after defeat. If the saved location was removed, the character falls back to their species start.
- Effects have no cooldown and may be used during combat. World authors manage the risk through placement. Crafting stations continue to work by presence alone.
- Regular items may combine healing, timed stat boosts, shields, teleport, and luck effects. Healing supports fixed, maximum-health percentage, and full restoration. Timed boosts affect attack, defense, or speed. Shield effects can absorb a finite total damage pool, reduce each hit by a fixed amount, or add expiring temporary health above normal maximum health; damage pools absorb damage before temporary health, which is then consumed before regular health. Teleport destinations are authored per item.
- Item effects can target the user or the user plus online party members in the same location. Only the user spends an item, and one item is consumed by default (each item can opt out). All item effects work during combat. Timed effects use real time; reapplying the same kind refreshes its duration without stacking its strength. Luck raises enemy-drop chances and gathering yields.
- Weapons equip only in the right hand. Dedicated shields equip only in the left hand and add their authored defense attribute to the character's defense.

### Rewards and scope

- When an enemy is defeated, each party member who is online and in that area at the moment of defeat receives an independent XP and loot roll as if they had defeated it. The party does not copy one member's identical drop to everyone.
- The current player-versus-player exclusion remains: PvP is not part of this design. If added later, it should be confined to a separate area.

## 6. Gathering, crafting, and trade

### Gathering and crafting

The supported proficiencies are Felling, Foraging, Gouging, Fishing, Herbology, Alchemy, Fletching, Smithing, Lapidary, and Woodworking. Every proficiency begins at level 1 and stores its own XP. The next level costs 100 times the current level; a successful gather or craft awards 10 times its configured required level in that proficiency's XP.

Each resource can author its gathering proficiency and required level, health, required right-hand weapon stat and minimum power, respawn seconds, and a weighted yield table whose entries choose existing items or gear and quantity ranges. Harvest duration is `resource health × 60 ÷ (player proficiency level + equipped right-hand tool power)`, rounded up to a whole second. A tool stat requirement requires a matching weapon in the right hand; a resource without a gathering profile or yield table cannot be harvested. Each character tracks resource depletion and respawn independently.

Starting a gather locks the character into the timed action. `stop` cancels without a reward or resource depletion; disconnect and defeat also cancel it without reward. Other actions cannot be performed while gathering. Once the timer completes, the character receives successful yield rolls and proficiency XP, and that character's resource enters its authored respawn cooldown.

Recipes can produce items, weapons, or shields and define ingredients, an optional station, and an optional skill/level requirement. Crafting is immediate after validation, requires the station to be present in the current location, consumes the required ingredients, creates the authored quantity, and awards the recipe proficiency's XP. Existing recipes without a skill requirement remain valid.

### Currencies and NPC shops (implemented)

- Currencies are authored in Content Studio's **Currencies** section (name, optional symbol such as `g`, description). Each character keeps a separate wallet balance per currency (`Character.wallet`); wallets start empty and are not inventory items.
- Players earn currency from enemy `currency_drops` (chance plus min/max amount, boosted by drop-chance luck effects) and quest `reward_currencies` (granted at turn-in). Gathering does not pay currency, and there is no exchange or death penalty.
- A shop stock entry has an item, a price, a `currency_id`, a `quantity` and `restock_seconds` (default 300). Entries with no currency cannot be bought. Vendors buy from players only through an authored per-NPC **Buys from players** list (item, price each, currency, max per player, reset seconds). Each player has their own capacity per entry, which refills after the reset time. Equipped items cannot be sold, and no entry means the vendor buys nothing. Players use `sell [quantity] <item> [to <npc>]` or the Sell buttons in the shop window (`POST /api/v1/shop/sell`); buy-list state is stored in `shop_state` under `<npc_id>#buy`.
- Stock is tracked per player in `Character.shop_state`: buying reduces that player's remaining quantity, and the first purchase starts a restock timer that resets the quantity when it elapses. Other players are unaffected.
- Players type `buy from <npc>` (or `shop <npc>`) to open the NPC's shop in a dialogue-style window in the activity stream, with a Buy button per offer that updates stock and wallet in place. `buy [quantity] <item> [from <npc>]` still buys directly (`POST /api/v1/shop/buy` backs the window). Deleting a currency removes its drops and rewards and clears the currency on stock entries.

### Enchantments, curses, and maps (implemented)

Content Studio has an **Enchantments** library. Each entry is an enchantment or a curse with one or more effects: stat changes (attack, defense, speed, max health; flat or percent; negative for penalties), luck (drop chance and gathering yield), quest path, damage over time, life steal, thorns, and a cursed binding that stops the item being unequipped or replaced. Items, weapons, and shields can carry any number of enchantments. They are active while a weapon or shield is equipped, or while a regular item is carried.

Damage over time never kills (it stops at 1 health). Thorns wound an attacking enemy but never finish it, and life steal heals a percentage of melee damage dealt. Effects from several items stack by summing.

Any item, weapon, or shield can be marked as a **map item**. Carrying one adds a Map button (or typing "open map") that shows the world map: locations the character has visited plus their adjacent locations. A `quest_path` enchantment, active from any source, draws the shortest route to the first active quest's objective on the map and marks the next exit with a star in the Exits list. Visited locations are stored in `Character.visited_areas`.
### Shops and player marketplace

- NPC shops buy and sell goods.
- Players can list goods on a global marketplace. Listings are visible everywhere, but a buyer must travel to the seller's last area to complete the transaction.
- The seller need not be online. When a transaction completes, the money or barter item and listed goods transfer immediately.
- Listings can request a currency price or a barter trade, such as wood in exchange for metal.
- Players can also trade directly or give items to each other.
- Player sale prices should influence a global NPC market price. Individual shopkeepers can apply a local modifier—for example, a shop in a high-traffic location might charge 1.5 times the market price.

Listing expiration, item reservation, cancellation, taxes, and how barter offers are represented are not yet settled and should be specified before marketplace implementation.

## 7. Accounts, persistence, and hosting

### Accounts and persistence

Players sign in with an email address and password. Each account has one character, and the character is restored into the shared world after login. The intended persistence scope is broadly “everything about the player,” including character details, location, skills, inventory, and other acquired state. Exact retention rules for chat, temporary combat state, and marketplace listings need definition.

### Browser and server architecture

GitHub Pages can host the static browser interface, but it cannot run the shared Python game server or securely maintain shared accounts and game state. A browser-based version therefore needs a separately reachable backend. The proposed zero-cost starting direction is:

- Host the static, responsive web client on GitHub Pages.
- Run the authoritative Python game server on the developer's laptop.
- Store persistent account, character, and world data in a database managed by that server.
- Send commands to the server and return text events to clients in real time.

The developer is willing to leave a laptop running as the server. This avoids requiring every player to install an executable; an executable is not necessary for a browser client. Self-hosting still creates operational requirements: the laptop and network must remain available, the server must be reachable from the public internet, and secure transport, backups, updates, and recovery must be planned. Home-network address changes, router configuration, and provider restrictions may affect availability. These constraints should be tested early rather than discovered after building the game.

All game-changing operations should be validated and persisted by the server so that multiple clients cannot independently invent conflicting versions of character or world state. Real-time transport and the specific Python web framework/database are implementation decisions to make during the architecture phase.

## 8. MVP scope

The first major release should prioritize what players directly interact with and prove that arbitrary natural-language input can drive the game effectively.

### MVP must demonstrate

- Email/password accounts and one persistent character per account.
- Character creation with human/goblin choice and initial structured character details.
- A human city and goblin town, species-based starting locations, and their initial hostile relationship.
- A guided introduction with the wise old NPC.
- Optional multi-step NPC quests with collect, kill, talk, and visit objectives, explicit branching choices, per-character progress, item/experience rewards, and quest-gated exits.
- A useful, tested set of canonical natural-language actions and sequential action chains.
- NPC and enemy interaction, including immediate combat responses and travel between areas.
- Global chat, party chat, profile-initiated private chats, and player blocking.
- Basic resource gathering, crafting, direct trading, and marketplace access consistent with the rules above.
- A responsive text-only browser UI with real-time updates.

The developer specifically wants to prioritize fleshing out and testing actions over building a broad world. Quests are optional content authored in the Content Studio; fetch-quest acceptance, progress, turn-in, loot, experience, character level, and quest-gated exits are character-specific and server-authoritative. Advanced economic simulation, extensive world simulation, additional species, and larger content sets can be developed after the core interaction loop is dependable. The MVP can contain simple initial relations and basic market features without attempting the full long-term simulation.

Content Studio audio authoring supports a looping MP3 track per location and one globally shared MP3 sound effect for each recognized player action. Audio uploads are editor-only, limited to 25 MiB per file, and stored separately from world JSON; the API serves those assets to game clients. Players explicitly enable or mute playback and may adjust volume, respecting browser autoplay restrictions. Backups must include the audio asset directory as well as the world-content file and database.

## 9. Recommended development process

Build in vertical slices: each stage should leave behind a runnable, testable game rather than a large collection of disconnected systems.

### Stage 1 — Turn the interview into a testable ruleset

Create the canonical action catalog with required targets and tools, valid contexts, costs, state changes, and player-facing responses. Record representative phrasings for each action, including paraphrases, Boolean expressions, chained sentences, context-sensitive wording, typos, invalid targets, and impossible actions. Use the companion NLP implementation document as the initial action and parser contract; mark later tuning values explicitly instead of encoding accidental assumptions.

### Stage 2 — Prove the text interaction loop in Python

Use RPGNLP as the parsing base and extend it where tests show gaps. Implement a minimal world model with a human city, goblin town, exits, a few NPCs, enemies, and inventory. Make the flow from sentence to structured intent to rule-checked outcome observable and testable before investing in a large UI.

### Stage 3 — Add authoritative state and persistence

Introduce accounts, character creation, and database-backed character state. Ensure actions are checked against server-owned state and saved reliably. Test simultaneous requests and duplicate submissions around consequential changes such as spending, trading, gathering, and combat.

### Stage 4 — Connect the browser client in real time

Build the text-first desktop layout and its stacked mobile counterpart. Connect command submission, output, atmosphere, and chat to the Python service. Verify the application on a phone as well as a desktop browser.

### Stage 5 — Complete the shared interaction MVP

Add immediate combat and party behavior, gathering timers, initial crafting, chat tabs and blocking, direct trade, and the marketplace. Exercise concurrent players and party membership changes in combat, as well as completing a transaction when the seller is offline.

### Stage 6 — Operate the shared world safely

Make the self-hosted service publicly reachable over secure transport. Add backups and restore procedures, server logging and health checks, and a clear way to deploy updates without corrupting persistent state. Test what a player sees when the server disconnects or restarts.

### Stage 7 — Expand simulation from observed play

After the MVP's actions are reliable, add richer recipes, content, market-price feedback, faction thresholds, world events, and offline world simulation. Introduce each system with tests that connect player actions to visible consequences.

## 10. Test strategy

Natural-language action reliability is a core product requirement, not a polish task. Maintain a hand-written, automated regression suite and run it whenever the parser, action catalog, world rules, or context changes.

The suite should cover:

- Many phrasings for every canonical action, including synonyms and natural variations.
- Correct extraction of action, subject, target, object, and relevant modifiers.
- Ordered action chains; truth-table coverage for every supported Boolean operator; valid, empty, and unsatisfiable action selections.
- Exact-tie clarification, target disambiguation, server-side random selection, and replay without rerolling.
- Context changes between actions in a selected sentence, such as a target moving or a player leaving an area.
- Required tools, inventory, reachability, species/faction restrictions, and unavailable targets.
- Best-interpretation behavior for ambiguous or unfamiliar sentences, including its in-world response.
- Immediate combat retaliation, passive enemies, enemy/NPC joins, spawn caps, player separation, and party membership changes.
- Item-effect targeting, consumption, refresh-without-stacking, combat use, teleport, and shield absorption.
- Gathering duration and tool/skill checks, per-character depletion and respawn, yield chances and quantities, cancellation/disconnect/defeat, and prevention of conflicting actions during its timed state.
- Crafting station, skill, ingredient, output, and proficiency progression checks.
- Trading and marketplace transfers, including offline sellers, barter, and two players attempting conflicting purchases.
- Persistence across logout, server restart, and reconnect.
- Real-time delivery of chat and relevant area changes, plus usability at phone-sized widths.

For parser tests, assert both the structured interpretation and the resulting game-state change. A sentence being mapped to a plausible action is not sufficient if it produces an invalid or surprising state transition.

## 11. Open design questions

These were deliberately left for focused design and implementation work:

The initial Speed-based attack initiative decision is implemented: attacks compare action-adjusted player Speed to each engaged non-passive enemy independently; light, normal, and heavy attacks use 1.05×, 1.0×, and 0.95× player Speed. The faster actor acts first. Exact Speed ties pause for player-triggered D20 rolls, and tied D20s require another click. An enemy that defeats the player before their turn cancels that attack. Defend and wait do not use initiative.

1. What combat behaviors and weighted join rules should helpful NPCs use if they later participate in fights?
2. What character backgrounds, additional appearance options, and religions are available at launch, and how should they affect mechanics?
3. Which authored resource profiles, NPC stock/prices, and shop inventories should populate the MVP world?
4. What moderation/reporting tools are needed beyond initial word blocking and player blocking? Chat retention is set to 90 days in [NETWORKING-AND-UI-ARCHITECTURE.md](./NETWORKING-AND-UI-ARCHITECTURE.md).
5. What clock and tick model drives weather, respawns, events, and offline simulation?

The NLP action semantics, starter recipes, and marketplace/direct-trade lifecycle are specified in the companion NLP document. The initial laptop-hosted networking, browser UI, framework, database, transport, and backup decisions are recorded in [NETWORKING-AND-UI-ARCHITECTURE.md](./NETWORKING-AND-UI-ARCHITECTURE.md). Resolve the remaining system-specific questions just before those systems are built, using small prototypes and concrete test cases. The initial priority is to prove that players can express intent in ordinary text and reliably see that intent resolved within a persistent, shared world.



## Crafting quantities (implemented)

`craft 4 cow hide`, `craft 4x cow hide` and `craft cow hide x4` craft several at once (1-999). Ingredients scale with the count, missing amounts are reported for the whole request, and skill XP is awarded per craft. A recipe whose exact name matches the full text is never treated as a quantity.


## Armor, jewelry, and die skins (implemented)

- Content Studio has Armor, Necklaces, Rings and Die skins tabs. Armor picks a body slot (helm, tunic, pants, sleeves, gloves, boots); rings fit ring slots 1-5 and necklaces fit necklace slots 1-2. Shields, armor, rings and necklaces all add their `defense` attribute while equipped, and every equipped piece (not only carried items) applies its enchantments.
- A die skin sets face, edge, number, glow and particle colors plus a particle effect (sparks, embers, snow, bubbles, stars, smoke). Quests grant skins as rewards; players choose the active skin from the Dice button (`PUT /api/v1/character/die-skin`). Characters gained `unlocked_die_skins` and `active_die_skin` (migration 0014).

