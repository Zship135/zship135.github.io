"""Add parties, scoped enemy populations, and timed combat queues."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_parties_and_combat"
down_revision: Union[str, None] = "0008_enemy_populations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("enemy_spawns", sa.Column("scope_type", sa.String(length=16), nullable=True))
    op.add_column("enemy_spawns", sa.Column("scope_id", sa.String(length=36), nullable=True))
    op.create_index(
        "ix_enemy_spawns_scope_location_alive",
        "enemy_spawns",
        ["scope_type", "scope_id", "location_id", "is_alive"],
        unique=False,
    )

    op.create_table(
        "parties",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("leader_account_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["leader_account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_parties_leader_account_id", "parties", ["leader_account_id"], unique=False)

    op.create_table(
        "party_members",
        sa.Column("party_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["party_id"], ["parties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("party_id", "account_id"),
        sa.UniqueConstraint("account_id", name="uq_party_members_account"),
    )
    op.create_index(
        "ix_party_members_party_joined",
        "party_members",
        ["party_id", "joined_at"],
        unique=False,
    )

    op.create_table(
        "party_invites",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("party_id", sa.String(length=36), nullable=False),
        sa.Column("sender_account_id", sa.String(length=36), nullable=False),
        sa.Column("recipient_account_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'cancelled')",
            name="ck_party_invites_status",
        ),
        sa.ForeignKeyConstraint(["party_id"], ["parties.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_party_invites_recipient_status",
        "party_invites",
        ["recipient_account_id", "status"],
        unique=False,
    )
    op.create_index("ix_party_invites_party_id", "party_invites", ["party_id"], unique=False)
    op.create_index(
        "ix_party_invites_sender_account_id",
        "party_invites",
        ["sender_account_id"],
        unique=False,
    )
    op.create_index(
        "ix_party_invites_recipient_account_id",
        "party_invites",
        ["recipient_account_id"],
        unique=False,
    )
    op.create_index(
        "uq_party_invites_pending_pair",
        "party_invites",
        ["party_id", "recipient_account_id"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "uq_party_invites_pending_recipient",
        "party_invites",
        ["recipient_account_id"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "combat_encounters",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("party_id", sa.String(length=36), nullable=True),
        sa.Column("solo_account_id", sa.String(length=36), nullable=True),
        sa.Column("location_id", sa.String(length=64), nullable=False),
        sa.Column("round_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("round_started_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(party_id IS NOT NULL AND solo_account_id IS NULL) OR "
            "(party_id IS NULL AND solo_account_id IS NOT NULL)",
            name="ck_combat_encounters_single_scope",
        ),
        sa.CheckConstraint("round_number >= 1", name="ck_combat_encounters_round_number"),
        sa.ForeignKeyConstraint(["party_id"], ["parties.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["solo_account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("party_id", "location_id", name="uq_combat_encounters_party_area"),
        sa.UniqueConstraint(
            "solo_account_id",
            "location_id",
            name="uq_combat_encounters_solo_area",
        ),
    )
    op.create_index(
        "ix_combat_encounters_party_id",
        "combat_encounters",
        ["party_id"],
        unique=False,
    )
    op.create_index(
        "ix_combat_encounters_solo_account_id",
        "combat_encounters",
        ["solo_account_id"],
        unique=False,
    )
    op.create_index(
        "ix_combat_encounters_location_id",
        "combat_encounters",
        ["location_id"],
        unique=False,
    )

    op.create_table(
        "combat_encounter_enemies",
        sa.Column("encounter_id", sa.String(length=36), nullable=False),
        sa.Column("enemy_spawn_id", sa.String(length=36), nullable=False),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["enemy_spawn_id"],
            ["enemy_spawns.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["encounter_id"],
            ["combat_encounters.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("encounter_id", "enemy_spawn_id"),
        sa.UniqueConstraint("enemy_spawn_id", name="uq_combat_encounter_enemy_spawn"),
    )
    op.create_index(
        "ix_combat_encounter_enemies_encounter",
        "combat_encounter_enemies",
        ["encounter_id"],
        unique=False,
    )

    op.create_table(
        "combat_actions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("encounter_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("command_id", sa.String(length=36), nullable=False),
        sa.Column("occurrence_index", sa.Integer(), nullable=False),
        sa.Column("occurrence", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "occurrence_index >= 0",
            name="ck_combat_actions_occurrence_index",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'resolved', 'cancelled')",
            name="ck_combat_actions_status",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["command_id"], ["commands.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["encounter_id"],
            ["combat_encounters.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "command_id",
            "occurrence_index",
            name="uq_combat_actions_command_occurrence",
        ),
    )
    op.create_index("ix_combat_actions_encounter_id", "combat_actions", ["encounter_id"], unique=False)
    op.create_index("ix_combat_actions_account_id", "combat_actions", ["account_id"], unique=False)
    op.create_index("ix_combat_actions_command_id", "combat_actions", ["command_id"], unique=False)
    op.create_index(
        "ix_combat_actions_queue",
        "combat_actions",
        ["encounter_id", "status", "submitted_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_combat_actions_queue", table_name="combat_actions")
    op.drop_index("ix_combat_actions_command_id", table_name="combat_actions")
    op.drop_index("ix_combat_actions_account_id", table_name="combat_actions")
    op.drop_index("ix_combat_actions_encounter_id", table_name="combat_actions")
    op.drop_table("combat_actions")

    op.drop_index(
        "ix_combat_encounter_enemies_encounter",
        table_name="combat_encounter_enemies",
    )
    op.drop_table("combat_encounter_enemies")

    op.drop_index("ix_combat_encounters_location_id", table_name="combat_encounters")
    op.drop_index("ix_combat_encounters_solo_account_id", table_name="combat_encounters")
    op.drop_index("ix_combat_encounters_party_id", table_name="combat_encounters")
    op.drop_table("combat_encounters")

    op.drop_index("uq_party_invites_pending_recipient", table_name="party_invites")
    op.drop_index("uq_party_invites_pending_pair", table_name="party_invites")
    op.drop_index("ix_party_invites_recipient_account_id", table_name="party_invites")
    op.drop_index("ix_party_invites_sender_account_id", table_name="party_invites")
    op.drop_index("ix_party_invites_party_id", table_name="party_invites")
    op.drop_index("ix_party_invites_recipient_status", table_name="party_invites")
    op.drop_table("party_invites")

    op.drop_index("ix_party_members_party_joined", table_name="party_members")
    op.drop_table("party_members")

    op.drop_index("ix_parties_leader_account_id", table_name="parties")
    op.drop_table("parties")
    op.drop_index("ix_enemy_spawns_scope_location_alive", table_name="enemy_spawns")
    op.drop_column("enemy_spawns", "scope_id")
    op.drop_column("enemy_spawns", "scope_type")
