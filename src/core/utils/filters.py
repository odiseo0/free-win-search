from dataclasses import dataclass
from datetime import date
from typing import Any, Literal


@dataclass
class DateAdded:
    date_added: date | None = None


@dataclass
class Before:
    date_added: date | None = None


@dataclass
class After:
    date_added: date | None = None


@dataclass
class BeforeAfter:
    date_before: date | None = None
    date_after: date | None = None


@dataclass
class OrderBy:
    order_by: str | None = None
    sort_by: Literal["descending", "ascending"] = "descending"


@dataclass
class Pagination:
    page: int
    shows: int


@dataclass
class Search:
    field_name: str | None = None
    value: str | None = None


@dataclass
class FieldFilter:
    field: str | None = None
    value: int | str | None = None


@dataclass
class MonthlyFilter:
    field_name: str | None = None
    month: date | None = None


@dataclass
class AnyFieldFilter:
    any_name: str | None = None
    any_value: Any | None = None


type FilterTypes = (
    Before | After | BeforeAfter | DateAdded | Search | FieldFilter | MonthlyFilter
)
