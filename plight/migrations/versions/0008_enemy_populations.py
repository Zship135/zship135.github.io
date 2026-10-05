"""Persist shared enemy populations."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_enemy_populations"
down_revision: Union[str, None] = "0007_fetch_quests_and_experience"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "enemy_spawns",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("location_id", sa.String(length=64), nullable=False),
        sa.Column("enemy_id", sa.String(length=64), nullable=False),
        sa.Column("health", sa.Integer(), nullable=False),
        sa.Column(
            "is_alive",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "is_initial",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("spawned_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("health >= 0", name="ck_enemy_spawns_nonnegative_health"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_enemy_spawns_location_alive",
        "enemy_spawns",
        ["location_id", "is_alive"],
        unique=False,
    )
    op.create_index(
        "ix_enemy_spawns_location_id",
        "enemy_spawns",
        ["location_id"],
        unique=False,
    )
    op.create_index(
        "ix_enemy_spawns_enemy_id",
        "enemy_spawns",
        ["enemy_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_enemy_spawns_enemy_id", table_name="enemy_spawns")
    op.drop_index("ix_enemy_spawns_location_id", table_name="enemy_spawns")
    op.drop_index("ix_enemy_spawns_location_alive", table_name="enemy_spawns")
    op.drop_table("enemy_spawns")
