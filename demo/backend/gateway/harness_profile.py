"""Validated, process-cached configuration shared by Gateway and Team server.

Only the default Profile is supported. Restart both services after editing it.
No credentials are loaded here and public inspection uses an explicit allow-list.
"""
from __future__ import annotations

import math
import os
import re
import tomllib
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .errors import HarnessError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_PATH = BACKEND_ROOT / "config" / "harness" / "fnb-default.yaml"
_TOOL_PARAMETERS = {
    "search_business_context": "request_text",
    "retrieve_business_evidence": "context_id",
    "calculate_profitability_scenarios": "context_id",
}
_TIMEOUT_KEYS = {
    "team_task", "a2a_connect", "ai_core_connect", "ai_core_discovery",
    "ai_core_completion", "ai_core_stream", "grounding_discovery",
    "grounding_documents", "rpt_request", "joule_cli",
}
_DOMAINS = {
    "facility", "production_execution", "procurement", "supply",
    "production_planning", "material_intake", "cost_driver", "business_outlook",
    "financial_control", "erp_readiness", "ehs", "workforce", "general_affairs",
    "process", "rnd", "quality",
}


def _invalid(field: str) -> None:
    raise HarnessError("invalid_harness_profile", "Harness Profile configuration is invalid: " + field + ".") from None


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid(field)
    return value


def _strings(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        _invalid(field)
    for item in value:
        _text(item, field)
    if len(value) != len(set(value)):
        _invalid(field + " contains duplicates")
    return value


def _records(value: Any, key: str, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        _invalid(field)
    identities = []
    for item in value:
        if not isinstance(item, dict):
            _invalid(field)
        identities.append(_text(item.get(key), field + " identity"))
    if len(identities) != len(set(identities)):
        _invalid(field + " contains duplicate identities")
    return value


def _path(value: Any, field: str, *, directory: bool = False) -> Path:
    relative = Path(_text(value, field))
    path = (BACKEND_ROOT / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(BACKEND_ROOT):
        _invalid(field + " must reference a demo backend resource")
    if not (path.is_dir() if directory else path.is_file()):
        _invalid(field + " resource is missing")
    return path


def validate_profile(raw: Any) -> dict[str, Any]:
    """Validate without imports from Agent runtimes or network calls."""
    if not isinstance(raw, dict) or raw.get("id") != "fnb-default" or raw.get("schema_version") != "demo.harness.v1":
        _invalid("id or schema_version")
    if set(raw) != {"id", "schema_version", "agents", "specialists", "tools", "runtime", "resources"}:
        _invalid("top-level fields")
    agents = _records(raw.get("agents"), "agent_id", "agents")
    specialists = _records(raw.get("specialists"), "name", "specialists")
    tools = _records(raw.get("tools"), "name", "tools")
    specialist_names = {item["name"] for item in specialists}
    tool_names = {item["name"] for item in tools}
    if tool_names != set(_TOOL_PARAMETERS):
        _invalid("tools must reference supported implementations")
    skills, labels = set(), set()
    for agent in agents:
        if set(agent) != {"agent_id", "agent_label", "skill_id", "description", "sub_agents", "tags", "keywords", "examples"}:
            _invalid("Agent fields")
        for key in ("agent_label", "skill_id", "description"):
            _text(agent.get(key), "agent " + key)
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", agent["agent_id"]):
            _invalid("agent_id")
        if agent["skill_id"] in skills or agent["agent_label"] in labels:
            _invalid("duplicate Agent label or Skill identity")
        skills.add(agent["skill_id"])
        labels.add(agent["agent_label"])
        members = _strings(agent.get("sub_agents"), "agent Specialists")
        if not set(members) <= specialist_names:
            _invalid("agent references an unknown Specialist")
        for key in ("tags", "keywords", "examples"):
            _strings(agent.get(key), "agent " + key)
    for specialist in specialists:
        if set(specialist) != {"name", "domains", "tools"}:
            _invalid("Specialist fields")
        domains = _strings(specialist.get("domains"), "Specialist domains")
        permissions = _strings(specialist.get("tools"), "Specialist tools")
        if not set(domains) <= _DOMAINS or not set(permissions) <= tool_names:
            _invalid("Specialist references an unknown domain or Tool")
    for tool in tools:
        if not {"name", "description", "required_parameter", "inputs"} <= set(tool) or set(tool) - {"name", "description", "required_parameter", "inputs", "policy_note"}:
            _invalid("Tool fields")
        _text(tool.get("description"), "Tool description")
        parameter = _TOOL_PARAMETERS[tool["name"]]
        inputs = tool.get("inputs")
        if tool.get("required_parameter") != parameter or not isinstance(inputs, list) or len(inputs) != 1:
            _invalid("Tool input contract")
        item = inputs[0]
        if not isinstance(item, dict) or item.get("name") != parameter or item.get("type") != "string" or item.get("required") is not True:
            _invalid("Tool input contract")
        if set(item) != {"name", "type", "required", "description", "example"}:
            _invalid("Tool input fields")
        for key in ("description", "example"):
            _text(item.get(key), "Tool input " + key)
        if "policy_note" in tool:
            _text(tool["policy_note"], "Tool policy_note")
    runtime = raw.get("runtime")
    if not isinstance(runtime, dict) or set(runtime) != {"max_handoffs", "max_tool_turns", "timeouts"}:
        _invalid("runtime")
    for key in ("max_handoffs", "max_tool_turns"):
        if type(runtime.get(key)) is not int or runtime[key] < 1:
            _invalid("runtime " + key + " must be a positive integer")
    timeouts = runtime.get("timeouts")
    if not isinstance(timeouts, dict) or set(timeouts) != _TIMEOUT_KEYS:
        _invalid("runtime timeouts")
    for value in timeouts.values():
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            _invalid("runtime timeout must be positive and finite")
    resources = raw.get("resources")
    if not isinstance(resources, dict) or set(resources) != {"prompts", "snapshots", "required_snapshots", "rpt_config"}:
        _invalid("resources")
    prompt_values: dict[str, Any] = {}
    for reference in _strings(resources.get("prompts"), "Prompt resources"):
        path = _path(reference, "Prompt")
        try:
            with path.open("rb") as handle:
                values = tomllib.load(handle)
        except (OSError, ValueError):
            _invalid("Prompt resource format")
        if prompt_values.keys() & values.keys():
            _invalid("duplicate Prompt section")
        prompt_values.update(values)
    for section, keys in {
        "roles": ("review", "specialist_review", "team_review", "final_review", "final_synthesis", "orchestrator", "team", "specialist"),
        "grounding": ("system_en", "sop_system_en", "answer_system_en", "user"),
        "rpt": ("grounded_state_system", "grounded_state_user", "final_grounded_state_system", "final_grounded_state_user", "ranking_system", "ranking_user"),
    }.items():
        block = prompt_values.get(section)
        if not isinstance(block, dict):
            _invalid("Prompt " + section)
        for key in keys:
            _text(block.get(key), "Prompt " + section + "." + key)
    try:
        prompt_values["roles"]["team"].format(agent_label="Team", description="Review")
        prompt_values["roles"]["specialist"].format(specialist="Specialist")
    except (ValueError, KeyError, IndexError):
        _invalid("role Prompt placeholders")
    snapshots = _path(resources.get("snapshots"), "CSV", directory=True)
    files = _strings(resources.get("required_snapshots"), "required CSV files")
    required = {"business_context.csv", "operations_evidence.csv", "product_cost_assumption.csv", "cost_center_master.csv"}
    if not required <= set(files):
        _invalid("required Tool CSV files")
    for filename in files:
        if Path(filename).name != filename or not filename.endswith(".csv") or not (snapshots / filename).is_file():
            _invalid("required CSV resource is missing or invalid")
    rpt_path = _path(resources.get("rpt_config"), "RPT")
    try:
        with rpt_path.open(encoding="utf-8") as handle:
            rpt = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError):
        _invalid("RPT resource format")
    if not isinstance(rpt, dict):
        _invalid("RPT resource format")
    return deepcopy(raw)


def load_profile(path: Path = DEFAULT_PROFILE_PATH) -> dict[str, Any]:
    """Uncached reader for validation/tests; runtime uses get_profile."""
    try:
        with path.open(encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError):
        _invalid("Profile file is missing or malformed")
    return validate_profile(raw)


@lru_cache(maxsize=1)
def _default_profile() -> dict[str, Any]:
    return load_profile()


def get_profile() -> dict[str, Any]:
    from .harness_settings import current_settings
    return deepcopy(current_settings().get("profile") or _default_profile())


def resource_path(key: str) -> Path:
    return (BACKEND_ROOT / get_profile()["resources"][key]).resolve()


def runtime_timeout(key: str, environment: str | None = None) -> float:
    """Existing environment overrides retain precedence over Profile defaults."""
    default = get_profile()["runtime"]["timeouts"][key]
    value = os.getenv(environment, str(default)) if environment else default
    try:
        result = float(value)
    except (ValueError, TypeError):
        _invalid((environment or key) + " timeout")
    if not math.isfinite(result) or result <= 0:
        _invalid((environment or key) + " timeout")
    return result


def public_profile() -> dict[str, Any]:
    profile = get_profile()
    return {
        "id": profile["id"], "schema_version": profile["schema_version"],
        "agents": [{key: agent[key] for key in ("agent_id", "agent_label", "skill_id", "description", "sub_agents", "tags", "examples")} for agent in profile["agents"]],
        "specialists": [{key: item[key] for key in ("name", "domains", "tools")} for item in profile["specialists"]],
        "tools": [{key: item[key] for key in ("name", "description", "required_parameter", "inputs", "policy_note") if key in item} for item in profile["tools"]],
        "runtime": {
            "max_handoffs": profile["runtime"]["max_handoffs"],
            "max_tool_turns": profile["runtime"]["max_tool_turns"],
            "timeouts": {key: runtime_timeout(key, {"team_task": "DEMO_TEAM_TASK_TIMEOUT", "joule_cli": "JOULE_CLI_TIMEOUT_SECONDS"}.get(key)) for key in profile["runtime"]["timeouts"]},
        },
    }
