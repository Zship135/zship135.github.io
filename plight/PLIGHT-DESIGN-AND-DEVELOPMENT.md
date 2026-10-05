# Plight: Game Vision and Development Process

**Document status:** Interview synthesis and initial development guide  
**Audience:** The solo creator of Plight and AI-assisted development collaborators

This document records the decisions made during the initial design interview and turns them into a practical process for building Plight. It distinguishes agreed direction from questions that are intentionally left for implementation and playtesting. It is a living specification, not a claim that every system is fully designed.

## 1. Game vision

Plight is a **purely text-based, persistent, shared-world high-fantasy sandbox**. Players use natural-language text to act in the world, communicate with each other, and shape the conditions that future players encounter. There is no graphical game world: places, characters, combat, weather, and activity are conveyed through text and text-based interface panels.

The central experience is the freedom to decide what kind of life to pursue. A player might explore dangerous places with friends, fight, gather resources, craft, trade, or specialize in an economic role. There is no required central storyline or traditional quest chain. The world supplies situations and events; players make their own adventures.

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

Actions in a chain execute sequentially, not as one indivisible batch. The game re-evaluates the world when each queued action reaches execution. Repeated mentions are distinct action occurrences; selected occurrences retain their sentence order. For example, if a player queues an attack and then travel, combat responses may occur between those actions, and the later travel action resolves against the state at that time.

The MVP supports English Boolean operator words and phrases, including `not`, `and`, `or`, `xor`, `nand`, `nor`, `xnor`, implication, converse/“only if,” and equivalence/“if and only if”; symbolic forms are deferred. Each action occurrence is a Boolean variable. The server uniformly selects one satisfying assignment when the expression reaches execution, including an empty action set when valid. Selected actions then run sequentially in sentence order. The exact formal semantics and failed-action behavior are defined in the linked implementation document.

### Parser boundary

“The player can type anything” describes the input experience; it must not mean that arbitrary text can bypass game rules. RPGNLP may identify the closest intended action, but the game server must still determine whether the target exists, the player has the required item or tool, the action is possible in that location, and the character can afford its costs. A failed selected action is not rerolled: the server explains the failure, skips it without stamina or combat-action cost, and continues the queue. A target that could refer to multiple present entities requires the player to choose; no action is executed until resolved.

## 4. World, characters, and social structure

### Areas and travel

The world is a graph of discrete, named areas connected by exits, not a grid of tiles. Travel moves a character between areas. A player can attempt to leave an area during combat, but travel is itself added to the relevant action queue and resolves when its turn arrives.

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

## 5. Combat, queues, and parties

Combat is turn-based in its effects but should feel responsive in the live shared world. Actions are submitted and resolved through queues; players can continue to enter actions while combat is underway. A passive creature such as a rat need not attack first, but may retaliate after the player attacks.

### Queue model established so far

- A player who is not in a party uses a personal attack queue.
- A party uses an area-specific queue for its members fighting in that area.
- Multiple enemies may participate in the same area fight.
- Enemies and helpful NPCs may join based on a weighted metric and probability. Area spawn limits constrain how many enemies can be present.
- Non-party players are not pulled into other players' fights.
- If a party member enters an area fight, the relevant queue is copied or recreated to include that member. If a member leaves the fight, the queue is copied or recreated without that member and their pending actions; obsolete queue context is removed.
- Leaving an area during combat is a queued action.
- The initial browser combat slice persists health, attack, defense, speed, and left/right hand equipment; speed/stamina action scheduling and party combat queues remain undecided.

Parties are formed by inviting a player through their profile. For the initial design, party benefits are party chat, the shared area combat queue, and rewards from monsters defeated while members are online in the same area. A party does not persist once all members log off.

For a defeated monster, each present party member receives a reward roll as if they had personally killed it; rewards are not simply duplicated from one identical drop. The exact definition of a reward roll and presence during a queued fight should be covered by tests.

Player-versus-player combat is not part of the initial scope. If added later, it should be confined to a separate area.

## 6. Gathering, crafting, and trade

### Gathering and crafting

Gathering is an in-world action expressed in text, such as “chop wood.” It requires the appropriate tool and a suitable resource in the current area. A successful start puts the character into a timed gathering state. Gathering is intentionally a substantial commitment: while it is underway, the player can wait or cancel, but cannot perform other actions. Gathering time, interruption behavior, resource availability, and crafting recipes need detailed design and playtesting.

Crafting is an intended player activity and should be available in the interaction-focused MVP, though its initial recipe list and exact rules remain to be specified.

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
- A useful, tested set of canonical natural-language actions and sequential action chains.
- NPC and enemy interaction, including basic queued combat and travel between areas.
- Global chat, party chat, profile-initiated private chats, and player blocking.
- Basic resource gathering, crafting, direct trading, and marketplace access consistent with the rules above.
- A responsive text-only browser UI with real-time updates.

The developer specifically wants to prioritize fleshing out and testing actions over building a broad world. Advanced economic simulation, extensive world simulation, additional species, and larger content sets can be developed after the core interaction loop is dependable. The MVP can contain simple initial relations and basic market features without attempting the full long-term simulation.

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

Add the combat queue and party behavior, gathering timers, initial crafting, chat tabs and blocking, direct trade, and the marketplace. Exercise concurrent players and queue changes, especially joining/leaving combat and completing a transaction when the seller is offline.

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
- Context changes between queued actions, such as a target moving or a player leaving an area.
- Required tools, inventory, reachability, species/faction restrictions, and unavailable targets.
- Best-interpretation behavior for ambiguous or unfamiliar sentences, including its in-world response.
- Combat retaliation, passive enemies, enemy/NPC joins, spawn caps, player separation, and party queue membership changes.
- Gathering completion, cancellation, and prevention of conflicting actions during its timed state.
- Trading and marketplace transfers, including offline sellers, barter, and two players attempting conflicting purchases.
- Persistence across logout, server restart, and reconnect.
- Real-time delivery of chat and relevant area changes, plus usability at phone-sized widths.

For parser tests, assert both the structured interpretation and the resulting game-state change. A sentence being mapped to a plausible action is not sufficient if it produces an invalid or surprising state transition.

## 11. Open design questions

These were deliberately left for focused design and implementation work:

1. What exact combat balance values should populate the speed/stamina action-budget table, and how do queues behave under latency or disconnects?
2. What are the exact area boundaries and queue rules when there are multiple simultaneous fights in one area?
3. Which skills, character backgrounds, appearance options, and religions are available at launch, and how do they affect mechanics?
4. What resource respawn rules, NPC stock/prices, and shop inventories should populate the MVP world?
5. What moderation/reporting tools are needed beyond initial word blocking and player blocking? Chat retention is set to 90 days in [NETWORKING-AND-UI-ARCHITECTURE.md](./NETWORKING-AND-UI-ARCHITECTURE.md).
6. What clock and tick model drives weather, respawns, events, and offline simulation?

The NLP action semantics, starter recipes, and marketplace/direct-trade lifecycle are specified in the companion NLP document. The initial laptop-hosted networking, browser UI, framework, database, transport, and backup decisions are recorded in [NETWORKING-AND-UI-ARCHITECTURE.md](./NETWORKING-AND-UI-ARCHITECTURE.md). Resolve the remaining system-specific questions just before those systems are built, using small prototypes and concrete test cases. The initial priority is to prove that players can express intent in ordinary text and reliably see that intent resolved within a persistent, shared world.
