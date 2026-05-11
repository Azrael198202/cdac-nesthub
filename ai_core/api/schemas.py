from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    interactive: bool = False
    human_feedback: dict[str, Any] | None = None


class ChatResponse(BaseModel):
    final_answer: str
    trace_file: str | None = None
    state: dict[str, Any]


class ApiKeyRequest(BaseModel):
    provider: str
    api_key: str
