"""Load Profile-referenced role, Grounding and RPT prompts once per process."""
from __future__ import annotations

import tomllib
from functools import lru_cache
from typing import Any

from .harness_profile import BACKEND_ROOT, get_profile


@lru_cache(maxsize=1)
def _resources() -> dict[str, Any]:
    values: dict[str, Any] = {}
    for reference in get_profile()["resources"]["prompts"]:
        path = BACKEND_ROOT / reference
        with path.open("rb") as handle:
            values.update(tomllib.load(handle))
    return values


def get_prompt(key: str) -> str:
    from .harness_settings import current_settings
    override = current_settings().get("prompt_resources", {}).get(key)
    if override is not None:
        return override
    value: Any = _resources()
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError("Unknown Demo prompt key: " + key)
        value = value[part]
    if not isinstance(value, str):
        raise TypeError("Prompt key must resolve to text.")
    return value


def render_prompt(key: str, /, **values: Any) -> str:
    return get_prompt(key).format(**values)
