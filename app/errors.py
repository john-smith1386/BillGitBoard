"""Machine-readable service errors shared across layers."""

from __future__ import annotations

from typing import Any


class ServiceError(Exception):
    """An expected request or analysis failure.

    ``payload`` is intentionally kept flat because the public API contract uses
    responses such as ``{"code": "NAME_TOO_LONG", "needed_cols": 95}``.
    """

    def __init__(
        self,
        code: str,
        detail: str | None = None,
        *,
        status_code: int = 422,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> None:
        self.code = code
        self.detail = detail
        self.status_code = status_code
        self.headers = headers or {}
        self.extra = extra
        super().__init__(detail or code)

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code}
        if self.detail:
            body["detail"] = self.detail
        body.update(self.extra)
        return body
