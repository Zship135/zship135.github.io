"""Add character appearance and case-insensitive unique names."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_character_creation"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("characters", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column(
                "appearance",
                sa.JSON(),
                server_default=sa.text("'{}'"),
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("name_key", sa.String(length=64), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, name FROM characters")).all()
    normalized_names: dict[str, str] = {}
    for character_id, name in rows:
        name_key = " ".join(name.split()).casefold()
        if name_key in normalized_names:
            raise RuntimeError(
                "Cannot enforce unique character names: existing names collide without regard to case."
            )
        normalized_names[name_key] = character_id
        connection.execute(
            sa.text("UPDATE characters SET name_key = :name_key WHERE id = :character_id"),
            {"name_key": name_key, "character_id": character_id},
        )

    with op.batch_alter_table("characters", recreate="always") as batch_op:
        batch_op.alter_column(
            "name_key",
            existing_type=sa.String(length=64),
            nullable=False,
        )
        batch_op.create_unique_constraint("uq_characters_name_key", ["name_key"])


def downgrade() -> None:
    with op.batch_alter_table("characters", recreate="always") as batch_op:
        batch_op.drop_constraint("uq_characters_name_key", type_="unique")
        batch_op.drop_column("name_key")
        batch_op.drop_column("appearance")
