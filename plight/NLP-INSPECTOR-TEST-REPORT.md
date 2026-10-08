# Plight NLP Inspector — Test Cases and Results

**Document type:** Test report  
**Scope:** Terminal NLP intent inspector, local Boolean-expression parser, and attack-initiative integration
**Test sources:** [test_plight_nlp_inspector.py](./test_plight_nlp_inspector.py), [tests/test_server.py](./tests/test_server.py), and `web/src`
**Implementation under test:** [plight_nlp_inspector.py](./plight_nlp_inspector.py)  
**Run date:** 2026-10-07
**Commands:** `python -m pytest -q test_plight_nlp_inspector.py`; focused initiative API tests; `npm --prefix web test`; `npm --prefix web run build`

## Summary

| Measure | Result |
|---|---:|
| NLP parser tests | 22 passed |
| Focused initiative API tests | 8 passed |
| Frontend tests | 6 passed |
| Production frontend build | Passed |
| Full backend and parser suite | 77 passed, 7 failed |
| Overall | **CHANGED-WORK TESTS PASS; full suite has unrelated content/fixture failures** |

## Running the inspector with input

Open PowerShell in the project folder:

```powershell
cd C:\Users\zship\dev\plight_ptmmorpg
```

The simplest way to enter a command is to pass it in quotes. The inspector prints a JSON result containing canonical action IDs, extracted arguments, the expression, and satisfying-assignment preview:

```powershell
python .\plight_nlp_inspector.py "attack the goblin with two daggers and then travel north"
```

To enter a command at the prompt, start the program without arguments, type each command after `plight>`, and exit with Ctrl+C or Ctrl+Z followed by Enter:

```powershell
python .\plight_nlp_inspector.py
```

To send input through standard input:

```powershell
"gather wood with an axe" | python .\plight_nlp_inspector.py
```

By default, the inspector uses its local, offline parser. To print compact one-line JSON, add `--compact`:

```powershell
python .\plight_nlp_inspector.py --compact "look at the old gate"
```

An optional `--engine rpgnlp` mode calls RPGNLP rather than the local parser. RPGNLP is not required for default mode. If using this option, install the pinned package first; its first run may download the spaCy model and NLTK data:

```powershell
python -m pip install rpgnlp==0.1.2
python .\plight_nlp_inspector.py --engine rpgnlp "attack the goblin with a sword"
```

## Test cases

| # | Test | Input / condition | Expected result | Result |
|---:|---|---|---|---|
| 1 | Attack target and instrument extraction | `Attack the goblin with two daggers` | Canonical action `attack`; subject `goblin`; object `daggers` with quantity 2. | PASS |
| 2 | Travel direction extraction | `Run north east` | Canonical action `travel`; direction `north east`. | PASS |
| 3 | NPC talk and quoted utterance | `Tell the guard about the plan: "attack the troll or flee"` | One `talk` occurrence; subject `guard`; topic `plan`; quoted text retained as the utterance, not parsed as actions/operators. | PASS |
| 4 | Ordered action chain | `Attack the rat then travel north` | Two occurrences in source order; expression is conjunction; only assignment selects both. | PASS |
| 5 | Inclusive OR assignments | `Attack the rat or defend` | Satisfying assignments are first action, second action, or both. | PASS |
| 6 | Single-action negation | `Do not attack the rat` | Expression is `not`; only satisfying assignment is the empty selection. | PASS |
| 7 | Negation in a chain | `Do not attack the rat or defend` | First operand is negated; assignments match the resulting OR expression. | PASS |
| 8 | “Only if” implication | `Attack the rat only if I defend` | Expression is implication; three satisfying assignments. | PASS |
| 9 | Binary Boolean truth tables | Each operator in `and`, `or`, `xor`, `nand`, `nor`, `xnor`, `iff`, `implies`, `converse` | Exact satisfying action-occurrence assignments match the expected truth table for each operator. | PASS |
| 10 | “If … then …” implication | `If I attack the rat then defend` | Expression is implication; assignments are empty, second action, or both. | PASS |
| 11 | Symbolic Boolean rejection | `Attack the rat && defend` | `no_parse`; symbolic operator syntax is rejected. | PASS |
| 12 | Best-match fallback | `observ` | Selects canonical `observe` using the local alias fallback and reports fallback rank source. | PASS |
| 13 | Boolean evaluator | Implication expression evaluated with both `false,false` and `true,false` | First assignment evaluates true; second evaluates false. | PASS |
| 14 | RPGNLP adapter mapping | Fake RPGNLP engine returns `light_attack`, subject, instrument, and modifier fields | Adapter maps action to canonical `light_attack` and preserves subject and instrument fields. | PASS |
| 15 | Hand equipment extraction | `Equip the iron sword in my right hand` | Canonical action `equip_item`; item `iron sword`; hand slot `right_hand`. | PASS |
| 16 | Inventory menu mapping | `observe my inventory`, `look in my inventory`, `what am I carrying?`, and armor/hands/weapons subjects | Each phrase maps to canonical `observe` with the normalized inventory-view subject. | PASS |
| 17 | Unequip extraction | `unequip my right hand`, `take off the iron sword` | Both map to canonical `unequip_item` with the equipment slot or item argument. | PASS |
| 18 | Light-attack phrase mapping | Quick/fast attack wording, “attack quickly,” and light aliases including `poke`, `jab`, `peck`, `nick`, `graze`, `scratch`, `nibble`, `prick`, `swipe`, and `sting` | Canonical action is `light_attack`; target remains the enemy, not the speed cue. | PASS |
| 19 | Heavy-attack phrase mapping | Powerful/strong/force wording and heavy aliases including `bash`, `slam`, `obliterate`, `smash`, `crush`, `demolish`, `shatter`, `pummel`, `pound`, `batter`, `pulverize`, `maul`, and `wreck` | Canonical action is `heavy_attack`; target remains the enemy, not the force cue. | PASS |
| 20 | Conflicting attack cues | A command includes both light and heavy cues | Conflicting cues cancel to the normal canonical action `attack`. | PASS |
| 21 | Normal attack verb aliases | `damage the forest rat`, `slime the forest rat` | Both map to canonical `attack` and retain `forest rat` as the target. | PASS |

## Attack initiative integration cases

The focused server tests exercise the effects of parsed attack styles and Speed:

| Test | Expected result | Result |
|---|---|---|
| Equal-Speed normal attack | Command waits for Roll; tied D20s wait for another click; winner's strike order is respected. | PASS |
| Light and heavy attack Speed modifiers | Light uses 1.05× player Speed and acts first against an equal-Speed enemy; heavy uses 0.95× and the enemy acts first. | PASS |
| Defeat before player attack | A faster enemy can defeat the player before the player's attack; the attack is cancelled and no attack action event is emitted. | PASS |
| Standalone Roll button | A D20 result is logged and animated without changing combat state. | PASS |
| Existing combat and reward behavior | Right-hand weapon damage, enemy retaliation, player defeat/respawn, and enemy rewards remain covered. | PASS |

## Execution evidence

Focused validation completed on 2026-10-07:

```text
python -m pytest -q test_plight_nlp_inspector.py
22 passed

python -m pytest -q tests\test_server.py -k "combat_uses_only_right_hand_and_enemy_attack_die or equal_speed_attack_waits_for_player_roll_and_rerolls_ties or attack_style_speed_modifier_orders_player_and_enemy or faster_enemy_can_defeat_player_before_attack_is_resolved or standalone_roll_returns_a_logged_d20_result or defeat_restores_player_and_enemy_at_species_start or slug_defeat_awards_configured_experience_and_loot"
8 passed

npm --prefix web test
6 passed

npm --prefix web run build
passed
```

The full `python -m pytest -q tests\test_server.py test_plight_nlp_inspector.py` run reported 77 passed and 7 failed. The failures concern mismatches between existing authored-world data and older content/profile/quest expectations; none of the NLP, initiative, or combat-reward tests failed. The RPGNLP adapter test uses a stubbed module and does **not** execute the installed/published RPGNLP package.

## Coverage boundaries

The parser tests validate parsed output and Boolean-expression behavior; focused API tests additionally validate attack initiative and its combat effects. They do not establish that:

- a game action is permitted, succeeds, or has any world-state effect;
- target names resolve against live entities or that duplicate targets are clarified;
- random assignment selection is uniform, persisted, or replay-safe;
- every catalog action, paraphrase, argument type, malformed input, or nested expression is covered;
- the production RPGNLP package, its NLP model/data downloads, or its behavior in this environment works end-to-end.

The inspector is diagnostic: it reports parsed intents and previews satisfying assignments; it does not execute actions or perform authoritative game validation. Extend this report when test coverage or implementation behavior changes.
