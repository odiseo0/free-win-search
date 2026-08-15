from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, Literal, TypedDict, Unpack, cast

from pydantic import BaseModel
from sqlalchemy import asc, desc, insert
from sqlalchemy import delete as sql_delete
from sqlalchemy import func as sql_func
from sqlalchemy import update as sql_update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, RelationshipProperty, strategy_options
from sqlalchemy.sql import Select, select

from src.core.utils.filters import OrderBy
from src.core.utils.utils import Empty, EmptyType

from .model import Base

StrategyOptions = Literal[
    "contains_eager",
    "defaultload",
    "defer",
    "immediateload",
    "joinedload",
    "lazyload",
    "Load",
    "load_only",
    "noload",
    "raiseload",
    "selectin_polymorphic",
    "selectinload",
    "subqueryload",
    "undefer",
    "undefer_group",
    "with_expression",
]


class KnownExecutionOptions(TypedDict, total=False):
    compiled_cache: dict[str, Literal["compiled"]] | None
    logging_token: str
    isolation_level: Literal[
        "SERIALIZABLE",
        "REPEATABLE READ",
        "READ COMMITTED",
        "READ UNCOMMITTED",
        "AUTOCOMMIT",
    ]
    no_parameters: bool
    stream_results: bool
    max_row_buffer: int
    yield_per: int
    insertmanyvalues_page_size: int
    schema_translate_map: dict[str | None, str | None] | None
    populate_existing: bool
    autoflush: bool
    synchronize_session: Literal[False, "auto", "evaluate", "fetch"]
    dml_strategy: Literal["bulk", "raw", "orm", "auto"]
    is_delete_using: bool
    is_update_from: bool
    render_nulls: bool


class Kwargs(TypedDict, total=False):
    bind_arguments: dict[str, Any]
    execution_options: KnownExecutionOptions


class DAOError(Exception):
    """Base error for persistence failures handled by the generic DAO."""


class DAOIntegrityError(DAOError):
    """A database constraint rejected a persistence operation."""


@contextmanager
def catch_sqlalchemy_exception() -> Generator[None]:
    try:
        yield
    except IntegrityError as error:
        raise DAOIntegrityError from error
    except SQLAlchemyError as error:
        raise DAOError from error


class DAO[ModelType: Base, CreateSchema: BaseModel, UpdateSchema: BaseModel]:
    def __init__(
        self,
        model: type[ModelType],
        *,
        default_options: list[tuple[str, StrategyOptions]] | None = None,
    ):
        self.model = model
        self.default_options = default_options

    async def get(
        self,
        db: AsyncSession,
        _id: int,
        options: list[tuple[str, StrategyOptions]] | None = None,
        *,
        for_update: bool = False,
        **kwargs: Unpack[Kwargs],
    ) -> ModelType | EmptyType:
        statement = select(self.model).where(self.model.id == _id)

        effective_options = options if options is not None else self.default_options

        if effective_options is not None:
            statement = self.options(statement, effective_options)

        if for_update:
            statement = statement.with_for_update()

        result = (await db.execute(statement, **kwargs)).unique().scalar_one_or_none()

        if result is None:
            return Empty

        return result

    async def get_for_update(
        self,
        db: AsyncSession,
        _id: int,
        options: list[tuple[str, StrategyOptions]] | None = None,
        **kwargs: Unpack[Kwargs],
    ) -> ModelType | EmptyType:
        return await self.get(
            db,
            _id,
            options=options,
            for_update=True,
            **kwargs,
        )

    async def get_by(
        self,
        db: AsyncSession,
        where: dict[str, Any],
        options: list[tuple[str, StrategyOptions]] | None = None,
        **kwargs: Unpack[Kwargs],
    ) -> ModelType | EmptyType:
        statement = select(self.model)

        if where is not None:
            statement = statement.where(
                *[getattr(self.model, k) == v for k, v in where.items()],
            )

        if options is not None:
            statement = self.options(statement, options)

        result = (await db.execute(statement, **kwargs)).unique().scalar_one_or_none()

        if result is None:
            return Empty

        return result

    async def get_multi(
        self,
        db: AsyncSession,
        *,
        where: dict[str, Any] | None = None,
        page: int = 0,
        shows: int | None = 100,
        ordering: list[tuple[str, bool]] | None = None,
        options: list[tuple[str, StrategyOptions]] | None = None,
        **kwargs: Unpack[Kwargs],
    ) -> tuple[list[ModelType], int]:
        statement = select(self.model)

        if where is not None:
            conditions = []

            for k, v in where.items():
                attr = getattr(self.model, k)

                if isinstance(v, list | tuple):
                    conditions.append(attr.in_(v))
                else:
                    conditions.append(attr == v)

            statement = statement.where(*conditions)

        if ordering is None:
            ordering = [("date_added", True)]

        if options is not None:
            statement = self.options(statement, options)

        ordered = cast("Select[tuple[ModelType]]", self.order_by(statement, ordering))
        paginated = ordered.offset(page)

        if shows is not None:
            paginated = paginated.limit(shows)

        count = await self.count(db, statement)
        results = (await db.execute(paginated, **kwargs)).unique().scalars().all()

        return results, count

    async def create(
        self,
        db: AsyncSession,
        *,
        obj_in: CreateSchema | dict[str, Any],
        commit: bool = True,
        options: list[tuple[str, StrategyOptions]] | None = None,
        exclude: set[str] | None = None,
    ) -> ModelType:
        if isinstance(obj_in, dict) is False:
            obj_in = cast(CreateSchema, obj_in)
            obj_in = obj_in.model_dump(mode="python", exclude=exclude)

        obj_in = cast("dict[str, Any]", obj_in)  # Redefinition because of type hinting
        stmt = insert(self.model).values(**obj_in).returning(self.model.id)

        with catch_sqlalchemy_exception():
            obj_id = cast("int", (await db.execute(stmt)).unique().scalar_one())

            if commit:
                await db.commit()

        created = await self.get(db, obj_id, options)

        if created is Empty:
            raise DAOError("El registro creado no pudo recuperarse")

        return created

    async def add(
        self,
        db: AsyncSession,
        db_object: ModelType,
        *,
        flush: bool = True,
    ) -> ModelType:
        db.add(db_object)

        if flush:
            await self.flush(db)

        return db_object

    async def flush(self, db: AsyncSession) -> None:
        with catch_sqlalchemy_exception():
            await db.flush()

    async def create_many(
        self,
        db: AsyncSession,
        *,
        objs_in: list[CreateSchema],
        commit: bool = True,
    ) -> list[int]:
        objs_in_data = [obj_in.model_dump(mode="python") for obj_in in objs_in]
        stmnt = (
            insert(self.model)
            .values([{**obj_data} for obj_data in objs_in_data])
            .returning(self.model.id)
        )

        with catch_sqlalchemy_exception():
            ids = (await db.execute(stmnt)).unique().scalars().all()

            if commit:
                await db.commit()

        return ids

    async def update(
        self,
        db: AsyncSession,
        db_obj_id: int,
        obj_in: UpdateSchema | dict[str, Any],
        commit: bool = True,
        options: list[tuple[str, StrategyOptions]] | None = None,
    ) -> ModelType:
        if isinstance(obj_in, dict) is False:
            obj_in = cast(UpdateSchema, obj_in)
            obj_in = obj_in.model_dump(mode="json", exclude_unset=True)

        update_data = cast(
            "dict[str, Any]", obj_in
        )  # Redefinition because of type hinting
        stmt = (
            sql_update(self.model)
            .where(self.model.id == db_obj_id)
            .values(**update_data)
            .returning(self.model.id)
        )

        with catch_sqlalchemy_exception():
            obj_id = (await db.execute(stmt)).scalar_one()

            if commit:
                await db.commit()

        updated = await self.get(db, obj_id, options)

        if updated is Empty:
            raise DAOError("El registro actualizado no pudo recuperarse")

        return updated

    async def delete(
        self, db: AsyncSession, db_object: ModelType, *, commit: bool = True
    ) -> None:
        with catch_sqlalchemy_exception():
            await db.delete(db_object)

            if commit:
                await db.commit()

    async def delete_many(
        self, db: AsyncSession, ids: list[int], *, commit: bool = True
    ) -> list[int]:
        stmnt = (
            sql_delete(self.model)
            .where(self.model.id.in_(ids))
            .returning(self.model.id)
        )

        with catch_sqlalchemy_exception():
            deleted = (await db.execute(stmnt)).scalars().all()

            if commit:
                await db.commit()

        return deleted

    async def count(self, db: AsyncSession, statement: Select) -> int:
        count_statement = statement.with_only_columns(
            sql_func.count(),
            maintain_column_froms=True,
        ).order_by(None)

        return (await db.execute(count_statement)).scalar_one()

    def order_by(
        self,
        statement: Select,
        ordering: list[tuple[str, bool]] | OrderBy | None = None,
    ) -> Select:
        if not ordering:
            return statement

        if isinstance(ordering, OrderBy):
            field = cast(
                "InstrumentedAttribute", getattr(self.model, ordering.order_by)
            )

            return statement.order_by(
                desc(field) if ordering.sort_by == "descending" else asc(field)
            )

        for attr, is_desc in ordering:
            try:
                field = cast("InstrumentedAttribute", getattr(self.model, attr))

                if (
                    isinstance(field.prop, RelationshipProperty)
                    and field.prop.lazy != "joined"
                ):
                    statement = statement.join(field)

                statement = statement.order_by(desc(field) if is_desc else asc(field))
            except AttributeError:
                # NOTE: Handle this error better.
                raise DAOError("Error")

        return statement

    def options(
        self,
        statement: Select,
        options: list[tuple[str, StrategyOptions]] | None = None,
    ) -> Select:
        if not options:
            return statement

        for attr, strat_op in options:
            try:
                field = cast("InstrumentedAttribute", getattr(self.model, attr))

                statement = statement.options(
                    getattr(strategy_options, strat_op)(field)
                )
            except AttributeError:
                raise DAOError("Error")

        return statement
