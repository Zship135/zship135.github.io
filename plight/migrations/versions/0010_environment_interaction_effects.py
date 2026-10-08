"""Add per-character bed respawn locations."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_environment_interaction_effects"
down_revision: Union[str, None] = "0009_parties_and_combat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "characters",
        sa.Column("respawn_area_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("characters", "respawn_area_id")
