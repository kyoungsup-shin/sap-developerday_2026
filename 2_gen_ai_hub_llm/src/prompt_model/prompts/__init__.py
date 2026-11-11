"""TOML-backed system prompts used by the LLM lesson."""

from __future__ import annotations

from pathlib import Path
import tomllib


_PROMPT_FILE = Path(__file__).with_name("system_prompts.toml")
with _PROMPT_FILE.open("rb") as prompt_file:
    _PROMPTS = tomllib.load(prompt_file)["system_prompts"]


def _prompt(name: str) -> str:
    value = _PROMPTS.get(name)
    if not isinstance(value, str):
        raise RuntimeError(f"system_prompts.toml에 {name!r} 프롬프트가 없습니다.")
    return value.strip()


CHAT_SYSTEM_PROMPT = _prompt("chat")
DEFAULT_COMPARISON_SYSTEM_PROMPT = _prompt("comparison")
REACT_SYSTEM_INSTRUCTION = _prompt("react")
