"""Public failures are stable codes, never provider bodies or credentials."""
from __future__ import annotations


class HarnessError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def public_error(error: Exception, fallback: str = "Agent review could not be completed. Check the server configuration and try again.") -> dict[str, str]:
    if isinstance(error, HarnessError):
        return {"code": error.code, "message": str(error)}
    return {"code": "dependency_error", "message": fallback}
