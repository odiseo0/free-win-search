"""Typed card collections and durable search index outbox."""

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision = "0004_card_search"
down_revision = "0003_scrape_target_state"
branch_labels = None
depends_on = None


def _verify_card_arrays() -> None:
    if context.is_offline_mode():
        return
    invalid = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM cards "
            "WHERE jsonb_typeof(sets) <> 'array' "
            "OR jsonb_typeof(images) <> 'array' "
            "OR jsonb_typeof(prices) <> 'array'"
        )
    ).scalar_one()
    if invalid:
        raise RuntimeError(
            f"Cannot migrate cards: {invalid} row(s) contain non-array "
            "sets, images or prices; resolve them explicitly first"
        )


def upgrade() -> None:
    _verify_card_arrays()
    op.create_check_constraint(
        "sets_json_array", "cards", "jsonb_typeof(sets) = 'array'"
    )
    op.create_check_constraint(
        "prices_json_array", "cards", "jsonb_typeof(prices) = 'array'"
    )
    op.create_check_constraint(
        "images_json_array", "cards", "jsonb_typeof(images) = 'array'"
    )
    op.create_index(
        "ix_card_listings_upper_code",
        "card_listings",
        [sa.text("upper(code)")],
    )
    op.create_table(
        "search_index_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("card_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remote_task_uid", sa.BigInteger(), nullable=True),
        sa.Column("last_error", sa.String(255), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "date_added",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("date_updated", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        sa.PrimaryKeyConstraint("id", name="pk_search_index_events"),
    )
    op.create_index(
        "ix_search_index_events_card_id", "search_index_events", ["card_id"]
    )
    op.create_index(
        "ix_search_index_events_claim",
        "search_index_events",
        ["status", "available_at"],
    )


def downgrade() -> None:
    op.drop_table("search_index_events")
    op.drop_index("ix_card_listings_upper_code", table_name="card_listings")
    op.drop_constraint("images_json_array", "cards", type_="check")
    op.drop_constraint("prices_json_array", "cards", type_="check")
    op.drop_constraint("sets_json_array", "cards", type_="check")
