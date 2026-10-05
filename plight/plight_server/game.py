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
    **{slot: "" for slot in EQUIPMENT_SLOTS if slot not in {"left_hand", "right_hand"}},
    "left_hand": "fist",
    "right_hand": "fist",
}
EQUIPMENT_TYPE_SLOTS = {"weapon": {"left_hand", "right_hand"}}
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
                step_progress.get(objective["id"], 0) + 1,
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


def _snapshot(
    character: Any,
    content: dict[str, Any],
    enemy_spawns_by_location: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    areas = _location_map(content)
    area = areas[character.area_id]
    entities = {entity["id"]: entity for entity in content["entities"]}
    quests = {quest["id"]: quest for quest in content.get("quests", [])}
    stats = {**PLAYER_BASE_STATS, **(character.combat_stats or {})}
    experience = getattr(character, "experience", 0) or 0
    level, experience_progress, experience_to_next_level = _level_progress(experience)
    equipment = {**DEFAULT_EQUIPMENT, **(character.equipment or {})}
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
    objects = visible_entities(area["object_ids"])
    resources = visible_entities(area["resource_ids"])
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
            "level": level,
            "experience": experience,
            "experience_progress": experience_progress,
            "experience_to_next_level": experience_to_next_level,
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
    available_players: list[Any] | None = None,
    enemy_spawns_by_location: dict[str, list[dict[str, Any]]] | None = None,
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

    selected = random.SystemRandom().choice(assignments)
    selected_ids = {key for key, value in selected.items() if value}
    parsed["selection_resolved"] = True
    parsed["selected_occurrences"] = sorted(
        selected_ids, key=lambda item: occurrence_ids.index(item)
    )
    messages: list[str] = []
    dialogues: list[dict[str, Any]] = []
    profile_account_ids: list[str] = []
    observed_player_equipment: dict[str, dict[str, str]] = {}
    inventory_view: str | None = None
    for occurrence in occurrences:
        if occurrence["occurrence_id"] not in selected_ids:
            continue
        action_id = occurrence["action_id"]
        args = occurrence["arguments"]
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
                )
            )
        elif action_id == "equip_item":
            messages.append(_equip(character, entities, args))
        elif action_id == "unequip_item":
            messages.append(_unequip(character, entities, args))
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
        "profile_account_ids": profile_account_ids,
        "observed_player_equipment": observed_player_equipment,
        "inventory_view": inventory_view,
        "snapshot": _snapshot(character, content, enemy_spawns_by_location),
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
) -> list[str]:
    experience_reward = _positive_stat(enemy, "experience", 0)
    messages = award_experience(character, experience_reward)
    if experience_reward == 0:
        messages.append("You gain 0 experience.")
    inventory = dict(character.inventory or {})
    dropped_items = False
    for drop in enemy.get("loot_table", []):
        if combat_rng.random() >= drop["chance"]:
            continue
        quantity = combat_rng.randint(
            drop["minimum_quantity"],
            drop["maximum_quantity"],
        )
        inventory[drop["item_id"]] = inventory.get(drop["item_id"], 0) + quantity
        item_name = entities[drop["item_id"]]["name"]
        dropped_items = True
        messages.append(
            f"Loot: {quantity} {item_name}{'' if quantity == 1 else 's'}."
        )
    if not dropped_items:
        messages.append("No items dropped.")
    character.inventory = inventory
    return messages


def _equip(
    character: Any, entities: dict[str, dict[str, Any]], arguments: dict[str, Any]
) -> str:
    item = arguments.get("item", {})
    item_name = item.get("name", "") if isinstance(item, dict) else str(item)
    slot = arguments.get("slot")
    item_key = _normalize_npc_name(item_name)
    if item_key == "fist":
        if slot not in {None, "left_hand", "right_hand"}:
            return "Fists can only be readied in your left hand or right hand."
        slot = slot or "right_hand"
        equipment = {**DEFAULT_EQUIPMENT, **(character.equipment or {})}
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
    slot = slot or ("right_hand" if item["type"] == "weapon" else None)
    if slot not in EQUIPMENT_SLOTS:
        return f"Choose an equipment slot: {', '.join(EQUIPMENT_SLOTS)}."
    if slot not in item_slots:
        return f"{item['name']} cannot be equipped in your {slot.replace('_', ' ')}."
    equipment = {**DEFAULT_EQUIPMENT, **(character.equipment or {})}
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
    equipment[slot] = "fist" if slot in {"left_hand", "right_hand"} else ""
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
    if subject:
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
    stats = {**PLAYER_BASE_STATS, **(character.combat_stats or {})}
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
        messages.extend(_reward_enemy_defeat(character, enemy, entities))
        _record_quest_event(character, content, "kill", enemy["id"])
        return messages

    character.combat_state = state
    if enemy.get("behavior", "neutral") == "passive":
        messages.append(f"{target['name']} does not fight back.")
        return messages
    messages.extend(enemy_strike(character, enemy, areas))
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
) -> list[str]:
    stats = {**PLAYER_BASE_STATS, **(character.combat_stats or {})}
    die_sides = enemy["attack_die_sides"]
    roll = combat_rng.randint(1, die_sides)
    incoming_damage = max(
        0,
        _positive_stat(enemy, "attack", 0) + roll - stats["defense"],
    )
    state = dict(character.combat_state or {})
    if state.pop("defending", False):
        incoming_damage //= 2
    stats["health"] = max(0, stats["health"] - incoming_damage)
    messages = [
        f"{enemy['name']} rolls D{die_sides} ({roll}) and hits you for "
        f"{incoming_damage} damage ({stats['health']}/{stats['max_health']} health)."
    ]
    if stats["health"] == 0:
        starting_area = starting_location(character.species)
        character.area_id = starting_area
        stats["health"] = stats["max_health"]
        state["target_id"] = None
        messages.append(
            f"You are defeated. You awaken in {areas[starting_area]['name']} with full health."
        )
    character.combat_stats = stats
    character.combat_state = state
    return messages


def _expression(value: dict[str, Any]) -> Any:
    from plight_nlp_inspector import Expression

    return Expression(
        operator=value["operator"],
        occurrence_id=value.get("occurrence_id"),
        children=tuple(_expression(child) for child in value.get("children", [])),
    )
