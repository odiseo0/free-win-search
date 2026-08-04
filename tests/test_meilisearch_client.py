from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any, cast

import httpx
import pytest

from src.core.services.meilisearch import (
    IndexSettingsUpdate,
    MeilisearchApiError,
    MeilisearchClient,
    MeilisearchCommunicationError,
    MeilisearchInvalidResponseError,
    MeilisearchSerializationError,
    MeilisearchTaskCanceledError,
    MeilisearchTaskFailedError,
    MeilisearchTaskWaitTimeoutError,
    MeilisearchTimeoutError,
    MeilisearchValidationError,
    SearchQuery,
    TaskStatus,
)

_DATE = "2026-08-04T12:00:00Z"


def _task_info(uid: int = 1) -> dict[str, object]:
    return {
        "taskUid": uid,
        "indexUid": "card-listings",
        "status": "enqueued",
        "type": "documentAdditionOrUpdate",
        "enqueuedAt": _DATE,
    }


def _task(uid: int, status: str, *, message: str | None = None) -> dict[str, object]:
    return {
        "uid": uid,
        "batchUid": 9,
        "indexUid": "card-listings",
        "status": status,
        "type": "documentAdditionOrUpdate",
        "canceledBy": 8 if status == "canceled" else None,
        "details": {"receivedDocuments": 1},
        "error": (
            {
                "message": message,
                "code": "invalid_document",
                "type": "invalid_request",
                "link": "https://example.test/errors#invalid_document",
            }
            if message is not None
            else None
        ),
        "duration": "PT0.001S" if status not in {"enqueued", "processing"} else None,
        "enqueuedAt": _DATE,
        "startedAt": _DATE if status != "enqueued" else None,
        "finishedAt": _DATE if status not in {"enqueued", "processing"} else None,
    }


def test_search_sends_auth_and_camel_case_body() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/indexes/card-listings/search"
        assert request.headers["Authorization"] == "Bearer secret-key"
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {
            "q": "Dark Magician",
            "limit": 10,
            "attributesToRetrieve": ["id", "name"],
            "filter": "is_active = true",
            "sort": ["price_minor:asc"],
            "showRankingScore": True,
        }
        return httpx.Response(
            200,
            json={
                "hits": [{"id": 1, "name": "Dark Magician"}],
                "query": "Dark Magician",
                "processingTimeMs": 2,
                "limit": 10,
                "offset": 0,
                "estimatedTotalHits": 1,
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MeilisearchClient(
                "https://meili.example.test/",
                "secret-key",
                max_retries=0,
                http_client=http,
            )
            result = await client.search(
                "card-listings",
                SearchQuery(
                    q="Dark Magician",
                    limit=10,
                    attributes_to_retrieve=["id", "name"],
                    filter="is_active = true",
                    sort=["price_minor:asc"],
                    show_ranking_score=True,
                ),
            )
            await client.aclose()
            assert not http.is_closed

        assert result.hits == [{"id": 1, "name": "Dark Magician"}]
        assert result.estimated_total_hits == 1

    asyncio.run(run())


def test_search_query_supports_placeholder_pagination_facets_and_highlights() -> None:
    query = SearchQuery(
        q="",
        page=2,
        hits_per_page=25,
        facets=["rarity", "condition"],
        attributes_to_highlight=["name"],
        highlight_pre_tag="<mark>",
        highlight_post_tag="</mark>",
    )

    assert query.model_dump(by_alias=True, exclude_none=True) == {
        "q": "",
        "page": 2,
        "hitsPerPage": 25,
        "attributesToHighlight": ["name"],
        "highlightPreTag": "<mark>",
        "highlightPostTag": "</mark>",
        "facets": ["rarity", "condition"],
    }


def test_document_methods_preserve_replace_and_partial_update_semantics() -> None:
    requests: list[tuple[str, str, dict[str, str], object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(
            (
                request.method,
                request.url.path,
                dict(request.url.params),
                json.loads(request.content),
            )
        )
        return httpx.Response(202, json=_task_info(len(requests)))

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MeilisearchClient("https://meili.test", http_client=http)
            added = await client.add_documents(
                "card-listings",
                [{"id": 1, "name": "Dark Magician"}],
                primary_key="id",
                custom_metadata="load-42",
            )
            updated = await client.update_documents(
                "card-listings",
                [{"id": 1, "stock": 2}],
                skip_creation=True,
            )

        assert added.task_uid == 1
        assert updated.task_uid == 2

    asyncio.run(run())

    assert requests == [
        (
            "POST",
            "/indexes/card-listings/documents",
            {"primaryKey": "id", "customMetadata": "load-42"},
            [{"id": 1, "name": "Dark Magician"}],
        ),
        (
            "PUT",
            "/indexes/card-listings/documents",
            {"skipCreation": "true"},
            [{"id": 1, "stock": 2}],
        ),
    ]


def test_index_settings_keep_explicit_nulls() -> None:
    received_body: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received_body.update(json.loads(request.content))
        return httpx.Response(202, json=_task_info())

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MeilisearchClient("https://meili.test", http_client=http)
            await client.update_settings(
                "card-listings",
                IndexSettingsUpdate(
                    searchable_attributes=["name", "code"],
                    distinct_attribute=None,
                ),
            )

    asyncio.run(run())

    assert received_body == {
        "searchableAttributes": ["name", "code"],
        "distinctAttribute": None,
    }


def test_health_version_and_index_responses_are_typed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payloads = {
            "/health": {"status": "available"},
            "/version": {
                "commitSha": "abc123",
                "commitDate": "2026-08-01",
                "pkgVersion": "1.45.1",
            },
            "/indexes/cards": {
                "uid": "cards",
                "primaryKey": "id",
                "createdAt": _DATE,
                "updatedAt": _DATE,
            },
        }
        return httpx.Response(200, json=payloads[request.url.path])

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MeilisearchClient("https://meili.test", http_client=http)
            health = await client.health()
            version = await client.version()
            index = await client.get_index("cards")

        assert health.status == "available"
        assert version.pkg_version == "1.45.1"
        assert index.primary_key == "id"

    asyncio.run(run())


def test_index_settings_and_mutation_routes() -> None:
    requested: list[tuple[str, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append((request.method, request.url.raw_path))
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "searchableAttributes": ["name"],
                    "localizedAttributes": [{"attributePatterns": ["name"]}],
                },
            )
        return httpx.Response(202, json=_task_info(len(requested)))

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MeilisearchClient("https://meili.test", http_client=http)
            settings = await client.get_settings("cards/current")
            await client.create_index("cards", primary_key="id")
            await client.delete_index("cards/current")
            await client.delete_document("cards", "listing/1")
            await client.delete_documents("cards", [1, "listing-2"])

        assert settings.searchable_attributes == ["name"]
        assert settings.model_extra == {
            "localizedAttributes": [{"attributePatterns": ["name"]}]
        }

    asyncio.run(run())

    assert requested == [
        ("GET", b"/indexes/cards%2Fcurrent/settings"),
        ("POST", b"/indexes"),
        ("DELETE", b"/indexes/cards%2Fcurrent"),
        ("DELETE", b"/indexes/cards/documents/listing%2F1"),
        ("POST", b"/indexes/cards/documents/delete-batch"),
    ]


def test_structured_api_error_keeps_safe_diagnostics() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "message": "Attribute `unknown` is not filterable",
                "code": "invalid_search_filter",
                "type": "invalid_request",
                "link": "https://example.test/errors#invalid_search_filter",
            },
            headers={"X-Request-Id": "request-123"},
        )

    async def run() -> MeilisearchApiError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MeilisearchClient(
                "https://meili.test", max_retries=0, http_client=http
            )
            with pytest.raises(MeilisearchApiError) as raised:
                await client.search("cards", SearchQuery(q="dark"))
            return raised.value

    error = asyncio.run(run())

    assert error.status_code == 400
    assert error.code == "invalid_search_filter"
    assert error.error_type == "invalid_request"
    assert error.request_id == "request-123"


def test_non_json_api_error_uses_status_reason_without_echoing_body() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="private upstream diagnostics")

    async def run() -> MeilisearchApiError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MeilisearchClient(
                "https://meili.test", max_retries=0, http_client=http
            )
            with pytest.raises(MeilisearchApiError) as raised:
                await client.health()
            return raised.value

    error = asyncio.run(run())

    assert error.status_code == 502
    assert str(error) == "Bad Gateway"
    assert "private upstream diagnostics" not in str(error)


def test_success_with_invalid_json_is_rejected() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MeilisearchClient("https://meili.test", http_client=http)
            with pytest.raises(MeilisearchInvalidResponseError):
                await client.health()

    asyncio.run(run())


def test_success_with_unexpected_json_shape_is_rejected() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MeilisearchClient("https://meili.test", http_client=http)
            with pytest.raises(MeilisearchInvalidResponseError):
                await client.health()

    asyncio.run(run())


def test_safe_search_retries_but_mutation_does_not() -> None:
    search_calls = 0
    mutation_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal search_calls, mutation_calls
        if request.url.path.endswith("/search"):
            search_calls += 1
            if search_calls == 1:
                return httpx.Response(503, json={"message": "busy"})
            return httpx.Response(
                200,
                json={"hits": [], "query": "dark", "processingTimeMs": 1},
            )
        mutation_calls += 1
        return httpx.Response(503, json={"message": "busy"})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MeilisearchClient(
                "https://meili.test",
                max_retries=1,
                retry_backoff_seconds=0,
                http_client=http,
            )
            await client.search("cards", SearchQuery(q="dark"))
            with pytest.raises(MeilisearchApiError):
                await client.add_documents("cards", [{"id": 1}])

    asyncio.run(run())

    assert search_calls == 2
    assert mutation_calls == 1


def test_request_timeout_is_translated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MeilisearchClient(
                "https://meili.test", max_retries=0, http_client=http
            )
            with pytest.raises(MeilisearchTimeoutError):
                await client.health()

    asyncio.run(run())


def test_network_error_is_translated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MeilisearchClient(
                "https://meili.test", max_retries=0, http_client=http
            )
            with pytest.raises(MeilisearchCommunicationError):
                await client.health()

    asyncio.run(run())


def test_safe_read_retries_after_network_error() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("unreachable", request=request)
        return httpx.Response(200, json={"status": "available"})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MeilisearchClient(
                "https://meili.test",
                max_retries=1,
                retry_backoff_seconds=0,
                http_client=http,
            )
            assert (await client.health()).status == "available"

    asyncio.run(run())

    assert calls == 2


def test_empty_batches_and_non_json_values_fail_before_network() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(202, json=_task_info())

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MeilisearchClient("https://meili.test", http_client=http)
            with pytest.raises(MeilisearchValidationError):
                await client.add_documents("cards", [])
            with pytest.raises(MeilisearchValidationError):
                await client.delete_documents("cards", [])
            invalid = cast(Any, [{"id": 1, "price": Decimal("1.25")}])
            with pytest.raises(MeilisearchSerializationError):
                await client.add_documents("cards", invalid)

    asyncio.run(run())

    assert calls == 0


@pytest.mark.parametrize(
    ("status", "expected_error"),
    [
        ("failed", MeilisearchTaskFailedError),
        ("canceled", MeilisearchTaskCanceledError),
    ],
)
def test_wait_for_task_raises_for_unsuccessful_terminal_status(
    status: str,
    expected_error: type[Exception],
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_task(7, status, message="invalid payload" if status == "failed" else None),
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MeilisearchClient("https://meili.test", http_client=http)
            with pytest.raises(expected_error):
                await client.wait_for_task(7)

    asyncio.run(run())


def test_wait_for_task_polls_until_success() -> None:
    statuses = iter(["enqueued", "processing", "succeeded"])

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_task(7, next(statuses)))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MeilisearchClient("https://meili.test", http_client=http)
            return await client.wait_for_task(7, poll_interval_seconds=0.001)

    task = asyncio.run(run())

    assert task.status is TaskStatus.SUCCEEDED


def test_wait_for_task_has_an_overall_timeout() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_task(7, "processing"))

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MeilisearchClient("https://meili.test", http_client=http)
            with pytest.raises(MeilisearchTaskWaitTimeoutError):
                await client.wait_for_task(
                    7,
                    timeout_seconds=0.01,
                    poll_interval_seconds=0.002,
                )

    asyncio.run(run())


def test_concurrency_is_limited_across_requests() -> None:
    active = 0
    maximum_active = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.005)
        active -= 1
        return httpx.Response(200, json={"status": "available"})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = MeilisearchClient(
                "https://meili.test",
                max_concurrency=2,
                http_client=http,
            )
            await asyncio.gather(*(client.health() for _ in range(6)))

    asyncio.run(run())

    assert maximum_active == 2
