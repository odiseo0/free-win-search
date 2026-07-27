"""Base cards schema with safe adoption of existing installations."""

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "0001_base"
down_revision = None
branch_labels = None
depends_on = None

EXPECTED = {
    "cards": {
        "id",
        "ygo_id",
        "sets",
        "card_type",
        "race",
        "name",
        "text",
        "attribute",
        "prices",
        "images",
        "date_added",
        "date_updated",
    },
    "card_listings": {
        "id",
        "card_id",
        "ygo_id",
        "ygo_set",
        "name",
        "code",
        "price",
        "rarity",
        "condition",
        "stock",
        "date_added",
        "date_updated",
    },
}


def _verify_existing(inspector) -> bool:
    existing = set(inspector.get_table_names())
    present = existing.intersection(EXPECTED)
    if not present:
        return False
    if present != set(EXPECTED):
        raise RuntimeError(
            "Partial legacy schema found; refusing to mark base revision"
        )
    for table, required in EXPECTED.items():
        actual = {column["name"] for column in inspector.get_columns(table)}
        missing = required - actual
        if missing:
            raise RuntimeError(
                f"Legacy table {table} is missing required columns: {sorted(missing)}"
            )
    return True


def upgrade() -> None:
    # Offline SQL is intended for a new installation and has no inspectable
    # connection. Online upgrades verify/adopt a legacy Search schema safely.
    if not context.is_offline_mode() and _verify_existing(inspect(op.get_bind())):
        return
    op.create_table(
        "cards",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ygo_id", sa.BigInteger(), nullable=False),
        sa.Column("sets", postgresql.JSONB(), nullable=False),
        sa.Column("card_type", sa.String(), nullable=False),
        sa.Column("race", sa.String(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("attribute", sa.String(), nullable=True),
        sa.Column("prices", postgresql.JSONB(), nullable=False),
        sa.Column("images", postgresql.JSONB(), nullable=False),
        sa.Column(
            "date_added",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("date_updated", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_cards"),
    )
    op.create_table(
        "card_listings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("card_id", sa.BigInteger(), nullable=True),
        sa.Column("ygo_id", sa.BigInteger(), nullable=True),
        sa.Column("ygo_set", sa.String(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("price", sa.Numeric(), nullable=False),
        sa.Column("rarity", sa.String(), nullable=False),
        sa.Column("condition", sa.String(), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "date_added",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("date_updated", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_card_listings"),
        sa.UniqueConstraint(
            "code", "condition", name="uq_card_listings_code_condition"
        ),
    )


def downgrade() -> None:
    op.drop_table("card_listings")
    op.drop_table("cards")
