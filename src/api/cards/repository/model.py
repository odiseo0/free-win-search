from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.db import Base, Date


class Card(Date, Base, kw_only=True):
    __table_args__ = (
        CheckConstraint("jsonb_typeof(sets) = 'array'", name="sets_json_array"),
        CheckConstraint("jsonb_typeof(prices) = 'array'", name="prices_json_array"),
        CheckConstraint("jsonb_typeof(images) = 'array'", name="images_json_array"),
    )
    id: Mapped[int] = mapped_column(
        BigInteger,
        init=False,
        autoincrement=True,
        primary_key=True,
    )
    ygo_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    sets: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    card_type: Mapped[str]
    race: Mapped[str]
    name: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    attribute: Mapped[str | None]
    prices: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    images: Mapped[list[dict[str, object]]] = mapped_column(JSONB)


class CardListing(Date, Base, kw_only=True):
    __table_args__ = (
        UniqueConstraint(
            "source",
            "code",
            "condition",
            name="uq_card_listings_source_code_condition",
        ),
        CheckConstraint("price >= 0", name="price_non_negative"),
        CheckConstraint("stock >= 0", name="stock_non_negative"),
        Index("ix_card_listings_upper_code", text("upper(code)")),
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
    source: Mapped[str] = mapped_column(String(64), default="coolstuffinc")
    ygo_set: Mapped[str]
    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str]
    price: Mapped[Decimal]
    rarity: Mapped[str]
    condition: Mapped[str]
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    stock: Mapped[int] = mapped_column(default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    card: Mapped[Card | None] = relationship("Card", lazy="selectin", init=False)


class SearchIndexEvent(Date, Base, kw_only=True):
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        Index("ix_search_index_events_claim", "status", "available_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    card_id: Mapped[int] = mapped_column(BigInteger, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )
    remote_task_uid: Mapped[int | None] = mapped_column(
        BigInteger, default=None, nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(
        String(255), default=None, nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )


class ScrapeTarget(Date, Base, kw_only=True):
    __table_args__ = (
        CheckConstraint(
            "last_in_stock_count >= 0",
            name="last_in_stock_count_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, init=False, autoincrement=True, primary_key=True
    )
    card_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cards.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    ygo_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    canonical_name: Mapped[str] = mapped_column(String(255))
    last_requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_succeeded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )
    next_refresh_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )
    last_result_count: Mapped[int] = mapped_column(Integer, default=0)
    last_in_stock_count: Mapped[int] = mapped_column(Integer, default=0)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    disabled_reason: Mapped[str | None] = mapped_column(
        String(64), default=None, nullable=True
    )
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )


class ScrapeJob(Date, Base, kw_only=True):
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        Index(
            "uq_scrape_jobs_active_target",
            "target_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running', 'retry_wait')"),
        ),
        Index("ix_scrape_jobs_claim", "status", "available_at", "priority"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default_factory=uuid4,
        insert_default=uuid4,
    )
    target_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("scrape_targets.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="pending")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(
        String(64), default=None, nullable=True
    )

    target: Mapped[ScrapeTarget] = relationship(
        "ScrapeTarget", lazy="joined", init=False
    )
