"""Create initial persistent Plight tables."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "characters",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("species", sa.String(length=16), nullable=False),
        sa.Column("area_id", sa.String(length=32), nullable=False),
        sa.Column("inventory", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_account_id", "sessions", ["account_id"], unique=False)
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"], unique=False)
    op.create_table(
        "commands",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("raw_text", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "request_id", name="uq_command_account_request"),
    )
    op.create_index("ix_commands_account_id", "commands", ["account_id"], unique=False)
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("channel_id", sa.String(length=128), nullable=False),
        sa.Column("sender_account_id", sa.String(length=36), nullable=False),
        sa.Column("sender_name", sa.String(length=32), nullable=False),
        sa.Column("text", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["sender_account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_messages_channel_id", "chat_messages", ["channel_id"], unique=False)
    op.create_index(
        "ix_chat_messages_sender_account_id", "chat_messages", ["sender_account_id"], unique=False
    )
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"], unique=False)
    op.create_table(
        "event_counters",
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("account_id"),
    )


def downgrade() -> None:
    op.drop_table("event_counters")
    op.drop_index("ix_chat_messages_created_at", table_name="chat_messages")
    op.drop_index("ix_chat_messages_sender_account_id", table_name="chat_messages")
    op.drop_index("ix_chat_messages_channel_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_commands_account_id", table_name="commands")
    op.drop_table("commands")
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_account_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("characters")
    op.drop_table("accounts")
