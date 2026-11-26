"""Demo-owned read-only Tool contracts."""
from __future__ import annotations

from typing import Any

from .harness_profile import get_profile

_TOOLS = tuple(get_profile()["tools"])


def public_tools() -> list[dict[str, Any]]:
    return [{**tool, "mode": "read-only", "source": "Demo Tool Registry"} for tool in get_profile()["tools"]]


def native_tool_schema(name: str) -> dict[str, Any]:
    tool = next(item for item in get_profile()["tools"] if item["name"] == name)
    parameter = tool["required_parameter"]
    return {"type": "function", "function": {
        "name": name, "description": tool["description"] + " " + tool.get("policy_note", ""),
        "parameters": {"type": "object", "properties": {
            parameter: {"type": "string", "minLength": 1, "description": tool["inputs"][0]["description"]},
        }, "required": [parameter], "additionalProperties": False},
    }}
