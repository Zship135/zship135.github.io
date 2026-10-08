"""Add per-character wallets and shop purchase state."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012_currencies_and_shops"
down_revision: Union[str, None] = "0011_item_effects_gathering_skills"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "characters",
        sa.Column("wallet", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "characters",
        sa.Column("shop_state", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("characters", "shop_state")
    op.drop_column("characters", "wallet")
