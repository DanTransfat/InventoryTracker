"""One error type for the whole API, rendered as a consistent JSON body:

    {"error": {"code": "DUPLICATE_SKU", "message": "...", "fields": {"sku": "..."}}}

``code`` is stable and machine-readable; ``message`` is for humans; ``fields`` maps a
request field to a message so the UI can show it next to the right input.
"""
from __future__ import annotations

from typing import Any


class ApiError(Exception):
    status = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None,
                 fields: dict[str, str] | None = None, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status:
            self.status = status
        self.fields = fields or {}
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.fields:
            body["fields"] = self.fields
        if self.details:
            body["details"] = self.details
        return {"error": body}


class BadRequest(ApiError):
    status, code = 400, "BAD_REQUEST"


class ValidationFailed(ApiError):
    status, code = 422, "VALIDATION_ERROR"


class NotFound(ApiError):
    status, code = 404, "NOT_FOUND"


class Conflict(ApiError):
    status, code = 409, "CONFLICT"
