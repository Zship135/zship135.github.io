"""Add per-character visited area history for the world map."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013_visited_areas"
down_revision: Union[str, None] = "0012_currencies_and_shops"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "characters",
        sa.Column("visited_areas", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("characters", "visited_areas")
