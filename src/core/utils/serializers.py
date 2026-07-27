from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import orjson
from asyncpg import pgproto
from pydantic import BaseModel

from src.core.constants import TZ


def add_timezone_to_datetime(dt: datetime) -> str:
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=TZ)

    return dt.isoformat().replace("+00:00", "Z")


def _serialize(value: Any) -> str:
    if isinstance(value, BaseModel):
        return value.model_dump_json(by_alias=True)

    # <hack>
    # In order for `isinstance(pgproto.UUID, uuid.UUID)` to work,
    # patch __bases__ and __mro__ by injecting `uuid.UUID`.
    #
    # We apply brute-force here because the following pattern stopped
    # working with Python 3.8:
    #
    #   cdef class OurUUID:
    #       ...
    #
    #   class UUID(OurUUID, uuid.UUID):
    #       ...
    #
    # With Python 3.8 it now produces
    #
    #   "TypeError: multiple bases have instance lay-out conflict"
    #
    # error.  Maybe it's possible to fix this some other way, but
    # the best solution possible would be to just contribute our
    # faster UUID to the standard library and not have this problem
    # at all.  For now this hack is pretty safe and should be
    # compatible with future Pythons for long enough.

    # FROM: https://github.com/MagicStack/py-pgproto/blob/484e3520d8cb0514b7596a8f9eaa80f3f7b79d0c/uuid.pyx#L307-L336
    # That's why I decided to ignore this error

    if isinstance(value, pgproto.UUID | UUID):  # type: ignore
        return str(value)
    if isinstance(value, datetime):
        return add_timezone_to_datetime(value)

    try:
        val = str(value)
    except Exception as exc:
        raise TypeError from exc
    else:
        return val


def serialize_object(obj: Any) -> str:
    return orjson.dumps(
        obj,
        default=_serialize,
        option=orjson.OPT_NAIVE_UTC | orjson.OPT_SERIALIZE_NUMPY,
    ).decode()


def deserialize_object(
    obj: bytes | bytearray | memoryview | str | dict[str, Any],
) -> Any:
    if isinstance(obj, dict):
        return obj

    return orjson.loads(obj)
