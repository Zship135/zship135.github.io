"""Add persistent character combat state."""

import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_character_combat"
down_revision: Union[str, None] = "0002_character_creation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "characters",
        sa.Column(
            "combat_stats",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "characters",
        sa.Column(
            "equipment",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "characters",
        sa.Column(
            "combat_state",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE characters SET combat_stats = :stats, equipment = :equipment, "
            "combat_state = :state"
        ),
        {
            "stats": json.dumps(
                {"health": 100, "max_health": 100, "attack": 3, "defense": 1, "speed": 10}
            ),
            "equipment": json.dumps({"left_hand": "fist", "right_hand": "fist"}),
            "state": json.dumps({"target_id": None, "enemy_health": {}}),
        },
    )


def downgrade() -> None:
    op.drop_column("characters", "combat_state")
    op.drop_column("characters", "equipment")
    op.drop_column("characters", "combat_stats")
