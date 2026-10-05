"""Expand persisted equipment to the supported equipment slots."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_equipment_slots"
down_revision: Union[str, None] = "0005_profiles_and_friends"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SLOTS = (
    "helm",
    "tunic",
    "pants",
    "sleeves",
    "gloves",
    "boots",
    "ring_1",
    "ring_2",
    "ring_3",
    "ring_4",
    "ring_5",
    "necklace_1",
    "necklace_2",
    "left_hand",
    "right_hand",
)


def upgrade() -> None:
    characters = sa.table(
        "characters",
        sa.column("id", sa.String()),
        sa.column("equipment", sa.JSON()),
    )
    bind = op.get_bind()
    rows = bind.execute(sa.select(characters.c.id, characters.c.equipment))
    for character_id, stored_equipment in rows:
        equipment = dict(stored_equipment or {})
        defaults = {slot: "" for slot in _SLOTS}
        defaults.update({"left_hand": "fist", "right_hand": "fist"})
        equipment = {**defaults, **equipment}
        bind.execute(
            sa.update(characters)
            .where(characters.c.id == character_id)
            .values(equipment=equipment)
        )


def downgrade() -> None:
    characters = sa.table(
        "characters",
        sa.column("id", sa.String()),
        sa.column("equipment", sa.JSON()),
    )
    bind = op.get_bind()
    rows = bind.execute(sa.select(characters.c.id, characters.c.equipment))
    retained_slots = {"left_hand", "right_hand"}
    for character_id, stored_equipment in rows:
        equipment = {
            slot: item_id
            for slot, item_id in (stored_equipment or {}).items()
            if slot in retained_slots
        }
        bind.execute(
            sa.update(characters)
            .where(characters.c.id == character_id)
            .values(equipment=equipment)
        )
