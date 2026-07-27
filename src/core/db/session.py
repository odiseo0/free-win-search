from asyncio import current_task
from datetime import datetime
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    async_scoped_session,
    async_sessionmaker,
    create_async_engine,
)

from src.core.constants import TZ
from src.core.utils import deserialize_object, serialize_object
from src.settings.db_settings import db_settings

engine = create_async_engine(
    db_settings.SQLALCHEMY_DATABASE_URI,
    json_serializer=serialize_object,
    json_deserializer=deserialize_object,
    pool_size=db_settings.pool_size,
    pool_timeout=db_settings.pool_timeout,
    pool_recycle=db_settings.pool_recycle,
    max_overflow=db_settings.pool_overflow,
    pool_use_lifo=True,
    pool_pre_ping=True,
    connect_args={"server_settings": {"TimeZone": "America/Caracas"}},
)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)
AsyncScopedSession = async_scoped_session(async_session_factory, scopefunc=current_task)


@event.listens_for(engine.sync_engine, "connect")
def _sqla_on_connect(dbapi_connection: Any, _: Any) -> Any:  # pragma: no cover
    """Asyncpg always return the binary format of a datetime with timezone that's always in UTC.
    set the type codec to read dates in the desired timezone.
    """

    def timestamptz_encoder(v: float | str | datetime | None) -> datetime:
        if isinstance(v, int | float):
            return datetime.fromtimestamp(v, tz=TZ).isoformat()
        if isinstance(v, datetime):
            return v.astimezone(TZ).isoformat()
        if isinstance(v, str):
            return datetime.fromisoformat(v).astimezone(TZ).isoformat()

        raise ValueError

    dbapi_connection.await_(
        dbapi_connection.driver_connection.set_type_codec(
            schema="pg_catalog",
            typename="timestamptz",
            encoder=timestamptz_encoder,
            decoder=lambda x: datetime.fromisoformat(x).astimezone(TZ),
        ),
    )
