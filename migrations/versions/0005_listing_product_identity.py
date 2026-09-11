"""Add the source product to the card listing identity.

Revision ID: 0005_listing_product_identity
Revises: 820269ec1b4d
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_listing_product_identity"
down_revision = "820269ec1b4d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "card_listings",
        sa.Column("source_product_key", sa.String(512), nullable=True),
    )
    op.execute(
        r"""
        UPDATE card_listings
        SET source_product_key = lower(
            regexp_replace(
                trim(
                    CASE
                        WHEN ygo_set <> ''
                         AND right(name, length(' - ' || ygo_set)) = ' - ' || ygo_set
                        THEN left(name, length(name) - length(' - ' || ygo_set))
                        ELSE name
                    END
                ),
                '\s+',
                ' ',
                'g'
            )
        )
        WHERE source_product_key IS NULL
        """
    )
    op.alter_column("card_listings", "source_product_key", nullable=False)
    op.drop_constraint(
        "uq_card_listings_source_code_condition",
        "card_listings",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_card_listings_source_product_code_condition",
        "card_listings",
        ["source", "source_product_key", "code", "condition"],
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM card_listings
                GROUP BY source, code, condition
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade: listing variants share source, code, and condition';
            END IF;
        END $$
        """
    )
    op.drop_constraint(
        "uq_card_listings_source_product_code_condition",
        "card_listings",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_card_listings_source_code_condition",
        "card_listings",
        ["source", "code", "condition"],
    )
    op.drop_column("card_listings", "source_product_key")
