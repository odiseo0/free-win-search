"""Track terminal targets and inventory-based refresh state."""

import sqlalchemy as sa
from alembic import op

revision = "0003_scrape_target_state"
down_revision = "0002_scrape_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scrape_targets",
        sa.Column(
            "last_in_stock_count", sa.Integer(), server_default="0", nullable=False
        ),
    )
    op.add_column(
        "scrape_targets",
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "scrape_targets", sa.Column("disabled_reason", sa.String(64), nullable=True)
    )
    op.add_column(
        "scrape_targets",
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "last_in_stock_count_non_negative",
        "scrape_targets",
        "last_in_stock_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "last_in_stock_count_non_negative",
        "scrape_targets",
        type_="check",
    )
    op.drop_column("scrape_targets", "disabled_at")
    op.drop_column("scrape_targets", "disabled_reason")
    op.drop_column("scrape_targets", "is_enabled")
    op.drop_column("scrape_targets", "last_in_stock_count")
