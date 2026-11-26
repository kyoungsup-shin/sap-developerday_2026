"""Independent Team execution: native delegation, Specialist Tools, synthesis."""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from .ai_core import chat_completion, chat_text_stream
from .catalog import SPECIALIST_REVIEW_STYLE, TEAM_REVIEW_STYLE, specialist_system_prompt, team_system_prompt
from .harness_profile import get_profile
from .errors import HarnessError
from .review_text import ReviewDisplay
from .harness_configuration import context_limits
from .local_tools import specialist_domains, execute_authorized_tool, normalized_arguments, tool_ids_for_subagent, tool_schemas_for_subagent

MAX_TOOL_TURNS = get_profile()["runtime"]["max_tool_turns"]


def artifact_digest(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Retain decision evidence and numeric calculations without nested trace copies."""
    return [{"team_id": item.get("team_id"), "finding": str(item.get("finding", ""))[:context_limits()["artifact_characters"]],
             "context_ids": sorted(context_ids(item)),
             "calculations": item.get("calculations", []), "record": item.get("record", {})}
            for item in artifacts[-context_limits()["prior_artifacts"]:]]


def context_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        if isinstance(value.get("CONTEXT_ID"), str):
            found.add(value["CONTEXT_ID"])
        if isinstance(value.get("context_ids"), list):
            found.update(item for item in value["context_ids"] if isinstance(item, str))
        for item in value.values():
            found.update(context_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(context_ids(item))
    return found


def _calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    calls = message.get("tool_calls", [])
    if not isinstance(calls, list) or any(not isinstance(call, dict) or not isinstance(call.get("id"), str)
                                          or not isinstance(call.get("function"), dict) for call in calls):
        raise HarnessError("invalid_tool_response", "The Agent returned an invalid Tool response.")
    return calls


def _assistant(message: dict[str, Any]) -> dict[str, Any]:
    return {key: message[key] for key in ("role", "content", "tool_calls") if key in message} | {"role": "assistant"}


def model_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "grounding": str(payload.get("grounding", ""))[:context_limits()["grounding_characters"]],
            "prior_artifacts": artifact_digest(payload.get("prior_artifacts", []))}


def select_specialists(team: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, str]]:
    schema = {"type": "function", "function": {
        "name": "delegate_specialists", "description": "Select only the registered Specialists required for this review, with a concrete goal for each.",
        "parameters": {"type": "object", "properties": {"delegations": {"type": "array", "minItems": 1, "maxItems": context_limits()["max_specialists"],
            "items": {"type": "object", "properties": {"agent": {"type": "string", "enum": team["sub_agents"]},
            "goal": {"type": "string", "minLength": 1}}, "required": ["agent", "goal"], "additionalProperties": False}}},
            "required": ["delegations"], "additionalProperties": False}}}
    messages = [{"role": "system", "content": team_system_prompt(team)}, {"role": "user", "content": json.dumps({
        **model_payload(payload),
        "available_specialists": [{"agent": specialist, "authorized_evidence_domains": list(specialist_domains(specialist)),
                                   "authorized_tools": list(tool_ids_for_subagent(specialist))} for specialist in team["sub_agents"]],
        "evidence_domain_meaning": {"financial_control": "Cost Center master, allocation changes, budgets, and approval requirements",
                                    "cost_driver": "Product unit-cost assumptions; does not expose Cost Center controls",
                                    "business_outlook": "Product demand and FX/raw-material scenario forecasts",
                                    "erp_readiness": "ERP change tickets and mapping validation; does not replace controller approval"},
    })}]
    for _ in range(2):
        response = chat_completion(messages, [schema], "required", agent_id=team["agent_id"])
        calls = _calls(response)
        try:
            if len(calls) != 1 or calls[0]["function"].get("name") != "delegate_specialists":
                raise ValueError("Choose delegate_specialists once.")
            plan = json.loads(calls[0]["function"]["arguments"])
            delegations = plan["delegations"]
            if not isinstance(delegations, list) or not 1 <= len(delegations) <= context_limits()["max_specialists"]:
                raise ValueError("Respect the configured Specialist count limit.")
            selected = set()
            for item in delegations:
                if (not isinstance(item, dict) or item.get("agent") not in team["sub_agents"]
                        or not isinstance(item.get("goal"), str) or not item["goal"].strip() or item["agent"] in selected):
                    raise ValueError("Use distinct registered Specialists with non-empty goals.")
                selected.add(item["agent"])
            return delegations
        except (KeyError, TypeError, ValueError):
            # Repair the schema response, never substitute a fixed Specialist route.
            messages.append({"role": "user", "content": "The last delegation violated the Tool contract. Respect the configured Specialist count limit, choose distinct registered Specialists and provide a concrete goal for each."})
    raise HarnessError("invalid_delegation", "The Team could not produce a valid Specialist delegation after a format retry.")


def specialist_review(specialist: str, goal: str, payload: dict[str, Any], prior_findings: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": specialist_system_prompt(specialist)},
        {"role": "user", "content": json.dumps({**model_payload(payload), "goal": goal,
            "prior_specialist_findings": prior_findings})},
    ]
    schemas = tool_schemas_for_subagent(specialist)
    observations: list[dict[str, Any]] = []
    cached: dict[str, dict[str, Any]] = {}
    resolved = context_ids(payload.get("prior_artifacts", [])) | context_ids(prior_findings)
    final_text = ""
    for _ in range(get_profile()["runtime"]["max_tool_turns"]):
        response = chat_completion(messages, schemas, agent_id="specialist:" + specialist)
        calls = _calls(response)
        messages.append(_assistant(response))
        if not calls:
            final_text = str(response.get("content") or "").strip()
            break
        for call in calls:
            function = call["function"]
            try:
                name = function.get("name")
                arguments = normalized_arguments(json.loads(function.get("arguments", "{}")))
                key = json.dumps({"tool": name, "arguments": arguments}, sort_keys=True, separators=(",", ":"))
                if key in cached:
                    result = cached[key]["result"]
                else:
                    if name != "search_business_context" and (not isinstance(arguments, dict) or arguments.get("context_id") not in resolved):
                        raise ValueError("Resolve the Context using search_business_context or supplied prior evidence before retrieving or calculating.")
                    observation = execute_authorized_tool(specialist, name, arguments)
                    cached[key] = observation
                    observations.append(observation)
                    resolved.update(context_ids(observation["result"]))
                    result = observation["result"]
                    yield {"type": "tool_observation", "subagent_label": specialist, "tool_call_id": call["id"],
                           "tool": name, "arguments": observation["arguments"], "domains": observation["domains"], "result": result}
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})
            except (TypeError, ValueError, KeyError):
                feedback = {"state": "invalid_input", "message": "Use an authorized Tool with its required string argument. Resolve the Context ID from lookup or prior evidence first."}
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(feedback)})
                yield {"type": "tool_input_rejected", "subagent_label": specialist, "tool_call_id": call["id"],
                       "code": "invalid_tool_input", "message": "The Specialist is correcting a Tool request."}
    display = ReviewDisplay()
    if not final_text:
        messages.append({"role": "user", "content": "Tool turn budget is exhausted. Provide an evidence-backed review in English Markdown prose now, cite available figures and source records, and state critical missing evidence. No further Tool calls; do not output JSON." + SPECIALIST_REVIEW_STYLE})
        for delta in chat_text_stream(messages, agent_id="specialist:" + specialist):
            visible = display.feed(delta)
            if visible:
                yield {"type": "subagent_message_delta", "subagent_label": specialist, "delta": visible}
    else:
        visible = display.feed(final_text)
        if visible:
            yield {"type": "subagent_message_delta", "subagent_label": specialist, "delta": visible}
    tail = display.finish()
    if tail:
        yield {"type": "subagent_message_delta", "subagent_label": specialist, "delta": tail}
    final_text = display.text
    if not final_text.strip():
        raise HarnessError("empty_specialist_review", "The Specialist returned no review.")
    artifact = {"subagent": specialist, "goal": goal, "finding": final_text, "record": display.record,
                "tool_calls": observations, "context_ids": sorted(resolved), "read_only": True}
    yield {"type": "subagent_completed", "subagent_label": specialist, "artifact": artifact}


def run_team(team: dict[str, Any], payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield {"type": "delegation_started"}
    delegations = select_specialists(team, payload)
    yield {"type": "delegation_selected", "delegations": [item["agent"] for item in delegations], "delegation_goals": delegations}
    findings: list[dict[str, Any]] = []
    for sub_step, delegation in enumerate(delegations, 1):
        specialist = delegation["agent"]
        yield {"type": "subagent_started", "subagent_label": specialist, "sub_step": sub_step}
        for event in specialist_review(specialist, delegation["goal"], payload, findings):
            yield {**event, "sub_step": sub_step}
            if event["type"] == "subagent_completed":
                findings.append(event["artifact"])
    calculations = [observation["result"] for finding in findings for observation in finding["tool_calls"]
                    if observation["name"] == "calculate_profitability_scenarios" and observation["result"]["state"] == "calculated"]
    messages = [{"role": "system", "content": team_system_prompt(team) +
                 " Synthesize the Specialist evidence into a concise readable Team assessment. Cite exact record IDs and scenario figures. "
                 "State only decision-critical missing inputs and the useful next review. Do not claim a purchase, approval, or data change occurred." + TEAM_REVIEW_STYLE},
                {"role": "user", "content": json.dumps({"request": payload["request"], "purpose": payload["purpose"],
                  "grounding": model_payload(payload)["grounding"], "specialist_findings": findings,
                  "prior_artifacts": artifact_digest(payload.get("prior_artifacts", []))})}]
    display = ReviewDisplay()
    for delta in chat_text_stream(messages, agent_id=team["agent_id"]):
        visible = display.feed(delta)
        if visible:
            yield {"type": "team_message_delta", "delta": visible}
    tail = display.finish()
    if tail:
        yield {"type": "team_message_delta", "delta": tail}
    summary = display.text
    if not summary.strip():
        raise HarnessError("empty_team_review", "The Team returned no synthesis.")
    artifact = {"team_id": team["agent_id"], "finding": summary, "record": display.record,
                "delegated_findings": findings, "context_ids": sorted(context_ids(findings)),
                "calculations": calculations, "read_only": True}
    yield {"type": "team_artifact", "artifact": artifact}
