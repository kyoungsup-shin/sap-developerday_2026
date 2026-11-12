"""TOML-backed system prompts for the RPT Decision lesson."""

from __future__ import annotations

from pathlib import Path
import tomllib


with Path(__file__).with_name("system_prompts.toml").open("rb") as prompt_file:
    _PROMPTS = tomllib.load(prompt_file)["system_prompts"]


def prompt(name: str) -> str:
    value = _PROMPTS.get(name)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"system_prompts.toml에 유효한 {name!r} 프롬프트가 없습니다.")
    return value.strip()


TASK_STATE_TRANSLATION_INSTRUCTION = prompt("task_state_translation")
SEMANTIC_COORDINATOR_CONTRACT = prompt("semantic_coordinator")
