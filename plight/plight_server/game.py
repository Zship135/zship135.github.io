from __future__ import annotations

from itertools import product
import random
import re
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
DEFAULT_EQUIPMENT = {"left_hand": "fist", "right_hand": "fist"}
combat_rng = random.SystemRandom()


def initial_area(species: str) -> str:
    return starting_location(species)


def _location_map(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {location["id"]: location for location in content["locations"]}


def _snapshot(character: Any, content: dict[str, Any]) -> dict[str, Any]:
    areas = _location_map(content)
    area = areas[character.area_id]
    entities = {entity["id"]: entity for entity in content["entities"]}
    stats = {**PLAYER_BASE_STATS, **(character.combat_stats or {})}
    equipment = {**DEFAULT_EQUIPMENT, **(character.equipment or {})}
    combat_state = character.combat_state or {}
    enemy_health = combat_state.get("enemy_health", {})

    def visible_entities(entity_ids: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "id": entity_id,
                "name": entities[entity_id]["name"],
                "description": entities[entity_id]["description"],
                "type": entities[entity_id]["type"],
                **(
                    {"race": entities[entity_id]["race"]}
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
    enemies = visible_entities(area["enemy_ids"])
    visible_npc_ids = [
        entity_id
        for entity_id in area["npc_ids"]
        if character.species in entities[entity_id]["present_for"]
    ]
    npcs = visible_entities(visible_npc_ids)
    objects = visible_entities(area["object_ids"])
    resources = visible_entities(area["resource_ids"])
    ambience_lines = list(area["ambience"])
    for entity_id in (*area["enemy_ids"], *visible_npc_ids):
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
            "stats": stats,
            "equipment": equipment,
        },
        "area": {
            "id": character.area_id,
            "name": area["name"],
            "description": area["description"],
            "exits": [key for key in ("north", "south", "east", "west") if key in exits],
            "exit_destinations": {
                direction: areas[destination]["name"]
                for direction, destination in exits.items()
            },
            "enemies": enemies,
            "npcs": npcs,
            "objects": objects,
            "resources": resources,
            "ambience_lines": ambience_lines,
        },
        "atmosphere": atmosphere_data,
    }


def snapshot(character: Any) -> dict[str, Any]:
    return _snapshot(character, world_content_dict())


def resolve_command(text: str, character: Any) -> dict[str, Any]:
    content = world_content_dict()
    areas = _location_map(content)
    entities = {entity["id"]: entity for entity in content["entities"]}
    parsed = parse_local(text)
    if parsed["status"] != "selected":
        return {
            "interpretation": parsed,
            "messages": ["I could not find a supported action in that sentence."],
            "dialogues": [],
            "snapshot": _snapshot(character, content),
        }

    occurrences = parsed["occurrences"]
    if len(occurrences) > 8:
        return {
            "interpretation": parsed,
            "messages": ["A single command can contain at most eight action occurrences."],
            "dialogues": [],
            "snapshot": _snapshot(character, content),
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
            "snapshot": _snapshot(character, content),
        }

    selected = random.SystemRandom().choice(assignments)
    selected_ids = {key for key, value in selected.items() if value}
    parsed["selection_resolved"] = True
    parsed["selected_occurrences"] = sorted(
        selected_ids, key=lambda item: occurrence_ids.index(item)
    )
    messages: list[str] = []
    dialogues: list[dict[str, Any]] = []
    for occurrence in occurrences:
        if occurrence["occurrence_id"] not in selected_ids:
            continue
        action_id = occurrence["action_id"]
        args = occurrence["arguments"]
        if action_id == "observe":
            messages.append(areas[character.area_id]["description"])
        elif action_id == "travel":
            direction = str(args.get("direction", "")).casefold()
            destination = areas[character.area_id]["exits"].get(direction)
            if destination:
                character.area_id = destination
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
            messages.extend(_attack(character, areas, entities, occurrence))
        elif action_id == "use_item" and occurrence["phrase"].casefold() == "equip":
            messages.append(_equip(character, entities, args))
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

    if not messages:
        messages.append("You do nothing.")
    return {
        "interpretation": parsed,
        "messages": messages,
        "dialogues": dialogues,
        "snapshot": _snapshot(character, content),
    }


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


def _equip(
    character: Any, entities: dict[str, dict[str, Any]], arguments: dict[str, Any]
) -> str:
    item = arguments.get("item", {})
    item_name = item.get("name", "") if isinstance(item, dict) else str(item)
    slot = arguments.get("slot")
    if slot not in {"left_hand", "right_hand"}:
        return "Choose either your left hand or right hand."
    if _normalize_npc_name(item_name) == "fist":
        equipment = {**DEFAULT_EQUIPMENT, **(character.equipment or {})}
        equipment[slot] = "fist"
        character.equipment = equipment
        return f"You ready your fist in your {slot.replace('_', ' ')}."
    matches = _matching_entities(
        item_name,
        [entity for entity in entities.values() if entity["type"] == "weapon"],
    )
    if len(matches) != 1:
        return f"There is no unique weapon named {item_name}."
    weapon = matches[0]
    if (character.inventory or {}).get(weapon["id"], 0) < 1:
        return f"You are not carrying a {weapon['name']}."
    equipment = {**DEFAULT_EQUIPMENT, **(character.equipment or {})}
    equipment[slot] = weapon["id"]
    character.equipment = equipment
    return f"You equip {weapon['name']} in your {slot.replace('_', ' ')}."


def _attack(
    character: Any,
    areas: dict[str, dict[str, Any]],
    entities: dict[str, dict[str, Any]],
    occurrence: dict[str, Any],
) -> list[str]:
    area = areas[character.area_id]
    enemies = [entities[enemy_id] for enemy_id in area["enemy_ids"]]
    available_enemies = [
        enemy
        for enemy in enemies
        if (character.combat_state or {}).get("enemy_health", {}).get(
            enemy["id"], _positive_stat(enemy, "health", 1)
        ) > 0
    ]
    arguments = occurrence["arguments"]
    target_id = (character.combat_state or {}).get("target_id")
    subject = arguments.get("subject", "")
    if subject:
        matches = _matching_entities(subject, available_enemies)
        if len(matches) != 1:
            if matches:
                return [f"Which enemy do you mean: {', '.join(enemy['name'] for enemy in matches)}?"]
            return [f"There is no {subject} here to attack."]
        target = matches[0]
    else:
        target = next((enemy for enemy in available_enemies if enemy["id"] == target_id), None)
        if target is None:
            return ["Name an enemy here to attack."]

    stats = {**PLAYER_BASE_STATS, **(character.combat_stats or {})}
    state = {
        **(character.combat_state or {}),
        "target_id": target["id"],
        "enemy_health": dict((character.combat_state or {}).get("enemy_health", {})),
    }
    max_enemy_health = _positive_stat(target, "health", 1)
    enemy_hp = min(state["enemy_health"].get(target["id"], max_enemy_health), max_enemy_health)
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
        character.combat_state = state
        messages.append(f"{target['name']} is defeated.")
        return messages

    die_sides = target["attack_die_sides"]
    roll = combat_rng.randint(1, die_sides)
    enemy_attack = _positive_stat(target, "attack", 0)
    incoming_damage = max(0, enemy_attack + roll - stats["defense"])
    if state.pop("defending", False):
        incoming_damage //= 2
    stats["health"] = max(0, stats["health"] - incoming_damage)
    character.combat_stats = stats
    messages.append(
        f"{target['name']} rolls D{die_sides} ({roll}) and hits you for "
        f"{incoming_damage} damage ({stats['health']}/{stats['max_health']} health)."
    )
    if stats["health"] == 0:
        starting_area = starting_location(character.species)
        character.area_id = starting_area
        stats["health"] = stats["max_health"]
        state["target_id"] = None
        state["enemy_health"][target["id"]] = max_enemy_health
        character.combat_stats = stats
        messages.append(
            f"You are defeated. You awaken in {areas[starting_area]['name']} with full health."
        )
        character.combat_state = state
    else:
        character.combat_state = state
    return messages


def _expression(value: dict[str, Any]) -> Any:
    from plight_nlp_inspector import Expression

    return Expression(
        operator=value["operator"],
        occurrence_id=value.get("occurrence_id"),
        children=tuple(_expression(child) for child in value.get("children", [])),
    )
