"""Read-only SAP RPT Decision API adapter for the F&B A2A demo."""
from __future__ import annotations

import json
import re
import os
from functools import lru_cache
from typing import Any

import requests
import yaml
from a2a.helpers import get_data_parts
from a2a.types import Artifact
from google.protobuf.json_format import ParseDict

from .ai_core import _load_repo_env, chat_text
from .prompt_resources import get_prompt, render_prompt
from .harness_profile import resource_path, runtime_timeout
from .harness_settings import current_settings

RPT_ENDPOINT = "https://rpt.cloud.sap/api/systemone"
RPT_MODEL = "sap-rpt-1.6"
_CONFIG_PATH = resource_path("rpt_config")
_CHOICE_FIELDS = ("next_agent", "handoff_mode", "risk")


def _required(value: str, name: str) -> str:
    if not value.strip():
        raise RuntimeError(f"{name} is not configured.")
    return value.strip()


def _nonempty_mapping(value: Any, name: str) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise RuntimeError(f"RPT config {name} must be a non-empty mapping.")
    result = {str(key).strip(): str(item).strip() for key, item in value.items()}
    if any(not key or not item for key, item in result.items()):
        raise RuntimeError(f"RPT config {name} contains an empty key or criterion.")
    return result


@lru_cache(maxsize=1)
def _base_config() -> dict[str, Any]:
    try:
        with _CONFIG_PATH.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as error:
        raise RuntimeError(f"RPT config could not be loaded: {_CONFIG_PATH}") from error
    return validate_rpt_config(raw)


def _config() -> dict[str, Any]:
    return current_settings().get("rpt") or _base_config()


def validate_rpt_config(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RuntimeError("RPT config root must be a mapping.")

    config: dict[str, Any] = {}
    for field in _CHOICE_FIELDS:
        block = raw.get(field)
        if not isinstance(block, dict) or not isinstance(block.get("instructions"), str) or not block["instructions"].strip():
            raise RuntimeError(f"RPT config {field} requires non-empty instructions.")
        config[field] = {
            "instructions": block["instructions"].strip(),
            "criteria": _nonempty_mapping(block.get("criteria"), f"{field}.criteria"),
        }
    priority = raw.get("priority")
    if not isinstance(priority, dict) or not isinstance(priority.get("instructions"), str) or not priority["instructions"].strip():
        raise RuntimeError("RPT config priority requires non-empty instructions.")
    priority_criteria = priority.get("criteria")
    if not isinstance(priority_criteria, list) or not all(isinstance(item, str) and item.strip() for item in priority_criteria):
        raise RuntimeError("RPT config priority.criteria must be non-empty strings.")
    config["priority"] = {"instructions": priority["instructions"].strip(), "criteria": priority_criteria}

    examples = raw.get("examples")
    if not isinstance(examples, list) or not examples:
        raise RuntimeError("RPT config examples must be a non-empty list.")
    validated_examples: list[dict[str, Any]] = []
    demonstrated = {field: set() for field in (*_CHOICE_FIELDS, "priority")}
    for index, item in enumerate(examples, start=1):
        if not isinstance(item, dict) or not isinstance(item.get("state"), str) or not item["state"].strip() or not isinstance(item.get("answers"), dict):
            raise RuntimeError(f"RPT config example {index} must contain state and answers.")
        answers = item["answers"]
        for field in _CHOICE_FIELDS:
            if answers.get(field) not in config[field]["criteria"]:
                raise RuntimeError(f"RPT config example {index} has an invalid {field}.")
        if str(answers.get("priority")) not in {"0", "1", "2"}:
            raise RuntimeError(f"RPT config example {index} has an invalid priority.")
        validated_examples.append({"state": item["state"].strip(), "answers": {key: str(answers[key]) for key in (*_CHOICE_FIELDS, "priority")}})
        for field in _CHOICE_FIELDS:
            demonstrated[field].add(str(answers[field]))
        demonstrated["priority"].add(str(answers["priority"]))
    for field in _CHOICE_FIELDS:
        missing = set(config[field]["criteria"]) - demonstrated[field]
        if missing:
            raise RuntimeError(f"RPT config examples do not demonstrate every {field} label: {', '.join(sorted(missing))}.")
    missing_priorities = {"0", "1", "2"} - demonstrated["priority"]
    if missing_priorities:
        raise RuntimeError(f"RPT config examples do not demonstrate every priority label: {', '.join(sorted(missing_priorities))}.")
    config["examples"] = validated_examples
    return config


def _synthesis_context(artifact: dict[str, Any] | None) -> dict[str, Any] | None:
    """Read the final A2A DataPart without duplicating its nested Team evidence."""
    if artifact is None:
        return None
    try:
        parsed = ParseDict(artifact, Artifact())
        parts = get_data_parts(parsed.parts)
        if len(parts) != 1 or not parsed.artifact_id:
            raise ValueError()
        data = parts[0]
        if (data.get("schema_version") != "demo.synthesis.v1" or data.get("kind") != "final_synthesis"
                or data.get("producer") != "orchestration-agent" or data.get("read_only") is not True
                or not isinstance(data.get("summary"), str) or not data["summary"].strip()):
            raise ValueError()
        return {"artifact_id": parsed.artifact_id, "producer": data["producer"],
                "context_id": data.get("context_id"), "summary": data["summary"],
                "summary_record": data.get("summary_record"), "sop_source_ids": data.get("sop_source_ids", []),
                "source_artifact_references": [{key: item[key] for key in ("team_id", "task_id", "handoff_id", "context_id") if key in item}
                                               for item in data.get("source_artifacts", [])]}
    except Exception:
        raise RuntimeError("The final Synthesis Artifact is invalid.") from None


def _grounded_state(request: str, grounding_context: str, artifacts: list[dict[str, Any]] | None = None,
                    synthesis_artifact: dict[str, Any] | None = None) -> str:
    """Create the compact English state consumed by RPT from verified retrieval evidence."""
    request = _required(request, "user request")
    grounding_context = grounding_context.strip() or "No Grounding search was requested. Assess only the request and supplied artifacts; external document evidence is absent."
    synthesis = _synthesis_context(synthesis_artifact)
    is_final = artifacts is not None or synthesis is not None
    messages = [
        {
            "role": "system",
            "content": get_prompt("rpt.final_grounded_state_system" if is_final else "rpt.grounded_state_system"),
        },
        {
            "role": "user",
            "content": render_prompt(
                "rpt.final_grounded_state_user" if is_final else "rpt.grounded_state_user",
                request=request, grounding_context=grounding_context,
                artifacts=json.dumps(artifacts or [], ensure_ascii=False),
                final_synthesis=json.dumps(synthesis, ensure_ascii=False),
            ),
        },
    ]
    normalized = chat_text(messages, max_tokens=500)
    if re.search(r"[가-힣]", normalized):
        # Source SOP department names can leak through despite the English
        # instruction. Ask the model to repair the generated state, preserving
        # facts/IDs rather than replacing operational data or routing by labels.
        repair = [{"role": "system", "content": "Rewrite the supplied decision state entirely in English. Translate every department name and label, including quotations. Preserve all facts, quantities, uncertainties, SOP source IDs and registered Agent IDs. Return only the repaired state; do not add facts."},
                  {"role": "user", "content": normalized}]
        normalized = chat_text(repair, max_tokens=500)
        if re.search(r"[가-힣]", normalized):
            raise RuntimeError("The RPT task state could not be generated in English.")
    return _required(normalized[:2000], "grounded English task state")


def _request(task_state: str) -> dict[str, Any]:
    config = _config()
    return {
        "model": RPT_MODEL,
        "state": task_state,
        "questions": {
            **{field: {"type": "choice", **config[field]} for field in _CHOICE_FIELDS},
            "priority": {"type": "score", **config["priority"]},
        },
        "examples": config["examples"],
    }


def _choice(answers: dict[str, Any], name: str) -> str:
    answer = answers.get(name)
    if not isinstance(answer, dict):
        raise RuntimeError(f"RPT response is missing {name}.")
    value = answer.get("score") if name == "priority" else answer.get("choice")
    if value is None:
        raise RuntimeError(f"RPT response has no {name} prediction.")
    if name in _CHOICE_FIELDS and str(value) not in _config()[name]["criteria"]:
        raise RuntimeError(f"RPT response selected an unknown {name}: {value}.")
    if name == "priority":
        try:
            numeric = float(value)
        except (TypeError, ValueError) as error:
            raise RuntimeError(f"RPT response has an invalid priority: {value}.") from error
        if not 0 <= numeric <= 2:
            raise RuntimeError(f"RPT response priority is outside 0–2: {value}.")
        return str(int(numeric) if numeric.is_integer() else numeric)
    return str(value)


def _team_rankings(task_state: str, selected_team: str) -> list[dict[str, Any]]:
    """Ask AI Core for the initial RPT routing-fit display without changing RPT routing."""
    criteria = _config()["next_agent"]["criteria"]
    catalog = [{"agent_id": team_id, "scope": scope} for team_id, scope in criteria.items()]
    prompt = render_prompt(
        "rpt.ranking_user",
        selected_team=selected_team,
        catalog=json.dumps(catalog, ensure_ascii=False),
        task_state=task_state,
    )
    try:
        raw = chat_text([
            {"role": "system", "content": get_prompt("rpt.ranking_system")},
            {"role": "user", "content": prompt},
        ], max_tokens=220)
        payload = json.loads(raw.removeprefix("```json").removesuffix("```").strip())
        candidates = payload.get("teams", [])
    except (ValueError, TypeError, AttributeError):
        candidates = []
    rankings: list[dict[str, Any]] = []
    for candidate in candidates if isinstance(candidates, list) else []:
        if not isinstance(candidate, dict) or candidate.get("agent_id") not in criteria:
            continue
        try:
            score = max(0, min(100, round(float(candidate.get("score")))))
        except (TypeError, ValueError):
            continue
        if candidate["agent_id"] not in {item["agent_id"] for item in rankings}:
            rankings.append({"agent_id": candidate["agent_id"], "score": score})
    rankings = [item for item in rankings if item["agent_id"] != selected_team]
    return [{"agent_id": selected_team, "score": 100}, *rankings[:2]]


def _json_object(text: str) -> dict[str, Any]:
    """Decode the small JSON contract returned by the AI Core fallback."""
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[-1]
        if candidate.rstrip().endswith("```"):
            candidate = candidate.rstrip()[:-3]
    payload = json.loads(candidate.strip())
    if not isinstance(payload, dict):
        raise ValueError("Fallback response must be a JSON object.")
    return payload


def _ai_core_fallback(task_state: str) -> dict[str, Any]:
    """Use the configured LLM only when the external RPT service is unavailable.

    This maintains the RPT decision contract without pretending that the external
    RPT endpoint answered. It is deliberately read-only and does not authorize a
    Joule or business-system write.
    """
    config = _config()
    contract = {
        field: list(config[field]["criteria"].keys())
        for field in _CHOICE_FIELDS
    }
    contract["priority"] = ["0", "1", "2"]
    prompt = (
        "Assess this operational request using the supplied decision state. \n+"
        "Return JSON only, with exactly these string fields: next_agent, handoff_mode, risk, priority. \n+"
        f"Allowed labels: {json.dumps(contract)}. \n+"
        "This is a read-only recommendation; never authorize an external action.\n\n"
        f"Decision state:\n{task_state}"
    )
    raw = chat_text([
        {"role": "system", "content": "You are a precise operational routing assessor. Return valid JSON only."},
        {"role": "user", "content": prompt},
    ], max_tokens=180)
    payload = _json_object(raw)
    answers = {
        "next_agent": {"choice": str(payload.get("next_agent", ""))},
        "handoff_mode": {"choice": str(payload.get("handoff_mode", ""))},
        "risk": {"choice": str(payload.get("risk", ""))},
        "priority": {"score": str(payload.get("priority", ""))},
    }
    # Validate through the same contract as an external RPT response.
    for field in _CHOICE_FIELDS:
        _choice(answers, field)
    _choice(answers, "priority")
    return answers


def decide(request: str, grounding_context: str, artifacts: list[dict[str, Any]] | None = None,
           *, synthesis_artifact: dict[str, Any] | None = None) -> dict[str, Any]:
    """Use grounded evidence for a read-only RPT assessment."""
    _load_repo_env()
    token = _required(os.getenv("SAP_RPT_API_KEY", ""), "SAP_RPT_API_KEY")
    grounded_state = _grounded_state(request, grounding_context, artifacts, synthesis_artifact)
    provider = "sap_rpt_decision_api"
    fallback_reason: str | None = None
    payload: dict[str, Any] | None = None
    try:
        response = requests.post(
            RPT_ENDPOINT,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=_request(grounded_state), timeout=runtime_timeout("rpt_request"),
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as error:
        fallback_reason = f"SAP RPT Decision API request failed ({getattr(error.response, 'status_code', 'network')})."
    except ValueError as error:
        fallback_reason = "SAP RPT Decision API returned invalid JSON."

    answers = payload.get("answers") if fallback_reason is None and isinstance(payload, dict) else None
    if not isinstance(answers, dict):
        provider = "ai_core_rpt_fallback"
        try:
            answers = _ai_core_fallback(grounded_state)
        except Exception as error:
            detail = fallback_reason or "SAP RPT Decision API response has no answers."
            raise RuntimeError(f"{detail} AI Core RPT fallback failed.") from error
    return {
        "original_state": request, "grounded_state": grounded_state, "grounding_used": bool(grounding_context.strip()),
        "model": RPT_MODEL if provider == "sap_rpt_decision_api" else "AI Core RPT fallback",
        "next_agent": _choice(answers, "next_agent"), "handoff_mode": _choice(answers, "handoff_mode"),
        "risk": _choice(answers, "risk"), "priority": _choice(answers, "priority"),
        "team_rankings": _team_rankings(grounded_state, _choice(answers, "next_agent")),
        "answers": answers, "usage": payload.get("usage", {}) if isinstance(payload, dict) else {},
        "provider": provider, "fallback_reason": fallback_reason,
        "execution_boundary": "Read-only RPT assessment; the Orchestrator retains all routing and no external action is authorized.",
    }
