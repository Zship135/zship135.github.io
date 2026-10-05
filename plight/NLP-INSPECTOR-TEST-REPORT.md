# Plight NLP Inspector — Test Cases and Results

**Document type:** Test report  
**Scope:** Terminal NLP intent inspector and local Boolean-expression parser  
**Test source:** [test_plight_nlp_inspector.py](./test_plight_nlp_inspector.py)  
**Implementation under test:** [plight_nlp_inspector.py](./plight_nlp_inspector.py)  
**Run date:** 2026-10-04  
**Command:** `python -m unittest -v test_plight_nlp_inspector`

## Summary

| Measure | Result |
|---|---:|
| Tests run | 15 |
| Passed | 15 |
| Failed | 0 |
| Errors | 0 |
| Duration | 0.013 seconds |
| Overall | **PASS** |

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
| 15 | Hand equipment extraction | `Equip the iron sword in my right hand` | Canonical action `use_item`; item `iron sword`; hand slot `right_hand`. | PASS |

## Execution evidence

The test command completed successfully:

```text
Ran 15 tests in 0.013s
OK
```

The adapter test uses a stubbed `rpgnlp` module. It verifies mapping of the documented `NLPEngine.run`-style result shape; it does **not** execute the installed/published RPGNLP package.

## Coverage boundaries

These tests validate parser output and Boolean-expression behavior only. They do not establish that:

- a game action is permitted, succeeds, or has any world-state effect;
- target names resolve against live entities or that duplicate targets are clarified;
- random assignment selection is uniform, persisted, or replay-safe;
- every catalog action, paraphrase, argument type, malformed input, or nested expression is covered;
- the production RPGNLP package, its NLP model/data downloads, or its behavior in this environment works end-to-end.

The inspector is diagnostic: it reports parsed intents and previews satisfying assignments; it does not execute actions or perform authoritative game validation. Extend this report when test coverage or implementation behavior changes.
