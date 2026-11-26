"""Safe, fixed-target Joule Studio CLI A2A adapter."""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any

from .ai_core import _load_repo_env
from .harness_profile import runtime_timeout
from .harness_settings import current_settings

_SECRET = re.compile(r"(?i)(bearer\s+|token[=:]\s*|password[=:]\s*)[^\s,;]+")


def _safe_error(value: str) -> str:
    return _SECRET.sub(r"\1[REDACTED]", value).strip() or "Joule CLI command failed."


def _settings() -> tuple[str, str, str, float]:
    _load_repo_env()
    target = current_settings().get("joule", {})
    solution = target.get("solution_id", os.getenv("JOULE_SOLUTION_ID", "")).strip()
    asset = target.get("asset_name", os.getenv("JOULE_ASSET_NAME", "")).strip()
    if not solution or not asset:
        raise RuntimeError("Joule Work Agent is not configured. Set JOULE_SOLUTION_ID and JOULE_ASSET_NAME.")
    timeout = runtime_timeout("joule_cli", "JOULE_CLI_TIMEOUT_SECONDS")
    return os.getenv("JOULE_CLI_PATH", "jl").strip() or "jl", solution, asset, timeout


def _run(arguments: list[str], timeout: float) -> Any:
    try:
        completed = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as error:
        raise RuntimeError("Joule CLI was not found. Install it or set JOULE_CLI_PATH.") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Joule CLI timed out.") from error
    if completed.returncode:
        raise RuntimeError("Joule CLI command failed (exit code " + str(completed.returncode) + ").")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("Joule CLI returned invalid JSON.") from error


def _discover_solution(executable: str, configured_id: str, timeout: float) -> dict[str, Any]:
    """Resolve the configured deployed Solution from the CLI registry first."""
    payload = _run([executable, "solution", "list", "--json"], timeout)
    solutions = payload.get("solutions") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or payload.get("ok") is not True or not isinstance(solutions, list):
        raise RuntimeError("Joule CLI solution list returned no Solution registry.")
    solution = next((item for item in solutions if isinstance(item, dict) and str(item.get("id", "")) == configured_id), None)
    if solution is None:
        raise RuntimeError("Configured JOULE_SOLUTION_ID was not found in the deployed Joule Solutions.")
    return solution


def verify_card() -> dict[str, Any]:
    executable, solution, asset, timeout = _settings()
    deployed_solution = _discover_solution(executable, solution, timeout)
    card = _run([executable, "a2a", "card", "--solution", solution, "--asset", asset, "--json"], timeout)
    return {"executable": executable, "solution_id": solution, "solution": deployed_solution, "asset_name": asset, "timeout": timeout, "card": card}


def send_message(request: str, decision: dict[str, Any], verified: dict[str, Any]) -> dict[str, Any]:
    """Send one isolated read-only A2A message after Card verification."""
    instruction = (
        "Perform a read-only review. Do not execute purchases, approvals, or data changes.\n"
        f"User request: {request}\n"
        f"RPT decision evidence: {json.dumps({key: decision[key] for key in ('next_agent', 'handoff_mode', 'risk', 'priority', 'grounded_state')}, ensure_ascii=False)}"
    )
    result = _run([str(verified["executable"]), "a2a", "message", instruction, "--solution", str(verified["solution_id"]), "--asset", str(verified["asset_name"]), "--json"], float(verified["timeout"]))
    return {"agent_id": "joule-work-agent", "agent_label": "Joule Work Agent", "solution_id": verified["solution_id"], "asset_name": verified["asset_name"], "card": verified["card"], "result": result, "read_only": True}
