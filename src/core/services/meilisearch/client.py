from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from time import monotonic
from typing import Any, Self, TypeVar
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ValidationError

from .errors import (
    MeilisearchApiError,
    MeilisearchCommunicationError,
    MeilisearchInvalidResponseError,
    MeilisearchSerializationError,
    MeilisearchTaskCanceledError,
    MeilisearchTaskFailedError,
    MeilisearchTaskWaitTimeoutError,
    MeilisearchTimeoutError,
    MeilisearchValidationError,
)
from .models import (
    Health,
    IndexInfo,
    IndexSettings,
    IndexSettingsUpdate,
    JsonObject,
    JsonValue,
    SearchQuery,
    SearchResult,
    Task,
    TaskInfo,
    TaskStatus,
    Version,
)

_ModelT = TypeVar("_ModelT", bound=BaseModel)
_NO_BODY = object()
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class MeilisearchConfig:
    url: str
    api_key: str | None = None
    timeout_seconds: float = 5.0
    max_connections: int = 20
    max_concurrency: int = 10
    max_retries: int = 2
    retry_backoff_seconds: float = 0.1
    max_retry_delay_seconds: float = 5.0

    def __post_init__(self) -> None:
        parsed_url = httpx.URL(self.url)

        if parsed_url.scheme not in {"http", "https"} or parsed_url.host is None:
            raise MeilisearchValidationError(
                "Meilisearch URL must be an absolute http:// or https:// URL"
            )
        if self.timeout_seconds <= 0:
            raise MeilisearchValidationError("timeout_seconds must be greater than 0")

        if self.max_connections < 1:
            raise MeilisearchValidationError("max_connections must be at least 1")

        if self.max_concurrency < 1:
            raise MeilisearchValidationError("max_concurrency must be at least 1")

        if self.max_retries < 0:
            raise MeilisearchValidationError("max_retries cannot be negative")

        if self.retry_backoff_seconds < 0 or self.max_retry_delay_seconds < 0:
            raise MeilisearchValidationError("retry delays cannot be negative")


class MeilisearchClient:
    def __init__(
        self,
        url: str,
        api_key: str | None = None,
        *,
        timeout_seconds: float = 5.0,
        max_connections: int = 20,
        max_concurrency: int = 10,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.1,
        max_retry_delay_seconds: float = 5.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = MeilisearchConfig(
            url=url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_connections=max_connections,
            max_concurrency=max_concurrency,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            max_retry_delay_seconds=max_retry_delay_seconds,
        )
        self._base_url = httpx.URL(f"{url.rstrip('/')}/")
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._owns_http_client = http_client is None
        self._closed = False
        self._headers = {
            "Accept": "application/json",
            "User-Agent": "free-win-search-meilisearch/0.1",
        }

        if api_key is not None:
            self._headers["Authorization"] = f"Bearer {api_key}"

        self._http = http_client or httpx.AsyncClient(
            timeout=timeout_seconds,
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_connections,
            ),
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._closed:
            return

        self._closed = True

        if self._owns_http_client:
            await self._http.aclose()

    async def health(self) -> Health:
        payload = await self._request("GET", "health", retry_safe=True)

        return self._validate_model(Health, payload, "GET /health")

    async def version(self) -> Version:
        payload = await self._request("GET", "version", retry_safe=True)

        return self._validate_model(Version, payload, "GET /version")

    async def get_index(self, index_uid: str) -> IndexInfo:
        path = self._index_path(index_uid)
        payload = await self._request("GET", path, retry_safe=True)

        return self._validate_model(IndexInfo, payload, f"GET /{path}")

    async def create_index(
        self, index_uid: str, *, primary_key: str | None = None
    ) -> TaskInfo:
        body: JsonObject = {"uid": index_uid}

        if primary_key is not None:
            body["primaryKey"] = primary_key

        payload = await self._request("POST", "indexes", body=body)

        return self._validate_model(TaskInfo, payload, "POST /indexes")

    async def delete_index(self, index_uid: str) -> TaskInfo:
        path = self._index_path(index_uid)
        payload = await self._request("DELETE", path)

        return self._validate_model(TaskInfo, payload, f"DELETE /{path}")

    async def get_settings(self, index_uid: str) -> IndexSettings:
        path = f"{self._index_path(index_uid)}/settings"
        payload = await self._request("GET", path, retry_safe=True)

        return self._validate_model(IndexSettings, payload, f"GET /{path}")

    async def update_settings(
        self, index_uid: str, settings: IndexSettingsUpdate
    ) -> TaskInfo:
        path = f"{self._index_path(index_uid)}/settings"
        body = settings.model_dump(
            by_alias=True,
            exclude_unset=True,
            mode="json",
        )
        payload = await self._request("PATCH", path, body=body)

        return self._validate_model(TaskInfo, payload, f"PATCH /{path}")

    async def add_documents(
        self,
        index_uid: str,
        documents: Sequence[Mapping[str, JsonValue]],
        *,
        primary_key: str | None = None,
        custom_metadata: str | None = None,
    ) -> TaskInfo:
        self._require_documents(documents)
        path = f"{self._index_path(index_uid)}/documents"
        params = self._document_params(primary_key, custom_metadata)
        payload = await self._request(
            "POST",
            path,
            body=list(documents),
            params=params,
        )

        return self._validate_model(TaskInfo, payload, f"POST /{path}")

    async def update_documents(
        self,
        index_uid: str,
        documents: Sequence[Mapping[str, JsonValue]],
        *,
        primary_key: str | None = None,
        custom_metadata: str | None = None,
        skip_creation: bool = False,
    ) -> TaskInfo:
        self._require_documents(documents)
        path = f"{self._index_path(index_uid)}/documents"
        params = self._document_params(primary_key, custom_metadata)

        if skip_creation:
            params["skipCreation"] = "true"

        payload = await self._request(
            "PUT",
            path,
            body=list(documents),
            params=params,
        )

        return self._validate_model(TaskInfo, payload, f"PUT /{path}")

    async def delete_document(self, index_uid: str, document_id: str | int) -> TaskInfo:
        encoded_id = quote(str(document_id), safe="")
        path = f"{self._index_path(index_uid)}/documents/{encoded_id}"
        payload = await self._request("DELETE", path)

        return self._validate_model(TaskInfo, payload, f"DELETE /{path}")

    async def delete_documents(
        self, index_uid: str, document_ids: Sequence[str | int]
    ) -> TaskInfo:
        if not document_ids:
            raise MeilisearchValidationError("document_ids cannot be empty")

        path = f"{self._index_path(index_uid)}/documents/delete-batch"
        payload = await self._request("POST", path, body=list(document_ids))

        return self._validate_model(TaskInfo, payload, f"POST /{path}")

    async def search(self, index_uid: str, query: SearchQuery) -> SearchResult:
        path = f"{self._index_path(index_uid)}/search"
        body = query.model_dump(by_alias=True, exclude_none=True, mode="json")
        payload = await self._request(
            "POST",
            path,
            body=body,
            retry_safe=True,
        )

        return self._validate_model(SearchResult, payload, f"POST /{path}")

    async def get_task(self, task_uid: int) -> Task:
        if task_uid < 0:
            raise MeilisearchValidationError("task_uid cannot be negative")

        path = f"tasks/{task_uid}"
        payload = await self._request("GET", path, retry_safe=True)

        return self._validate_model(Task, payload, f"GET /{path}")

    async def wait_for_task(
        self,
        task_uid: int,
        *,
        timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.05,
    ) -> Task:
        if timeout_seconds <= 0:
            raise MeilisearchValidationError("timeout_seconds must be greater than 0")

        if poll_interval_seconds <= 0:
            raise MeilisearchValidationError(
                "poll_interval_seconds must be greater than 0"
            )

        deadline = monotonic() + timeout_seconds

        while True:
            remaining = deadline - monotonic()

            if remaining <= 0:
                raise MeilisearchTaskWaitTimeoutError(task_uid, timeout_seconds)

            try:
                async with asyncio.timeout(remaining):
                    task = await self.get_task(task_uid)
            except TimeoutError as error:
                raise MeilisearchTaskWaitTimeoutError(
                    task_uid, timeout_seconds
                ) from error

            if task.status is TaskStatus.SUCCEEDED:
                return task

            if task.status is TaskStatus.FAILED:
                message = (
                    task.error.message if task.error else f"Task {task_uid} failed"
                )

                raise MeilisearchTaskFailedError(message, task)

            if task.status is TaskStatus.CANCELED:
                raise MeilisearchTaskCanceledError(
                    f"Task {task_uid} was canceled", task
                )

            remaining = deadline - monotonic()

            if remaining <= 0:
                raise MeilisearchTaskWaitTimeoutError(task_uid, timeout_seconds)

            await asyncio.sleep(min(poll_interval_seconds, remaining))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: object = _NO_BODY,
        params: Mapping[str, str] | None = None,
        retry_safe: bool = False,
    ) -> Any:
        if self._closed:
            raise MeilisearchCommunicationError("Meilisearch client is closed")

        content: str | None = None
        headers = dict(self._headers)

        if body is not _NO_BODY:
            try:
                content = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
            except (TypeError, ValueError) as error:
                raise MeilisearchSerializationError(
                    "Meilisearch request body is not JSON serializable"
                ) from error
            headers["Content-Type"] = "application/json"

        attempts = self.config.max_retries + 1 if retry_safe else 1

        async with self._semaphore:
            for attempt in range(attempts):
                try:
                    response = await self._http.request(
                        method,
                        self._base_url.join(path.lstrip("/")),
                        params=params,
                        content=content,
                        headers=headers,
                        timeout=self.config.timeout_seconds,
                    )
                except httpx.TimeoutException as error:
                    if retry_safe and attempt + 1 < attempts:
                        await self._sleep_before_retry(attempt)

                        continue
                    raise MeilisearchTimeoutError(
                        f"{method} /{path} timed out"
                    ) from error
                except httpx.RequestError as error:
                    if retry_safe and attempt + 1 < attempts:
                        await self._sleep_before_retry(attempt)

                        continue
                    raise MeilisearchCommunicationError(
                        f"Could not complete {method} /{path}"
                    ) from error

                if (
                    retry_safe
                    and response.status_code in _RETRYABLE_STATUS_CODES
                    and attempt + 1 < attempts
                ):
                    await self._sleep_before_retry(
                        attempt,
                        retry_after=response.headers.get("Retry-After"),
                    )

                    continue

                if not response.is_success:
                    raise self._api_error(response)

                if response.status_code == 204 or not response.content:
                    return None

                try:
                    return response.json()
                except ValueError as error:
                    raise MeilisearchInvalidResponseError(
                        f"{method} /{path} returned invalid JSON"
                    ) from error

        raise AssertionError("request loop exhausted without returning")

    async def _sleep_before_retry(
        self, attempt: int, *, retry_after: str | None = None
    ) -> None:
        delay = self.config.retry_backoff_seconds * (2**attempt)

        if retry_after is not None:
            try:
                delay = max(0.0, float(retry_after))
            except ValueError:
                pass

        await asyncio.sleep(min(delay, self.config.max_retry_delay_seconds))

    @staticmethod
    def _validate_model(
        model: type[_ModelT], payload: object, operation: str
    ) -> _ModelT:
        try:
            return model.model_validate(payload)
        except ValidationError as error:
            raise MeilisearchInvalidResponseError(
                f"{operation} returned an unexpected response"
            ) from error

    @staticmethod
    def _api_error(response: httpx.Response) -> MeilisearchApiError:
        message = response.reason_phrase or "Meilisearch API request failed"
        code: str | None = None
        error_type: str | None = None
        link: str | None = None

        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            if isinstance(payload.get("message"), str):
                message = payload["message"]

            if isinstance(payload.get("code"), str):
                code = payload["code"]

            if isinstance(payload.get("type"), str):
                error_type = payload["type"]

            if isinstance(payload.get("link"), str):
                link = payload["link"]

        return MeilisearchApiError(
            message,
            status_code=response.status_code,
            code=code,
            error_type=error_type,
            link=link,
            request_id=response.headers.get("X-Request-Id"),
        )

    @staticmethod
    def _index_path(index_uid: str) -> str:
        if not index_uid.strip():
            raise MeilisearchValidationError("index_uid cannot be empty")

        return f"indexes/{quote(index_uid, safe='')}"

    @staticmethod
    def _document_params(
        primary_key: str | None, custom_metadata: str | None
    ) -> dict[str, str]:
        params: dict[str, str] = {}

        if primary_key is not None:
            params["primaryKey"] = primary_key

        if custom_metadata is not None:
            params["customMetadata"] = custom_metadata

        return params

    @staticmethod
    def _require_documents(documents: Sequence[Mapping[str, JsonValue]]) -> None:
        if not documents:
            raise MeilisearchValidationError("documents cannot be empty")
