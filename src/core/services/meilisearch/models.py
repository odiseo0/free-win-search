from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
type SearchFilter = str | list[str | list[str]]


class MeilisearchModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
    )


class MeilisearchRequestModel(MeilisearchModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class Health(MeilisearchModel):
    status: str


class Version(MeilisearchModel):
    commit_sha: str
    commit_date: str
    pkg_version: str


class IndexInfo(MeilisearchModel):
    uid: str
    primary_key: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PaginationSettings(MeilisearchRequestModel):
    max_total_hits: int = Field(ge=0)


class IndexSettingsUpdate(MeilisearchRequestModel):
    displayed_attributes: list[str] | None = None
    searchable_attributes: list[str] | None = None
    filterable_attributes: list[str | JsonObject] | None = None
    sortable_attributes: list[str] | None = None
    ranking_rules: list[str] | None = None
    distinct_attribute: str | None = None
    stop_words: list[str] | None = None
    synonyms: dict[str, list[str]] | None = None
    typo_tolerance: JsonObject | None = None
    pagination: PaginationSettings | None = None
    faceting: JsonObject | None = None
    search_cutoff_ms: int | None = Field(default=None, ge=0)


class IndexSettings(IndexSettingsUpdate):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
    )


class SearchQuery(MeilisearchRequestModel):
    q: str = ""
    offset: int | None = Field(default=None, ge=0)
    limit: int | None = Field(default=None, ge=0)
    page: int | None = Field(default=None, ge=1)
    hits_per_page: int | None = Field(default=None, ge=0)
    attributes_to_retrieve: list[str] | None = None
    attributes_to_crop: list[str] | None = None
    crop_length: int | None = Field(default=None, ge=0)
    crop_marker: str | None = None
    attributes_to_highlight: list[str] | None = None
    highlight_pre_tag: str | None = None
    highlight_post_tag: str | None = None
    show_matches_position: bool | None = None
    filter: SearchFilter | None = None
    sort: list[str] | None = None
    distinct: str | None = None
    facets: list[str] | None = None
    attributes_to_search_on: list[str] | None = None
    matching_strategy: Literal["last", "all", "frequency"] | None = None
    ranking_score_threshold: float | None = Field(default=None, ge=0, le=1)
    show_ranking_score: bool | None = None
    show_ranking_score_details: bool | None = None


class SearchResult(MeilisearchModel):
    hits: list[JsonObject]
    query: str = ""
    processing_time_ms: int = Field(default=0, ge=0)
    offset: int | None = Field(default=None, ge=0)
    limit: int | None = Field(default=None, ge=0)
    estimated_total_hits: int | None = Field(default=None, ge=0)
    page: int | None = Field(default=None, ge=0)
    hits_per_page: int | None = Field(default=None, ge=0)
    total_pages: int | None = Field(default=None, ge=0)
    total_hits: int | None = Field(default=None, ge=0)
    facet_distribution: dict[str, dict[str, int]] | None = None
    facet_stats: JsonObject | None = None


class TaskStatus(StrEnum):
    ENQUEUED = "enqueued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class TaskError(MeilisearchModel):
    message: str
    code: str | None = None
    type: str | None = None
    link: str | None = None


class TaskInfo(MeilisearchModel):
    task_uid: int = Field(ge=0)
    index_uid: str | None = None
    status: TaskStatus
    type: str
    enqueued_at: datetime
    custom_metadata: str | None = None


class Task(MeilisearchModel):
    uid: int = Field(ge=0)
    batch_uid: int | None = Field(default=None, ge=0)
    index_uid: str | None = None
    status: TaskStatus
    type: str
    canceled_by: int | None = Field(default=None, ge=0)
    details: JsonObject | None = None
    error: TaskError | None = None
    duration: str | None = None
    enqueued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    custom_metadata: str | None = None
