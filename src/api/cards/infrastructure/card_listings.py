from typing import Annotated, assert_never

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.cards.application import get_multi_listings, get_one_listing, search
from src.api.cards.domain import (
    CardListingListResponse,
    CardListingNotFound,
    CardListingResponse,
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
from src.core.services.scraper import CardListingSearch, get_card_listing_search

router = APIRouter(tags=["card-listings"])

type CardListingId = Annotated[
    int,
    Path(gt=0, description="Identificador positivo de la publicación de carta."),
]

_AUTH_RESPONSES = {
    401: UNAUTHORIZED_RESPONSE,
    403: FORBIDDEN_RESPONSE,
    422: VALIDATION_RESPONSE,
}


@router.get(
    "/search",
    status_code=status.HTTP_200_OK,
    response_model=list[CardListingResponse],
    operation_id="searchCardListings",
    summary="Buscar publicaciones de cartas",
    description=(
        "Busca por nombre o texto en los datos almacenados y, cuando corresponde, "
        "consulta el scraper externo. Los resultados pueden no estar persistidos ni "
        "vinculados todavía con una carta interna."
    ),
    responses=_AUTH_RESPONSES,
)
async def search_card_listings(
    db: Annotated[AsyncSession, Depends(get_db)],
    cache: Annotated[Cache, Depends(get_cache)],
    scraper: Annotated[CardListingSearch, Depends(get_card_listing_search)],
    query: Annotated[
        str,
        Query(
            min_length=1,
            max_length=255,
            pattern=r".*\S.*",
            description="Texto no vacío usado para buscar cartas.",
        ),
    ],
    limit: Annotated[
        int,
        Query(ge=1, le=100, description="Máximo de resultados devueltos."),
    ] = 100,
) -> list[CardListingResponse]:
    result = await search(
        db,
        cache,
        scraper,
        query,
        limit=limit,
    )

    match result:
        case Ok(listings):
            return listings
        case Err(error):
            assert_never(error)


@router.get(
    "/",
    status_code=status.HTTP_200_OK,
    response_model=CardListingListResponse,
    operation_id="listCardListings",
    summary="Listar publicaciones guardadas",
    description=(
        "Devuelve las publicaciones conocidas de la página y el total disponible."
    ),
    responses=_AUTH_RESPONSES,
)
async def read_card_listings(
    db: Annotated[AsyncSession, Depends(get_db)],
    cache: Annotated[Cache, Depends(get_cache)],
    page: Annotated[
        int, Query(ge=1, description="Página solicitada; comienza en 1.")
    ] = 1,
    shows: Annotated[
        int,
        Query(
            ge=1,
            le=100,
            description="Cantidad máxima de publicaciones por página.",
        ),
    ] = 100,
) -> CardListingListResponse:
    result = await get_multi_listings(
        db,
        cache,
        page=page,
        shows=shows,
    )

    match result:
        case Ok(response):
            return response
        case Err(error):
            assert_never(error)


@router.get(
    "/{card_listing_id}",
    status_code=status.HTTP_200_OK,
    response_model=CardListingResponse,
    operation_id="getCardListing",
    summary="Consultar una publicación de carta",
    description=(
        "Devuelve una publicación conocida con precio, stock, condición y rareza."
    ),
    responses={
        **_AUTH_RESPONSES,
        404: {
            **NOT_FOUND_RESPONSE,
            "description": "La publicación de carta no existe.",
        },
    },
)
async def read_card_listing(
    db: Annotated[AsyncSession, Depends(get_db)],
    cache: Annotated[Cache, Depends(get_cache)],
    card_listing_id: CardListingId,
) -> CardListingResponse:
    result = await get_one_listing(db, cache, card_listing_id)

    match result:
        case Ok(listing):
            return listing
        case Err(CardListingNotFound()):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La publicación de la carta no existe",
            )
        case unexpected:
            assert_never(unexpected)
