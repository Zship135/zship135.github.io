"""Persist character experience and fetch-quest progress."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_fetch_quests_and_experience"
down_revision: Union[str, None] = "0006_equipment_slots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "characters",
        sa.Column("experience", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "characters",
        sa.Column("quest_state", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("characters", "quest_state")
    op.drop_column("characters", "experience")
