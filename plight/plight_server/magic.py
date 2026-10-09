from __future__ import annotations

import math
import time
from typing import Any

MAX_MAGIC_LEVEL = 100
XP_CURVE = 30
BASE_MANA = 20
MANA_PER_SCHOOL_LEVEL = 5
SCHOOL_POWER_PER_LEVEL_PERCENT = 1
MAX_COST_REDUCTION_PERCENT = 60


def experience_for_level(level: int) -> int:
    return XP_CURVE * max(0, level - 1) ** 2


def level_for_experience(experience: int) -> int:
    return min(MAX_MAGIC_LEVEL, 1 + math.isqrt(max(0, int(experience)) // XP_CURVE))


def _state(character: Any) -> dict[str, Any]:
    state = getattr(character, "magic_state", None)
    return dict(state) if isinstance(state, dict) else {}


def _experience(character: Any) -> dict[str, int]:
    values = _state(character).get("experience")
    return dict(values) if isinstance(values, dict) else {}


def _specialty_key(school_id: str, specialty_id: str) -> str:
    return f"{school_id}/{specialty_id}"


def school_level(character: Any, school_id: str) -> int:
    return level_for_experience(_experience(character).get(school_id, 0))


def specialty_level(character: Any, school_id: str, specialty_id: str) -> int:
    return level_for_experience(
        _experience(character).get(_specialty_key(school_id, specialty_id), 0)
    )


def max_mana(character: Any, content: dict[str, Any]) -> int:
    bonus = sum(
        school_level(character, school["id"]) - 1
        for school in content.get("magic_schools", [])
    )
    return BASE_MANA + MANA_PER_SCHOOL_LEVEL * bonus


def mana_regen_per_second(maximum: int) -> float:
    return max(0.2, maximum * 0.01)


def current_mana(
    character: Any, content: dict[str, Any], now: float | None = None
) -> float:
    current_time = time.time() if now is None else now
    maximum = max_mana(character, content)
    state = _state(character)
    stored = state.get("mana")
    if not isinstance(stored, (int, float)):
        return float(maximum)
    elapsed = max(0.0, current_time - float(state.get("mana_at", current_time)))
    return min(float(maximum), float(stored) + elapsed * mana_regen_per_second(maximum))


def set_mana(
    character: Any, content: dict[str, Any], value: float, now: float | None = None
) -> None:
    current_time = time.time() if now is None else now
    state = _state(character)
    state["mana"] = max(0.0, min(float(max_mana(character, content)), float(value)))
    state["mana_at"] = current_time
    character.magic_state = state


def spell_catalog(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {spell["id"]: spell for spell in content.get("spells", [])}


def _school(content: dict[str, Any], school_id: str) -> dict[str, Any] | None:
    return next((item for item in content.get("magic_schools", []) if item["id"] == school_id), None)


def _specialty(school: dict[str, Any] | None, specialty_id: str) -> dict[str, Any] | None:
    return next(
        (item for item in (school or {}).get("specialties", []) if item["id"] == specialty_id),
        None,
    )


def power_multiplier(character: Any, content: dict[str, Any], spell: dict[str, Any]) -> float:
    school = _school(content, spell["school_id"])
    specialty = _specialty(school, spell["specialty_id"]) or {}
    specialty_bonus = (
        (specialty_level(character, spell["school_id"], spell["specialty_id"]) - 1)
        * specialty.get("power_per_level_percent", 0)
    )
    school_bonus = (school_level(character, spell["school_id"]) - 1) * SCHOOL_POWER_PER_LEVEL_PERCENT
    return 1 + (specialty_bonus + school_bonus) / 100


def effective_mana_cost(character: Any, content: dict[str, Any], spell: dict[str, Any]) -> int:
    base = int(spell["mana_cost"])
    if base <= 0:
        return 0
    school = _school(content, spell["school_id"])
    specialty = _specialty(school, spell["specialty_id"]) or {}
    reduction = min(
        MAX_COST_REDUCTION_PERCENT,
        (specialty_level(character, spell["school_id"], spell["specialty_id"]) - 1)
        * specialty.get("cost_reduction_per_level_percent", 0),
    )
    return max(1, math.ceil(base * (100 - reduction) / 100))


def scale_effect(effect: dict[str, Any], multiplier: float) -> dict[str, Any]:
    scaled = dict(effect)
    kind = effect["type"]
    if kind in {"damage", "restore_mana", "shield"}:
        scaled["amount"] = max(1, round(effect["amount"] * multiplier))
    elif kind == "heal" and effect.get("mode") != "full":
        scaled["amount"] = max(1, round(int(effect["amount"]) * multiplier))
    elif kind == "stat_buff":
        scaled["amount"] = max(1, round(effect["amount"] * multiplier))
    return scaled


def effect_text(effect: dict[str, Any], multiplier: float = 1.0) -> str:
    effect = scale_effect(effect, multiplier)
    kind = effect["type"]
    if kind == "damage":
        return f"Deals {effect['amount']} damage"
    if kind == "restore_mana":
        return f"Restores {effect['amount']} mana"
    if kind == "conjure_item":
        return f"Conjures {effect['quantity']} × {effect['item_id'].replace('_', ' ')}"
    if kind == "heal":
        if effect["mode"] == "full":
            return "Fully heals"
        unit = "%" if effect["mode"] == "percent" else ""
        return f"Heals {effect['amount']}{unit}"
    if kind == "stat_buff":
        unit = "%" if effect["mode"] == "percent" else ""
        return f"+{effect['amount']}{unit} {effect['stat']} for {effect['duration_seconds']}s"
    if kind == "shield":
        return f"Shield {effect['amount']} ({effect['mode'].replace('_', ' ')}) for {effect['duration_seconds']}s"
    if kind == "luck":
        return f"Luck for {effect['duration_seconds']}s"
    if kind == "teleport":
        return "Teleports you"
    return kind


def equipped_spellbook(
    character: Any, entities: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    item_id = (getattr(character, "equipment", None) or {}).get("spellbook") or ""
    item = entities.get(item_id)
    if item is None or item.get("type") != "spellbook":
        return None
    if (getattr(character, "inventory", None) or {}).get(item_id, 0) < 1:
        return None
    return item


def learned_spell_ids(character: Any) -> list[str]:
    values = _state(character).get("known_spells")
    return [str(value) for value in values] if isinstance(values, list) else []


def carried_spellbooks(
    character: Any, entities: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    inventory = getattr(character, "inventory", None) or {}
    return [
        entity for entity in entities.values()
        if entity.get("type") == "spellbook" and inventory.get(entity["id"], 0) > 0
    ]


def known_spell_ids(
    character: Any, content: dict[str, Any], entities: dict[str, dict[str, Any]]
) -> set[str]:
    catalog = spell_catalog(content)
    known = {spell_id for spell_id in learned_spell_ids(character) if spell_id in catalog}
    for spell in catalog.values():
        if spell.get("auto_unlock", True) and specialty_level(
            character, spell["school_id"], spell["specialty_id"]
        ) >= spell["required_level"]:
            known.add(spell["id"])
    for book in carried_spellbooks(character, entities):
        known.update(
            slot["spell_id"] for slot in book.get("spell_slots", [])
            if slot.get("spell_id") in catalog
        )
    return known


def learn_spell(character: Any, content: dict[str, Any], spell_id: str) -> str | None:
    spell = spell_catalog(content).get(spell_id)
    if spell is None:
        return None
    learned = learned_spell_ids(character)
    if spell_id in learned:
        return None
    state = _state(character)
    state["known_spells"] = [*learned, spell_id]
    character.magic_state = state
    return f"You learn the spell {spell['name']}."


def slot_spell_id(character: Any, book: dict[str, Any], index: int) -> str | None:
    overrides = (_state(character).get("books") or {}).get(book["id"]) or {}
    if str(index) in overrides:
        return overrides[str(index)] or None
    return (book.get("spell_slots") or [])[index].get("spell_id")


def book_slot_spell_ids(character: Any, book: dict[str, Any]) -> list[str | None]:
    return [slot_spell_id(character, book, index) for index in range(len(book.get("spell_slots", [])))]


def assign_slot(
    character: Any,
    content: dict[str, Any],
    entities: dict[str, dict[str, Any]],
    book_id: str,
    index: int,
    spell_id: str | None,
) -> str | None:
    """Put a known spell into a slot of a carried spellbook. Returns an error message or None."""
    book = next((entry for entry in carried_spellbooks(character, entities) if entry["id"] == book_id), None)
    if book is None:
        return "You are not carrying that spellbook."
    slots = book.get("spell_slots", [])
    if not 0 <= index < len(slots):
        return "That spellbook has no such slot."
    if spell_id:
        spell = spell_catalog(content).get(spell_id)
        if spell is None or spell_id not in known_spell_ids(character, content, entities):
            return "You do not know that spell."
        slot = slots[index]
        if slot.get("school_id") and slot["school_id"] != spell["school_id"]:
            return "That slot only holds spells from another school."
        if slot.get("max_level") and spell["required_level"] > slot["max_level"]:
            return "That spell is too advanced for this slot."
        current = book_slot_spell_ids(character, book)
        if spell_id in [value for position, value in enumerate(current) if position != index]:
            return "That spell is already in this spellbook."
    state = _state(character)
    books = {key: dict(value) for key, value in (state.get("books") or {}).items()}
    books.setdefault(book_id, {})[str(index)] = spell_id or ""
    state["books"] = books
    character.magic_state = state
    return None


def book_spells(
    character: Any, content: dict[str, Any], entities: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    book = equipped_spellbook(character, entities)
    if book is None:
        return []
    catalog = spell_catalog(content)
    return [catalog[spell_id] for spell_id in book_slot_spell_ids(character, book) if spell_id in catalog]


def cast_blocker(
    character: Any,
    content: dict[str, Any],
    spell: dict[str, Any],
    now: float | None = None,
) -> str | None:
    level = specialty_level(character, spell["school_id"], spell["specialty_id"])
    if level < spell["required_level"]:
        school = _school(content, spell["school_id"])
        specialty = _specialty(school, spell["specialty_id"]) or {}
        return (
            f"{spell['name']} needs {specialty.get('name', 'its specialty')} "
            f"level {spell['required_level']} (you are level {level})."
        )
    cost = effective_mana_cost(character, content, spell)
    mana = current_mana(character, content, now)
    if mana < cost:
        return f"You need {cost} mana to cast {spell['name']} (you have {int(mana)})."
    return None


def award_experience(
    character: Any, content: dict[str, Any], spell: dict[str, Any]
) -> list[str]:
    amount = 5 + spell["required_level"] * 3 + int(spell["mana_cost"]) // 4
    school = _school(content, spell["school_id"]) or {}
    specialty = _specialty(school, spell["specialty_id"]) or {}
    state = _state(character)
    experience = dict(state.get("experience") or {})
    keys = {
        "school": spell["school_id"],
        "specialty": _specialty_key(spell["school_id"], spell["specialty_id"]),
    }
    before = {name: level_for_experience(experience.get(key, 0)) for name, key in keys.items()}
    for key in keys.values():
        experience[key] = int(experience.get(key, 0)) + amount
    state["experience"] = experience
    character.magic_state = state
    messages = [f"You gain {amount} {school.get('name', 'magic')} experience."]
    for name, label in (("school", school.get("name", "magic")), ("specialty", specialty.get("name", "specialty"))):
        after = level_for_experience(experience[keys[name]])
        if after > before[name]:
            messages.append(f"Your {label} reaches level {after}.")
    return messages


def _spell_view(
    character: Any, content: dict[str, Any], spell: dict[str, Any], now: float
) -> dict[str, Any]:
    school = _school(content, spell["school_id"]) or {}
    specialty = _specialty(school, spell["specialty_id"]) or {}
    multiplier = power_multiplier(character, content, spell)
    blocker = cast_blocker(character, content, spell, now)
    return {
        "id": spell["id"],
        "name": spell["name"],
        "description": spell["description"],
        "school_id": spell["school_id"],
        "school_name": school.get("name", spell["school_id"]),
        "school_color": school.get("color", "#8f7cff"),
        "specialty_id": spell["specialty_id"],
        "specialty_name": specialty.get("name", spell["specialty_id"]),
        "required_level": spell["required_level"],
        "base_mana_cost": spell["mana_cost"],
        "mana_cost": effective_mana_cost(character, content, spell),
        "target": spell["target"],
        "effects": [effect_text(effect, multiplier) for effect in spell["effects"]],
        "visual": spell["visual"],
        "castable": blocker is None,
        "blocker": blocker,
    }


def magic_view(
    character: Any,
    content: dict[str, Any],
    entities: dict[str, dict[str, Any]],
    now: float | None = None,
) -> dict[str, Any] | None:
    if not content.get("magic_schools"):
        return None
    current_time = time.time() if now is None else now
    experience = _experience(character)
    schools = []
    for school in content["magic_schools"]:
        xp = int(experience.get(school["id"], 0))
        level = level_for_experience(xp)
        specialties = []
        for specialty in school["specialties"]:
            spec_xp = int(experience.get(_specialty_key(school["id"], specialty["id"]), 0))
            spec_level = level_for_experience(spec_xp)
            specialties.append({
                "id": specialty["id"],
                "name": specialty["name"],
                "description": specialty["description"],
                "level": spec_level,
                "experience": spec_xp - experience_for_level(spec_level),
                "experience_to_next_level": (
                    experience_for_level(spec_level + 1) - experience_for_level(spec_level)
                    if spec_level < MAX_MAGIC_LEVEL else 0
                ),
                "power_bonus_percent": (spec_level - 1) * specialty["power_per_level_percent"],
            })
        schools.append({
            "id": school["id"],
            "name": school["name"],
            "description": school["description"],
            "color": school["color"],
            "level": level,
            "experience": xp - experience_for_level(level),
            "experience_to_next_level": (
                experience_for_level(level + 1) - experience_for_level(level)
                if level < MAX_MAGIC_LEVEL else 0
            ),
            "specialties": specialties,
        })
    maximum = max_mana(character, content)
    book = equipped_spellbook(character, entities)
    catalog = spell_catalog(content)
    def book_view(entry: dict[str, Any]) -> dict[str, Any]:
        slots = []
        for index, slot in enumerate(entry.get("spell_slots", [])):
            spell = catalog.get(slot_spell_id(character, entry, index) or "")
            slots.append({
                "index": index,
                "label": slot.get("label") or f"Slot {index + 1}",
                "school_id": slot.get("school_id"),
                "max_level": slot.get("max_level"),
                "spell": _spell_view(character, content, spell, current_time) if spell else None,
            })
        return {
            "id": entry["id"],
            "name": entry["name"],
            "equipped": bool(book and book["id"] == entry["id"]),
            "slots": slots,
        }

    known = known_spell_ids(character, content, entities)
    return {
        "mana": int(current_mana(character, content, current_time)),
        "max_mana": maximum,
        "regen_per_second": round(mana_regen_per_second(maximum), 2),
        "schools": schools,
        "spellbook": book_view(book) if book else None,
        "books": [book_view(entry) for entry in carried_spellbooks(character, entities)],
        "known_spells": [
            _spell_view(character, content, spell, current_time)
            for spell in content["spells"] if spell["id"] in known
        ],
    }
