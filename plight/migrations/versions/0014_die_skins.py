"""Add unlocked and active die skins to characters."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_die_skins"
down_revision: Union[str, None] = "0013_visited_areas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "characters",
        sa.Column("unlocked_die_skins", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column("characters", sa.Column("active_die_skin", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("characters", "active_die_skin")
    op.drop_column("characters", "unlocked_die_skins")
