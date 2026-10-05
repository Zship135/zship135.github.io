"""Offline terminal inspector for Plight's canonical natural-language actions."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from dataclasses import dataclass
from typing import Any


CATALOG_VERSION = "plight-actions-1"
LOCAL_PARSER_VERSION = "plight-local-0.1"


# Each entry is an allow-listed Plight action and its player-facing verb aliases.
ACTION_ALIASES: dict[str, tuple[str, ...]] = {
    "observe": (
        "observe", "look", "look at", "inspect", "examine", "study", "check",
        "view my profile", "view my character", "show my profile",
        "what am i carrying", "what do i carry", "show my inventory", "open my inventory",
    ),
    "talk": ("talk", "speak", "say", "tell", "ask", "whisper", "shout", "chat"),
    "travel": ("travel", "go", "walk", "run", "move", "head", "travel to", "sprint"),
    "attack": ("attack", "hit", "strike", "slash", "stab", "shoot", "kick", "fight"),
    "light_attack": ("light attack", "poke", "prod", "tap", "flick", "nip"),
    "heavy_attack": ("heavy attack", "smash", "crush", "demolish", "shatter"),
    "defend": ("defend", "block", "parry", "dodge", "guard", "protect"),
    "wait": ("wait", "rest"),
    "gather": ("gather", "chop", "mine", "harvest", "collect", "forage"),
    "cancel_gather": ("cancel gathering", "cancel gather", "stop gathering"),
    "craft": ("craft", "make", "build", "create", "forge"),
    "equip_item": ("equip", "wear", "wield"),
    "unequip_item": ("unequip", "remove", "take off"),
    "use_item": ("use", "drink", "eat", "activate", "open"),
    "shop_buy": ("buy", "purchase"),
    "shop_sell": ("sell", "vend"),
    "give_item": ("give", "gift"),
    "trade_offer": ("offer a trade", "propose a trade", "offer trade"),
    "trade_accept": ("accept the trade", "accept trade"),
    "market_list": ("list for sale", "list on the market", "list"),
    "market_buy": ("buy the listing", "purchase the listing"),
    "market_cancel": ("cancel the listing", "cancel listing"),
}

ACTION_DESCRIPTIONS: dict[str, str] = {
    "observe": "look at an area, entity, or object",
    "talk": "speak to an NPC about a topic or utterance",
    "travel": "move to a connected area or direction",
    "attack": "attack an enemy",
    "light_attack": "make a light or quick attack",
    "heavy_attack": "make a heavy or powerful attack",
    "defend": "block or defend against an attack",
    "wait": "wait for an event or rest",
    "gather": "gather, chop, mine, or harvest a resource with a tool",
    "cancel_gather": "cancel active gathering",
    "craft": "craft or make an item from a recipe",
    "equip_item": "equip an owned item in a compatible equipment slot",
    "unequip_item": "unequip an item or clear an equipment slot",
    "use_item": "use an item on a target",
    "shop_buy": "buy an item from a shop",
    "shop_sell": "sell an item to a shop",
    "give_item": "give an item to another player",
    "trade_offer": "offer a direct trade to another player",
    "trade_accept": "accept a trade offer",
    "market_list": "list an item for sale on the market",
    "market_buy": "buy a marketplace listing",
    "market_cancel": "cancel a marketplace listing",
}

_ALIAS_TO_ACTION = {
    alias: action_id
    for action_id, aliases in ACTION_ALIASES.items()
    for alias in aliases
}
_ALIAS_TO_ACTION.update({"speak": "talk", "inspect": "observe", "use": "use_item"})
_ALIAS_TO_ACTION.update({action_id: action_id for action_id in ACTION_ALIASES})
_ACTION_PATTERN = re.compile(
    r"(?<!\w)("
    + "|".join(
        re.escape(alias).replace(r"\ ", r"\s+")
        for alias in sorted(_ALIAS_TO_ACTION, key=len, reverse=True)
    )
    + r")(?!\w)",
    re.IGNORECASE,
)

_OPERATOR_PATTERN = re.compile(
    r"\b(if and only if|only if|implies|imply|xor|xnor|nand|nor|iff|"
    r"conversely|converse|and then|then|and|or|if)\b",
    re.IGNORECASE,
)
_SYMBOLIC_OPERATOR_PATTERN = re.compile(r"&&|\|\||(?<!\w)!(?!\=)|\^")
_DIRECTION_PATTERN = re.compile(
    r"\b(north(?:\s+east|\s+west)?|south(?:\s+east|\s+west)?|"
    r"east|west|up|down|inside|outside)\b",
    re.IGNORECASE,
)
_QUOTED_PATTERN = re.compile(r'"([^"]*)"|\'([^\']*)\'')
_ARTICLE_PATTERN = re.compile(r"^(?:the|a|an|some|any)\s+", re.IGNORECASE)
_QUANTITY_WORDS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


@dataclass(frozen=True)
class Occurrence:
    occurrence_id: str
    action_id: str
    arguments: dict[str, Any]
    source_span: tuple[int, int] | None
    phrase: str
    raw_arguments: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "occurrence_id": self.occurrence_id,
            "action_id": self.action_id,
            "arguments": self.arguments,
            "source_span": list(self.source_span) if self.source_span else None,
            "phrase": self.phrase,
            "raw_arguments": self.raw_arguments.strip(),
        }


@dataclass(frozen=True)
class Expression:
    operator: str
    children: tuple["Expression", ...] = ()
    occurrence_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"operator": self.operator}
        if self.operator == "leaf":
            result["occurrence_id"] = self.occurrence_id
        else:
            result["children"] = [child.to_dict() for child in self.children]
        return result


@dataclass(frozen=True)
class _Mention:
    start: int
    end: int
    action_id: str
    phrase: str


def _quoted_ranges(text: str) -> list[tuple[int, int]]:
    return [match.span() for match in _QUOTED_PATTERN.finditer(text)]


def _inside_ranges(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start >= quote_start and end <= quote_end for quote_start, quote_end in ranges)


def _mask_quoted(text: str) -> str:
    chars = list(text)
    for start, end in _quoted_ranges(text):
        for index in range(start, end):
            if chars[index] not in "\r\n":
                chars[index] = " "
    return "".join(chars)


def _find_mentions(text: str) -> list[_Mention]:
    quoted_ranges = _quoted_ranges(text)
    candidates: list[_Mention] = []
    for match in _ACTION_PATTERN.finditer(text):
        if _inside_ranges(match.start(), match.end(), quoted_ranges):
            continue
        alias = re.sub(r"\s+", " ", match.group(0).casefold()).strip()
        candidates.append(
            _Mention(match.start(), match.end(), _ALIAS_TO_ACTION[alias], match.group(0))
        )

    selected: list[_Mention] = []
    for candidate in sorted(candidates, key=lambda item: (item.start, -(item.end - item.start))):
        if selected and candidate.start < selected[-1].end:
            continue
        if selected:
            gap = _mask_quoted(text[selected[-1].end : candidate.start])
            if not _OPERATOR_PATTERN.search(gap):
                continue
        selected.append(candidate)
    return selected


def _clean_phrase(value: str) -> str:
    value = value.strip(" \t\r\n,.;:!?")
    value = _ARTICLE_PATTERN.sub("", value)
    return re.sub(r"\s+", " ", value).strip()


def _quantity_and_name(value: str) -> dict[str, Any]:
    cleaned = _clean_phrase(value)
    match = re.match(r"^(a|an|one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+(.+)$", cleaned, re.I)
    if match:
        quantity_word = match.group(1).casefold()
        quantity = int(quantity_word) if quantity_word.isdigit() else _QUANTITY_WORDS[quantity_word]
        return {"name": _clean_phrase(match.group(2)), "quantity": quantity}
    if cleaned:
        return {"name": cleaned, "quantity": 1}
    return {}


def _extract_arguments(
    text: str, mention: _Mention, raw_arguments: str, all_quoted: list[re.Match[str]]
) -> dict[str, Any]:
    args: dict[str, Any] = {}
    fragment = raw_arguments.strip(" \t\r\n,.;:!?")
    quote = next(
        (
            match.group(1) if match.group(1) is not None else match.group(2)
            for match in all_quoted
            if match.start() >= mention.end and match.start() < mention.end + len(raw_arguments) + 4
        ),
        None,
    )

    if mention.action_id == "observe":
        if mention.phrase.casefold() in {
            "view my profile", "view my character", "show my profile",
        }:
            target = "self"
        elif mention.phrase.casefold() in {
            "what am i carrying", "what do i carry", "show my inventory", "open my inventory",
        }:
            args["subject"] = "inventory"
            target = ""
        else:
            target = _clean_phrase(
                re.sub(r"^(?:at|around|about|over|in|into)\s+", "", fragment, flags=re.I)
            )
        area_phrases = {
            "area",
            "current area",
            "here",
            "around",
            "about",
            "there",
            "surroundings",
            "my surroundings",
            "the surroundings",
            "room",
            "the room",
            "everything",
            "the area",
            "the whole area",
        }
        target_key = target.casefold().removeprefix("my ").removeprefix("the ")
        if target and target.casefold() not in area_phrases:
            self_subjects = {
                "me",
                "myself",
                "my self",
                "self",
                "profile",
                "own profile",
                "character",
                "own character",
            }
            args["subject"] = (
                "self"
                if target_key in self_subjects
                else target_key
                if target_key in {"inventory", "armor", "armour", "hands", "weapons"}
                else target
            )
    elif mention.action_id in {"travel"}:
        direction = _DIRECTION_PATTERN.search(fragment)
        if direction:
            args["direction"] = re.sub(r"\s+", " ", direction.group(0).casefold())
        else:
            destination = re.search(r"\b(?:to|toward|towards)\s+(.+)$", fragment, re.I)
            if destination:
                args["destination"] = _clean_phrase(destination.group(1))
            elif mention.phrase.casefold().endswith(" to") and fragment:
                args["destination"] = _clean_phrase(fragment)
    elif mention.action_id == "talk":
        without_quotes = _QUOTED_PATTERN.sub("", fragment).rstrip(" :,-")
        target = re.search(r"\b(?:to|with)\s+(.+?)(?=\s+\babout\b|$)", without_quotes, re.I)
        topic = re.search(r"\babout\s+(.+)$", without_quotes, re.I)
        if target:
            args["subject"] = _clean_phrase(target.group(1))
        elif topic:
            direct_target = without_quotes[: topic.start()].rstrip(" :,-")
            if _clean_phrase(direct_target):
                args["subject"] = _clean_phrase(direct_target)
        elif without_quotes:
            args["subject"] = _clean_phrase(without_quotes)
        if topic:
            args["topic"] = _clean_phrase(topic.group(1))
        if quote is not None:
            args["utterance"] = quote
    elif mention.action_id in {"attack", "light_attack", "heavy_attack"}:
        target_end = re.search(r"\b(?:with|using|while|quickly|slowly|carefully)\b", fragment, re.I)
        target = fragment[: target_end.start()] if target_end else fragment
        target = re.sub(r"\b(?:and|or)\s*$", "", target, flags=re.I)
        if _clean_phrase(target):
            args["subject"] = _clean_phrase(target)
        instrument = re.search(r"\b(?:with|using)\s+(.+)$", fragment, re.I)
        if instrument:
            args["objects"] = [_quantity_and_name(instrument.group(1))]
    elif mention.action_id in {"gather"}:
        tool = re.search(r"\b(?:with|using)\s+(.+)$", fragment, re.I)
        resource = fragment[: tool.start()] if tool else fragment
        if _clean_phrase(resource):
            args["resource"] = _clean_phrase(re.sub(r"^(?:for|some)\s+", "", resource, flags=re.I))
        if tool:
            args["tool"] = _quantity_and_name(tool.group(1))
    elif mention.action_id == "craft":
        product = re.search(r"\b(?:a|an|the)?\s*(.+?)(?:\s+from\s+.+)?$", fragment, re.I)
        if product and _clean_phrase(product.group(1)):
            args["product"] = _clean_phrase(product.group(1))
        ingredients = re.search(r"\bfrom\s+(.+)$", fragment, re.I)
        if ingredients:
            args["ingredients"] = _clean_phrase(ingredients.group(1))
    elif mention.action_id in {"inspect_inventory"}:
        if fragment:
            args["item_filter"] = _clean_phrase(fragment)
    elif mention.action_id in {"equip_item", "unequip_item"}:
        slot_names = (
            "left hand", "right hand", "helm", "tunic", "pants", "sleeves",
            "gloves", "boots", "ring 1", "ring 2", "ring 3", "ring 4", "ring 5",
            "necklace 1", "necklace 2",
        )
        slot_pattern = re.compile(
            r"\b(?:(?:in|to|from|into|off|out of)\s+)?(?:my\s+)?("
            + "|".join(re.escape(name) for name in slot_names)
            + r")\b",
            re.I,
        )
        slot = slot_pattern.search(fragment)
        if not slot:
            slot = re.search(
                r"\b(?:in|to|from|into|off|out of)\s+(?:my\s+)?"
                r"([a-z][a-z0-9_]*(?:\s+\d+)?)\s*$",
                fragment,
                re.I,
            )
        if slot:
            slot_name = re.sub(r"\s+", "_", slot.group(1).casefold())
            args["slot"] = slot_name
        item_text = fragment[: slot.start()] if slot else fragment
        item_text = re.sub(r"^(?:my|the|a|an)\s+", "", item_text, flags=re.I)
        if _clean_phrase(item_text) and _clean_phrase(item_text).casefold() not in {
            "left hand", "right hand", *slot_names[2:],
        }:
            args["item"] = _quantity_and_name(item_text)
    elif mention.action_id in {"use_item", "shop_buy", "shop_sell", "market_list", "market_buy", "market_cancel"}:
        slot = (
            re.search(r"\b(?:in|to)\s+(?:my\s+)?(left|right)\s+hand\b", fragment, re.I)
            if mention.phrase.casefold() == "equip"
            else None
        )
        item = re.search(r"\b(?:on|at|with|to|for|of)\s+(.+)$", fragment, re.I)
        if slot:
            args["item"] = _quantity_and_name(fragment[: slot.start()])
            args["slot"] = f"{slot.group(1).casefold()}_hand"
        object_text = fragment[: slot.start()] if slot else fragment[: item.start()] if item else fragment
        object_text = re.sub(r"^(?:the|a|an)\s+", "", object_text, flags=re.I)
        if _clean_phrase(object_text):
            args["item"] = _quantity_and_name(object_text)
        if item and mention.action_id == "use_item":
            args["target"] = _clean_phrase(item.group(1))
        if item and mention.action_id in {"shop_buy", "shop_sell"}:
            args["shop"] = _clean_phrase(item.group(1))
        quantity = re.search(r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b", fragment, re.I)
        if quantity and mention.action_id in {"shop_buy", "shop_sell", "market_list"}:
            word = quantity.group(1).casefold()
            args["quantity"] = int(word) if word.isdigit() else _QUANTITY_WORDS[word]
    elif mention.action_id in {"give_item", "trade_offer", "trade_accept"}:
        recipient = re.search(r"\b(?:to|with|from)\s+(.+)$", fragment, re.I)
        item_text = fragment[: recipient.start()] if recipient else fragment
        if recipient:
            args["subject"] = _clean_phrase(recipient.group(1))
        if fragment:
            args["offer"] = _clean_phrase(fragment)
        if item_text and mention.action_id == "give_item":
            args["item"] = _quantity_and_name(item_text)
    elif mention.action_id == "wait" and fragment:
        args["duration"] = _clean_phrase(fragment)
    elif fragment:
        args["subject"] = _clean_phrase(fragment)

    modifiers = [
        word.casefold()
        for word in re.findall(r"\b(quickly|slowly|carefully|quietly|stealthily)\b", fragment, re.I)
    ]
    if modifiers:
        args["modifiers"] = modifiers
    return args


def _operator_from_gap(gap: str, has_if_prefix: bool) -> str:
    matches = list(_OPERATOR_PATTERN.finditer(_mask_quoted(gap)))
    if not matches:
        return "and"
    token = re.sub(r"\s+", " ", matches[-1].group(0).casefold())
    if token in {"and", "and then", "then"}:
        return "and"
    if token in {"or"}:
        return "or"
    if token == "xor":
        return "xor"
    if token == "nand":
        return "nand"
    if token == "nor":
        return "nor"
    if token in {"xnor", "iff", "if and only if"}:
        return "iff" if token != "xnor" else "xnor"
    if token in {"implies", "imply"}:
        return "implies"
    if token == "only if":
        return "implies"
    if token in {"converse", "conversely"}:
        return "converse"
    if token == "if":
        return "implies" if has_if_prefix else "converse"
    return "and"


_OPERATOR_PRECEDENCE = {
    "iff": 1,
    "implies": 2,
    "converse": 2,
    "or": 3,
    "nor": 3,
    "xor": 4,
    "xnor": 4,
    "and": 5,
    "nand": 5,
}


def _apply_operator(operator: str, left: Expression, right: Expression) -> Expression:
    return Expression(operator, (left, right))


def _build_expression(
    text: str, mentions: list[_Mention], occurrences: list[Occurrence]
) -> Expression:
    leaves = [Expression("leaf", occurrence_id=item.occurrence_id) for item in occurrences]
    prefix = _mask_quoted(text[: mentions[0].start])
    first_leaf = (
        Expression("not", (leaves[0],))
        if re.search(r"\bnot\s*$", prefix, re.I)
        else leaves[0]
    )
    if len(leaves) == 1:
        return first_leaf

    operators: list[str] = []
    prefix_has_if = bool(re.search(r"\bif\b", prefix, re.I))
    for index in range(len(mentions) - 1):
        gap = text[mentions[index].end : mentions[index + 1].start]
        op = _operator_from_gap(gap, prefix_has_if and index == 0)
        if prefix_has_if and index == 0 and op == "and":
            op = "implies"
        operators.append(op)

    values: list[Expression] = [first_leaf]
    ops: list[str] = []
    for index, operator in enumerate(operators):
        current = leaves[index + 1]
        between = text[mentions[index].end : mentions[index + 1].start]
        if re.search(r"\bnot\s*$", between, re.I):
            current = Expression("not", (current,))
        while ops and (
            _OPERATOR_PRECEDENCE[ops[-1]] > _OPERATOR_PRECEDENCE[operator]
            or (
                _OPERATOR_PRECEDENCE[ops[-1]] == _OPERATOR_PRECEDENCE[operator]
                and operator not in {"implies", "converse"}
            )
        ):
            right = values.pop()
            left = values.pop()
            values.append(_apply_operator(ops.pop(), left, right))
        ops.append(operator)
        values.append(current)
    while ops:
        right = values.pop()
        left = values.pop()
        values.append(_apply_operator(ops.pop(), left, right))
    return values[0]


def evaluate_expression(expression: Expression, assignment: dict[str, bool]) -> bool:
    if expression.operator == "leaf":
        return assignment[expression.occurrence_id or ""]
    values = [evaluate_expression(child, assignment) for child in expression.children]
    if expression.operator == "not":
        return not values[0]
    if expression.operator == "and":
        return all(values)
    if expression.operator == "or":
        return any(values)
    if expression.operator == "xor":
        return sum(values) % 2 == 1
    if expression.operator == "xnor":
        return sum(values) % 2 == 0
    if expression.operator == "nand":
        return not all(values)
    if expression.operator == "nor":
        return not any(values)
    if expression.operator == "implies":
        return not values[0] or values[1]
    if expression.operator == "converse":
        return not values[1] or values[0]
    if expression.operator == "iff":
        return all(value == values[0] for value in values[1:])
    raise ValueError(f"Unknown expression operator: {expression.operator}")


def _satisfying_assignments(expression: Expression, occurrences: list[Occurrence]) -> list[list[str]]:
    if len(occurrences) > 8:
        return []
    ids = [item.occurrence_id for item in occurrences]
    satisfying: list[list[str]] = []
    for mask in range(1 << len(ids)):
        assignment = {item: bool(mask & (1 << index)) for index, item in enumerate(ids)}
        if evaluate_expression(expression, assignment):
            satisfying.append([item for item in ids if assignment[item]])
    return satisfying


def _fallback_candidate(text: str) -> tuple[str, float, list[str]]:
    normalized = re.sub(r"[^a-z0-9 ]", " ", text.casefold())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    ranked: list[tuple[float, str]] = []
    for action_id, aliases in ACTION_ALIASES.items():
        phrases = (*aliases, action_id.replace("_", " "), ACTION_DESCRIPTIONS[action_id])
        best = 0.0
        for phrase in phrases:
            candidate = phrase.casefold()
            similarity = difflib.SequenceMatcher(None, normalized, candidate).ratio()
            token_overlap = len(set(normalized.split()) & set(candidate.split())) / max(
                len(set(candidate.split())), 1
            )
            best = max(best, similarity, token_overlap)
        ranked.append((best, action_id))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    highest = ranked[0][0]
    ties = [action_id for score, action_id in ranked if score == highest]
    return ranked[0][1], highest, ties


def parse_local(text: str) -> dict[str, Any]:
    original = text
    text = text.strip()
    if not text:
        return {
            "status": "no_parse",
            "error": "Input is empty.",
            "catalog_version": CATALOG_VERSION,
            "parser_version": LOCAL_PARSER_VERSION,
        }
    if _SYMBOLIC_OPERATOR_PATTERN.search(text):
        return {
            "status": "no_parse",
            "error": "Symbolic Boolean operators are not supported; use English words.",
            "catalog_version": CATALOG_VERSION,
            "parser_version": LOCAL_PARSER_VERSION,
        }

    mentions = _find_mentions(text)
    occurrences: list[Occurrence] = []
    quoted_matches = list(_QUOTED_PATTERN.finditer(text))

    if mentions:
        for index, mention in enumerate(mentions):
            raw_end = len(text)
            if index + 1 < len(mentions):
                gap = text[mention.end : mentions[index + 1].start]
                matches = list(_OPERATOR_PATTERN.finditer(_mask_quoted(gap)))
                if matches:
                    raw_end = mention.end + matches[-1].start()
                else:
                    raw_end = mentions[index + 1].start
            raw_arguments = text[mention.end : raw_end].strip(" \t\r\n,.;:!?")
            occurrence_id = f"action-{index + 1}"
            occurrences.append(
                Occurrence(
                    occurrence_id=occurrence_id,
                    action_id=mention.action_id,
                    arguments=_extract_arguments(text, mention, raw_arguments, quoted_matches),
                    source_span=(mention.start, mention.end),
                    phrase=mention.phrase,
                    raw_arguments=raw_arguments,
                )
            )
        expression = _build_expression(text, mentions, occurrences)
        outcome: dict[str, Any] = {
            "status": "selected",
            "selection_resolved": False,
            "expression": expression.to_dict(),
            "occurrences": [item.to_dict() for item in occurrences],
            "satisfying_assignments_preview": _satisfying_assignments(expression, occurrences),
        }
        if len(occurrences) > 8:
            outcome["satisfying_assignments_preview_truncated"] = True
    else:
        action_id, score, ties = _fallback_candidate(text)
        if len(ties) > 1:
            outcome = {
                "status": "clarification",
                "reason": "exact_rank_tie",
                "alternatives": [{"action_id": item, "rank": score} for item in ties],
            }
        else:
            occurrence = Occurrence(
                occurrence_id="action-1",
                action_id=action_id,
                arguments={},
                source_span=None,
                phrase="",
                raw_arguments="",
            )
            outcome = {
                "status": "selected",
                "selection_resolved": False,
                "rank_source": "local_alias_fallback",
                "rank": score,
                "expression": Expression("leaf", occurrence_id="action-1").to_dict(),
                "occurrences": [occurrence.to_dict()],
                "satisfying_assignments_preview": [["action-1"]],
            }

    outcome["original_text"] = original
    outcome["catalog_version"] = CATALOG_VERSION
    outcome["parser_version"] = LOCAL_PARSER_VERSION
    return outcome


class RPGNLPAdapterError(RuntimeError):
    pass


def parse_with_rpgnlp(text: str) -> dict[str, Any]:
    try:
        from rpgnlp import NLPEngine
    except ImportError as exc:
        raise RPGNLPAdapterError(
            "RPGNLP is not installed. Install the pinned package with "
            "'python -m pip install rpgnlp==0.1.2', then retry. "
            "The default local mode remains available without dependencies."
        ) from exc

    try:
        engine = NLPEngine()
        result = engine.run(text)
    except Exception as exc:
        raise RPGNLPAdapterError(f"RPGNLP failed to parse the input: {exc}") from exc
    if not isinstance(result, dict):
        raise RPGNLPAdapterError(f"Unexpected RPGNLP result type: {type(result).__name__}")

    raw_action = str(result.get("action", "")).strip().casefold()
    canonical = _ALIAS_TO_ACTION.get(raw_action)
    if canonical is None:
        action_id, rank, ties = _fallback_candidate(text)
        if len(ties) > 1:
            return {
                "status": "clarification",
                "reason": "exact_rank_tie",
                "alternatives": [{"action_id": item, "rank": rank} for item in ties],
                "raw_rpgnlp": result,
            }
        canonical = action_id

    args: dict[str, Any] = {}
    for source, target in (
        ("subject", "subject"),
        ("direction", "direction"),
        ("instrument", "objects"),
        ("modifiers", "modifiers"),
        ("topic", "topic"),
    ):
        value = result.get(source)
        if value not in (None, "", []):
            args[target] = value
    utterance = next(
        (match.group(1) if match.group(1) is not None else match.group(2)
         for match in _QUOTED_PATTERN.finditer(text)),
        None,
    )
    if canonical == "talk" and utterance is not None:
        args["utterance"] = utterance

    occurrence = Occurrence(
        occurrence_id="action-1",
        action_id=canonical,
        arguments=args,
        source_span=None,
        phrase=raw_action,
        raw_arguments="",
    )
    return {
        "status": "selected",
        "selection_resolved": False,
        "expression": Expression("leaf", occurrence_id="action-1").to_dict(),
        "occurrences": [occurrence.to_dict()],
        "satisfying_assignments_preview": [["action-1"]],
        "raw_rpgnlp": result,
        "catalog_version": CATALOG_VERSION,
        "parser_version": "rpgnlp-0.1.2-adapter-0.1",
        "original_text": text,
    }


def _format_result(result: dict[str, Any], compact: bool) -> str:
    return json.dumps(
        result, ensure_ascii=False, indent=None if compact else 2, separators=(",", ":") if compact else None
    )


def _run_one(text: str, engine: str, compact: bool) -> int:
    try:
        result = parse_with_rpgnlp(text) if engine == "rpgnlp" else parse_local(text)
    except RPGNLPAdapterError as exc:
        print(f"Parser error: {exc}", file=sys.stderr)
        return 2
    print(_format_result(result, compact))
    return 0 if result["status"] != "no_parse" else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect how a raw Plight command maps to canonical actions and arguments."
    )
    parser.add_argument(
        "--engine",
        choices=("local", "rpgnlp"),
        default="local",
        help="local is offline and dependency-free; rpgnlp uses RPGNLP 0.1.2 (which may download language data).",
    )
    parser.add_argument("--compact", action="store_true", help="Print compact JSON.")
    parser.add_argument("text", nargs="*", help="Raw player command. Omit to read stdin or start a prompt.")
    args = parser.parse_args(argv)
    text = " ".join(args.text)
    if text:
        return _run_one(text, args.engine, args.compact)
    if not sys.stdin.isatty():
        return _run_one(sys.stdin.read(), args.engine, args.compact)

    print("Plight NLP inspector. Enter a command; press Ctrl+C or Ctrl+Z then Enter to exit.")
    try:
        while True:
            line = input("plight> ")
            if line.strip():
                _run_one(line, args.engine, args.compact)
    except (EOFError, KeyboardInterrupt):
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
