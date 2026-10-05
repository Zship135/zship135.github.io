"""Repair malformed combat JSON defaults from 0003."""

import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_repair_combat_json_defaults"
down_revision: Union[str, None] = "0003_character_combat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULTS = {
    "combat_stats": {
        "health": 100,
        "max_health": 100,
        "attack": 3,
        "defense": 1,
        "speed": 10,
    },
    "equipment": {"left_hand": "fist", "right_hand": "fist"},
    "combat_state": {"target_id": None, "enemy_health": {}},
}


def _load_object(value: str | None) -> dict | None:
    try:
        parsed = json.loads(value) if value is not None else None
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, combat_stats, equipment, combat_state FROM characters")
    ).all()
    for row in rows:
        values = {
            column: _load_object(row._mapping[column]) or _DEFAULTS[column]
            for column in _DEFAULTS
        }
        connection.execute(
            sa.text(
                "UPDATE characters SET combat_stats = :combat_stats, "
                "equipment = :equipment, combat_state = :combat_state WHERE id = :id"
            ),
            {
                **{column: json.dumps(value) for column, value in values.items()},
                "id": row._mapping["id"],
            },
        )


def downgrade() -> None:
    pass
