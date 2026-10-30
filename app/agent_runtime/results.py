"""The single tool observation envelope used by the product loop and events."""

from typing import Any, Literal
from pydantic import BaseModel


class ToolResult(BaseModel):
    status: Literal["ok", "error"]
    data: Any
    retryable: bool = False
    code: str | None = None

    @classmethod
    def success(cls, data):
        return cls(status="ok", data=data).model_dump(exclude_none=True)

    @classmethod
    def failure(cls, error):
        return cls(status="error", code=error.code, data=error.data).model_dump(exclude_none=True)
