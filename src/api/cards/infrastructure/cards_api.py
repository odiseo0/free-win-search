from typing import Annotated, assert_never

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.cards.application import (
    create,
    get_detail,
    get_multi,
    remove,
    search_cards,
    update,
)
from src.api.cards.application.search import CardSearch
from src.api.cards.application.search_deps import get_card_search
from src.api.cards.domain import (
    CardCreate,
    CardDetailResponse,
    CardListResponse,
    CardNotFound,
    CardResponse,
    CardSearchResponse,
    CardUpdate,
)
from src.core import Err, Ok
from src.core.db import get_db
from src.core.schema import (
    FORBIDDEN_RESPONSE,
    NOT_FOUND_RESPONSE,
    UNAUTHORIZED_RESPONSE,
    VALIDATION_RESPONSE,
)
from src.core.services.cache import Cache, get_cache

router = APIRouter(tags=["cards"])

type CardId = Annotated[
    int,
    Path(gt=0, description="Identificador positivo de la carta."),
]

_AUTH_RESPONSES = {
    401: UNAUTHORIZED_RESPONSE,
    403: FORBIDDEN_RESPONSE,
    422: VALIDATION_RESPONSE,
}
_CARD_NOT_FOUND_RESPONSE = {
    **NOT_FOUND_RESPONSE,
    "description": "La carta no existe.",
}


@router.get(
    "/search",
    response_model=CardSearchResponse,
    operation_id="searchCards",
    summary="Buscar cartas del catálogo",
    responses={**_AUTH_RESPONSES, 503: {"description": "Búsqueda no disponible."}},
)
async def search_card_catalog(
    db: Annotated[AsyncSession, Depends(get_db)],
    search_backend: Annotated[CardSearch | None, Depends(get_card_search)],
    query: Annotated[str, Query(min_length=1, max_length=255, pattern=r".*\S.*")],
    page: Annotated[int, Query(ge=1)] = 1,
    shows: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CardSearchResponse:
    result = await search_cards(db, search_backend, query, page=page, shows=shows)

    match result:
        case Ok(response):
            return response
        case Err():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="La búsqueda no está disponible",
            )


@router.get(
    "/",
    status_code=status.HTTP_200_OK,
    response_model=CardListResponse,
    operation_id="listCards",
    summary="Listar cartas",
    description=(
        "Devuelve una página del catálogo propio. La implementación consulta primero "
        "la caché y responde con los elementos de la página y el total disponible."
    ),
    responses=_AUTH_RESPONSES,
)
async def read_cards(
    db: Annotated[AsyncSession, Depends(get_db)],
    cache: Annotated[Cache, Depends(get_cache)],
    page: Annotated[
        int, Query(ge=1, description="Página solicitada; comienza en 1.")
    ] = 1,
    shows: Annotated[
        int,
        Query(ge=1, le=100, description="Cantidad máxima de cartas por página."),
    ] = 100,
) -> CardListResponse:
    result = await get_multi(db, cache, page=page, shows=shows)

    match result:
        case Ok(response):
            return response
        case Err(error):
            assert_never(error)


@router.get(
    "/{card_id}",
    status_code=status.HTTP_200_OK,
    response_model=CardDetailResponse,
    operation_id="getCard",
    summary="Consultar una carta",
    description="Devuelve una carta persistida del catálogo propio.",
    responses={
        **_AUTH_RESPONSES,
        404: _CARD_NOT_FOUND_RESPONSE,
    },
)
async def read_card(
    db: Annotated[AsyncSession, Depends(get_db)],
    card_id: CardId,
) -> CardDetailResponse:
    result = await get_detail(db, card_id)

    match result:
        case Ok(card):
            return card
        case Err(CardNotFound()):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La carta no existe",
            )
        case unexpected:
            assert_never(unexpected)


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    response_model=CardResponse,
    operation_id="createCard",
    summary="Crear una carta",
    description=(
        "Incorpora al catálogo propio una carta ya transformada desde la fuente "
        "externa y actualiza la caché."
    ),
    responses=_AUTH_RESPONSES,
)
async def create_card(
    db: Annotated[AsyncSession, Depends(get_db)],
    cache: Annotated[Cache, Depends(get_cache)],
    card_in: CardCreate,
) -> CardResponse:
    result = await create(db, cache, card_in)

    match result:
        case Ok(card):
            return card
        case Err(error):
            assert_never(error)


@router.patch(
    "/{card_id}",
    status_code=status.HTTP_200_OK,
    response_model=CardResponse,
    operation_id="updateCard",
    summary="Actualizar una carta",
    description=(
        "Actualiza los campos enviados de una carta persistida y refresca su caché."
    ),
    responses={
        **_AUTH_RESPONSES,
        404: _CARD_NOT_FOUND_RESPONSE,
    },
)
async def update_card(
    db: Annotated[AsyncSession, Depends(get_db)],
    cache: Annotated[Cache, Depends(get_cache)],
    card_id: CardId,
    card_in: CardUpdate,
) -> CardResponse:
    result = await update(db, cache, card_id, card_in)

    match result:
        case Ok(card):
            return card
        case Err(CardNotFound()):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La carta no existe",
            )
        case unexpected:
            assert_never(unexpected)


@router.delete(
    "/{card_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    operation_id="deleteCard",
    summary="Eliminar una carta",
    description="Elimina la carta del catálogo propio y de la caché.",
    responses={
        **_AUTH_RESPONSES,
        404: _CARD_NOT_FOUND_RESPONSE,
    },
)
async def delete_card(
    db: Annotated[AsyncSession, Depends(get_db)],
    cache: Annotated[Cache, Depends(get_cache)],
    card_id: CardId,
) -> Response:
    result = await remove(db, cache, card_id)

    match result:
        case Ok():
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        case Err(CardNotFound()):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La carta no existe",
            )
        case unexpected:
            assert_never(unexpected)
