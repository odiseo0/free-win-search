from __future__ import annotations

import dataclasses
from collections.abc import Awaitable
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import DeclarativeBase, Mapped, declarative_mixin, mapped_column
from sqlalchemy.orm import registry as _registry
from sqlalchemy.util import greenlet_spawn

from src.core.utils.utils import datetime_now, pluralize, to_snake

_T = TypeVar("_T", bound=Any)
meta = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    },
)


class AwaitAttrs:
    class _AwaitAttrGetitem:
        __slots__ = ("_instance",)

        def __init__(self, _instance: Any):
            self._instance = _instance

        def __getattr__(self, name: str) -> Awaitable[Any]:
            return greenlet_spawn(getattr, self._instance, name)

    @property
    def await_attr(self) -> AwaitAttrs._AwaitAttrGetitem:
        """provide awaitable attribute access"""
        return AwaitAttrs._AwaitAttrGetitem(self)

    async def await_load(self, attr: Mapped[_T]) -> _T:
        """typed version of getattr"""
        return await greenlet_spawn(
            getattr,
            self,
            attr.key,  # type: ignore
        )


class Base(AwaitAttrs, DeclarativeBase):
    id: Any
    metadata = meta
    registry = _registry(type_annotation_map={datetime: DateTime(timezone=True)})

    @declared_attr
    @classmethod
    def __tablename__(cls) -> str:
        return pluralize(to_snake(cls.__name__))


@declarative_mixin
class Date:
    date_added: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default_factory=datetime_now,
        server_default=func.now(),
    )
    date_updated: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        nullable=True,
        onupdate=datetime_now,
    )
