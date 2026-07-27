from typing import Annotated, assert_never
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from fastapi.responses import ORJSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.cards.application import (
    get_multi_listings,
    get_one_listing,
    get_scrape_job,
    search,
)
from src.api.cards.domain import (
    CardListingListResponse,
    CardListingNotFound,
    CardListingResponse,
    ScrapeAcceptedResponse,
    ScrapeJobNotFound,
    ScrapeJobResponse,
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

router = APIRouter(tags=["card-listings"])
_AUTH_RESPONSES = {
    401: UNAUTHORIZED_RESPONSE,
    403: FORBIDDEN_RESPONSE,
    422: VALIDATION_RESPONSE,
}


@router.get(
    "/search",
    response_model=list[CardListingResponse] | ScrapeAcceptedResponse,
    operation_id="searchCardListings",
    summary="Buscar publicaciones de cartas",
    description=(
        "Consulta caché y PostgreSQL. En un cold miss canónico crea o reutiliza "
        "un trabajo durable y responde 202. Los datos vencidos se sirven mientras "
        "se refrescan en segundo plano."
    ),
    responses={
        **_AUTH_RESPONSES,
        202: {
            "model": ScrapeAcceptedResponse,
            "description": "Trabajo durable creado o reutilizado.",
        },
    },
)
async def search_card_listings(
    db: Annotated[AsyncSession, Depends(get_db)],
    cache: Annotated[Cache, Depends(get_cache)],
    query: Annotated[
        str,
        Query(
            min_length=1,
            max_length=255,
            pattern=r".*\S.*",
            description="Texto no vacío usado para buscar cartas.",
        ),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[CardListingResponse] | Response:
    result = await search(db, cache, query, limit=limit)
    match result:
        case Ok(ScrapeAcceptedResponse() as accepted):
            return ORJSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content=accepted.model_dump(mode="json"),
                headers={"Retry-After": str(accepted.retry_after_seconds)},
            )
        case Ok(listings):
            return listings
        case Err(error):
            assert_never(error)


@router.get(
    "/jobs/{job_id}",
    response_model=ScrapeJobResponse,
    operation_id="getCardListingScrapeJob",
    summary="Consultar el estado de un trabajo de scraping",
    responses={
        **_AUTH_RESPONSES,
        404: {**NOT_FOUND_RESPONSE, "description": "El trabajo no existe."},
    },
)
async def read_scrape_job(
    db: Annotated[AsyncSession, Depends(get_db)],
    job_id: Annotated[UUID, Path(description="UUID del trabajo durable.")],
) -> ScrapeJobResponse:
    result = await get_scrape_job(db, job_id)
    match result:
        case Ok(job):
            return job
        case Err(ScrapeJobNotFound()):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El trabajo de scraping no existe",
            )
        case unexpected:
            assert_never(unexpected)


@router.get(
    "/",
    response_model=CardListingListResponse,
    operation_id="listCardListings",
    summary="Listar publicaciones guardadas",
    responses=_AUTH_RESPONSES,
)
async def read_card_listings(
    db: Annotated[AsyncSession, Depends(get_db)],
    cache: Annotated[Cache, Depends(get_cache)],
    page: Annotated[int, Query(ge=1)] = 1,
    shows: Annotated[int, Query(ge=1, le=100)] = 100,
) -> CardListingListResponse:
    result = await get_multi_listings(db, cache, page=page, shows=shows)
    match result:
        case Ok(response):
            return response
        case Err(error):
            assert_never(error)


@router.get(
    "/{card_listing_id}",
    response_model=CardListingResponse,
    operation_id="getCardListing",
    summary="Consultar una publicación de carta",
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
    card_listing_id: Annotated[int, Path(gt=0)],
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
