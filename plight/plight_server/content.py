from __future__ import annotations

from hashlib import sha256
import json
import re
import threading
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


WORLD_CONTENT_PATH = Path(__file__).with_name("world_content.json")
_CONTENT_LOCK = threading.Lock()
_SLUG = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DIRECTIONS = {"north", "south", "east", "west"}


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
    starting_species: list[Literal["human", "goblin"]] = Field(default_factory=list, max_length=2)
    exits: dict[str, str] = Field(default_factory=dict, max_length=4)
    ambience: list[str] = Field(default_factory=list, max_length=100)
    enemy_ids: list[str] = Field(default_factory=list, max_length=100)
    npc_ids: list[str] = Field(default_factory=list, max_length=100)
    object_ids: list[str] = Field(default_factory=list, max_length=100)
    resource_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("ambience")
    @classmethod
    def validate_ambience(cls, lines: list[str]) -> list[str]:
        if any(not line.strip() or len(line) > 1000 for line in lines):
            raise ValueError("Ambience lines must contain 1 to 1000 characters.")
        return [line.strip() for line in lines]


class StockEntry(ContentModel):
    item_id: str = Field(pattern=_SLUG.pattern)
    quantity: int = Field(ge=0, le=1_000_000)
    price: int = Field(ge=0, le=1_000_000_000)


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


class ContentEntity(ContentModel):
    id: str = Field(pattern=_SLUG.pattern)
    type: Literal["enemy", "npc", "item", "weapon", "furniture", "object", "resource"]
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(max_length=4000)
    attributes: dict[str, Any] = Field(default_factory=dict)
    attack_die_sides: int | None = Field(default=None, ge=2, le=100)
    race: Literal["human", "goblin"] | None = None
    present_for: list[Literal["human", "goblin"]] | None = Field(default=None, max_length=2)
    dialogue: NPCDialogue | None = None
    ambience: list[str] = Field(default_factory=list, max_length=100)
    stock: list[StockEntry] = Field(default_factory=list, max_length=100)
    weapon_ids: list[str] = Field(default_factory=list, max_length=50)

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
    skill: str = Field(default="", max_length=100)
    skill_level: int = Field(default=0, ge=0, le=100)


class WorldContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    locations: list[ContentLocation] = Field(min_length=1, max_length=500)
    entities: list[ContentEntity] = Field(default_factory=list, max_length=2000)
    recipes: list[ContentRecipe] = Field(default_factory=list, max_length=2000)

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
        entity_types = {entity_id: entity.type for entity_id, entity in entities.items()}

        starting_species = {
            species for location in self.locations for species in location.starting_species
        }
        if starting_species != {"human", "goblin"}:
            raise ValueError("At least one starting location is required for both human and goblin.")

        for location in self.locations:
            if set(location.exits) - _DIRECTIONS:
                raise ValueError(f"Location {location.id} has an invalid exit direction.")
            if any(destination not in locations for destination in location.exits.values()):
                raise ValueError(f"Location {location.id} has an exit to a missing location.")
            for entity_id in location.enemy_ids:
                if entity_types.get(entity_id) != "enemy":
                    raise ValueError(f"Location {location.id} references a missing or non-enemy entity.")
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
                for attribute in ("health", "attack", "defense"):
                    value = entity.attributes.get(attribute)
                    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                        raise ValueError(f"Enemy {entity.id} must have a non-negative integer {attribute}.")
                if entity.attributes["health"] < 1:
                    raise ValueError(f"Enemy {entity.id} must have at least 1 health.")
            elif entity.attack_die_sides is not None:
                raise ValueError(f"Attack dice only apply to enemies ({entity.id}).")
            if entity.type == "weapon":
                damage = entity.attributes.get("damage", 0)
                if not isinstance(damage, int) or isinstance(damage, bool) or damage < 0:
                    raise ValueError(f"Weapon {entity.id} must have a non-negative integer damage value.")
            if entity.type not in {"enemy", "npc"} and entity.ambience:
                raise ValueError(f"Only NPCs and enemies can have ambience lines ({entity.id}).")
            if entity.type != "npc" and (entity.stock or entity.weapon_ids):
                raise ValueError(f"Only NPCs can have shop stock or equipped weapons ({entity.id}).")
            if any(entity_types.get(weapon_id) != "weapon" for weapon_id in entity.weapon_ids):
                raise ValueError(f"NPC {entity.id} references a missing or non-weapon entity.")
            if any(
                entity_types.get(entry.item_id) not in {"item", "weapon", "resource"}
                for entry in entity.stock
            ):
                raise ValueError(f"NPC {entity.id} has stock referencing a missing or invalid item.")

        for recipe in self.recipes:
            if entity_types.get(recipe.output_item_id) not in {"item", "weapon"}:
                raise ValueError(f"Recipe {recipe.id} must produce an existing item or weapon.")
            if any(
                entity_types.get(ingredient.item_id) not in {"item", "weapon", "resource"}
                for ingredient in recipe.ingredients
            ):
                raise ValueError(f"Recipe {recipe.id} has a missing or invalid ingredient.")
            if recipe.station_id and entity_types.get(recipe.station_id) not in {"furniture", "object"}:
                raise ValueError(f"Recipe {recipe.id} references a missing or invalid crafting station.")
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
