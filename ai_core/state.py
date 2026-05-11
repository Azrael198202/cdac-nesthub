from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any
from uuid import uuid4

class CoreState(BaseModel):
    request_id: str = Field(default_factory=lambda: uuid4().hex)
    user_input: str
    intent: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    plan: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    approvals: list[dict[str, Any]] = Field(default_factory=list)
    final_answer: str = ""
