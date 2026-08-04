from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Task


class MeilisearchError(Exception):
    """Base error for all failures reported by the client."""


class MeilisearchValidationError(MeilisearchError):
    """The request is invalid before it reaches Meilisearch."""


class MeilisearchSerializationError(MeilisearchError):
    """The request body cannot be represented as JSON."""


class MeilisearchCommunicationError(MeilisearchError):
    """The client could not communicate with Meilisearch."""


class MeilisearchTimeoutError(MeilisearchCommunicationError):
    """An individual HTTP request exceeded its timeout."""


class MeilisearchInvalidResponseError(MeilisearchError):
    """Meilisearch returned a successful but invalid response."""


class MeilisearchApiError(MeilisearchError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        code: str | None = None,
        error_type: str | None = None,
        link: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.error_type = error_type
        self.link = link
        self.request_id = request_id


class MeilisearchTaskError(MeilisearchError):
    def __init__(self, message: str, task: Task) -> None:
        super().__init__(message)
        self.task = task


class MeilisearchTaskFailedError(MeilisearchTaskError):
    """A queued task reached the failed state."""


class MeilisearchTaskCanceledError(MeilisearchTaskError):
    """A queued task reached the canceled state."""


class MeilisearchTaskWaitTimeoutError(MeilisearchError):
    def __init__(self, task_uid: int, timeout_seconds: float) -> None:
        super().__init__(
            f"Task {task_uid} did not finish within {timeout_seconds:g} seconds"
        )
        self.task_uid = task_uid
        self.timeout_seconds = timeout_seconds
