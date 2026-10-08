from __future__ import annotations

from hashlib import sha256
import json
import re
import threading
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from plight_nlp_inspector import ACTION_ALIASES


WORLD_CONTENT_PATH = Path(__file__).with_name("world_content.json")
_CONTENT_LOCK = threading.Lock()
_SLUG = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DIRECTIONS = {"north", "south", "east", "west"}
Direction = Literal["north", "south", "east", "west"]
SkillName = Literal[
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
]
GatheringSkill = Literal["felling", "foraging", "gouging", "fishing", "herbology"]
NPCRace = Literal[
    "human",
    "elf",
    "high_elf",
    "wood_elf",
    "dark_elf",
    "sea_elf",
    "dwarf",
    "hill_dwarf",
    "mountain_dwarf",
    "gnome",
    "halfling",
    "orc",
    "half_orc",
    "goblin",
    "hobgoblin",
    "bugbear",
    "kobold",
    "ogre",
    "troll",
    "giant",
    "cyclops",
    "fae",
    "fairy",
    "pixie",
    "sprite",
    "brownie",
    "dryad",
    "nymph",
    "satyr",
    "faun",
    "centaur",
    "minotaur",
    "changeling",
    "fey_touched",
    "harpy",
    "siren",
    "mermaid",
    "merman",
    "merfolk",
    "selkie",
    "sea_folk",
    "triton",
    "naiad",
    "undine",
    "sylph",
    "salamander",
    "oni",
    "tengu",
    "kitsune",
    "kappa",
    "elemental",
    "air_elemental",
    "earth_elemental",
    "fire_elemental",
    "water_elemental",
    "djinn",
    "genie",
    "golem",
    "construct",
    "automaton",
    "homunculus",
    "dragon",
    "dragonkin",
    "draconic",
    "drakefolk",
    "lizardfolk",
    "snakefolk",
    "beastfolk",
    "catfolk",
    "wolfkin",
    "foxfolk",
    "ratfolk",
    "bearfolk",
    "boarfolk",
    "rabbitfolk",
    "deerfolk",
    "lionfolk",
    "birdfolk",
    "avian",
    "insectfolk",
    "mothfolk",
    "spiderfolk",
    "fishfolk",
    "sharkfolk",
    "turtlefolk",
    "octopoid",
    "amphibian",
    "reptilian",
    "plantfolk",
    "mushroom_folk",
    "slimefolk",
    "vampire",
    "dhampir",
    "werewolf",
    "lycanthrope",
    "undead",
    "revenant",
    "skeleton",
    "ghost",
    "ghoul",
    "lich",
    "mummy",
    "zombie",
    "angel",
    "celestial",
    "nephilim",
    "demon",
    "devil",
    "fiend",
    "spirit",
    "shadowborn",
    "starborn",
    "dreamborn",
    "void_touched",
    "shapeshifter",
    "half_elf",
    "half_giant",
    "half_dragon",
    "half_fae",
]


class ContentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MapPosition(ContentModel):
    x: int = Field(ge=0, le=100)
    y: int = Field(ge=0, le=100)


class ContentLocation(ContentModel):
    id: str = Field(pattern=_SLUG.pattern)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(max_length=4000)
    position: MapPosition
    music_asset_id: UUID | None = None
    starting_species: list[Literal["human", "goblin"]] = Field(default_factory=list, max_length=2)
    exits: dict[str, str] = Field(default_factory=dict, max_length=4)
    exit_requirements: dict[str, str] = Field(default_factory=dict, max_length=4)
    ambience: list[str] = Field(default_factory=list, max_length=100)
    enemy_ids: list[str] = Field(default_factory=list, max_length=100)
    enemy_spawn_limit: int = Field(default=1, ge=1, le=1000)
    npc_ids: list[str] = Field(default_factory=list, max_length=100)
    object_ids: list[str] = Field(default_factory=list, max_length=100)
    resource_ids: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="before")
    @classmethod
    def default_enemy_spawn_limit(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "enemy_spawn_limit" in value:
            return value
        location = dict(value)
        enemy_ids = location.get("enemy_ids", [])
        location["enemy_spawn_limit"] = max(
            1,
            len(set(enemy_ids)) if isinstance(enemy_ids, list) and all(
                isinstance(enemy_id, str) for enemy_id in enemy_ids
            ) else 0,
        )
        return location

    @field_validator("ambience")
    @classmethod
    def validate_ambience(cls, lines: list[str]) -> list[str]:
        if any(not line.strip() or len(line) > 1000 for line in lines):
            raise ValueError("Ambience lines must contain 1 to 1000 characters.")
        return [line.strip() for line in lines]


class Currency(ContentModel):
    id: str = Field(pattern=_SLUG.pattern)
    name: str = Field(min_length=1, max_length=100)
    symbol: str = Field(default="", max_length=8)
    description: str = Field(default="", max_length=1000)


class CurrencyAmount(ContentModel):
    currency_id: str = Field(pattern=_SLUG.pattern)
    amount: int = Field(ge=1, le=1_000_000_000)


class CurrencyDrop(ContentModel):
    currency_id: str = Field(pattern=_SLUG.pattern)
    chance: float = Field(ge=0, le=1)
    minimum_amount: int = Field(default=1, ge=1, le=1_000_000_000)
    maximum_amount: int = Field(default=1, ge=1, le=1_000_000_000)

    @model_validator(mode="after")
    def validate_amount_range(self) -> CurrencyDrop:
        if self.maximum_amount < self.minimum_amount:
            raise ValueError("Maximum currency amount must be at least the minimum.")
        return self


class StockEntry(ContentModel):
    item_id: str = Field(pattern=_SLUG.pattern)
    quantity: int = Field(ge=0, le=1_000_000)
    price: int = Field(ge=0, le=1_000_000_000)
    currency_id: str | None = Field(default=None, pattern=_SLUG.pattern)
    restock_seconds: int = Field(default=300, ge=1, le=604_800)


class BuyEntry(StockEntry):
    """An item a vendor purchases from players; quantity is the per-player capacity."""

class DialogueChoice(ContentModel):
    id: str = Field(pattern=_SLUG.pattern)
    text: str = Field(min_length=1, max_length=200)
    next_node_id: str = Field(pattern=_SLUG.pattern)


class DialogueNode(ContentModel):
    id: str = Field(pattern=_SLUG.pattern)
    title: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=2000)
    choices: list[DialogueChoice] = Field(default_factory=list, max_length=12)


class NPCDialogue(ContentModel):
    start_node_id: str | None = Field(default=None, pattern=_SLUG.pattern)
    nodes: list[DialogueNode] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_dialogue(self) -> NPCDialogue:
        nodes = {node.id: node for node in self.nodes}
        if len(nodes) != len(self.nodes):
            raise ValueError("Dialogue node IDs must be unique.")
        if not nodes:
            if self.start_node_id is not None:
                raise ValueError("An empty dialogue cannot have a start node.")
            return self
        if self.start_node_id not in nodes:
            raise ValueError("The dialogue start node must reference an existing node.")
        for node in self.nodes:
            choice_ids = [choice.id for choice in node.choices]
            if len(set(choice_ids)) != len(choice_ids):
                raise ValueError(f"Dialogue choice IDs must be unique within node {node.id}.")
            if any(choice.next_node_id not in nodes for choice in node.choices):
                raise ValueError(f"Every dialogue choice in {node.id} must lead to an existing node.")
        return self


class LootDrop(ContentModel):
    item_id: str = Field(pattern=_SLUG.pattern)
    chance: float = Field(ge=0, le=1)
    minimum_quantity: int = Field(default=1, ge=1, le=1_000_000)
    maximum_quantity: int = Field(default=1, ge=1, le=1_000_000)

    @model_validator(mode="after")
    def validate_quantity_range(self) -> LootDrop:
        if self.maximum_quantity < self.minimum_quantity:
            raise ValueError("Maximum loot quantity must be at least the minimum.")
        return self


class ItemHealingEffect(ContentModel):
    type: Literal["heal"]
    mode: Literal["fixed", "percent", "full"] = "fixed"
    amount: int | None = Field(default=25, ge=1, le=10_000)

    @model_validator(mode="after")
    def validate_amount(self) -> ItemHealingEffect:
        if self.mode == "full":
            return self
        maximum = 100 if self.mode == "percent" else 10_000
        if self.amount is None or self.amount > maximum:
            raise ValueError(f"{self.mode} healing requires an amount from 1 to {maximum}.")
        return self


class ItemStatBuffEffect(ContentModel):
    type: Literal["stat_buff"]
    stat: Literal["attack", "defense", "speed"]
    mode: Literal["flat", "percent"]
    amount: int = Field(ge=1, le=500)
    duration_seconds: int = Field(ge=1, le=86_400)


class ItemShieldEffect(ContentModel):
    type: Literal["shield"]
    mode: Literal["damage_pool", "damage_reduction", "temporary_health"]
    amount: int = Field(ge=1, le=100_000)
    duration_seconds: int = Field(ge=1, le=86_400)


class ItemTeleportEffect(ContentModel):
    type: Literal["teleport"]
    destination_area_id: str = Field(pattern=_SLUG.pattern)


class ItemLuckEffect(ContentModel):
    type: Literal["luck"]
    drop_chance_bonus_percent: int = Field(default=0, ge=0, le=1_000)
    gathering_yield_bonus_percent: int = Field(default=0, ge=0, le=1_000)
    duration_seconds: int = Field(ge=1, le=86_400)

    @model_validator(mode="after")
    def validate_bonus(self) -> ItemLuckEffect:
        if self.drop_chance_bonus_percent == self.gathering_yield_bonus_percent == 0:
            raise ValueError("A luck effect must boost at least one reward chance or yield.")
        return self


ItemEffect = Annotated[
    ItemHealingEffect
    | ItemStatBuffEffect
    | ItemShieldEffect
    | ItemTeleportEffect
    | ItemLuckEffect,
    Field(discriminator="type"),
]


class ItemUseConfig(ContentModel):
    effects: list[ItemEffect] = Field(default_factory=list, max_length=20)
    target_scope: Literal["self", "party"] = "self"
    consume_on_use: bool = True

    @model_validator(mode="after")
    def validate_effects(self) -> ItemUseConfig:
        active_effect_keys: set[tuple[str, str]] = set()
        teleport_count = 0
        for effect in self.effects:
            if isinstance(effect, ItemTeleportEffect):
                teleport_count += 1
            if isinstance(effect, ItemStatBuffEffect):
                key = ("stat_buff", effect.stat)
            elif isinstance(effect, ItemShieldEffect):
                key = ("shield", effect.mode)
            elif isinstance(effect, ItemLuckEffect):
                key = ("luck", "luck")
            else:
                continue
            if key in active_effect_keys:
                raise ValueError("An item cannot contain duplicate timed effects of the same kind.")
            active_effect_keys.add(key)
        if teleport_count > 1:
            raise ValueError("An item can have at most one teleport destination.")
        return self


class EnchantStatEffect(ContentModel):
    type: Literal["stat_modifier"]
    stat: Literal["attack", "defense", "speed", "max_health"]
    mode: Literal["flat", "percent"] = "flat"
    amount: int = Field(ge=-500, le=500)

    @model_validator(mode="after")
    def validate_amount(self) -> EnchantStatEffect:
        if self.amount == 0:
            raise ValueError("A stat modifier cannot be zero.")
        return self


class EnchantLuckEffect(ContentModel):
    type: Literal["luck"]
    drop_chance_bonus_percent: int = Field(default=0, ge=0, le=1_000)
    gathering_yield_bonus_percent: int = Field(default=0, ge=0, le=1_000)

    @model_validator(mode="after")
    def validate_bonus(self) -> EnchantLuckEffect:
        if self.drop_chance_bonus_percent == self.gathering_yield_bonus_percent == 0:
            raise ValueError("A luck enchantment must boost at least one reward chance or yield.")
        return self


class EnchantQuestPathEffect(ContentModel):
    type: Literal["quest_path"]


class EnchantDamageOverTimeEffect(ContentModel):
    type: Literal["damage_over_time"]
    amount: int = Field(default=1, ge=1, le=1_000)
    interval_seconds: int = Field(default=15, ge=5, le=3_600)


class EnchantLifeStealEffect(ContentModel):
    type: Literal["life_steal"]
    percent: int = Field(default=10, ge=1, le=100)


class EnchantThornsEffect(ContentModel):
    type: Literal["thorns"]
    amount: int = Field(default=1, ge=1, le=1_000)


class EnchantCursedBindingEffect(ContentModel):
    type: Literal["cursed_binding"]


EnchantmentEffect = Annotated[
    EnchantStatEffect
    | EnchantLuckEffect
    | EnchantQuestPathEffect
    | EnchantDamageOverTimeEffect
    | EnchantLifeStealEffect
    | EnchantThornsEffect
    | EnchantCursedBindingEffect,
    Field(discriminator="type"),
]


class Enchantment(ContentModel):
    id: str = Field(pattern=_SLUG.pattern)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    kind: Literal["enchantment", "curse"] = "enchantment"
    effects: list[EnchantmentEffect] = Field(min_length=1, max_length=20)


class ResourceGathering(ContentModel):
    skill: GatheringSkill
    skill_level: int = Field(default=1, ge=1, le=100)
    health: int = Field(default=100, ge=1, le=1_000_000)
    tool_stat: str | None = Field(default=None, pattern=_SLUG.pattern)
    minimum_tool_power: int = Field(default=0, ge=0, le=1_000_000)
    respawn_seconds: int = Field(default=3_600, ge=1, le=31_536_000)
    loot_table: list[LootDrop] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_tool_requirement(self) -> ResourceGathering:
        if self.minimum_tool_power > 0 and self.tool_stat is None:
            raise ValueError("A minimum tool power requires a tool stat name.")
        return self


class ContentEntity(ContentModel):
    id: str = Field(pattern=_SLUG.pattern)
    type: Literal[
        "enemy", "npc", "item", "weapon", "shield", "furniture", "object", "resource"
    ]
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(max_length=4000)
    attributes: dict[str, Any] = Field(default_factory=dict)
    interaction_effect: Literal["restore_health", "set_respawn"] | None = None
    item_use: ItemUseConfig | None = None
    gathering: ResourceGathering | None = None
    attack_die_sides: int | None = Field(default=None, ge=2, le=100)
    respawn_chance_percent: int | None = Field(default=None, ge=0, le=100)
    aggressive_attack_chance_percent: int | None = Field(default=None, ge=0, le=100)
    behavior: Literal["passive", "neutral", "aggressive"] | None = None
    race: NPCRace | None = None
    present_for: list[Literal["human", "goblin"]] | None = Field(default=None, max_length=2)
    dialogue: NPCDialogue | None = None
    ambience: list[str] = Field(default_factory=list, max_length=100)
    stock: list[StockEntry] = Field(default_factory=list, max_length=100)
    buy_list: list[BuyEntry] = Field(default_factory=list, max_length=100)
    weapon_ids: list[str] = Field(default_factory=list, max_length=50)
    loot_table: list[LootDrop] = Field(default_factory=list, max_length=100)
    currency_drops: list[CurrencyDrop] = Field(default_factory=list, max_length=20)
    enchantment_ids: list[str] = Field(default_factory=list, max_length=10)
    is_map: bool = False

    @field_validator("ambience")
    @classmethod
    def validate_ambience(cls, lines: list[str]) -> list[str]:
        if any(not line.strip() or len(line) > 1000 for line in lines):
            raise ValueError("Ambience lines must contain 1 to 1000 characters.")
        return [line.strip() for line in lines]


class RecipeIngredient(ContentModel):
    item_id: str = Field(pattern=_SLUG.pattern)
    quantity: int = Field(ge=1, le=1_000_000)


class ContentRecipe(ContentModel):
    id: str = Field(pattern=_SLUG.pattern)
    name: str = Field(min_length=1, max_length=100)
    output_item_id: str = Field(pattern=_SLUG.pattern)
    output_quantity: int = Field(ge=1, le=1_000_000)
    ingredients: list[RecipeIngredient] = Field(min_length=1, max_length=50)
    station_id: str | None = Field(default=None, pattern=_SLUG.pattern)
    skill: SkillName | Literal[""] = ""
    skill_level: int = Field(default=0, ge=0, le=100)


class QuestObjective(ContentModel):
    id: str = Field(pattern=_SLUG.pattern)
    type: Literal["collect", "kill", "talk", "visit"]
    target_id: str = Field(pattern=_SLUG.pattern)
    quantity: int = Field(default=1, ge=1, le=1_000_000)


class QuestChoice(ContentModel):
    id: str = Field(pattern=_SLUG.pattern)
    text: str = Field(min_length=1, max_length=100)
    next_step_id: str | None = Field(default=None, pattern=_SLUG.pattern)


class QuestStep(ContentModel):
    id: str = Field(pattern=_SLUG.pattern)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    objectives: list[QuestObjective] = Field(min_length=1, max_length=20)
    choices: list[QuestChoice] = Field(min_length=1, max_length=20)


class QuestRewardItem(ContentModel):
    item_id: str = Field(pattern=_SLUG.pattern)
    quantity: int = Field(ge=1, le=1_000_000)


class Quest(ContentModel):
    id: str = Field(pattern=_SLUG.pattern)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2000)
    giver_npc_id: str = Field(pattern=_SLUG.pattern)
    start_step_id: str = Field(pattern=_SLUG.pattern)
    steps: list[QuestStep] = Field(min_length=1, max_length=100)
    reward_experience: int = Field(default=0, ge=0, le=1_000_000)
    reward_items: list[QuestRewardItem] = Field(default_factory=list, max_length=20)
    reward_currencies: list[CurrencyAmount] = Field(default_factory=list, max_length=20)

    @model_validator(mode="before")
    @classmethod
    def migrate_fetch_quest(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "steps" in value or "objectives" not in value:
            return value
        legacy = dict(value)
        objectives = legacy.pop("objectives")
        step_id = "step_1"
        legacy["start_step_id"] = step_id
        legacy["steps"] = [
            {
                "id": step_id,
                "title": "Collect the required items",
                "description": "",
                "objectives": [
                    {
                        "id": f"objective_{index}",
                        "type": "collect",
                        "target_id": objective["item_id"],
                        "quantity": objective["quantity"],
                    }
                    for index, objective in enumerate(objectives, start=1)
                ],
                "choices": [
                    {"id": "finish", "text": "Return to the quest giver", "next_step_id": None}
                ],
            }
        ]
        return legacy

    @model_validator(mode="after")
    def validate_steps(self) -> Quest:
        steps = {step.id: step for step in self.steps}
        if len(steps) != len(self.steps):
            raise ValueError("Quest step IDs must be unique.")
        if self.start_step_id not in steps:
            raise ValueError(f"Quest {self.id} has a missing starting step.")
        graph: dict[str, set[str]] = {}
        for step in self.steps:
            objective_ids = [objective.id for objective in step.objectives]
            if len(objective_ids) != len(set(objective_ids)):
                raise ValueError(f"Quest {self.id} step {step.id} has duplicate objective IDs.")
            objective_targets = [
                (objective.type, objective.target_id)
                for objective in step.objectives
            ]
            if len(objective_targets) != len(set(objective_targets)):
                raise ValueError(
                    f"Quest {self.id} step {step.id} can only target each objective type and target once."
                )
            choice_ids = [choice.id for choice in step.choices]
            if len(choice_ids) != len(set(choice_ids)):
                raise ValueError(f"Quest {self.id} step {step.id} has duplicate choice IDs.")
            graph[step.id] = set()
            for choice in step.choices:
                if choice.next_step_id is not None:
                    if choice.next_step_id not in steps:
                        raise ValueError(
                            f"Quest {self.id} step {step.id} references a missing next step."
                        )
                    graph[step.id].add(choice.next_step_id)

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError(f"Quest {self.id} has a step-choice cycle.")
            if step_id in visited:
                return
            visiting.add(step_id)
            for next_step_id in graph[step_id]:
                visit(next_step_id)
            visiting.remove(step_id)
            visited.add(step_id)

        visit(self.start_step_id)
        if visited != set(steps):
            raise ValueError(f"Quest {self.id} has unreachable steps.")
        return self


class WorldContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    locations: list[ContentLocation] = Field(min_length=1, max_length=500)
    action_sounds: dict[str, UUID] = Field(default_factory=dict)
    entities: list[ContentEntity] = Field(default_factory=list, max_length=2000)
    recipes: list[ContentRecipe] = Field(default_factory=list, max_length=2000)
    quests: list[Quest] = Field(default_factory=list, max_length=2000)
    currencies: list[Currency] = Field(default_factory=list, max_length=100)
    enchantments: list[Enchantment] = Field(default_factory=list, max_length=500)

    @field_validator("action_sounds")
    @classmethod
    def validate_action_sounds(cls, sounds: dict[str, UUID]) -> dict[str, UUID]:
        unsupported = set(sounds) - set(ACTION_ALIASES)
        if unsupported:
            raise ValueError(
                f"Action sounds reference unsupported actions: {', '.join(sorted(unsupported))}."
            )
        return sounds

    @model_validator(mode="after")
    def validate_references(self) -> WorldContent:
        def unique_ids(values: list[Any], label: str) -> dict[str, Any]:
            by_id = {value.id: value for value in values}
            if len(by_id) != len(values):
                raise ValueError(f"{label} IDs must be unique.")
            return by_id

        locations = unique_ids(self.locations, "Location")
        entities = unique_ids(self.entities, "Entity")
        recipes = unique_ids(self.recipes, "Recipe")
        quests = unique_ids(self.quests, "Quest")
        currencies = unique_ids(self.currencies, "Currency")
        enchantments = unique_ids(self.enchantments, "Enchantment")
        entity_types = {entity_id: entity.type for entity_id, entity in entities.items()}

        starting_species = {
            species for location in self.locations for species in location.starting_species
        }
        if starting_species != {"human", "goblin"}:
            raise ValueError("At least one starting location is required for both human and goblin.")

        for location in self.locations:
            if set(location.exits) - _DIRECTIONS:
                raise ValueError(f"Location {location.id} has an invalid exit direction.")
            if set(location.exit_requirements) - _DIRECTIONS:
                raise ValueError(f"Location {location.id} has an invalid exit requirement direction.")
            if any(destination not in locations for destination in location.exits.values()):
                raise ValueError(f"Location {location.id} has an exit to a missing location.")
            if set(location.exit_requirements) - set(location.exits):
                raise ValueError(f"Location {location.id} has a requirement for a missing exit.")
            if any(quest_id not in quests for quest_id in location.exit_requirements.values()):
                raise ValueError(f"Location {location.id} has an exit requirement for a missing quest.")
            for entity_id in location.enemy_ids:
                if entity_types.get(entity_id) != "enemy":
                    raise ValueError(f"Location {location.id} references a missing or non-enemy entity.")
            if location.enemy_spawn_limit < len(set(location.enemy_ids)):
                raise ValueError(
                    f"Location {location.id} spawn limit cannot be less than its initial enemy count."
                )
            for entity_id in location.npc_ids:
                if entity_types.get(entity_id) != "npc":
                    raise ValueError(f"Location {location.id} references a missing or non-NPC entity.")
            for entity_id in location.object_ids:
                if entity_types.get(entity_id) not in {"furniture", "object"}:
                    raise ValueError(f"Location {location.id} references a missing or non-object entity.")
            for entity_id in location.resource_ids:
                if entity_types.get(entity_id) != "resource":
                    raise ValueError(f"Location {location.id} references a missing or non-resource entity.")

        for entity in self.entities:
            if entity.type not in {"furniture", "object"} and entity.interaction_effect is not None:
                raise ValueError(
                    f"Interaction effects only apply to furniture and objects ({entity.id})."
                )
            if entity.type != "item" and entity.item_use is not None:
                raise ValueError(f"Item effects only apply to regular items ({entity.id}).")
            if entity.type not in {"item", "weapon", "shield"} and (
                entity.enchantment_ids or entity.is_map
            ):
                raise ValueError(f"Only items, weapons, and shields can be enchanted or be maps ({entity.id}).")
            if len(set(entity.enchantment_ids)) != len(entity.enchantment_ids) or any(
                enchantment_id not in enchantments for enchantment_id in entity.enchantment_ids
            ):
                raise ValueError(f"Entity {entity.id} has a duplicate or missing enchantment.")
            if entity.type != "resource" and entity.gathering is not None:
                raise ValueError(f"Gathering settings only apply to resources ({entity.id}).")
            if entity.item_use is not None:
                for effect in entity.item_use.effects:
                    if (
                        isinstance(effect, ItemTeleportEffect)
                        and effect.destination_area_id not in locations
                    ):
                        raise ValueError(
                            f"Item {entity.id} teleports to a missing location."
                        )
            if entity.gathering is not None:
                for drop in entity.gathering.loot_table:
                    if entity_types.get(drop.item_id) not in {
                        "item", "weapon", "shield", "resource"
                    }:
                        raise ValueError(
                            f"Resource {entity.id} has a gathering drop referencing a missing item."
                        )
            if entity.type == "npc":
                if entity.race is None:
                    entity.race = "human"
                if entity.present_for is None:
                    entity.present_for = ["human", "goblin"]
                if entity.dialogue is None:
                    entity.dialogue = NPCDialogue()
            elif entity.race is not None or entity.present_for is not None or entity.dialogue is not None:
                raise ValueError(f"Race, presence, and dialogue settings only apply to NPCs ({entity.id}).")
            if entity.type == "enemy":
                if entity.attack_die_sides is None:
                    entity.attack_die_sides = 2
                if entity.respawn_chance_percent is None:
                    entity.respawn_chance_percent = 0
                if entity.aggressive_attack_chance_percent is None:
                    entity.aggressive_attack_chance_percent = 0
                if entity.behavior is None:
                    entity.behavior = "neutral"
                for attribute in ("health", "attack", "defense"):
                    value = entity.attributes.get(attribute)
                    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                        raise ValueError(f"Enemy {entity.id} must have a non-negative integer {attribute}.")
                if entity.attributes["health"] < 1:
                    raise ValueError(f"Enemy {entity.id} must have at least 1 health.")
                experience = entity.attributes.get("experience", 0)
                if not isinstance(experience, int) or isinstance(experience, bool) or experience < 0:
                    raise ValueError(f"Enemy {entity.id} must have non-negative integer experience.")
                for drop in entity.loot_table:
                    if entity_types.get(drop.item_id) not in {
                        "item", "weapon", "shield", "resource"
                    }:
                        raise ValueError(f"Enemy {entity.id} has loot referencing a missing or invalid item.")
                if any(drop.currency_id not in currencies for drop in entity.currency_drops):
                    raise ValueError(f"Enemy {entity.id} has a currency drop referencing a missing currency.")
            elif (
                entity.attack_die_sides is not None
                or entity.respawn_chance_percent is not None
                or entity.aggressive_attack_chance_percent is not None
                or entity.behavior is not None
            ):
                raise ValueError(f"Enemy combat settings only apply to enemies ({entity.id}).")
            elif entity.loot_table or entity.currency_drops:
                raise ValueError(f"Loot tables only apply to enemies ({entity.id}).")
            if entity.type == "weapon":
                damage = entity.attributes.get("damage", 0)
                if not isinstance(damage, int) or isinstance(damage, bool) or damage < 0:
                    raise ValueError(f"Weapon {entity.id} must have a non-negative integer damage value.")
            if entity.type == "shield":
                defense = entity.attributes.get("defense", 0)
                if not isinstance(defense, int) or isinstance(defense, bool) or defense < 0:
                    raise ValueError(f"Shield {entity.id} must have a non-negative integer defense value.")
            if entity.type not in {"enemy", "npc"} and entity.ambience:
                raise ValueError(f"Only NPCs and enemies can have ambience lines ({entity.id}).")
            if entity.type != "npc" and (entity.stock or entity.buy_list or entity.weapon_ids):
                raise ValueError(f"Only NPCs can have shop stock, buy lists or equipped weapons ({entity.id}).")
            if any(
                entity_types.get(entry.item_id) not in {"item", "weapon", "shield", "resource"}
                or (entry.currency_id is not None and entry.currency_id not in currencies)
                for entry in entity.buy_list
            ):
                raise ValueError(f"NPC {entity.id} has a buy list with a missing item or currency.")
            if len({entry.item_id for entry in entity.buy_list}) != len(entity.buy_list):
                raise ValueError(f"NPC {entity.id} lists the same item twice in its buy list.")
            if any(entity_types.get(weapon_id) != "weapon" for weapon_id in entity.weapon_ids):
                raise ValueError(f"NPC {entity.id} references a missing or non-weapon entity.")
            if any(
                entity_types.get(entry.item_id) not in {
                    "item", "weapon", "shield", "resource"
                }
                for entry in entity.stock
            ):
                raise ValueError(f"NPC {entity.id} has stock referencing a missing or invalid item.")
            if any(
                entry.currency_id is not None and entry.currency_id not in currencies
                for entry in entity.stock
            ):
                raise ValueError(f"NPC {entity.id} has stock priced in a missing currency.")

        for recipe in self.recipes:
            if entity_types.get(recipe.output_item_id) not in {"item", "weapon", "shield"}:
                raise ValueError(f"Recipe {recipe.id} must produce an existing item, weapon, or shield.")
            if any(
                entity_types.get(ingredient.item_id) not in {
                    "item", "weapon", "shield", "resource"
                }
                for ingredient in recipe.ingredients
            ):
                raise ValueError(f"Recipe {recipe.id} has a missing or invalid ingredient.")
            if recipe.station_id and entity_types.get(recipe.station_id) not in {"furniture", "object"}:
                raise ValueError(f"Recipe {recipe.id} references a missing or invalid crafting station.")

        for quest in self.quests:
            if entity_types.get(quest.giver_npc_id) != "npc":
                raise ValueError(f"Quest {quest.id} references a missing or non-NPC quest giver.")
            for step in quest.steps:
                for objective in step.objectives:
                    valid_types = {
                        "collect": {"item", "weapon", "shield", "resource"},
                        "kill": {"enemy"},
                        "talk": {"npc"},
                        "visit": set(),
                    }[objective.type]
                    if objective.type == "visit":
                        if objective.target_id not in locations:
                            raise ValueError(
                                f"Quest {quest.id} references a missing visit location."
                            )
                    elif entity_types.get(objective.target_id) not in valid_types:
                        raise ValueError(
                            f"Quest {quest.id} has a missing or invalid {objective.type} target."
                        )
            if any(
                entity_types.get(reward.item_id) not in {
                    "item", "weapon", "shield", "resource"
                }
                for reward in quest.reward_items
            ):
                raise ValueError(f"Quest {quest.id} has a missing or invalid reward item.")
            if any(reward.currency_id not in currencies for reward in quest.reward_currencies):
                raise ValueError(f"Quest {quest.id} has a reward in a missing currency.")
        return self


class WorldContentUpdate(ContentModel):
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    content: WorldContent


def _read_document() -> tuple[WorldContent, str]:
    with _CONTENT_LOCK:
        raw = WORLD_CONTENT_PATH.read_bytes()
    content = WorldContent.model_validate_json(raw)
    return content, sha256(raw).hexdigest()


def read_world_content() -> tuple[WorldContent, str]:
    return _read_document()


def write_world_content(content: WorldContent, expected_revision: str) -> str:
    with _CONTENT_LOCK:
        current_bytes = WORLD_CONTENT_PATH.read_bytes()
        current_revision = sha256(current_bytes).hexdigest()
        if current_revision != expected_revision:
            raise ValueError("World content changed since it was loaded. Reload before saving.")
        serialized = (json.dumps(content.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n").encode()
        temporary_path = WORLD_CONTENT_PATH.with_suffix(".json.tmp")
        temporary_path.write_bytes(serialized)
        temporary_path.replace(WORLD_CONTENT_PATH)
        return sha256(serialized).hexdigest()


def world_content_dict() -> dict[str, Any]:
    content, _ = read_world_content()
    return content.model_dump(mode="json")


def starting_location(species: str) -> str:
    content, _ = read_world_content()
    for location in content.locations:
        if species in location.starting_species:
            return location.id
    raise ValueError(f"No starting location is configured for {species}.")


_LIBRARY_CACHE: dict[str, Any] = {"key": None, "value": ({}, {})}


def enchantment_library() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return (enchantments, entities) by id, cached until the world file changes."""
    stat = WORLD_CONTENT_PATH.stat()
    key = (str(WORLD_CONTENT_PATH), stat.st_mtime_ns, stat.st_size)
    if _LIBRARY_CACHE["key"] != key:
        data = world_content_dict()
        _LIBRARY_CACHE["value"] = (
            {item["id"]: item for item in data["enchantments"]},
            {item["id"]: item for item in data["entities"]},
        )
        _LIBRARY_CACHE["key"] = key
    return _LIBRARY_CACHE["value"]
