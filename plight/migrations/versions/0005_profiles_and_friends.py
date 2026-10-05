"""Add player profiles and explicit friend requests."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_profiles_and_friends"
down_revision: Union[str, None] = "0004_repair_combat_json_defaults"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("characters", sa.Column("profile_pronouns", sa.String(length=64), nullable=True))
    op.add_column(
        "characters",
        sa.Column("profile_lore", sa.Text(), server_default="", nullable=False),
    )
    op.add_column("characters", sa.Column("profile_picture_data", sa.LargeBinary(), nullable=True))
    op.add_column("characters", sa.Column("profile_picture_mime", sa.String(length=32), nullable=True))
    op.create_table(
        "friend_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sender_account_id", sa.String(length=36), nullable=False),
        sa.Column("recipient_account_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("sender_account_id != recipient_account_id", name="ck_friend_request_not_self"),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'rejected')", name="ck_friend_request_status"),
        sa.ForeignKeyConstraint(["sender_account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sender_account_id", "recipient_account_id", name="uq_friend_request_pair"),
    )
    op.create_index("ix_friend_requests_sender_account_id", "friend_requests", ["sender_account_id"])
    op.create_index("ix_friend_requests_recipient_account_id", "friend_requests", ["recipient_account_id"])


def downgrade() -> None:
    op.drop_index("ix_friend_requests_recipient_account_id", table_name="friend_requests")
    op.drop_index("ix_friend_requests_sender_account_id", table_name="friend_requests")
    op.drop_table("friend_requests")
    op.drop_column("characters", "profile_picture_mime")
    op.drop_column("characters", "profile_picture_data")
    op.drop_column("characters", "profile_lore")
    op.drop_column("characters", "profile_pronouns")
