from __future__ import annotations

from typing import TypeVar

from pydantic import Field

from .base import BaseModel

T = TypeVar("T")


class ErrorResponse(BaseModel):
    detail: str = Field(
        description="Mensaje comprensible que explica el error recuperable.",
        examples=["El recurso no existe"],
    )


class ValidationErrorDetail(BaseModel):
    type: str
    loc: list[str | int]
    msg: str
    input: object | None = None
    ctx: dict[str, object] | None = None


class ValidationErrorResponse(BaseModel):
    detail: list[ValidationErrorDetail]


class PaginatedResponse[T](BaseModel):
    items: list[T]
    total: int = Field(ge=0)


UNAUTHORIZED_RESPONSE = {
    "model": ErrorResponse,
    "description": "No existe una identidad autenticada válida.",
}
FORBIDDEN_RESPONSE = {
    "model": ErrorResponse,
    "description": "La identidad no posee el permiso requerido.",
}
NOT_FOUND_RESPONSE = {
    "model": ErrorResponse,
    "description": "El recurso solicitado no existe o no es visible.",
}
CONFLICT_RESPONSE = {
    "model": ErrorResponse,
    "description": "La operación entra en conflicto con el estado actual del recurso.",
}
VALIDATION_RESPONSE = {
    "model": ValidationErrorResponse,
    "description": "La entrada no cumple el contrato de la operación.",
}
