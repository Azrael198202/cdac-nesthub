from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class JSONRepairResult:
    repaired: bool
    parsed: dict[str, Any] | None
    text: str
    attempts: list[str]
    error: str = ""


def repair_json_object_text(raw: str) -> JSONRepairResult:
    """Best-effort, domain-neutral JSON object repair for local model output.

    The repair is intentionally structural only. It does not infer task meaning,
    add business fields, or change the execution decision. It only fixes common
    serialization damage such as wrappers, smart quotes, trailing commas,
    literal newlines inside strings, unclosed strings, and missing closing
    brackets/braces.
    """
    attempts: list[str] = []
    for candidate in _candidate_texts(raw):
        for repaired in _repair_variants(candidate):
            if repaired in attempts:
                continue
            attempts.append(repaired)
            try:
                value = json.loads(repaired)
                if isinstance(value, dict):
                    return JSONRepairResult(True, value, repaired, attempts)
            except Exception as exc:
                last_error = str(exc)
    return JSONRepairResult(False, None, attempts[-1] if attempts else str(raw or ""), attempts, locals().get("last_error", "invalid JSON"))


def _candidate_texts(raw: str) -> list[str]:
    s = _strip_wrappers(str(raw or ""))
    candidates: list[str] = []
    if s:
        candidates.append(s)
    first_obj = _slice_between_first_and_last(s, "{", "}")
    if first_obj:
        candidates.append(first_obj)
    first_arr = _slice_between_first_and_last(s, "[", "]")
    if first_arr:
        candidates.append(first_arr)
    # If the model started an object but did not close it, keep from the first
    # object delimiter to the end so the balancer can add terminators.
    start = s.find("{")
    if start >= 0:
        candidates.append(s[start:])
    out: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        text = item.strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _repair_variants(text: str) -> list[str]:
    base = _basic_normalize(text)
    escaped = _escape_newlines_in_strings(base)
    balanced = _balance_json(escaped)
    variants = [text, base, escaped, balanced]
    # If a local model emitted a quoted JSON object string, parse that layer.
    try:
        nested = json.loads(base)
        if isinstance(nested, str):
            variants.extend(_repair_variants(nested))
    except Exception:
        pass
    out: list[str] = []
    seen: set[str] = set()
    for item in variants:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _strip_wrappers(text: str) -> str:
    s = text.strip()
    s = re.sub(r"<think>.*?</think>", "", s, flags=re.DOTALL | re.IGNORECASE).strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?", "", s, flags=re.IGNORECASE).strip()
        s = re.sub(r"```$", "", s).strip()
    return s


def _slice_between_first_and_last(text: str, open_ch: str, close_ch: str) -> str | None:
    start = text.find(open_ch)
    end = text.rfind(close_ch)
    if start >= 0 and end >= start:
        return text[start:end + 1]
    return None


def _basic_normalize(text: str) -> str:
    s = text.strip()
    s = s.replace("“", '"').replace("”", '"').replace("„", '"').replace("‟", '"')
    s = s.replace("’", "'").replace("‘", "'")
    s = re.sub(r",\s*([}\]])", r"\1", s)
    s = re.sub(r"\bTrue\b", "true", s)
    s = re.sub(r"\bFalse\b", "false", s)
    s = re.sub(r"\bNone\b", "null", s)
    return s


def _escape_newlines_in_strings(text: str) -> str:
    out: list[str] = []
    in_string = False
    escape = False
    for ch in text:
        if in_string:
            if escape:
                out.append(ch)
                escape = False
                continue
            if ch == "\\":
                out.append(ch)
                escape = True
                continue
            if ch == '"':
                out.append(ch)
                in_string = False
                continue
            if ch == "\n":
                out.append("\\n")
                continue
            if ch == "\r":
                continue
            if ord(ch) < 32:
                out.append(" ")
                continue
            out.append(ch)
            continue
        out.append(ch)
        if ch == '"':
            in_string = True
            escape = False
    if in_string:
        out.append('"')
    return "".join(out)


def _balance_json(text: str) -> str:
    out: list[str] = []
    stack: list[str] = []
    in_string = False
    escape = False
    for ch in text:
        out.append(ch)
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()
    if in_string:
        out.append('"')
    while stack:
        closer = stack.pop()
        # Remove dangling comma before adding a closer.
        while out and out[-1].isspace():
            out.pop()
        if out and out[-1] == ",":
            out.pop()
        out.append(closer)
    return "".join(out)
