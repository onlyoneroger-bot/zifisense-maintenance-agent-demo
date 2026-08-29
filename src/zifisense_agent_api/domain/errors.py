from __future__ import annotations

from typing import Any

from zifisense_agent_api.transport.schemas import ErrorCode


class ApplicationError(Exception):
    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details
