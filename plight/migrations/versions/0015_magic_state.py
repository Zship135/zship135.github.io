"""Magic state for characters."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0015_magic_state"
down_revision: Union[str, None] = "0014_die_skins"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "characters",
        sa.Column("magic_state", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("characters", "magic_state")
