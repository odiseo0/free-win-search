"""Durable scrape targets, jobs, and idempotent listing reconciliation."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_scrape_pipeline"
down_revision = "0001_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_cards_ygo_id", "cards", ["ygo_id"])
    op.create_index("ix_cards_ygo_id", "cards", ["ygo_id"])
    op.add_column(
        "card_listings",
        sa.Column(
            "source", sa.String(64), server_default="coolstuffinc", nullable=False
        ),
    )
    op.add_column(
        "card_listings",
        sa.Column("currency", sa.String(3), server_default="USD", nullable=False),
    )
    op.add_column(
        "card_listings",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "card_listings",
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.drop_constraint(
        "uq_card_listings_code_condition", "card_listings", type_="unique"
    )
    op.create_unique_constraint(
        "uq_card_listings_source_code_condition",
        "card_listings",
        ["source", "code", "condition"],
    )
    op.create_check_constraint(
        "ck_card_listings_price_non_negative", "card_listings", "price >= 0"
    )
    op.create_check_constraint(
        "ck_card_listings_stock_non_negative", "card_listings", "stock >= 0"
    )

    op.create_table(
        "scrape_targets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("card_id", sa.BigInteger(), nullable=False),
        sa.Column("ygo_id", sa.BigInteger(), nullable=False),
        sa.Column("canonical_name", sa.String(255), nullable=False),
        sa.Column(
            "last_requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_result_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "date_added",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("date_updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_scrape_targets"),
        sa.UniqueConstraint("card_id", name="uq_scrape_targets_card_id"),
        sa.UniqueConstraint("ygo_id", name="uq_scrape_targets_ygo_id"),
    )
    op.create_index("ix_scrape_targets_card_id", "scrape_targets", ["card_id"])
    op.create_index("ix_scrape_targets_ygo_id", "scrape_targets", ["ygo_id"])

    op.create_table(
        "scrape_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column(
            "date_added",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("date_updated", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "attempts >= 0", name="ck_scrape_jobs_attempts_non_negative"
        ),
        sa.ForeignKeyConstraint(
            ["target_id"], ["scrape_targets.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scrape_jobs"),
    )
    op.create_index("ix_scrape_jobs_target_id", "scrape_jobs", ["target_id"])
    op.create_index(
        "ix_scrape_jobs_claim",
        "scrape_jobs",
        ["status", "available_at", "priority"],
    )
    op.create_index(
        "uq_scrape_jobs_active_target",
        "scrape_jobs",
        ["target_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running', 'retry_wait')"),
    )


def downgrade() -> None:
    op.drop_table("scrape_jobs")
    op.drop_table("scrape_targets")
    op.drop_constraint(
        "ck_card_listings_stock_non_negative", "card_listings", type_="check"
    )
    op.drop_constraint(
        "ck_card_listings_price_non_negative", "card_listings", type_="check"
    )
    op.drop_constraint(
        "uq_card_listings_source_code_condition", "card_listings", type_="unique"
    )
    op.create_unique_constraint(
        "uq_card_listings_code_condition", "card_listings", ["code", "condition"]
    )
    for column in ("is_active", "last_seen_at", "currency", "source"):
        op.drop_column("card_listings", column)
    op.drop_index("ix_cards_ygo_id", table_name="cards")
    op.drop_constraint("uq_cards_ygo_id", "cards", type_="unique")
