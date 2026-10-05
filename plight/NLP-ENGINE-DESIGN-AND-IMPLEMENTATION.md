# Plight NLP Engine: Design and Implementation

**Document status:** Developer implementation specification  
**Audience:** Developers implementing Plight's Python server and natural-language action system  
**Parent document:** [PLIGHT-DESIGN-AND-DEVELOPMENT.md](./PLIGHT-DESIGN-AND-DEVELOPMENT.md)

## 1. Purpose and scope

The NLP engine converts a player's English command into one or more typed, ordered action intents. It does not decide whether an action is allowed or apply game effects. The authoritative game server resolves references against current world state, validates each action, applies its rules, persists the result, and returns player-facing text.

Use the existing RPGNLP Python package as the parsing base and extend it where the acceptance tests require. Keep the package behind a Plight-owned adapter so the game server and its tests do not depend on RPGNLP's internal object model. The MVP is local/offline: it must not require an external LLM, network inference service, or client-side model. English is the only supported input language at launch.

This specification defines:

- the parse-to-execution boundary and internal intent contract;
- ambiguity, action chaining, and Boolean operator semantics;
- the initial commandable world-action catalog and its MVP rules;
- the queue lifecycle, failure handling, persistence, and test requirements.

Chat composition/moderation, complete character creation, and general NPC dialogue generation are outside the NLP engine. `talk` is an action intent that carries the player's utterance or topic to the separate NPC dialogue rules.

## 2. Product decisions

| Topic | MVP rule |
|---|---|
| Parser base | RPGNLP, extended as needed behind a Plight adapter |
| Language | English only |
| External inference | None required; parsing and scoring run locally |
| Best match | Select the highest-ranked supported interpretation, even if the match is weak |
| Parse ambiguity | Ask only when the highest-ranked distinct interpretations tie exactly |
| Entity ambiguity | Ask the player to select when a target name matches multiple present entities |
| Boolean operators | English words/phrases for standard Boolean connectives; no symbolic forms initially |
| Random choices | Uniformly select a satisfying action-occurrence assignment when the expression reaches execution; record the selected assignment |
| Action order | Preserve sentence order among selected action occurrences; revalidate each at execution |
| Failed action | Do not reroll. Explain the failure, skip without stamina/action-opportunity cost, and continue the queue |
| Empty satisfying assignment | Execute no action and return a short neutral message, such as “You do nothing.” |
| No satisfying assignment | Execute nothing and explain that the requested combination has no valid action |

“Exact tie” refers to a tie in the parser/ranker result after duplicate semantic parses have been collapsed. Do not add a confidence-margin threshold in the MVP. If two distinct highest-ranked interpretations tie, return a clarification prompt with the candidate interpretations and do not enqueue either one until the player chooses.

## 3. Processing architecture

Use a pipeline with explicit boundaries:

1. **Receive:** Accept raw command text from the authenticated server session. Associate it with the actor, command/request ID, and current session; never trust a client-supplied actor ID or game state.
2. **Normalize:** Normalize whitespace and casing for analysis while retaining original text and character spans for names, quoted phrases, and NPC utterances. Do not discard negation, operator words, or target wording.
3. **Parse:** Call RPGNLP through the Plight adapter. Produce typed candidate action occurrences and expression structure, not executable callbacks.
4. **Canonicalize:** Map synonyms and paraphrases to allow-listed action IDs and typed parameters. Preserve repeated mentions as separate occurrences; “attack the rat and attack the rat” is two queued attempts.
5. **Rank:** Select the highest-ranked semantic parse. If distinct highest-ranked parses tie exactly, return clarification. The ranker must always be able to score supported action candidates, including a deterministic local lexical/alias fallback when RPGNLP produces no usable candidate. Do not use a confidence cutoff; game validation remains responsible for failure.
6. **Resolve references:** Resolve names and aliases against authoritative, current world state. Missing or inaccessible references become ordinary action failures. Multiple present-entity matches require player selection before execution.
7. **Build queue entry:** Store the parsed expression and ordered occurrences with the request ID. Do not apply world effects during parsing.
8. **Resolve Boolean choice:** When a queued Boolean expression reaches execution, use server-owned randomness to select uniformly among satisfying assignments. Persist the selected assignment before applying its actions; never re-draw it after a retry or restart.
9. **Execute:** Execute the selected occurrences sequentially in source order. Re-read and validate authoritative state before every occurrence. Persist each result and emit its player-facing outcome.

The game-action layer owns preconditions, costs, target existence, location restrictions, inventory changes, combat results, and transaction atomicity. The NLP layer must never infer success from a grammatical parse.

### 3.1 RPGNLP adapter

Before implementation, inspect the installed/published RPGNLP version and its actual input/output API. Pin the tested package version using the repository's eventual dependency-management convention. Do not make up or leak RPGNLP-specific types into the game server.

The adapter should expose a stable internal operation equivalent to:

```python
parse_command(text: str, catalog: ActionCatalog) -> ParseOutcome
```

`ParseOutcome` is a typed result with one of:

- `selected`: a canonical action expression and rank;
- `clarification`: tied parse alternatives, with no action committed;
- `no_parse`: reserved for a genuine adapter/parser failure, surfaced explicitly to the caller and logs.

Unrecognized player wording is not a parser exception: it still yields the highest-ranked supported action through the fallback ranker. Keep fallback scoring deterministic and based on the action catalog's names, aliases, and descriptions; do not use a confidence cutoff. Do not silently convert RPGNLP/adapter exceptions into a plausible action.

### 3.2 Internal data contract

Use typed internal models (dataclasses or the project's established validation library) and serialize only at service boundaries. A logical schema is:

```text
CommandEnvelope
  request_id: unique idempotency key
  actor_id: authenticated server-side character/account reference
  text: original player text
  language: "en"

ActionOccurrence
  occurrence_id: unique within the command
  action_id: allow-listed canonical ID
  arguments: action-specific typed values
  source_span: optional offsets into original text

ActionExpression
  operator: leaf | not | and | or | xor | nand | nor | xnor
             | implies | converse | iff
  children: ordered expressions

ParseOutcome
  status: selected | clarification | no_parse
  expression: ActionExpression, when selected
  alternatives: ranked candidate expressions, when clarifying
  catalog_version: action catalog version used
  parser_version: adapter/RPGNLP version used

ExecutionRecord
  request_id: idempotency key
  selected_occurrence_ids: exact result of Boolean selection
  resolution_events: ordered per-action success/failure results
  expression/catalog/parser versions
```

Use a closed `action_id` registry. Parameters should be action-specific types rather than unconstrained strings wherever practical. Preserve the original utterance separately for `talk`; do not treat the utterance as a game command after it has been attached to a `talk` intent.

## 4. Boolean operators and action chains

### 4.1 Supported MVP forms

Recognize English words/phrases that express:

- negation: `not`;
- conjunction/disjunction: `and`, `or`;
- exclusive disjunction: `xor`;
- negated conjunction/disjunction: `nand`, `nor`;
- equivalence/parity: `xnor`, `iff`, “if and only if”;
- implication and converse: `implies`, “if … then …”, “only if,” and their ordinary-English forms.

Resolve grouping using ordinary-English parsing. If that produces distinct highest-ranked structures with the same rank, ask which one the player intended. Do not accept symbolic forms such as `&&`, `||`, `!`, or `^` in the MVP. Operator words inside an entity name, quoted NPC utterance, or other non-operator phrase are not operators.

### 4.2 Formal selection semantics

Each action occurrence in the parsed expression is a Boolean variable: `true` means include that occurrence in the selected action set; `false` means omit it. Separate mentions are separate variables, even when they map to the same canonical action and target. Evaluate the parsed Boolean expression over assignments to its occurrence variables, enumerate assignments for which the expression is true, and choose uniformly from that set.

Examples for two distinct action occurrences `A` then `B`:

| Expression | Satisfying selected sets |
|---|---|
| `A and B` | `{A, B}` |
| `A or B` | `{A}`, `{B}`, `{A, B}` |
| `A xor B` | `{A}`, `{B}` |
| `A nand B` | `{}`, `{A}`, `{B}` |
| `A nor B` | `{}` |
| `A xnor B` | `{}`, `{A, B}` |
| `A implies B` | `{}`, `{B}`, `{A, B}` |
| `A iff B` | `{}`, `{A, B}` |

`not A` selects the empty set. Converses use the standard converse of material implication; for `A only if B`, evaluate `A implies B`. Generalize n-ary `and`, `or`, `nand`, and `nor` by their truth tables. For chained implication or other grouping that is genuinely ambiguous in English, use ranked parses and the exact-tie clarification rule rather than inventing a special precedence.

If there are no satisfying assignments, emit a no-valid-combination result and execute nothing. If the empty set is one of several satisfying assignments and is selected, emit the neutral “You do nothing” response. Random selection happens once, at the queue head, for that expression; persist the selected occurrence IDs before executing. A restart or duplicate request must resume from the recorded choice, not draw again.

### 4.3 Ordering, validation, and failures

After selection, execute included occurrences in their original sentence order. Each action is independently checked against current state when its turn arrives. If one is no longer possible (for example, its target disappeared), report the concrete failure, skip that occurrence without stamina or combat-action-opportunity cost, and continue with remaining selected occurrences. Never choose an alternate Boolean assignment just because a selected action failed.

When multiple live entities match a target reference, return a target clarification and pause that command before execution. When none match, return the action's normal missing-target failure. A later action in the same queue may resolve differently after earlier actions have changed the world.

## 5. Starter canonical action catalog

IDs below are internal examples of stable lowercase identifiers. The implementation should define their argument schemas in the action registry and keep rules in the server's action handlers. This list is the initial world-action scope; chat commands and moderation are separate systems.

| Canonical ID | Player intent / argument | MVP rule |
|---|---|---|
| `observe` | Optional visible entity/object target or self-view subject | Without a target, describe the current area. A self-reference opens the player's own profile. `inventory` opens the player's own inventory/equipment menu; `armor`, `hands`, and `weapons` open that menu on the corresponding view. Phrases such as “look in my inventory” and “what am I carrying?” map to `observe` with subject `inventory`. Observing a co-located player opens that player's existing profile with equipped gear only; it never reveals their inventory. Resolve immediately; it does not use a combat action slot. |
| `talk` | Required NPC target plus utterance/topic | Carry the player's utterance/topic to NPC dialogue rules. The NPC system, not the parser, generates the reply. Resolve immediately and do not use a combat action slot. Player-to-player chat is not this action. |
| `travel` | One directly connected exit/direction | Move only through an exit from the current area; do not path-find to a farther destination. Resolve immediately outside combat and through the appropriate combat queue during combat. Validate the exit and current state at execution. |
| `attack` | Enemy target | Strike with both equipped hands. Fists are the default; an owned weapon adds its authored damage to the player's attack stat. A named target must be present. |
| `light_attack` | Enemy target | Make a weaker attack with both equipped hands. |
| `heavy_attack` | Enemy target | Make a stronger attack with both equipped hands. |
| `defend` | No target | Reduce damage from the next enemy response by half, rounded down. |
| `wait` | Optional duration only if a later rule adds it | In combat, consume the player's action without attacking or defending. During gathering, wait for the timed gathering action to complete. Otherwise do nothing and return a brief “nothing to wait for” result. |
| `gather` | Resource/action plus required tool | Require a suitable resource in the current area and the correct tool. Start a timed gathering state; consume the resource and grant yield only on completion. While gathering, the character is action-locked except for `wait` and `cancel_gather`; the queue resumes after completion or cancellation. |
| `cancel_gather` | No target | Cancel the active gathering state. Award no yield, consume no resource, and discard elapsed progress; a later attempt starts over. |
| `craft` | Recipe ID or unambiguous recipe/product reference | Require a known recipe, all ingredients, required station, and required skill. Validate then consume ingredients and grant outputs atomically. |
| `equip_item` | Owned item and optional equipment slot | The server validates item ownership, authored equipment definition, and slot compatibility. The current content defines weapons for `left_hand` and `right_hand`; other item types are rejected with a clear missing-definition message. |
| `unequip_item` | Equipment slot or equipped item | Clear the selected slot or locate the named equipped item. Hands return to fists. |
| `use_item` | Item and optional target | Defer consumption/effect rules to item data and the authoritative item handler. Equipping is a separate `equip_item` action. |
| `shop_buy` / `shop_sell` | Shop, item, quantity | Require a local NPC shop and valid stock/inventory. Use configured shop prices with local modifiers; do not feed player sales into global market prices in the MVP. Apply payment and item transfer atomically. |
| `give_item` | Co-located player, item, quantity | Transfer immediately only when both players are in the same area; validate and transfer atomically. |
| `trade_offer` / `trade_accept` | Co-located player and exact offered items/currency | A proposal reserves the proposer's offered items/currency. Both players must be co-located when proposed and accepted. Acceptance is explicit and atomic. Offers expire after 24 hours; rejection, cancellation, and expiry release reservations. |
| `market_list` | Item/quantity and currency or barter request; seller chooses currency partial-fill setting | Reserve listed goods immediately. No automatic expiry, listing fee, or tax. Currency listings may allow partial fills as chosen by the seller; barter listings require the exact full exchange and cannot be partially filled. |
| `market_buy` | Listing | Buyer must be in the seller's latest saved area at purchase time; seller may be offline. Revalidate availability and transfer both sides atomically. |
| `market_cancel` | Listing | Seller may cancel; immediately return unsold reserved goods. |

Unknown named action words may map to the highest-ranked supported action as specified in Section 2, but handlers must never accept unknown action IDs. In particular, natural-language matching cannot create items, bypass tools/stations, skip costs, or transfer another character's assets without the corresponding server-side rule.

The equipment schema supports `helm`, `tunic`, `pants`, `sleeves`, `gloves`, `boots`, `ring_1`–`ring_5`, `necklace_1`–`necklace_2`, `left_hand`, and `right_hand`. Empty armor/jewelry slots are stored explicitly. Existing two-hand equipment is retained when adding the expanded slots. New equipment definitions and bonuses belong in authored item data and server rules; do not infer or fabricate them from item names.

### 5.1 Starter recipes and resources

Seed these recipes in data, not parser code:

| Output | Inputs | Station | Skill |
|---|---|---|---|
| 1 plank | 2 wood | Workbench | None specified |
| 1 ingot | 5 ore | Workbench | None specified |
| 1 basic axe | 2 planks + 1 ingot | Smithy | Smithing level 2 |
| 1 basic pickaxe | 2 planks + 2 ingots | Smithy | Smithing level 2 |

The blacksmith sells a basic pickaxe so a new character can acquire a first one without already having crafted one. Add the required workbench, smithy, blacksmith stock, and gatherable resources to MVP area/item data. Configure shop prices and any initial starting tools as game content; do not hard-code them in the NLP parser.

### 5.2 Combat and gathering tuning data

Use a small, capped, data-driven combat action-budget model. Speed determines the number of queued actions before an enemy response; stamina limits the burst and funds action costs. The action handlers/configuration define the cap, thresholds, costs, damage, and defend reduction. Keep these values outside parser logic and cover their effect with game-rule tests.

Gathering duration scales with both resource and tool/skill:

```text
duration = max(minimum_duration,
              base_resource_duration * tool_multiplier
              / (1 + skill_level * skill_factor))
```

The server starts the timer only after validating area, resource, tool, and character state. Completion consumes the configured resource amount and grants configured yield atomically. Cancellation has the no-yield/no-resource-loss behavior in the action catalog.

## 6. Queue and persistence contract

- The server creates a stable request ID and enforces idempotency for command submission and consequential actions.
- Persist the raw command only according to the game's command-history/privacy policy; the execution record must at minimum preserve the canonical expression, selected occurrence IDs, parser/catalog versions, and ordered outcomes.
- The Boolean draw is made by the server, never the browser. Inject the random source so tests can force each satisfying assignment. Persist the actual selected assignment before applying its first effect.
- Store enough queue data to resume after a server restart without reparsing under a different package/catalog version or rerolling a Boolean choice.
- Process state mutations and inventory/economy transfers in transactions or equivalent atomic operations. Duplicate submissions must not double-spend, double-gather, double-craft, or double-transfer.
- Treat parser/catalog versions as part of reproducibility data. A new catalog version must not silently reinterpret already queued actions.
- Return structured outcomes (`succeeded`, `failed`, `clarification_required`, or `no_action`) with player-facing text. Do not return success-shaped defaults on parser, persistence, or handler errors.

## 7. Implementation sequence

1. **Audit and wrap RPGNLP:** Verify its installed API/version and current canonical-action behavior. Write adapter contract tests and pin the version.
2. **Define models and catalog:** Add typed action occurrences, Boolean expression nodes, catalog entries, candidate rankings, and explicit outcome variants.
3. **Implement expression semantics:** Add parser mappings for supported English operator forms and truth-table assignment enumeration. Test all supported operators independently of the world.
4. **Implement ranking and clarifications:** Deduplicate semantically equivalent candidates, choose the top candidate, ask on exact ties, and expose live target ambiguity as a separate resolution result.
5. **Wire the authoritative queue:** Persist command/expression/choice/outcomes, apply selection at queue head, revalidate every occurrence, skip failures without rerolls, and resume safely after restart.
6. **Add action handlers in vertical slices:** Begin with observe/talk/travel, then combat, gathering/crafting, inventory/shops, and player/marketplace transactions. Keep parsing and game effects independently testable.
7. **Expand the hand-written corpus:** Add paraphrases and regressions whenever parser behavior or action rules change.

## 8. Test and acceptance requirements

Maintain a hand-written automated corpus with input text, expected ranked parse/clarification, canonical IDs and arguments, and expected server-side state changes. Assert both interpretation and outcome; a plausible parse is not sufficient if it creates an invalid state transition.

### Parser and expression tests

- Every catalog action has representative direct, paraphrased, colloquial, and context-dependent phrasings.
- Synonyms map to stable canonical IDs without losing target, quantity, tool, item, direction, or utterance arguments.
- Repeated mentions remain separate action occurrences and preserve source order.
- Exercise each supported operator's full truth table for two operands and representative nested/n-ary expressions; verify the satisfying-assignment set, including empty and unsatisfiable cases.
- Force every possible random assignment through an injected test RNG; assert the selected assignment is satisfying, uniform selection is implemented over assignments (not just operands), and the saved choice is not rerolled.
- Verify exact top-rank ties ask for a choice, non-ties choose the highest-ranked parse regardless of weak score, and duplicate semantic candidates do not create false clarification.
- Verify ordinary-English grouping and operator words inside entity names/quoted dialogue.
- Check target resolution for unique, missing, inaccessible, and duplicate-name entities.
- Check unknown wording maps to the best supported action and is still subject to ordinary server validation.

### Game-state and queue tests

- Execute selected actions in sentence order, rereading state before each one.
- When a selected action fails, assert its concrete failure text, no stamina/action-opportunity cost, no alternate random draw, and continued processing of later selected actions.
- Combat: current-target fallback, missing target, target ambiguity, attack variants, defend against next response, wait, speed/stamina budget cap, queued travel, and no effect when a target is no longer present.
- Gathering: missing tool/resource, timer formula, action lock, completion consumption/yield, wait, cancellation, and restart behavior.
- Crafting: all starter recipes, missing ingredients/station/skill, atomic ingredient/output changes, and blacksmith pickaxe purchase.
- Shops, gifts, offers, and marketplace: insufficient funds/items, co-location, reservation/release, explicit acceptance, 24-hour offer expiry, seller offline/location changes, seller-selected currency partial fills, full barter fills, cancellation, and concurrent purchase attempts.
- Persistence: duplicate command IDs, process restart during a queue, and no duplicate effects or random rerolls.

### Release gate

- All committed hand-written golden cases pass with exact expected parse/arguments and outcome.
- All operator truth-table and queue replay tests pass.
- No parser test can directly mutate state or bypass a server-side action precondition.
- Every canonical action has explicit target/argument requirements, context checks, failure text, and state-transition tests before being enabled for players.

## 9. Values and content to tune outside the parser

The first browser combat slice uses persistent per-character encounters. Initial player stats are 100 health, 3 attack, 1 defense, and 10 speed, with a fist in each hand. An attack applies both hand strikes in left-to-right order; fists are the default, and an owned weapon adds its authored damage. Standard, light, and heavy attacks use 1x, 0.75x, and 1.5x multipliers respectively. Each player strike deals `max(1, round((player attack + weapon damage) * multiplier) - enemy defense)`. A living enemy then retaliates with `base attack + roll(1..attack_die_sides) - player defense`, floored at zero. Defend halves the next retaliation's damage, rounded down. Defeated players respawn at their species' starting area with full health, keep their inventory, and reset their current enemy. Enemy damage state resets for that character when they leave the area. The configured speed stat is recorded but is not yet used to schedule actions; there is not yet a shared party combat queue.

The following remain game-data decisions or later action-system work, not NLP parser behavior:

- stamina costs, action-budget thresholds/cap, and combat scheduling;
- resource IDs, yields, respawn rules, base gathering durations, tool multipliers, skill factors, and minimum duration;
- smithing skill progression and how characters reach level 2;
- item catalog, shop stock, currency denomination, blacksmith pickaxe price, and shop modifiers;
- workbench/smithy placement and NPC dialogue content;
- marketplace listing quantity UX and seller-selected partial-fill configuration.

Keep these values in versioned configuration/content records and cover them with action-handler tests. New values must not require changing the NLP parser or its Boolean evaluator.

## 10. Terminal intent inspector

Use the repository's dependency-free terminal inspector to inspect raw command text without changing game state:

```powershell
python .\plight_nlp_inspector.py "attack the goblin with two daggers and then travel north"
python -m unittest -v test_plight_nlp_inspector
```

The default `local` engine prints JSON with canonical action occurrences, extracted arguments, source spans, the Boolean expression, and a satisfying-assignment preview. It is an offline diagnostic recognizer, not a replacement for the production RPGNLP adapter or authoritative game validation. It never executes actions or selects the server's random Boolean assignment.

To inspect RPGNLP's own structured output through the Plight adapter, run:

```powershell
python -m pip install rpgnlp==0.1.2
python .\plight_nlp_inspector.py --engine rpgnlp "attack the goblin with a sword"
```

RPGNLP may download its spaCy model and NLTK data on first use. Adapter or package errors are reported rather than silently replaced with a local parse.
