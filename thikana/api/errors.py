"""One error shape for the whole API.

Every error is  {"error": {"code": "...", "message": "...", "request_id": "..."}}.
Clients can switch on `code`; the request_id lets a person find the log line.
Messages never include the submitted text: addresses are personal data.
"""

from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def envelope(code: str, message: str, request_id: str) -> dict:
    return {"error": {"code": code, "message": message, "request_id": request_id}}
