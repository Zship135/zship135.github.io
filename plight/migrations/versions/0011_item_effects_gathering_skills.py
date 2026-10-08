"""Add item effects, proficiencies, and resource gathering state."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011_item_effects_gathering_skills"
down_revision: Union[str, None] = "0010_environment_interaction_effects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "characters",
        sa.Column("skills", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "characters",
        sa.Column(
            "skill_experience",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "characters",
        sa.Column(
            "resource_state",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "characters",
        sa.Column("gathering_state", sa.JSON(), nullable=True),
    )
    op.add_column(
        "characters",
        sa.Column(
            "active_effects",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("characters", "active_effects")
    op.drop_column("characters", "gathering_state")
    op.drop_column("characters", "resource_state")
    op.drop_column("characters", "skill_experience")
    op.drop_column("characters", "skills")
