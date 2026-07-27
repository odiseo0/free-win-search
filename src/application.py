from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api import router
from src.core.services.cache import close_cache, get_cache

API_DESCRIPTION = "Free Win Search es el API de búsqueda de cartas"

OPENAPI_TAGS = [
    {
        "name": "cards",
        "description": "Catálogo propio de cartas de Yu-Gi-Oh!.",
    },
    {
        "name": "card-listings",
        "description": (
            "Publicaciones y resultados externos disponibles para una carta."
        ),
    },
]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    cache = get_cache()

    try:
        await cache.start()
        yield
    finally:
        await close_cache()


app = FastAPI(
    title="Free Win Search",
    description=API_DESCRIPTION,
    version="0.1.0",
    license_info={"name": "MIT"},
    openapi_tags=OPENAPI_TAGS,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/")
async def welcome():
    return {"message": "Bienvenido a Free Win"}
