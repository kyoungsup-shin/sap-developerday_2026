"""Validated management sections backed by the shared runtime revision store."""
from __future__ import annotations

import csv
import os
import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from string import Formatter
from typing import Any
from urllib.parse import urlparse

from .errors import HarnessError
from .harness_profile import get_profile, validate_profile, resource_path
from .harness_settings import read_revision, current_settings, settings_scope, save_revision

CONTEXT_DEFAULTS = {"history_messages": 6, "history_characters": 6000, "grounding_characters": 4500,
                    "artifact_characters": 1800, "prior_artifacts": 3, "max_specialists": 3}
SECTION_IDS = {"agents", "tools", "data", "grounding", "runtime", "rpt", "joule", "evaluation"}


def context_limits() -> dict[str, int]:
    return {**CONTEXT_DEFAULTS, **current_settings().get("context_limits", {})}


def _invalid(message: str) -> None:
    raise HarnessError("invalid_configuration", message)


def _prompts(prefix: str) -> dict[str, str]:
    from .prompt_resources import _resources, get_prompt
    return {key: get_prompt(prefix + "." + key) for key in _resources()[prefix]}


def configuration_manifest(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    from .local_tools import read_snapshot
    from .rpt_decision import _config
    from .harness_evaluation import evaluation_defaults
    with settings_scope(snapshot) as current:
        profile = get_profile()
        sections = {
            "agents": {"teams": profile["agents"], "specialists": profile["specialists"], "external_agents": current.get("external_agents", [])},
            "tools": {"contracts": profile["tools"], "specialist_permissions": profile["specialists"]},
            "data": {filename: read_snapshot(filename) for filename in profile["resources"]["required_snapshots"]},
            "grounding": {"repository_id": current.get("grounding_repository", os.getenv("GROUNDING_REPOSITORY_ID", "")), "prompts": _prompts("grounding"), "sop_required": True},
            "runtime": {**profile["runtime"], "context_limits": context_limits(), "hitl_mode": current.get("hitl_mode", "advisory")},
            "rpt": {"decision": _config(), "prompts": _prompts("rpt")},
            "joule": current.get("joule", {"solution_id": os.getenv("JOULE_SOLUTION_ID", ""), "asset_name": os.getenv("JOULE_ASSET_NAME", "")}),
            "evaluation": current.get("evaluation") or evaluation_defaults(),
        }
        return {"revision": current["revision"], "sections": sections, "application": "Changes apply to new requests. Running requests retain their settings revision."}


def _validate_prompt_resources(prefix: str, values: Any) -> dict[str, str]:
    from .prompt_resources import _resources
    if not isinstance(values, dict) or set(values) != set(_resources()[prefix]):
        _invalid("Preserve the registered " + prefix + " Prompt keys.")
    allowed = {"grounded_state_user": {"request", "grounding_context"}, "final_grounded_state_user": {"request", "grounding_context", "artifacts", "final_synthesis"}, "ranking_user": {"selected_team", "catalog", "task_state"}}
    for key, text in values.items():
        if not isinstance(text, str) or not text.strip() or len(text) > 64000:
            _invalid("Each Prompt must contain 1 to 64,000 characters.")
        if prefix == "rpt":
            try:
                for _, field, spec, conversion in Formatter().parse(text):
                    if field is not None and (field not in allowed.get(key, set()) or spec or conversion):
                        raise ValueError()
            except ValueError:
                _invalid("Use the existing RPT template variables and escape literal braces.")
    if prefix == "grounding" and any(marker not in values["user"] for marker in ("{{?user_query}}", "{{?grounding_context}}")):
        _invalid("Grounding requires its user_query and grounding_context placeholders.")
    return {prefix + "." + key: text for key, text in values.items()}


def _validate_data(value: Any, profile: dict[str, Any]) -> None:
    expected = set(profile["resources"]["required_snapshots"])
    if not isinstance(value, dict) or set(value) != expected:
        _invalid("Provide all registered CSV datasets together.")
    for filename, rows in value.items():
        with (resource_path("snapshots") / filename).open(encoding="utf-8", newline="") as handle:
            columns = next(csv.reader(handle), [])
        if not isinstance(rows, list) or not rows or len(rows) > 10000:
            _invalid("Each dataset must contain 1 to 10,000 rows.")
        for row in rows:
            if not isinstance(row, dict) or set(row) != set(columns) or any(not isinstance(item, str) for item in row.values()):
                _invalid("Dataset rows must preserve their CSV columns and use string values.")
    contexts = [row["CONTEXT_ID"] for row in value["business_context.csv"]]
    if any(not item for item in contexts) or len(contexts) != len(set(contexts)):
        _invalid("Business Context IDs must be non-empty and unique.")
    for filename, rows in value.items():
        if any(row["CONTEXT_ID"] not in contexts for row in rows):
            _invalid("Every evidence row must reference a registered Business Context ID.")
    numeric = ("SELLING_PRICE", "QUARTER_VOLUME", "IMPORTED_COST_EUR", "LOCAL_VARIABLE_COST_USD", "FIXED_COST_USD", "BASE_FX_USD_EUR", "STRESS_FX_USD_EUR", "RAW_MATERIAL_INCREASE_PCT")
    try:
        for row in value["product_cost_assumption.csv"]:
            for key in numeric:
                number = Decimal(row[key])
                if not number.is_finite() or number < 0 or (key in {"BASE_FX_USD_EUR", "STRESS_FX_USD_EUR"} and number == 0):
                    raise InvalidOperation()
    except (InvalidOperation, ValueError):
        _invalid("Cost assumptions require finite non-negative numbers and positive exchange rates.")


def update_configuration(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {"section", "value", "expected_revision"} or not isinstance(payload.get("section"), str) or payload["section"] not in SECTION_IDS:
        _invalid("Provide a supported configuration section, value and expected_revision.")
    snapshot = read_revision()
    with settings_scope(snapshot):
        profile = get_profile()
        section, value = payload["section"], deepcopy(payload["value"])
        if section == "agents":
            if not isinstance(value, dict) or set(value) != {"teams", "specialists", "external_agents"}:
                _invalid("Provide Team, Specialist and external Agent registries.")
            profile.update(agents=value["teams"], specialists=value["specialists"])
            validate_profile(profile)
            external = value["external_agents"]
            if not isinstance(external, list):
                _invalid("External Agents must be a list.")
            used = {item["agent_id"] for item in profile["agents"]}
            for agent in external:
                if not isinstance(agent, dict) or set(agent) != {"agent_id", "label", "base_url", "enabled"} or type(agent["enabled"]) is not bool:
                    _invalid("External Agents require agent_id, label, base_url and enabled.")
                if not all(isinstance(agent[key], str) and agent[key].strip() for key in ("agent_id", "label", "base_url")) or agent["agent_id"] in used or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", agent["agent_id"]):
                    _invalid("Agent identities must be non-empty and unique.")
                url = urlparse(agent["base_url"])
                if url.scheme not in {"http", "https"} or not url.netloc or url.username or url.password or url.query or url.fragment:
                    _invalid("Use an HTTP(S) Agent base URL without credentials, query or fragment.")
                used.add(agent["agent_id"])
            snapshot["profile"] = profile
            snapshot["external_agents"] = external
            registered = {"orchestrator", *used, *("specialist:" + item["name"] for item in profile["specialists"])}
            snapshot["agents"] = {key: item for key, item in snapshot.get("agents", {}).items() if key in registered}
        elif section == "tools":
            if not isinstance(value, dict) or set(value) != {"contracts", "specialist_permissions"}:
                _invalid("Provide Tool contracts and Specialist permissions.")
            profile.update(tools=value["contracts"], specialists=value["specialist_permissions"])
            validate_profile(profile)
            snapshot["profile"] = profile
        elif section == "data":
            _validate_data(value, profile)
            snapshot["datasets"] = value
        elif section == "grounding":
            if not isinstance(value, dict) or set(value) != {"repository_id", "prompts", "sop_required"} or value["sop_required"] is not True:
                _invalid("All operational requests require verified SOP Grounding.")
            if not isinstance(value["repository_id"], str) or len(value["repository_id"]) > 128:
                _invalid("Repository ID must be a string of at most 128 characters.")
            snapshot["grounding_repository"] = value["repository_id"].strip()
            snapshot.setdefault("prompt_resources", {}).update(_validate_prompt_resources("grounding", value["prompts"]))
        elif section == "runtime":
            if not isinstance(value, dict) or set(value) != {"max_handoffs", "max_tool_turns", "timeouts", "context_limits", "hitl_mode"}:
                _invalid("Preserve the registered runtime settings.")
            profile["runtime"] = {key: value[key] for key in ("max_handoffs", "max_tool_turns", "timeouts")}
            validate_profile(profile)
            limits = value["context_limits"]
            if not isinstance(limits, dict) or set(limits) != set(CONTEXT_DEFAULTS) or any(type(item) is not int or item < 1 for item in limits.values()):
                _invalid("Context limits must be positive integers with the registered keys.")
            if value["hitl_mode"] not in {"advisory", "require_input"}:
                _invalid("HITL mode must be advisory or require_input.")
            snapshot.update(profile=profile, context_limits=limits, hitl_mode=value["hitl_mode"])
        elif section == "rpt":
            from .rpt_decision import validate_rpt_config
            if not isinstance(value, dict) or set(value) != {"decision", "prompts"}:
                _invalid("Provide RPT decision criteria, examples and Prompts.")
            try:
                snapshot["rpt"] = validate_rpt_config(value["decision"])
            except RuntimeError:
                _invalid("RPT criteria and examples must cover all configured decision labels and priorities.")
            snapshot.setdefault("prompt_resources", {}).update(_validate_prompt_resources("rpt", value["prompts"]))
        elif section == "joule":
            if not isinstance(value, dict) or set(value) != {"solution_id", "asset_name"} or any(not isinstance(item, str) or len(item) > 256 for item in value.values()):
                _invalid("Provide the deployed Joule Solution ID and Asset name.")
            if bool(value["solution_id"].strip()) != bool(value["asset_name"].strip()):
                _invalid("Set both Joule target fields, or leave both empty.")
            snapshot["joule"] = {key: item.strip() for key, item in value.items()}
        elif section == "evaluation":
            from .harness_evaluation import validate_evaluation
            snapshot["evaluation"] = validate_evaluation(value)
    return configuration_manifest(save_revision(snapshot, payload["expected_revision"]))
