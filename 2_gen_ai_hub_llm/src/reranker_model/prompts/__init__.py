"""TOML-backed prompts for the reranker lesson."""

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


POLICY_ANALYST_SYSTEM_PROMPT = prompt("policy_analyst")
