from __future__ import annotations

from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, MappedAsDataclass, mapped_column, relationship

from src.core.db import Base, Date


class Card(MappedAsDataclass, Base, Date, kw_only=True):
    id: Mapped[int] = mapped_column(
        BigInteger,
        init=False,
        autoincrement=True,
        primary_key=True,
    )
    ygo_id: Mapped[int] = mapped_column(BigInteger)
    sets: Mapped[dict] = mapped_column(JSONB)
    card_type: Mapped[str]
    race: Mapped[str]
    name: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    attribute: Mapped[str | None]
    prices: Mapped[dict] = mapped_column(JSONB)
    images: Mapped[dict] = mapped_column(JSONB)


class CardListing(MappedAsDataclass, Base, Date, kw_only=True):
    __table_args__ = (
        UniqueConstraint("code", "condition", name="uq_card_listings_code_condition"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        init=False,
        autoincrement=True,
        primary_key=True,
    )
    card_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("cards.id", ondelete="SET NULL"),
        default=None,
        nullable=True,
    )
    ygo_id: Mapped[int | None] = mapped_column(
        BigInteger,
        default=None,
        nullable=True,
    )
    ygo_set: Mapped[str]
    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str]
    price: Mapped[Decimal]
    rarity: Mapped[str]
    condition: Mapped[str]
    stock: Mapped[int] = mapped_column(default=0)

    card: Mapped[Card | None] = relationship("Card", lazy="selectin", init=False)
