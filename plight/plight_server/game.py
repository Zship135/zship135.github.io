from __future__ import annotations

from collections.abc import Sequence
from itertools import product
from math import ceil
import random
import re
import time
from typing import Any

from plight_server.content import starting_location, world_content_dict
from plight_nlp_inspector import evaluate_expression, parse_local

PLAYER_BASE_STATS = {
    "health": 100,
    "max_health": 100,
    "attack": 3,
    "defense": 1,
    "speed": 10,
}
ATTACK_INITIATIVE_MULTIPLIERS = {
    "light_attack": 1.05,
    "attack": 1.0,
    "heavy_attack": 0.95,
}
EQUIPMENT_SLOTS = (
    "helm",
    "tunic",
    "pants",
    "sleeves",
    "gloves",
    "boots",
    *(f"ring_{index}" for index in range(1, 6)),
    "necklace_1",
    "necklace_2",
    "left_hand",
    "right_hand",
)
DEFAULT_EQUIPMENT = {
    **{slot: "" for slot in EQUIPMENT_SLOTS},
    "right_hand": "fist",
}
EQUIPMENT_TYPE_SLOTS = {"weapon": {"right_hand"}, "shield": {"left_hand"}}
SKILL_NAMES = (
    "felling",
    "foraging",
    "gouging",
    "fishing",
    "herbology",
    "alchemy",
    "fletching",
    "smithing",
    "lapidary",
    "woodworking",
)
GATHERING_SKILLS = frozenset({"felling", "foraging", "gouging", "fishing", "herbology"})
SKILL_LABELS = {
    "felling": "Felling",
    "foraging": "Foraging",
    "gouging": "Gouging",
    "fishing": "Fishing",
    "herbology": "Herbology",
    "alchemy": "Alchemy",
    "fletching": "Fletching",
    "smithing": "Smithing",
    "lapidary": "Lapidary",
    "woodworking": "Woodworking",
}


def _skill_levels(character: Any) -> dict[str, int]:
    values = dict(getattr(character, "skills", None) or {})
    return {
        skill: max(1, int(values.get(skill, 1)))
        for skill in SKILL_NAMES
    }


def _award_skill_experience(
    character: Any,
    skill: str,
    required_level: int = 1,
) -> list[str]:
    if skill not in SKILL_NAMES:
        return []
    levels = _skill_levels(character)
    experience = dict(getattr(character, "skill_experience", None) or {})
    amount = max(10, required_level * 10)
    experience[skill] = max(0, int(experience.get(skill, 0))) + amount
    messages = [f"You gain {amount} {SKILL_LABELS[skill]} experience."]
    while experience[skill] >= levels[skill] * 100:
        experience[skill] -= levels[skill] * 100
        levels[skill] += 1
        messages.append(
            f"Your {SKILL_LABELS[skill]} reaches level {levels[skill]}."
        )
    character.skills = levels
    character.skill_experience = experience
    return messages


def _skill_progress(character: Any) -> list[dict[str, Any]]:
    levels = _skill_levels(character)
    experience = dict(getattr(character, "skill_experience", None) or {})
    return [
        {
            "id": skill,
            "name": SKILL_LABELS[skill],
            "level": levels[skill],
            "experience": max(0, int(experience.get(skill, 0))),
            "experience_to_next_level": levels[skill] * 100,
        }
        for skill in SKILL_NAMES
    ]


def _live_effects(character: Any, now: float | None = None) -> list[dict[str, Any]]:
    current_time = time.time() if now is None else now
    return [
        effect
        for effect in (getattr(character, "active_effects", None) or [])
        if isinstance(effect, dict)
        and isinstance(effect.get("expires_at"), (int, float))
        and effect["expires_at"] > current_time
    ]


def _temporary_health(character: Any, now: float | None = None) -> int:
    return sum(
        max(0, int(effect.get("remaining", effect.get("amount", 0))))
        for effect in _live_effects(character, now)
        if effect.get("type") == "shield" and effect.get("mode") == "temporary_health"
    )


def _timed_effect_key(effect: dict[str, Any]) -> tuple[str, str]:
    kind = str(effect.get("type", ""))
    return kind, str(effect.get("stat") or effect.get("mode") or kind)


def _apply_timed_effect(
    character: Any,
    effect: dict[str, Any],
    now: float | None = None,
) -> None:
    current_time = time.time() if now is None else now
    expires_at = current_time + int(effect["duration_seconds"])
    key = _timed_effect_key(effect)
    active = [
        existing
        for existing in _live_effects(character, current_time)
        if _timed_effect_key(existing) != key
    ]
    active.append(
        {
            **effect,
            "expires_at": expires_at,
            **(
                {"remaining": int(effect["amount"])}
                if effect.get("type") == "shield"
                and effect.get("mode") in {"damage_pool", "temporary_health"}
                else {}
            ),
        }
    )
    character.active_effects = active


def _currency_text(currencies: dict[str, dict[str, Any]], currency_id: str, amount: int) -> str:
    currency = currencies.get(currency_id, {})
    symbol = currency.get("symbol") or ""
    if symbol:
        return f"{symbol}{amount:,}"
    return f"{amount:,} {currency.get('name', currency_id.replace('_', ' ').title())}"


def _add_currency(character: Any, currency_id: str, amount: int) -> None:
    wallet = dict(getattr(character, "wallet", None) or {})
    wallet[currency_id] = int(wallet.get(currency_id, 0)) + amount
    character.wallet = wallet


def _wallet_view(character: Any, content: dict[str, Any]) -> list[dict[str, Any]]:
    wallet = getattr(character, "wallet", None) or {}
    return [
        {
            "currency_id": currency["id"],
            "name": currency["name"],
            "symbol": currency.get("symbol", ""),
            "amount": max(0, int(wallet.get(currency["id"], 0))),
        }
        for currency in content.get("currencies", [])
    ]


def _stock_state(
    character: Any,
    npc_id: str,
    entry: dict[str, Any],
    now: float,
) -> tuple[int, int]:
    state = ((getattr(character, "shop_state", None) or {}).get(npc_id) or {}).get(
        entry["item_id"]
    ) or {}
    restock_at = state.get("restock_at")
    if isinstance(restock_at, (int, float)) and restock_at > now:
        purchased = max(0, int(state.get("purchased", 0)))
        return max(0, entry["quantity"] - purchased), max(0, ceil(restock_at - now))
    return entry["quantity"], 0


def _shop_view(
    character: Any,
    npc: dict[str, Any],
    entities: dict[str, dict[str, Any]],
    currencies: dict[str, dict[str, Any]],
    now: float,
) -> list[dict[str, Any]]:
    shop = []
    for entry in npc.get("stock", []):
        item = entities.get(entry["item_id"])
        if item is None or entry.get("currency_id") not in currencies:
            continue
        remaining, restock_in = _stock_state(character, npc["id"], entry, now)
        shop.append(
            {
                "item_id": entry["item_id"],
                "item_name": item["name"],
                "currency_id": entry["currency_id"],
                "price": entry["price"],
                "price_text": _currency_text(currencies, entry["currency_id"], entry["price"]),
                "remaining": remaining,
                "capacity": entry["quantity"],
                "restock_seconds_remaining": restock_in,
            }
        )
    return shop


def _buy(
    character: Any,
    arguments: dict[str, Any],
    content: dict[str, Any],
    areas: dict[str, dict[str, Any]],
    entities: dict[str, dict[str, Any]],
    now: float | None = None,
) -> list[str]:
    current_time = time.time() if now is None else now
    currencies = {currency["id"]: currency for currency in content.get("currencies", [])}
    area = areas.get(character.area_id)
    if area is None:
        return ["You are not in a valid location."]
    item_value = arguments.get("item")
    quantity = 1
    if isinstance(item_value, dict):
        quantity = int(item_value.get("quantity") or 1)
    if arguments.get("quantity"):
        quantity = int(arguments["quantity"])
    item_text = _command_subject(arguments, "item", "subject", "target")
    shop_text = str(arguments.get("shop") or "")
    parts = re.split(r"\s+from\s+", item_text, maxsplit=1, flags=re.I)
    item_text = parts[0]
    if len(parts) == 2 and not shop_text:
        shop_text = parts[1]
    shop_text = re.sub(r"^(?:the|a|an)\s+", "", shop_text.strip(), flags=re.I)
    if "from" in shop_text.casefold().split():
        shop_text = re.split(r"\s+from\s+", shop_text, maxsplit=1, flags=re.I)[-1]
    if not item_text:
        return ["Name what you would like to buy."]
    quantity = max(1, quantity)
    shopkeepers = [
        entities[npc_id]
        for npc_id in area["npc_ids"]
        if character.species in entities[npc_id]["present_for"]
        and entities[npc_id].get("stock")
    ]
    if shop_text:
        shopkeepers = _matching_entities(shop_text, shopkeepers)
    if not shopkeepers:
        return [f"There is no shop called {shop_text} here." if shop_text else "Nobody here is selling anything."]
    offers = []
    for npc in shopkeepers:
        for entry in npc["stock"]:
            item = entities.get(entry["item_id"])
            if item is not None and _matching_entities(item_text, [item]):
                offers.append((npc, entry, item))
    exact = [
        offer for offer in offers
        if _normalize_npc_name(offer[2]["name"]) == _normalize_npc_name(item_text)
    ]
    offers = exact or offers
    if not offers:
        return [f"Nobody here is selling {item_text}."]
    if len({offer[2]["id"] for offer in offers}) > 1:
        return [f"Which item do you mean: {', '.join(sorted({offer[2]['name'] for offer in offers}))}?"]
    if len(offers) > 1:
        return [f"Who do you want to buy {offers[0][2]['name']} from: {', '.join(offer[0]['name'] for offer in offers)}?"]
    npc, entry, item = offers[0]
    currency_id = entry.get("currency_id")
    if currency_id not in currencies:
        return [f"{npc['name']} has not set a price for {item['name']}."]
    remaining, restock_in = _stock_state(character, npc["id"], entry, current_time)
    if remaining == 0:
        return [
            f"{npc['name']} is out of {item['name']} for you"
            + (f"; more arrives in {_duration_text(restock_in)}." if restock_in else ".")
        ]
    if quantity > remaining:
        return [f"{npc['name']} only has {remaining} {item['name']} left for you."]
    total = entry["price"] * quantity
    wallet = dict(getattr(character, "wallet", None) or {})
    balance = int(wallet.get(currency_id, 0))
    if balance < total:
        return [
            f"You need {_currency_text(currencies, currency_id, total)} but only have "
            f"{_currency_text(currencies, currency_id, balance)}."
        ]
    wallet[currency_id] = balance - total
    character.wallet = wallet
    inventory = dict(character.inventory or {})
    inventory[item["id"]] = inventory.get(item["id"], 0) + quantity
    character.inventory = inventory
    shop_state = {k: dict(v) for k, v in (getattr(character, "shop_state", None) or {}).items()}
    npc_state = dict(shop_state.get(npc["id"]) or {})
    previous = npc_state.get(item["id"]) or {}
    still_restocking = (
        isinstance(previous.get("restock_at"), (int, float))
        and previous["restock_at"] > current_time
    )
    npc_state[item["id"]] = {
        "purchased": (int(previous.get("purchased", 0)) if still_restocking else 0) + quantity,
        "restock_at": previous["restock_at"]
        if still_restocking
        else current_time + entry["restock_seconds"],
    }
    shop_state[npc["id"]] = npc_state
    character.shop_state = shop_state
    _record_quest_event(character, content, "collect", item["id"], quantity)
    return [
        f"You buy {_quantity_name(quantity, item['name'])} from {npc['name']} "
        f"for {_currency_text(currencies, currency_id, total)}."
    ]


def _luck_bonuses(character: Any, now: float | None = None) -> tuple[int, int]:
    drop_chance = 0
    gathering_yield = 0
    for effect in _live_effects(character, now):
        if effect.get("type") == "luck":
            drop_chance = max(
                drop_chance, int(effect.get("drop_chance_bonus_percent", 0))
            )
            gathering_yield = max(
                gathering_yield,
                int(effect.get("gathering_yield_bonus_percent", 0)),
            )
    return drop_chance, gathering_yield


def _effective_stats(
    character: Any,
    entities: dict[str, dict[str, Any]] | None = None,
    now: float | None = None,
) -> dict[str, int]:
    stats = {**PLAYER_BASE_STATS, **(character.combat_stats or {})}
    for effect in _live_effects(character, now):
        if effect.get("type") != "stat_buff":
            continue
        stat = effect.get("stat")
        if stat not in {"attack", "defense", "speed"}:
            continue
        amount = int(effect.get("amount", 0))
        bonus = amount if effect.get("mode") == "flat" else ceil(stats[stat] * amount / 100)
        stats[stat] += bonus
    equipment = {**DEFAULT_EQUIPMENT, **(character.equipment or {})}
    if (entities or {}).get(equipment["left_hand"], {}).get("type") != "shield":
        equipment["left_hand"] = ""
    if equipment["right_hand"] != "fist" and (entities or {}).get(
        equipment["right_hand"], {}
    ).get("type") != "weapon":
        equipment["right_hand"] = "fist"
    shield_id = equipment.get("left_hand")
    shield = (entities or {}).get(shield_id or "")
    if shield is not None and shield.get("type") == "shield":
        defense = (shield.get("attributes") or {}).get("defense", 0)
        if isinstance(defense, int) and not isinstance(defense, bool) and defense > 0:
            stats["defense"] += defense
    return stats


def _set_current_health(character: Any, health: int) -> None:
    stats = {**PLAYER_BASE_STATS, **(character.combat_stats or {})}
    stats["health"] = health
    character.combat_stats = stats


combat_rng = random.SystemRandom()


def initial_area(species: str) -> str:
    return starting_location(species)


def _level_progress(experience: int) -> tuple[int, int, int]:
    total = max(0, experience)
    level = 1
    level_start = 0
    while total >= level_start + level * 100:
        level_start += level * 100
        level += 1
    return level, total - level_start, level * 100


def award_experience(character: Any, amount: int) -> list[str]:
    if amount <= 0:
        return []
    previous_level, _, _ = _level_progress(character.experience or 0)
    character.experience = (character.experience or 0) + amount
    new_level, _, _ = _level_progress(character.experience)
    messages = [f"You gain {amount} experience."]
    if new_level > previous_level:
        stats = {**PLAYER_BASE_STATS, **(character.combat_stats or {})}
        for _ in range(new_level - previous_level):
            stats["attack"] += 1
            stats["max_health"] += 10
            stats["health"] = min(stats["max_health"], stats["health"] + 10)
        character.combat_stats = stats
        messages.append(
            f"You reached level {new_level}! Attack increases by 1 and maximum health by 10."
        )
    return messages


def _location_map(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {location["id"]: location for location in content["locations"]}


def _quest_view(
    character: Any,
    quest: dict[str, Any],
    entities: dict[str, dict[str, Any]],
    areas: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    inventory = character.inventory or {}
    quest_state = getattr(character, "quest_state", None) or {}
    saved_state = quest_state.get(quest["id"], {})
    status = saved_state.get("status", "available")
    current_step_id = (
        None
        if saved_state.get("ready_to_turn_in") or status == "completed"
        else saved_state.get("current_step_id") or quest["start_step_id"]
    )
    step = next(
        (candidate for candidate in quest["steps"] if candidate["id"] == current_step_id),
        None,
    )
    objective_progress = (saved_state.get("progress") or {}).get(current_step_id, {})
    objectives = []
    for objective in step["objectives"] if step is not None else []:
        target_id = objective["target_id"]
        if objective["type"] == "collect":
            current = min(objective["quantity"], inventory.get(target_id, 0))
        else:
            current = min(
                objective["quantity"],
                objective_progress.get(objective["id"], 0),
            )
        target_name = (
            areas.get(target_id, {}).get("name", target_id.replace("_", " ").title())
            if objective["type"] == "visit" and areas is not None
            else entities[target_id]["name"]
        )
        objectives.append(
            {
                "id": objective["id"],
                "type": objective["type"],
                "target_id": target_id,
                "target_name": target_name,
                "item_id": target_id if objective["type"] == "collect" else None,
                "item_name": target_name,
                "required": objective["quantity"],
                "current": current,
            }
        )
    objectives_complete = bool(objectives) and all(
        objective["current"] >= objective["required"] for objective in objectives
    )
    can_choose = (
        status == "active"
        and not saved_state.get("ready_to_turn_in", False)
        and objectives_complete
        and step is not None
    )
    return {
        "id": quest["id"],
        "title": quest["title"],
        "description": quest["description"],
        "giver_npc_id": quest["giver_npc_id"],
        "giver_name": entities[quest["giver_npc_id"]]["name"],
        "status": status,
        "current_step_id": current_step_id if status == "active" else None,
        "current_step_title": step["title"] if step is not None else None,
        "step_description": step["description"] if step is not None else "",
        "objectives": objectives,
        "choices": step["choices"] if can_choose and step is not None else [],
        "can_choose": can_choose,
        "reward_experience": quest["reward_experience"],
        "reward_items": [
            {
                **reward,
                "item_name": entities[reward["item_id"]]["name"],
            }
            for reward in quest.get("reward_items", [])
        ],
        "reward_currencies": list(quest.get("reward_currencies", [])),
        "can_turn_in": status == "active" and saved_state.get("ready_to_turn_in", False),
    }


def initialize_quest_step(
    quest: dict[str, Any],
    quest_state: dict[str, Any],
    area_id: str,
) -> dict[str, Any]:
    step_id = quest_state.get("current_step_id") or quest["start_step_id"]
    step = next((candidate for candidate in quest["steps"] if candidate["id"] == step_id), None)
    if step is None:
        return quest_state
    progress = {
        step_key: dict(objectives)
        for step_key, objectives in (quest_state.get("progress") or {}).items()
    }
    step_progress = progress.setdefault(step_id, {})
    for objective in step["objectives"]:
        if objective["type"] == "visit" and objective["target_id"] == area_id:
            step_progress[objective["id"]] = max(step_progress.get(objective["id"], 0), 1)
    return {**quest_state, "progress": progress}


def _record_quest_event(
    character: Any,
    content: dict[str, Any],
    event_type: str,
    target_id: str,
    quantity: int = 1,
) -> None:
    state = dict(getattr(character, "quest_state", None) or {})
    changed = False
    for quest in content.get("quests", []):
        quest_state = dict(state.get(quest["id"], {}))
        if quest_state.get("status") != "active" or quest_state.get("ready_to_turn_in"):
            continue
        step_id = quest_state.get("current_step_id") or quest["start_step_id"]
        step = next((candidate for candidate in quest["steps"] if candidate["id"] == step_id), None)
        if step is None:
            continue
        matching = [
            objective
            for objective in step["objectives"]
            if objective["type"] == event_type and objective["target_id"] == target_id
        ]
        if not matching:
            continue
        progress = {
            step_key: dict(objectives)
            for step_key, objectives in (quest_state.get("progress") or {}).items()
        }
        step_progress = progress.setdefault(step_id, {})
        for objective in matching:
            step_progress[objective["id"]] = min(
                objective["quantity"],
                step_progress.get(objective["id"], 0) + quantity,
            )
        state[quest["id"]] = {**quest_state, "progress": progress}
        changed = True
    if changed:
        character.quest_state = state


def _exit_lock_reason(
    character: Any,
    quest_id: str,
    destination_name: str,
    quests: dict[str, dict[str, Any]],
    entities: dict[str, dict[str, Any]],
    areas: dict[str, dict[str, Any]],
) -> str | None:
    quest = quests[quest_id]
    progress = _quest_view(character, quest, entities, areas)
    if progress["status"] == "completed":
        return None
    if progress["status"] == "available":
        return (
            f"The way to {destination_name} is sealed. Speak with {progress['giver_name']} "
            f"about “{progress['title']}”."
        )
    missing = []
    for objective in progress["objectives"]:
        remaining = objective["required"] - objective["current"]
        if remaining <= 0:
            continue
        target = objective["target_name"]
        if objective["type"] == "collect":
            missing.append(f"{remaining} more {target}")
        elif objective["type"] == "kill":
            missing.append(f"defeat {remaining} more {target}")
        elif objective["type"] == "talk":
            missing.append(f"talk to {target}")
        else:
            missing.append(f"visit {target}")
    if missing:
        return f"The way to {destination_name} is sealed. Complete this quest step: {', '.join(missing)}."
    if progress["can_choose"]:
        return f"The way to {destination_name} is sealed. Choose your next step in the quest tracker."
    return (
        f"The way to {destination_name} is sealed. Return to {progress['giver_name']} "
        "to turn in the quest."
    )


def _resource_state_key(location_id: str, resource_id: str) -> str:
    return f"{location_id}:{resource_id}"


def _resource_status(
    character: Any,
    location_id: str,
    entity: dict[str, Any],
    now: float | None = None,
) -> dict[str, Any]:
    config = entity.get("gathering")
    if not isinstance(config, dict):
        return {"configured": False, "available": False}
    current_time = time.time() if now is None else now
    key = _resource_state_key(location_id, entity["id"])
    state = (getattr(character, "resource_state", None) or {}).get(key, {})
    respawn_at = state.get("respawn_at")
    remaining = (
        max(0, ceil(float(respawn_at) - current_time))
        if isinstance(respawn_at, (int, float))
        else 0
    )
    health = (
        int(state.get("health", config["health"]))
        if remaining > 0
        else config["health"]
    )
    return {
        "configured": bool(config.get("loot_table")),
        "available": remaining == 0 and health > 0,
        "health": health,
        "max_health": config["health"],
        "respawn_seconds_remaining": remaining,
        "respawn_at": respawn_at,
        "skill": config["skill"],
        "skill_name": SKILL_LABELS[config["skill"]],
        "skill_level": config["skill_level"],
        "tool_stat": config.get("tool_stat"),
        "minimum_tool_power": config["minimum_tool_power"],
    }


def _active_effect_views(character: Any, now: float | None = None) -> list[dict[str, Any]]:
    current_time = time.time() if now is None else now
    return [
        {
            **effect,
            "remaining_seconds": max(0, ceil(effect["expires_at"] - current_time)),
        }
        for effect in _live_effects(character, current_time)
    ]


def _snapshot(
    character: Any,
    content: dict[str, Any],
    enemy_spawns_by_location: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    areas = _location_map(content)
    area = areas[character.area_id]
    entities = {entity["id"]: entity for entity in content["entities"]}
    quests = {quest["id"]: quest for quest in content.get("quests", [])}
    stats = _effective_stats(character, entities)
    stats["health"] += _temporary_health(character)
    experience = getattr(character, "experience", 0) or 0
    level, experience_progress, experience_to_next_level = _level_progress(experience)
    equipment = {**DEFAULT_EQUIPMENT, **(character.equipment or {})}
    if entities.get(equipment["left_hand"], {}).get("type") != "shield":
        equipment["left_hand"] = ""
    if equipment["right_hand"] != "fist" and entities.get(
        equipment["right_hand"], {}
    ).get("type") != "weapon":
        equipment["right_hand"] = "fist"
    combat_state = character.combat_state or {}
    enemy_health = combat_state.get("enemy_health", {})
    inventory_items = []
    for item_id, quantity in (character.inventory or {}).items():
        item = entities.get(item_id)
        item_type = item["type"] if item else None
        inventory_items.append(
            {
                "id": item_id,
                "name": item["name"] if item else item_id.replace("_", " ").title(),
                "quantity": quantity,
                "type": item_type,
                "equipable_slots": sorted(EQUIPMENT_TYPE_SLOTS.get(item_type, set())),
                "can_use": bool(
                    item
                    and item_type == "item"
                    and (item.get("item_use") or {}).get("effects")
                ),
            }
        )

    def visible_entities(entity_ids: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "id": entity_id,
                "name": entities[entity_id]["name"],
                "description": entities[entity_id]["description"],
                "type": entities[entity_id]["type"],
                **(
                    {"gathering": entities[entity_id]["gathering"]}
                    if entities[entity_id]["type"] == "resource"
                    and entities[entity_id].get("gathering") is not None
                    else {}
                ),
                **(
                    {"race": entities[entity_id]["race"]}
                    if entities[entity_id]["type"] == "npc"
                    else {}
                ),
                **(
                    {
                        "quests": [
                            _quest_view(character, quest, entities, areas)
                            for quest in content.get("quests", [])
                            if quest["giver_npc_id"] == entity_id
                        ]
                    }
                    if entities[entity_id]["type"] == "npc"
                    else {}
                ),
                **(
                    {
                        "health": enemy_health.get(
                            entity_id,
                            entities[entity_id]["attributes"].get("health", 1),
                        ),
                        "max_health": entities[entity_id]["attributes"].get("health", 1),
                        "attack_die_sides": entities[entity_id]["attack_die_sides"],
                    }
                    if entities[entity_id]["type"] == "enemy"
                    else {}
                ),
            }
            for entity_id in entity_ids
            if (
                entities[entity_id]["type"] != "npc" or entity_id in visible_npc_ids
            )
            and (
                entities[entity_id]["type"] != "enemy"
                or enemy_health.get(entity_id, entities[entity_id]["attributes"].get("health", 1)) > 0
            )
        ]

    exits = area["exits"]
    exit_details = []
    for direction in ("north", "south", "east", "west"):
        destination_id = exits.get(direction)
        if destination_id is None:
            continue
        destination_name = areas[destination_id]["name"]
        quest_id = area.get("exit_requirements", {}).get(direction)
        reason = (
            _exit_lock_reason(character, quest_id, destination_name, quests, entities, areas)
            if quest_id
            else None
        )
        exit_details.append(
            {
                "direction": direction,
                "destination_id": destination_id,
                "destination_name": destination_name,
                "accessible": reason is None,
                "reason": reason,
            }
        )
    if enemy_spawns_by_location is None:
        enemies = visible_entities(area["enemy_ids"])
        ambience_enemy_ids = area["enemy_ids"]
    else:
        enemies = []
        ambience_enemy_ids = []
        for spawn in enemy_spawns_by_location.get(character.area_id, []):
            enemy_id = spawn["enemy_id"]
            enemy = entities.get(enemy_id)
            if not spawn["is_alive"] or enemy is None or enemy["type"] != "enemy":
                continue
            ambience_enemy_ids.append(enemy_id)
            enemies.append(
                {
                    "id": spawn["id"],
                    "entity_id": enemy_id,
                    "name": enemy["name"],
                    "description": enemy["description"],
                    "type": "enemy",
                    "health": spawn["health"],
                    "max_health": enemy["attributes"].get("health", 1),
                    "attack_die_sides": enemy["attack_die_sides"],
                    "behavior": enemy.get("behavior", "neutral"),
                }
            )
    visible_npc_ids = [
        entity_id
        for entity_id in area["npc_ids"]
        if character.species in entities[entity_id]["present_for"]
    ]
    npcs = visible_entities(visible_npc_ids)
    currency_map = {currency["id"]: currency for currency in content.get("currencies", [])}
    snapshot_time = time.time()
    for npc_view in npcs:
        npc_view["shop"] = _shop_view(
            character, entities[npc_view["id"]], entities, currency_map, snapshot_time
        )
    objects = visible_entities(area["object_ids"])
    resources = visible_entities(area["resource_ids"])
    for resource_view in resources:
        resource = entities[resource_view["id"]]
        resource_view["gather_status"] = _resource_status(
            character,
            character.area_id,
            resource,
        )
    ambience_lines = list(area["ambience"])
    for entity_id in (*ambience_enemy_ids, *visible_npc_ids):
        ambience_lines.extend(entities[entity_id]["ambience"])
    atmosphere = (
        f"{', '.join(enemy['name'] for enemy in enemies)} nearby."
        if enemies
        else "Distant voices drift through the street."
    )
    atmosphere_data = {
        "weather": "Clear",
        "time_of_day": "Evening",
        "sounds": atmosphere,
    }

    return {
        "account_id": character.account_id,
        "character": {
            "id": character.id,
            "name": character.name,
            "species": character.species,
            "area_id": character.area_id,
            "area_name": area["name"],
            "appearance": character.appearance,
            "inventory": character.inventory or {},
            "inventory_items": inventory_items,
            "stats": stats,
            "skills": _skill_progress(character),
            "active_effects": _active_effect_views(character),
            "gathering": (
                {
                    **character.gathering_state,
                    "remaining_seconds": max(
                        0,
                        ceil(
                            float(character.gathering_state["completes_at"])
                            - time.time()
                        ),
                    ),
                }
                if isinstance(getattr(character, "gathering_state", None), dict)
                else None
            ),
            "respawn_area_id": getattr(character, "respawn_area_id", None)
            or starting_location(character.species),
            "level": level,
            "wallet": _wallet_view(character, content),
            "experience": experience,
            "experience_progress": experience_progress,
            "experience_to_next_level": experience_to_next_level,
            "equipment": equipment,
        },
        "area": {
            "id": character.area_id,
            "name": area["name"],
            "description": area["description"],
            "music_asset_id": area.get("music_asset_id"),
            "exits": [key for key in ("north", "south", "east", "west") if key in exits],
            "exit_destinations": {
                direction: areas[destination]["name"]
                for direction, destination in exits.items()
            },
            "exit_details": exit_details,
            "enemies": enemies,
            "npcs": npcs,
            "objects": objects,
            "resources": resources,
            "ambience_lines": ambience_lines,
        },
        "quest_log": [
            _quest_view(character, quest, entities, areas)
            for quest in content.get("quests", [])
            if (getattr(character, "quest_state", None) or {}).get(quest["id"], {}).get("status")
            in {"active", "completed"}
        ],
        "action_sounds": content.get("action_sounds", {}),
        "atmosphere": atmosphere_data,
    }


def snapshot(
    character: Any,
    enemy_spawns_by_location: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    return _snapshot(character, world_content_dict(), enemy_spawns_by_location)


def resolve_command(
    text: str,
    character: Any,
    available_players: Sequence[Any] | None = None,
    enemy_spawns_by_location: dict[str, list[dict[str, Any]]] | None = None,
    deferred_action_ids: set[str] | None = None,
    defer_all_actions: bool = False,
    selected_occurrence_ids: set[str] | None = None,
    combat_context: bool = False,
    party_members: Sequence[Any] | None = None,
) -> dict[str, Any]:
    content = world_content_dict()
    areas = _location_map(content)
    entities = {entity["id"]: entity for entity in content["entities"]}
    parsed = parse_local(text)
    if parsed["status"] != "selected":
        return {
            "interpretation": parsed,
            "messages": ["I could not find a supported action in that sentence."],
            "dialogues": [],
            "snapshot": _snapshot(character, content, enemy_spawns_by_location),
        }

    occurrences = parsed["occurrences"]
    if len(occurrences) > 8:
        return {
            "interpretation": parsed,
            "messages": ["A single command can contain at most eight action occurrences."],
            "dialogues": [],
            "snapshot": _snapshot(character, content, enemy_spawns_by_location),
        }

    assignments: list[dict[str, bool]] = []
    occurrence_ids = [item["occurrence_id"] for item in occurrences]
    expression = parsed["expression"]
    for values in product((False, True), repeat=len(occurrence_ids)):
        assignment = dict(zip(occurrence_ids, values, strict=True))
        if evaluate_expression(_expression(expression), assignment):
            assignments.append(assignment)
    if not assignments:
        return {
            "interpretation": parsed,
            "messages": ["That combination has no valid action selection."],
            "dialogues": [],
            "snapshot": _snapshot(character, content, enemy_spawns_by_location),
        }

    if selected_occurrence_ids is None:
        selected = random.SystemRandom().choice(assignments)
        selected_ids = {key for key, value in selected.items() if value}
    else:
        selected_ids = set(selected_occurrence_ids)
        if not selected_ids.issubset(occurrence_ids):
            return {
                "interpretation": parsed,
                "messages": ["That selected action is no longer available."],
                "dialogues": [],
                "queued_actions": [],
                "snapshot": _snapshot(character, content, enemy_spawns_by_location),
            }
    parsed["selection_resolved"] = True
    parsed["selected_occurrences"] = sorted(
        selected_ids, key=lambda item: occurrence_ids.index(item)
    )
    messages: list[str] = []
    active_gathering = getattr(character, "gathering_state", None)
    if isinstance(active_gathering, dict) and float(
        active_gathering.get("completes_at", float("inf"))
    ) <= time.time():
        messages.extend(_complete_gathering(character, content))
        active_gathering = getattr(character, "gathering_state", None)
    selected_actions = [
        occurrence["action_id"]
        for occurrence in occurrences
        if occurrence["occurrence_id"] in selected_ids
    ]
    if isinstance(active_gathering, dict) and any(
        action_id != "cancel_gather" for action_id in selected_actions
    ):
        messages.append(
            f"You are busy gathering {active_gathering['resource_name']}. "
            "Type stop to cancel."
        )
        return {
            "interpretation": parsed,
            "messages": messages,
            "dialogues": [],
            "queued_actions": [],
            "snapshot": _snapshot(character, content, enemy_spawns_by_location),
        }
    dialogues: list[dict[str, Any]] = []
    profile_account_ids: list[str] = []
    observed_player_equipment: dict[str, dict[str, str]] = {}
    inventory_view: str | None = None
    queued_actions: list[dict[str, Any]] = []
    party_effect_messages: dict[str, list[str]] = {}
    for occurrence in occurrences:
        if occurrence["occurrence_id"] not in selected_ids:
            continue
        action_id = occurrence["action_id"]
        args = occurrence["arguments"]
        if defer_all_actions or action_id in (deferred_action_ids or set()):
            queued_actions.append(dict(occurrence))
            continue
        if action_id == "observe":
            subject = args.get("subject", "")
            inventory_subjects = {
                "inventory": "all",
                "armor": "armor",
                "armour": "armor",
                "hands": "hands",
                "weapons": "hands",
            }
            normalized_subject = str(subject).casefold()
            if normalized_subject in inventory_subjects:
                inventory_view = inventory_subjects[normalized_subject]
                messages.append("You check your inventory and equipment.")
                continue
            if normalized_subject == "self":
                messages.append("You look over your character profile.")
                profile_account_ids.append(character.account_id)
                continue
            if not subject:
                messages.append(areas[character.area_id]["description"])
                continue
            area = areas[character.area_id]
            present_ids = [
                *area["enemy_ids"],
                *(
                    entity_id
                    for entity_id in area["npc_ids"]
                    if character.species in entities[entity_id]["present_for"]
                ),
                *area["object_ids"],
                *area["resource_ids"],
            ]
            present = [entities[entity_id] for entity_id in present_ids]
            player_entities = [
                {"id": player.id, "name": player.name, "account_id": player.account_id}
                for player in (available_players or [])
                if player.area_id == character.area_id and player.account_id != character.account_id
            ]
            matches = _matching_entities(str(subject), [*present, *player_entities])
            if len(matches) == 1:
                entity = matches[0]
                if entity.get("account_id"):
                    messages.append(f"You observe {entity['name']}.")
                    profile_account_ids.append(entity["account_id"])
                    other_player = next(
                        (
                            player
                            for player in (available_players or [])
                            if player.account_id == entity["account_id"]
                        ),
                        None,
                    )
                    if other_player is not None:
                        player_equipment = {
                            **DEFAULT_EQUIPMENT,
                            **(other_player.equipment or {}),
                        }
                        if entities.get(player_equipment["left_hand"], {}).get(
                            "type"
                        ) != "shield":
                            player_equipment["left_hand"] = ""
                        if (
                            player_equipment["right_hand"] != "fist"
                            and entities.get(player_equipment["right_hand"], {}).get(
                                "type"
                            )
                            != "weapon"
                        ):
                            player_equipment["right_hand"] = "fist"
                        observed_player_equipment[entity["account_id"]] = {
                            slot: (
                                entities.get(item_id, {}).get(
                                    "name", item_id.replace("_", " ").title()
                                )
                                if item_id != "fist"
                                else "Fist"
                            )
                            for slot, item_id in player_equipment.items()
                        }
                else:
                    messages.append(f"{entity['name']}: {entity['description']}")
            elif matches:
                messages.append(
                    f"Which one do you mean: {', '.join(entity['name'] for entity in matches)}?"
                )
            else:
                messages.append(f"There is no {subject} here to observe.")
        elif action_id == "travel":
            direction = str(args.get("direction", "")).casefold()
            current_area = areas[character.area_id]
            destination = current_area["exits"].get(direction)
            if destination:
                quest_id = current_area.get("exit_requirements", {}).get(direction)
                if quest_id:
                    reason = _exit_lock_reason(
                        character,
                        quest_id,
                        areas[destination]["name"],
                        {quest["id"]: quest for quest in content.get("quests", [])},
                        entities,
                        areas,
                    )
                    if reason:
                        messages.append(reason)
                        continue
                character.area_id = destination
                _record_quest_event(character, content, "visit", destination)
                combat_state = dict(character.combat_state or {})
                combat_state["target_id"] = None
                combat_state["enemy_health"] = {}
                combat_state["defending"] = False
                character.combat_state = combat_state
                messages.append(f"You travel {direction} to {areas[destination]['name']}.")
            else:
                messages.append(f"You cannot travel {direction or 'that way'} from here.")
        elif action_id == "talk":
            area = areas[character.area_id]
            available_npcs = [
                entities[npc_id]
                for npc_id in area["npc_ids"]
                if character.species in entities[npc_id]["present_for"]
            ]
            subject = _normalize_npc_name(args.get("subject", ""))
            if subject:
                matches = [
                    npc
                    for npc in available_npcs
                    if subject in _normalize_npc_name(npc["name"])
                    or _normalize_npc_name(npc["name"]) in subject
                ]
                if len(matches) != 1:
                    messages.append(
                        f"There is no {args['subject']} here to talk to."
                        if not matches
                        else f"Which person do you mean: {', '.join(npc['name'] for npc in matches)}?"
                    )
                    continue
                npc = matches[0]
            elif len(available_npcs) == 1:
                npc = available_npcs[0]
            elif not available_npcs:
                messages.append("There is nobody here to talk to.")
                continue
            else:
                messages.append(f"Who would you like to talk to: {', '.join(npc['name'] for npc in available_npcs)}?")
                continue

            dialogue = npc["dialogue"]
            _record_quest_event(character, content, "talk", npc["id"])
            if not dialogue["nodes"]:
                messages.append(f"{npc['name']} has nothing to say right now.")
                continue
            node = next(
                item for item in dialogue["nodes"]
                if item["id"] == dialogue["start_node_id"]
            )
            messages.append(f"You speak with {npc['name']}.")
            dialogues.append(
                {
                    "occurrence_id": occurrence["occurrence_id"],
                    "npc_id": npc["id"],
                    "npc_name": npc["name"],
                    "node_id": node["id"],
                    "title": node["title"],
                    "text": node["text"],
                    "choices": node["choices"],
                    "history": [{"speaker": npc["name"], "text": node["text"]}],
                }
            )
        elif action_id in {"attack", "light_attack", "heavy_attack"}:
            messages.extend(
                _attack(
                    character,
                    areas,
                    entities,
                    occurrence,
                    content,
                    enemy_spawns_by_location,
                    resolve_retaliation=not combat_context,
                    award_rewards=not combat_context,
                )
            )
        elif action_id == "equip_item":
            messages.append(_equip(character, entities, args))
        elif action_id == "unequip_item":
            messages.append(_unequip(character, entities, args))
        elif action_id == "gather":
            messages.extend(_start_gathering(character, args, areas, entities))
        elif action_id == "cancel_gather":
            messages.append(_cancel_gathering(character))
        elif action_id == "craft":
            messages.extend(_craft(character, args, content, areas, entities))
        elif action_id == "shop_buy":
            messages.extend(_buy(character, args, content, areas, entities))
        elif action_id == "shop_sell":
            messages.append("Shopkeepers here do not buy items back.")
        elif action_id == "use_item":
            item = args.get("item")
            subject = (
                str(item.get("name", ""))
                if isinstance(item, dict)
                else str(args.get("subject") or args.get("target") or item or "")
            )
            item_messages, affected_messages = _use_item(
                character,
                subject,
                content,
                areas,
                entities,
                party_members or [],
            )
            messages.extend(item_messages)
            for account_id, recipient_messages in affected_messages.items():
                party_effect_messages.setdefault(account_id, []).extend(
                    recipient_messages
                )
        elif action_id == "inspect_inventory":
            contents = ", ".join(f"{count} {item}" for item, count in character.inventory.items())
            messages.append(f"You are carrying {contents}." if contents else "Your inventory is empty.")
        elif action_id == "wait":
            messages.append("You wait and listen to the sounds of the area.")
        elif action_id == "defend":
            combat_state = dict(character.combat_state or {})
            combat_state["defending"] = True
            character.combat_state = combat_state
            messages.append("You take a guarded stance; your next enemy strike will deal half damage.")
        else:
            messages.append(f"You cannot {action_id.replace('_', ' ')} here yet.")

    if not messages and not queued_actions:
        messages.append("You do nothing.")
    return {
        "interpretation": parsed,
        "messages": messages,
        "dialogues": dialogues,
        "profile_account_ids": profile_account_ids,
        "observed_player_equipment": observed_player_equipment,
        "party_effect_messages": party_effect_messages,
        "inventory_view": inventory_view,
        "queued_actions": queued_actions,
        "snapshot": _snapshot(character, content, enemy_spawns_by_location),
    }


def _duration_text(seconds: int) -> str:
    minutes, remainder = divmod(seconds, 60)
    if minutes:
        return f"{minutes} minute{'s' if minutes != 1 else ''} {remainder} second{'s' if remainder != 1 else ''}"
    return f"{remainder} second{'s' if remainder != 1 else ''}"


def _quantity_name(quantity: int, name: str) -> str:
    if quantity == 1:
        return f"1 {name}"
    words = name.split()
    last = words[-1]
    if last.casefold().endswith("y") and len(last) > 1 and last[-2].casefold() not in "aeiou":
        words[-1] = f"{last[:-1]}ies"
    elif last.casefold().endswith(("s", "x", "z", "ch", "sh")):
        words[-1] = f"{last}es"
    else:
        words[-1] = f"{last}s"
    return f"{quantity} {' '.join(words)}"


def _command_subject(arguments: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = arguments.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("id")
        if value:
            return str(value)
    return ""


def _start_gathering(
    character: Any,
    arguments: dict[str, Any],
    areas: dict[str, dict[str, Any]],
    entities: dict[str, dict[str, Any]],
    now: float | None = None,
) -> list[str]:
    subject = _command_subject(arguments, "resource", "subject", "target", "item")
    area = areas.get(character.area_id)
    if area is None:
        return ["You are not in a valid location."]
    resources = [
        entities[entity_id]
        for entity_id in area["resource_ids"]
        if entity_id in entities
    ]
    matches = _matching_entities(subject, resources) if subject else resources
    if len(matches) > 1:
        return [f"Which resource do you mean: {', '.join(item['name'] for item in matches)}?"]
    if not matches:
        return [f"There is no {subject} here to gather." if subject else "Name a resource to gather."]
    resource = matches[0]
    config = resource.get("gathering")
    if not isinstance(config, dict) or not config.get("loot_table"):
        return [f"{resource['name']} is not configured for gathering."]
    current_time = time.time() if now is None else now
    status = _resource_status(character, character.area_id, resource, current_time)
    if not status["available"]:
        remaining = status.get("respawn_seconds_remaining", 0)
        if remaining:
            return [f"{resource['name']} has been depleted. It will return in {_duration_text(remaining)}."]
        return [f"There is nothing left to gather from {resource['name']}."]

    skill = config["skill"]
    levels = _skill_levels(character)
    if levels[skill] < config["skill_level"]:
        return [
            f"You need {SKILL_LABELS[skill]} level {config['skill_level']} "
            f"to gather {resource['name']}."
        ]
    tool_power = 0
    tool_stat = config.get("tool_stat")
    if tool_stat:
        equipment = {**DEFAULT_EQUIPMENT, **(character.equipment or {})}
        tool = entities.get(equipment.get("right_hand", ""))
        raw_power = (tool or {}).get("attributes", {}).get(tool_stat)
        if (
            tool is None
            or tool.get("type") != "weapon"
            or not isinstance(raw_power, int)
            or isinstance(raw_power, bool)
            or raw_power < config["minimum_tool_power"]
        ):
            return [
                f"You need a right-hand tool with at least "
                f"{config['minimum_tool_power']} {tool_stat} power to gather {resource['name']}."
            ]
        tool_power = raw_power
    duration = max(1, ceil(config["health"] * 60 / (levels[skill] + tool_power)))
    character.gathering_state = {
        "resource_id": resource["id"],
        "resource_name": resource["name"],
        "location_id": character.area_id,
        "skill": skill,
        "duration_seconds": duration,
        "started_at": current_time,
        "completes_at": current_time + duration,
    }
    return [
        f"You begin gathering {resource['name']}. It will take about "
        f"{_duration_text(duration)}. Type stop to cancel."
    ]


def _cancel_gathering(character: Any) -> str:
    state = getattr(character, "gathering_state", None)
    if not isinstance(state, dict):
        return "You are not gathering anything."
    character.gathering_state = None
    return f"You stop gathering {state['resource_name']}. Nothing is collected."


def _complete_gathering(
    character: Any,
    content: dict[str, Any],
    now: float | None = None,
) -> list[str]:
    state = getattr(character, "gathering_state", None)
    if not isinstance(state, dict):
        return []
    current_time = time.time() if now is None else now
    if float(state.get("completes_at", float("inf"))) > current_time:
        return []
    areas = _location_map(content)
    entities = {entity["id"]: entity for entity in content.get("entities", [])}
    resource = entities.get(state.get("resource_id"))
    area = areas.get(state.get("location_id"))
    if character.area_id != state.get("location_id"):
        character.gathering_state = None
        return ["Your gathering is interrupted because you left the location."]
    if (
        resource is None
        or resource.get("type") != "resource"
        or area is None
        or resource["id"] not in area["resource_ids"]
        or not isinstance(resource.get("gathering"), dict)
    ):
        character.gathering_state = None
        return ["Your gathering attempt ends because that resource is no longer available."]

    config = resource["gathering"]
    key = _resource_state_key(state["location_id"], resource["id"])
    resource_state = dict(getattr(character, "resource_state", None) or {})
    node_state = dict(resource_state.get(key, {}))
    respawn_at = node_state.get("respawn_at")
    if isinstance(respawn_at, (int, float)) and respawn_at > current_time:
        character.gathering_state = None
        return [f"{resource['name']} has already been depleted."]

    inventory = dict(character.inventory or {})
    drop_chance_bonus, gathering_yield_bonus = _luck_bonuses(character, current_time)
    messages = [f"You finish gathering {resource['name']}."]
    gathered: list[str] = []
    for drop in config.get("loot_table", []):
        chance = min(1.0, drop["chance"] * (1 + drop_chance_bonus / 100))
        if combat_rng.random() >= chance:
            continue
        quantity = combat_rng.randint(
            drop["minimum_quantity"],
            drop["maximum_quantity"],
        )
        if gathering_yield_bonus:
            quantity = ceil(quantity * (1 + gathering_yield_bonus / 100))
        inventory[drop["item_id"]] = inventory.get(drop["item_id"], 0) + quantity
        item = entities.get(drop["item_id"])
        item_name = item["name"] if item else drop["item_id"].replace("_", " ").title()
        gathered.append(_quantity_name(quantity, item_name))
        _record_quest_event(character, content, "collect", drop["item_id"], quantity)
    if gathered:
        messages.append(f"You gather {', '.join(gathered)}.")
    else:
        messages.append("You find nothing this time.")
    character.inventory = inventory
    resource_state[key] = {
        "health": 0,
        "respawn_at": current_time + config["respawn_seconds"],
    }
    character.resource_state = resource_state
    character.gathering_state = None
    messages.extend(_award_skill_experience(character, config["skill"], config["skill_level"]))
    return messages


def _craft(
    character: Any,
    arguments: dict[str, Any],
    content: dict[str, Any],
    areas: dict[str, dict[str, Any]],
    entities: dict[str, dict[str, Any]],
) -> list[str]:
    subject = _command_subject(
        arguments, "recipe", "product", "item", "subject", "target"
    )
    recipes = content.get("recipes", [])
    matches = _matching_entities(subject, recipes) if subject else recipes
    if len(matches) > 1:
        return [f"Which recipe do you mean: {', '.join(item['name'] for item in matches)}?"]
    if not matches:
        return [f"There is no recipe for {subject}." if subject else "Name something to craft."]
    recipe = matches[0]
    area = areas.get(character.area_id)
    if area is None:
        return ["You are not in a valid location."]
    station_id = recipe.get("station_id")
    if station_id and station_id not in area["object_ids"]:
        station_name = entities.get(station_id, {}).get("name", station_id.replace("_", " "))
        return [f"You need to be at {station_name} to craft {recipe['name']}."]
    levels = _skill_levels(character)
    skill = recipe.get("skill")
    skill_level = int(recipe.get("skill_level", 0))
    if skill and levels.get(skill, 1) < skill_level:
        return [f"You need {SKILL_LABELS[skill]} level {skill_level} to craft {recipe['name']}."]
    inventory = dict(character.inventory or {})
    missing = [
        f"{ingredient['quantity'] - inventory.get(ingredient['item_id'], 0)} "
        f"{entities.get(ingredient['item_id'], {}).get('name', ingredient['item_id'])}"
        for ingredient in recipe["ingredients"]
        if inventory.get(ingredient["item_id"], 0) < ingredient["quantity"]
    ]
    if missing:
        return [f"You are missing {', '.join(missing)} to craft {recipe['name']}."]
    for ingredient in recipe["ingredients"]:
        inventory[ingredient["item_id"]] -= ingredient["quantity"]
        if inventory[ingredient["item_id"]] == 0:
            del inventory[ingredient["item_id"]]
    output_id = recipe["output_item_id"]
    inventory[output_id] = inventory.get(output_id, 0) + recipe["output_quantity"]
    character.inventory = inventory
    _record_quest_event(character, content, "collect", output_id, recipe["output_quantity"])
    output = entities.get(output_id)
    output_name = output["name"] if output else output_id.replace("_", " ").title()
    messages = [
        f"You craft {recipe['output_quantity']} {output_name}"
        f"{'' if recipe['output_quantity'] == 1 else 's'}."
    ]
    if skill:
        messages.extend(_award_skill_experience(character, skill, max(1, skill_level)))
    return messages


def _apply_item_effect(
    character: Any,
    effect: dict[str, Any],
    entities: dict[str, dict[str, Any]],
    now: float,
) -> str:
    kind = effect["type"]
    if kind == "heal":
        base_stats = {**PLAYER_BASE_STATS, **(character.combat_stats or {})}
        stats = _effective_stats(character, entities, now)
        previous_health = base_stats["health"]
        if effect["mode"] == "full":
            base_stats["health"] = base_stats["max_health"]
        else:
            restored = (
                int(effect["amount"])
                if effect["mode"] == "fixed"
                else ceil(stats["max_health"] * effect["amount"] / 100)
            )
            base_stats["health"] = min(
                stats["max_health"], previous_health + restored
            )
        _set_current_health(character, base_stats["health"])
        restored = base_stats["health"] - previous_health
        total_health = base_stats["health"] + _temporary_health(character, now)
        return f"restore {restored} health ({total_health}/{stats['max_health']})"
    _apply_timed_effect(character, effect, now)
    if kind == "stat_buff":
        return f"boost {effect['stat']} for {_duration_text(effect['duration_seconds'])}"
    if kind == "shield":
        return f"grant a {_duration_text(effect['duration_seconds'])} shield"
    if kind == "luck":
        return f"improve your luck for {_duration_text(effect['duration_seconds'])}"
    return "have no effect"


def _use_item(
    character: Any,
    subject: str,
    content: dict[str, Any],
    areas: dict[str, dict[str, Any]],
    entities: dict[str, dict[str, Any]],
    party_members: Sequence[Any],
    now: float | None = None,
) -> tuple[list[str], dict[str, list[str]]]:
    current_time = time.time() if now is None else now
    inventory = dict(character.inventory or {})
    usable_items = [
        entity
        for entity in entities.values()
        if entity["type"] == "item"
        and inventory.get(entity["id"], 0) > 0
        and (entity.get("item_use") or {}).get("effects")
    ]
    matches = _matching_items(subject, usable_items) if subject else []
    if len(matches) > 1:
        return [f"Which item do you mean: {', '.join(item['name'] for item in matches)}?"], {}
    if matches:
        item = matches[0]
        use_config = item["item_use"]
        source_location = character.area_id
        if use_config.get("target_scope") == "party":
            targets = [
                target
                for target in party_members
                if target.area_id == source_location
            ]
            if all(target.account_id != character.account_id for target in targets):
                targets.append(character)
        else:
            targets = [character]
        unique_targets: dict[str, Any] = {
            target.account_id: target for target in targets
        }
        party_messages: dict[str, list[str]] = {}
        actor_effects: list[str] = []
        teleport_effects = [
            effect
            for effect in use_config["effects"]
            if effect["type"] == "teleport"
        ]
        for target in unique_targets.values():
            effects = [
                _apply_item_effect(target, effect, entities, current_time)
                for effect in use_config["effects"]
                if effect["type"] != "teleport"
            ]
            for effect in teleport_effects:
                destination = effect["destination_area_id"]
                if (
                    target.area_id != destination
                    and isinstance(getattr(target, "gathering_state", None), dict)
                ):
                    target.gathering_state = None
                    effects.append("stop gathering")
                target.area_id = destination
                effects.append(f"travel to {areas[destination]['name']}")
            if target.account_id == character.account_id:
                actor_effects = effects
            else:
                party_messages[target.account_id] = [
                    f"You receive the effects of {character.name}'s {item['name']}: "
                    f"{', '.join(effects)}."
                ]
        if use_config.get("consume_on_use", True):
            inventory[item["id"]] -= 1
            if inventory[item["id"]] <= 0:
                del inventory[item["id"]]
            character.inventory = inventory
        recipient_count = max(0, len(unique_targets) - 1)
        if use_config.get("target_scope") == "party":
            result = [
                f"You use {item['name']}; its effects reach you and "
                f"{recipient_count} online party member{'s' if recipient_count != 1 else ''} here."
            ]
        else:
            result = [f"You use {item['name']}."]
        result.extend(f"The effects {effect}." for effect in actor_effects)
        return result, party_messages

    area = areas.get(character.area_id)
    if area is None:
        return ["You are not in a valid location."], {}
    environment_objects = [
        entities[entity_id]
        for entity_id in area["object_ids"]
        if entity_id in entities
    ]
    object_matches = _matching_entities(subject, environment_objects) if subject else []
    if len(object_matches) > 1:
        return [
            f"Which object do you mean: {', '.join(entity['name'] for entity in object_matches)}?"
        ], {}
    if not object_matches:
        return [
            f"There is no {subject} here to use."
            if subject
            else "Name an item or object to use."
        ], {}
    target = object_matches[0]
    effect = target.get("interaction_effect")
    if effect == "restore_health":
        stats = _effective_stats(character, entities, current_time)
        _set_current_health(character, stats["max_health"])
        stats["health"] = stats["max_health"]
        total_health = stats["health"] + _temporary_health(character, current_time)
        return [
            f"You rest at {target['name']} and restore your health to full "
            f"({total_health}/{stats['max_health']})."
        ], {}
    if effect == "set_respawn":
        character.respawn_area_id = character.area_id
        return [
            f"You set {target['name']} in {area['name']} as your respawn point."
        ], {}
    return [f"{target['name']} has no available interaction."], {}


def _normalize_npc_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    for article in ("the ", "a ", "an "):
        if normalized.startswith(article):
            normalized = normalized[len(article):]
            break
    return normalized


def _positive_stat(entity: dict[str, Any], key: str, default: int) -> int:
    value = entity.get("attributes", {}).get(key, default)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else default


def attack_initiative_relation(character: Any, action_id: str, enemy: dict[str, Any]) -> int:
    entities = {
        entity["id"]: entity for entity in world_content_dict().get("entities", [])
    }
    stats = _effective_stats(character, entities)
    player_speed = stats["speed"] * ATTACK_INITIATIVE_MULTIPLIERS[action_id]
    enemy_speed = _positive_stat(enemy, "speed", 0)
    return (player_speed > enemy_speed) - (player_speed < enemy_speed)


def roll_d20() -> int:
    return combat_rng.randint(1, 20)


def _matching_entities(
    reference: str, candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    normalized = _normalize_npc_name(reference)
    if not normalized:
        return []
    return [
        entity
        for entity in candidates
        if normalized in _normalize_npc_name(entity["name"])
        or _normalize_npc_name(entity["name"]) in normalized
        or normalized == entity["id"].replace("_", " ")
    ]


def _matching_items(reference: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = _normalize_npc_name(reference)
    exact_matches = [
        entity
        for entity in candidates
        if normalized == _normalize_npc_name(entity["name"])
        or normalized == entity["id"].replace("_", " ")
    ]
    return exact_matches or _matching_entities(reference, candidates)


def _reward_enemy_defeat(
    character: Any,
    enemy: dict[str, Any],
    entities: dict[str, dict[str, Any]],
    content: dict[str, Any] | None = None,
) -> list[str]:
    experience_reward = _positive_stat(enemy, "experience", 0)
    messages = award_experience(character, experience_reward)
    if experience_reward == 0:
        messages.append("You gain 0 experience.")
    inventory = dict(character.inventory or {})
    dropped_items = False
    drop_chance_bonus, _ = _luck_bonuses(character)
    for drop in enemy.get("loot_table", []):
        chance = min(1.0, drop["chance"] * (1 + drop_chance_bonus / 100))
        if combat_rng.random() >= chance:
            continue
        quantity = combat_rng.randint(
            drop["minimum_quantity"],
            drop["maximum_quantity"],
        )
        inventory[drop["item_id"]] = inventory.get(drop["item_id"], 0) + quantity
        item_name = entities[drop["item_id"]]["name"]
        dropped_items = True
        if content is not None:
            _record_quest_event(
                character,
                content,
                "collect",
                drop["item_id"],
                quantity,
            )
        messages.append(
            f"Loot: {quantity} {item_name}{'' if quantity == 1 else 's'}."
        )
    currencies = {
        currency["id"]: currency for currency in (content or {}).get("currencies", [])
    }
    dropped_currency = False
    for drop in enemy.get("currency_drops", []):
        if drop["currency_id"] not in currencies:
            continue
        chance = min(1.0, drop["chance"] * (1 + drop_chance_bonus / 100))
        if combat_rng.random() >= chance:
            continue
        amount = combat_rng.randint(drop["minimum_amount"], drop["maximum_amount"])
        _add_currency(character, drop["currency_id"], amount)
        dropped_currency = True
        messages.append(f"Currency: {_currency_text(currencies, drop['currency_id'], amount)}.")
    if not dropped_items and not dropped_currency:
        messages.append("No items dropped.")
    character.inventory = inventory
    return messages


def award_enemy_defeat(
    character: Any,
    enemy_id: str,
    content: dict[str, Any] | None = None,
) -> list[str]:
    current_content = content or world_content_dict()
    entities = {entity["id"]: entity for entity in current_content["entities"]}
    enemy = entities.get(enemy_id)
    if enemy is None:
        return []
    messages = _reward_enemy_defeat(character, enemy, entities, current_content)
    _record_quest_event(character, current_content, "kill", enemy_id)
    return messages


def resolve_attack_target_id(
    character: Any,
    occurrence: dict[str, Any],
    enemy_spawns_by_location: dict[str, list[dict[str, Any]]],
) -> tuple[str | None, str | None]:
    content = world_content_dict()
    entities = {entity["id"]: entity for entity in content["entities"]}
    area = _location_map(content).get(character.area_id)
    if area is None:
        return None, "You are not in a valid area."
    enemies = []
    for spawn in enemy_spawns_by_location.get(character.area_id, []):
        enemy = entities.get(spawn["enemy_id"])
        if not spawn["is_alive"] or enemy is None or enemy["type"] != "enemy":
            continue
        enemies.append({
            **enemy,
            "id": spawn["id"],
            "entity_id": spawn["enemy_id"],
            "health": spawn["health"],
        })
    enemies = [enemy for enemy in enemies if enemy["health"] > 0]
    arguments = occurrence["arguments"]
    subject = str(arguments.get("subject", ""))
    if subject:
        matches = _matching_entities(subject, enemies)
        if len(matches) > 1 and len({enemy["entity_id"] for enemy in matches}) == 1:
            return matches[0]["id"], None
        if len(matches) == 1:
            return matches[0]["id"], None
        if matches:
            return None, f"Which enemy do you mean: {', '.join(enemy['name'] for enemy in matches)}?"
        return None, f"There is no {subject} here to attack."
    target_id = (character.combat_state or {}).get("target_id")
    target = next((enemy for enemy in enemies if enemy["id"] == target_id), None)
    if target is None:
        return None, "Name an enemy here to attack."
    return target["id"], None


def resolve_combat_occurrence(
    character: Any,
    occurrence: dict[str, Any],
    enemy_spawns_by_location: dict[str, list[dict[str, Any]]],
    command_text: str | None = None,
) -> dict[str, Any]:
    content = world_content_dict()
    areas = _location_map(content)
    entities = {entity["id"]: entity for entity in content["entities"]}
    action_id = occurrence["action_id"]
    if action_id == "defend":
        state = dict(character.combat_state or {})
        state["defending"] = True
        character.combat_state = state
        return {
            "messages": ["You take a guarded stance; damage from the immediate enemy response is halved."],
            "defeated_enemy_id": None,
        }
    if action_id == "wait":
        return {
            "messages": ["You wait and listen to the sounds of the area."],
            "defeated_enemy_id": None,
        }
    if action_id not in {"attack", "light_attack", "heavy_attack"}:
        if command_text is None:
            return {
                "messages": ["That action cannot be used in combat."],
                "defeated_enemy_id": None,
            }
        result = resolve_command(
            command_text,
            character,
            enemy_spawns_by_location=enemy_spawns_by_location,
            selected_occurrence_ids={occurrence["occurrence_id"]},
            combat_context=True,
        )
        return {
            **{
                key: result[key]
                for key in (
                    "dialogues",
                    "profile_account_ids",
                    "observed_player_equipment",
                    "inventory_view",
                )
                if key in result
            },
            "messages": result["messages"],
            "defeated_enemy_id": None,
        }

    target_spawn_id = occurrence.get("target_spawn_id")
    was_alive = any(
        spawn["id"] == target_spawn_id and spawn["is_alive"]
        for spawn in enemy_spawns_by_location.get(character.area_id, [])
    )
    messages = _attack(
        character,
        areas,
        entities,
        occurrence,
        content,
        enemy_spawns_by_location,
        resolve_retaliation=False,
        award_rewards=False,
    )
    defeated_enemy_id = None
    if was_alive:
        spawn = next(
            (
                candidate
                for candidate in enemy_spawns_by_location.get(character.area_id, [])
                if candidate["id"] == target_spawn_id
            ),
            None,
        )
        if spawn is not None and not spawn["is_alive"]:
            defeated_enemy_id = spawn["enemy_id"]
    if defeated_enemy_id is None:
        target_enemy = entities.get(
            next(
                (
                    spawn["enemy_id"]
                    for spawn in enemy_spawns_by_location.get(character.area_id, [])
                    if spawn["id"] == target_spawn_id
                ),
                "",
            )
        )
        if target_enemy is not None and target_enemy.get("behavior", "neutral") == "passive":
            messages.append(f"{target_enemy['name']} does not fight back.")
    return {"messages": messages, "defeated_enemy_id": defeated_enemy_id}


def _equip(
    character: Any, entities: dict[str, dict[str, Any]], arguments: dict[str, Any]
) -> str:
    item = arguments.get("item", {})
    item_name = item.get("name", "") if isinstance(item, dict) else str(item)
    slot = arguments.get("slot")
    item_key = _normalize_npc_name(item_name)
    if item_key == "fist":
        if slot not in {None, "right_hand"}:
            return "Fists can only be readied in your right hand."
        slot = slot or "right_hand"
        equipment = {**DEFAULT_EQUIPMENT, **(character.equipment or {})}
        equipment["left_hand"] = "" if equipment["left_hand"] == "fist" else equipment["left_hand"]
        equipment[slot] = "fist"
        character.equipment = equipment
        return f"You ready your fist in your {slot.replace('_', ' ')}."
    if not item_name:
        return "Name an item you are carrying to equip."
    matches = _matching_items(item_name, list(entities.values()))
    if len(matches) != 1:
        return f"There is no unique item named {item_name}."
    item = matches[0]
    item_slots = EQUIPMENT_TYPE_SLOTS.get(item["type"])
    if item_slots is None:
        return f"{item['name']} cannot be equipped; this item type has no equipment definition."
    if (character.inventory or {}).get(item["id"], 0) < 1:
        return f"You are not carrying a {item['name']}."
    slot = slot or next(iter(sorted(item_slots)))
    if slot not in EQUIPMENT_SLOTS:
        return f"Choose an equipment slot: {', '.join(EQUIPMENT_SLOTS)}."
    if slot not in item_slots:
        return f"{item['name']} cannot be equipped in your {slot.replace('_', ' ')}."
    equipment = {**DEFAULT_EQUIPMENT, **(character.equipment or {})}
    if equipment["left_hand"] == "fist":
        equipment["left_hand"] = ""
    equipment[slot] = item["id"]
    character.equipment = equipment
    return f"You equip {item['name']} in your {slot.replace('_', ' ')}."


def _unequip(
    character: Any, entities: dict[str, dict[str, Any]], arguments: dict[str, Any]
) -> str:
    equipment = {**DEFAULT_EQUIPMENT, **(character.equipment or {})}
    item = arguments.get("item", {})
    item_name = item.get("name", "") if isinstance(item, dict) else str(item)
    slot = arguments.get("slot")
    if slot not in {None, *EQUIPMENT_SLOTS}:
        return f"Choose an equipment slot: {', '.join(EQUIPMENT_SLOTS)}."
    if item_name:
        matches = _matching_items(item_name, list(entities.values()))
        if len(matches) != 1:
            return f"There is no unique item named {item_name}."
        equipped_slots = [
            equipped_slot
            for equipped_slot, item_id in equipment.items()
            if item_id == matches[0]["id"]
        ]
        if slot:
            equipped_slots = [equipped_slot for equipped_slot in equipped_slots if equipped_slot == slot]
        if len(equipped_slots) != 1:
            return (
                f"{matches[0]['name']} is not equipped there."
                if slot
                else f"{matches[0]['name']} is not equipped."
                if not equipped_slots
                else f"{matches[0]['name']} is equipped in multiple slots; specify a slot."
            )
        slot = equipped_slots[0]
    if slot is None:
        return "Choose an equipment slot or name an equipped item to unequip."
    previous = equipment[slot]
    if not previous or (previous == "fist" and slot not in {"left_hand", "right_hand"}):
        return f"Nothing is equipped in your {slot.replace('_', ' ')}."
    equipment[slot] = "fist" if slot == "right_hand" else ""
    character.equipment = equipment
    previous_name = entities.get(previous, {}).get("name", "Fist" if previous == "fist" else previous)
    return f"You unequip {previous_name} from your {slot.replace('_', ' ')}."


def _attack(
    character: Any,
    areas: dict[str, dict[str, Any]],
    entities: dict[str, dict[str, Any]],
    occurrence: dict[str, Any],
    content: dict[str, Any],
    enemy_spawns_by_location: dict[str, list[dict[str, Any]]] | None = None,
    *,
    resolve_retaliation: bool = True,
    award_rewards: bool = True,
) -> list[str]:
    area = areas[character.area_id]
    spawn_instances: dict[str, dict[str, Any]] = {}
    if enemy_spawns_by_location is None:
        enemies = [entities[enemy_id] for enemy_id in area["enemy_ids"]]
    else:
        enemies = []
        for spawn in enemy_spawns_by_location.get(character.area_id, []):
            enemy = entities.get(spawn["enemy_id"])
            if not spawn["is_alive"] or enemy is None or enemy["type"] != "enemy":
                continue
            enemy_instance = {
                **enemy,
                "id": spawn["id"],
                "entity_id": spawn["enemy_id"],
                "health": spawn["health"],
            }
            enemies.append(enemy_instance)
            spawn_instances[spawn["id"]] = spawn
    available_enemies = [
        enemy
        for enemy in enemies
        if (
            enemy["health"] > 0
            if enemy["id"] in spawn_instances
            else (character.combat_state or {}).get("enemy_health", {}).get(
                enemy["id"], _positive_stat(enemy, "health", 1)
            ) > 0
        )
    ]
    arguments = occurrence["arguments"]
    target_id = (character.combat_state or {}).get("target_id")
    subject = arguments.get("subject", "")
    planned_spawn_id = occurrence.get("target_spawn_id")
    if planned_spawn_id:
        target = next(
            (enemy for enemy in available_enemies if enemy["id"] == planned_spawn_id),
            None,
        )
        if target is None:
            return ["That enemy is no longer alive here."]
    elif subject:
        matches = _matching_entities(subject, available_enemies)
        if len(matches) > 1 and len({enemy.get("entity_id", enemy["id"]) for enemy in matches}) == 1:
            target = matches[0]
        elif len(matches) != 1:
            if matches:
                return [f"Which enemy do you mean: {', '.join(enemy['name'] for enemy in matches)}?"]
            return [f"There is no {subject} here to attack."]
        else:
            target = matches[0]
    else:
        target = next(
            (
                enemy
                for enemy in available_enemies
                if enemy["id"] == target_id or enemy.get("entity_id") == target_id
            ),
            None,
        )
        if target is None:
            return ["Name an enemy here to attack."]

    is_spawn_instance = target["id"] in spawn_instances
    spawn = spawn_instances.get(target["id"])
    enemy = entities.get(target.get("entity_id", target["id"]), target)
    stats = _effective_stats(character, entities)
    state = {
        **(character.combat_state or {}),
        "target_id": target["id"],
        "enemy_health": dict((character.combat_state or {}).get("enemy_health", {})),
    }
    max_enemy_health = _positive_stat(enemy, "health", 1)
    enemy_hp = (
        min(spawn["health"], max_enemy_health)
        if spawn is not None
        else min(state["enemy_health"].get(target["id"], max_enemy_health), max_enemy_health)
    )
    equipment = {**DEFAULT_EQUIPMENT, **(character.equipment or {})}
    inventory = character.inventory or {}
    multipliers = {"attack": 1.0, "light_attack": 0.75, "heavy_attack": 1.5}
    multiplier = multipliers[occurrence["action_id"]]
    messages: list[str] = []

    for hand in ("right_hand",):
        weapon_id = equipment[hand]
        weapon = entities.get(weapon_id) if weapon_id != "fist" else None
        if weapon_id != "fist" and (
            weapon is None
            or weapon["type"] != "weapon"
            or inventory.get(weapon_id, 0) < 1
        ):
            weapon = None
            equipment[hand] = "fist"
        weapon_damage = _positive_stat(weapon, "damage", 0) if weapon else 0
        strength = max(1, round((stats["attack"] + weapon_damage) * multiplier))
        damage = max(1, strength - _positive_stat(target, "defense", 0))
        enemy_hp = max(0, enemy_hp - damage)
        if spawn is not None:
            spawn["health"] = enemy_hp
        else:
            state["enemy_health"][target["id"]] = enemy_hp
        weapon_name = weapon["name"] if weapon else "fist"
        messages.append(
            f"You strike {target['name']} with your {hand.replace('_', ' ')} {weapon_name} "
            f"for {damage} damage ({enemy_hp}/{max_enemy_health} health)."
        )
        if enemy_hp == 0:
            break

    character.equipment = equipment
    if enemy_hp == 0:
        state["target_id"] = None
        if spawn is not None:
            spawn["is_alive"] = False
        character.combat_state = state
        messages.append(f"{target['name']} is defeated.")
        if award_rewards:
            messages.extend(_reward_enemy_defeat(character, enemy, entities, content))
            _record_quest_event(character, content, "kill", enemy["id"])
        return messages

    character.combat_state = state
    if not resolve_retaliation:
        return messages
    if enemy.get("behavior", "neutral") == "passive":
        messages.append(f"{target['name']} does not fight back.")
        return messages
    messages.extend(enemy_strike(character, enemy, areas, entities=entities))
    if not is_spawn_instance and character.area_id != area["id"]:
        state = dict(character.combat_state or {})
        state["enemy_health"] = dict(state.get("enemy_health", {}))
        state["enemy_health"][target["id"]] = max_enemy_health
        character.combat_state = state
    return messages


def enemy_strike(
    character: Any,
    enemy: dict[str, Any],
    areas: dict[str, dict[str, Any]],
    *,
    consume_defending: bool = True,
    entities: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    stats = _effective_stats(character, entities)
    die_sides = enemy["attack_die_sides"]
    roll = combat_rng.randint(1, die_sides)
    incoming_damage = max(
        0,
        _positive_stat(enemy, "attack", 0) + roll - stats["defense"],
    )
    state = dict(character.combat_state or {})
    if state.get("defending", False):
        incoming_damage //= 2
    active_effects = _live_effects(character)
    shield_messages: list[str] = []
    retained_effects = []
    buffer_effects = []
    for effect in active_effects:
        if effect.get("type") != "shield":
            retained_effects.append(effect)
            continue
        if effect.get("mode") == "damage_reduction":
            incoming_damage = max(0, incoming_damage - int(effect["amount"]))
            retained_effects.append(effect)
            continue
        buffer_effects.append(effect)
    for mode in ("damage_pool", "temporary_health"):
        for effect in buffer_effects:
            if effect.get("mode") != mode:
                continue
            remaining = max(0, int(effect.get("remaining", effect["amount"])))
            absorbed = min(incoming_damage, remaining)
            if absorbed:
                incoming_damage -= absorbed
                remaining -= absorbed
                shield_messages.append(
                    (
                        f"Your temporary health absorbs {absorbed} damage."
                        if mode == "temporary_health"
                        else f"Your damage pool absorbs {absorbed} damage."
                    )
                )
            if remaining > 0:
                retained_effects.append({**effect, "remaining": remaining})
    character.active_effects = retained_effects
    if consume_defending:
        state.pop("defending", None)
    stats["health"] = max(0, stats["health"] - incoming_damage)
    _set_current_health(character, stats["health"])
    displayed_health = stats["health"] + _temporary_health(character)
    messages = [
        f"{enemy['name']} rolls D{die_sides} ({roll}) and hits you for "
        f"{incoming_damage} damage ({displayed_health}/{stats['max_health']} health)."
    ]
    messages.extend(shield_messages)
    if stats["health"] == 0:
        saved_respawn_area = getattr(character, "respawn_area_id", None)
        starting_area = starting_location(character.species)
        respawn_area = (
            saved_respawn_area
            if saved_respawn_area in areas
            else starting_area
        )
        stale_respawn = saved_respawn_area is not None and saved_respawn_area not in areas
        if stale_respawn:
            character.respawn_area_id = None
        character.area_id = respawn_area
        character.gathering_state = None
        stats["health"] = stats["max_health"]
        _set_current_health(character, stats["health"])
        state["target_id"] = None
        stale_notice = (
            "Your saved respawn location is no longer available. "
            if stale_respawn
            else ""
        )
        messages.append(
            f"You are defeated. {stale_notice}You awaken in {areas[respawn_area]['name']} "
            "with full health."
        )
    character.combat_state = state
    return messages


def _expression(value: dict[str, Any]) -> Any:
    from plight_nlp_inspector import Expression

    return Expression(
        operator=value["operator"],
        occurrence_id=value.get("occurrence_id"),
        children=tuple(_expression(child) for child in value.get("children", [])),
    )
