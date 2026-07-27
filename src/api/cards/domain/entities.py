from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from src.core.schema import BaseModel, PaginatedResponse


class Card(BaseModel):
    ygo_id: int | None = Field(
        default=None,
        description="Identificador de la carta en la fuente externa de Yu-Gi-Oh!.",
        examples=[46986414],
    )
    sets: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Sets recibidos de la fuente externa. Su estructura aún no está "
            "normalizada en campos propios."
        ),
    )
    card_type: str | None = Field(
        default=None, description="Tipo de carta informado por la fuente externa."
    )
    race: str | None = Field(
        default=None, description="Raza o categoría informada por la fuente externa."
    )
    name: str | None = Field(default=None, description="Nombre oficial de la carta.")
    text: str | None = Field(
        default=None, description="Texto o efecto oficial de la carta."
    )
    attribute: str | None = Field(
        default=None,
        description="Atributo de la carta, cuando la fuente lo proporciona.",
    )
    prices: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Precios de referencia recibidos de la fuente externa; no representan "
            "el precio definitivo de una Orden."
        ),
    )
    images: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Metadatos de imágenes de la fuente externa, todavía sin normalizar."
        ),
    )


class CardCreate(Card):
    ygo_id: int = Field(
        default=...,
        description="Identificador de la carta en la fuente externa de Yu-Gi-Oh!.",
    )
    sets: dict[str, Any] = Field(
        default=...,
        description=(
            "Sets recibidos de la fuente externa, todavía sin normalizar en campos "
            "propios."
        ),
    )
    card_type: str = Field(
        default=..., description="Tipo de carta (Mágica, Trampa, Monstruo)"
    )
    race: str = Field(default=..., description="Tipo de monstruo.")
    name: str = Field(default=..., description="Nombre oficial de la carta.")
    text: str = Field(default=..., description="Texto oficial de la carta.")
    attribute: str = Field(default=..., description="Atributo de la carta.")
    prices: dict[str, Any] = Field(
        default=...,
        description=(
            "Precios externos de referencia; no representan el precio definitivo "
            "de una Orden."
        ),
    )
    images: dict[str, Any] = Field(
        default=...,
        description="Metadatos externos de imágenes, todavía sin normalizar.",
    )


class CardUpdate(Card):
    pass


class CardResponse(CardCreate):
    id: int = Field(description="Identificador interno de la carta.")
    date_added: datetime = Field(description="Fecha de creación con zona horaria.")
    date_updated: datetime | None = Field(
        default=None,
        description="Última actualización con zona horaria, si ocurrió.",
    )


class CardListResponse(PaginatedResponse[CardResponse]):
    pass


class CardListingResponse(BaseModel):
    id: int | None = Field(
        default=None,
        description="Identificador interno; nulo si el resultado aún no fue persistido.",
    )
    card_id: int | None = Field(
        default=None,
        description="Carta interna vinculada; nula mientras no exista la asociación.",
    )
    ygo_id: int | None = Field(
        default=None,
        description="Identificador externo de la carta, si pudo resolverse.",
    )
    ygo_set: str = Field(description="Set anunciado por la publicación externa.")
    name: str = Field(description="Nombre de la carta en la publicación.")
    code: str = Field(description="Código de set de la publicación.")
    price: Decimal = Field(
        description="Precio unitario observado en la fuente externa, en USD."
    )
    rarity: str = Field(description="Rareza anunciada.")
    condition: str = Field(description="Condición anunciada.")
    stock: int = Field(
        default=0,
        description="Cantidad disponible observada; cero indica falta de stock.",
    )
    source: str = Field(default="coolstuffinc")
    currency: str = Field(default="USD")
    last_seen_at: datetime | None = None
    is_active: bool = True
    date_added: datetime | None = Field(
        default=None,
        description="Fecha de persistencia; nula para resultados aún no guardados.",
    )
    date_updated: datetime | None = Field(
        default=None,
        description="Última actualización persistida, si ocurrió.",
    )


class CardListingListResponse(PaginatedResponse[CardListingResponse]):
    pass


class ScrapeJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ScrapeJobResponse(BaseModel):
    job_id: UUID
    ygo_id: int
    status: ScrapeJobStatus
    attempts: int
    available_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None


class ScrapeAcceptedResponse(BaseModel):
    job_id: UUID
    ygo_id: int
    status: ScrapeJobStatus
    status_url: str
    retry_after_seconds: int = 2
