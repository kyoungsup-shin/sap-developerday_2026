"""Render Agent review text without exposing serialized JSON in Chat."""
from __future__ import annotations

import json
import re
from typing import Any


def review_record(raw: str) -> Any | None:
    candidate = raw.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", candidate, re.I)
    if fenced:
        candidate = fenced.group(1)
    if not candidate.startswith(("{", "[")):
        return None
    try:
        parsed = json.loads(candidate)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _label(key: str) -> str:
    return key.replace("_", " ").strip().title().replace(" Id", " ID")


def _value(value: Any) -> str:
    if value is None:
        return "Not provided"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def record_markdown(value: Any, level: int = 2) -> str:
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            if level >= 3 and not isinstance(item, (dict, list)):
                parts.append("- **" + _label(str(key)) + ":** " + _value(item))
                continue
            heading = "#" * min(level, 6) + " " + _label(str(key))
            parts.append(heading + "\n\n" + record_markdown(item, level + 1))
        return "\n\n".join(parts)
    if isinstance(value, list):
        parts = []
        for index, item in enumerate(value, 1):
            if isinstance(item, (dict, list)):
                parts.append("### Item " + str(index) + "\n\n" + record_markdown(item, 4))
            else:
                parts.append("- " + _value(item))
        return "\n".join(parts)
    return _value(value)


def readable_review(raw: str) -> str:
    parsed = review_record(raw)
    return record_markdown(parsed) if parsed is not None else raw


class ReviewDisplay:
    """Stream prose immediately; hold JSON until it can be rendered as a review."""
    def __init__(self):
        self.raw = ""
        self.mode: str | None = None

    def feed(self, delta: str) -> str:
        self.raw += delta
        if self.mode == "prose":
            return delta
        if self.mode == "structured":
            return ""
        text = self.raw.lstrip()
        if not text:
            return ""
        if text.startswith(("{", "[", "`")):
            self.mode = "structured"
            return ""
        self.mode = "prose"
        return self.raw

    def finish(self) -> str:
        return readable_review(self.raw) if self.mode != "prose" else ""

    @property
    def text(self) -> str:
        return readable_review(self.raw)

    @property
    def record(self) -> Any:
        parsed = review_record(self.raw)
        return parsed if parsed is not None else {"summary": self.raw}
