import json
from collections.abc import Sequence

from src.core.schema import BaseModel
from src.core.services.cache import Cache


async def get_cached_model[Model: BaseModel](
    cache: Cache,
    key: str,
    model: Model,
) -> Model | None:
    value = await cache.get(key)

    if value is None:
        return None

    return model.model_validate_json(value)


async def set_cached_model(
    cache: Cache,
    key: str,
    value: BaseModel,
    *,
    ttl_seconds: int,
) -> None:
    await cache.set(key, value.model_dump_json(), ttl_seconds=ttl_seconds)


async def get_cached_models[Model: BaseModel](
    cache: Cache,
    key: str,
    model: Model,
) -> list[Model] | None:
    value = await cache.get(key)

    if value is None:
        return None

    payload = json.loads(value)
    return [model.model_validate(item) for item in payload]


async def set_cached_models(
    cache: Cache,
    key: str,
    values: Sequence[BaseModel],
    *,
    ttl_seconds: int,
) -> None:
    serialized = json.dumps(
        [value.model_dump(mode="json") for value in values],
        separators=(",", ":"),
    )
    await cache.set(key, serialized, ttl_seconds=ttl_seconds)
