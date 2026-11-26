"""Demo Orchestrator: observe Cards/Artifacts, invoke capabilities, delegate over A2A."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

from a2a.helpers import new_data_part, new_text_part
from a2a.types import Artifact
from google.protobuf.json_format import MessageToDict

from .ai_core import chat_completion
from .a2a_transport import discover_cards, handoff_envelope, send_task, sync_stream
from .catalog import AGENT_CATALOG, FINAL_REVIEW_STYLE, ORCHESTRATOR_SYSTEM_PROMPT, public_agents, public_prompts
from .harness_profile import get_profile
from .errors import HarnessError, public_error
from .grounding import retrieve_context
from .joule_cli import send_message, verify_card
from .rpt_decision import decide as rpt_decide
from .review_text import readable_review, review_record
from .catalog import orchestrator_system_prompt
from .harness_settings import settings_scope, agent_scope, current_settings, read_revision
from .harness_configuration import context_limits
from .prompt_resources import get_prompt

MAX_HANDOFFS = get_profile()["runtime"]["max_handoffs"]


def _synthesis_artifact(summary: str, record: dict[str, Any] | None, context_id: str,
                        grounding: str, sources: list[str], source_ids: list[str],
                        artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    """Package the model's final synthesis with original evidence and provenance."""
    evidence = [{key: artifact[key] for key in ("team_id", "task_id", "handoff_id", "context_id",
                 "finding", "record", "context_ids", "calculations") if key in artifact} for artifact in artifacts]
    data = {"schema_version": "demo.synthesis.v1", "kind": "final_synthesis",
            "producer": "orchestration-agent", "context_id": context_id, "read_only": True,
            "summary": summary, "summary_record": record, "grounding": grounding,
            "sop_sources": sources, "sop_source_ids": source_ids, "source_artifacts": evidence}
    artifact = Artifact(artifact_id=str(uuid4()), name="Final synthesis",
                        description="Custom Extension Assistant synthesis of verified SOP and completed review evidence.",
                        parts=[new_text_part(summary), new_data_part(data)])
    return MessageToDict(artifact, preserving_proto_field_name=True)


def _artifact_digest(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"team_id": artifact.get("team_id"), "finding": str(artifact.get("finding", ""))[:context_limits()["artifact_characters"]],
             "context_ids": artifact.get("context_ids", []), "calculations": artifact.get("calculations", [])}
            for artifact in artifacts[-context_limits()["prior_artifacts"]:]]


def _history_digest(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    remaining = context_limits()["history_characters"]
    result = []
    for message in reversed(history[-context_limits()["history_messages"]:]):
        content = message.get("content", "")
        if isinstance(content, dict):
            content = content.get("summary", "")
        content = str(content)[:remaining]
        remaining -= len(content)
        result.insert(0, {"role": str(message.get("role", "user")), "content": content})
        if not remaining:
            break
    return result


def _function(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}}}


def _generate_final_summary(request: str, history: list[dict[str, Any]], grounding: str,
                            sources: list[str], source_ids: list[str], artifacts: list[dict[str, Any]],
                            decision_summary: str, failures: list[dict[str, Any]]) -> str:
    """Generate the actual requester answer after the model ends capability selection."""
    context = {"request": request, "conversation_history": _history_digest(history),
               "grounding": grounding[:context_limits()["grounding_characters"]],
               "sop_sources": sources, "sop_source_ids": source_ids,
               "completed_artifacts": _artifact_digest(artifacts),
               "decision_draft": decision_summary, "failed_handoffs": failures}
    messages = [{"role": "system", "content": orchestrator_system_prompt()},
                {"role": "system", "content": get_prompt("roles.final_synthesis")},
                {"role": "user", "content": json.dumps(context)}]
    try:
        response = chat_completion(messages, agent_id="orchestrator")
        summary = response.get("content")
        if not isinstance(summary, str) or not summary.strip() or response.get("tool_calls"):
            raise ValueError("Missing final text")
        return summary.strip()
    except Exception:
        raise HarnessError("final_summary_unavailable", "The final summary could not be generated. Retry the review.") from None


def _decide(request: str, history: list[dict[str, Any]], grounding: str, artifacts: list[dict[str, Any]],
            cards: dict[str, Any], remaining: int, failures: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    text = {"type": "string", "minLength": 1}
    tools = [_function("finish_review", "Create the final Synthesis Artifact with an evidence-backed English answer. The runtime preserves this synthesis together with verified SOP and completed review evidence. Include decision-critical quantities, scenario numbers, sources, missing inputs, and next steps; never claim external execution." + FINAL_REVIEW_STYLE,
                       {"summary": text | {"description": "The complete requester-facing answer, about 150 words: conclusion, decisive quantities and source IDs, critical missing inputs, and next steps. Evidence belongs here, not only in reason."},
                        "reason": text | {"description": "One short sentence explaining why the review can end. This internal rationale is not the final Chat answer."}})]
    if remaining > 0:
        tools.append(_function("delegate_team", "Delegate a scoped evidence review to one discovered Team. Use prior Artifacts to choose the next useful capability; repeated Team handoff needs a distinct purpose.",
                               {"target_agent_id": {"type": "string", "enum": list(cards)}, "purpose": text, "reason": text}))
    if not grounding:
        tools.append(_function("search_grounding", "Retrieve the applicable SOP evidence required for every operational request. Choose a focused English query from the request and conversation context. SOP verification must complete before any Team review or final business assessment.",
                               {"query": text, "reason": text}))
    context = {"request": request, "conversation_history": _history_digest(history), "grounding": grounding[:context_limits()["grounding_characters"]],
               "grounding_status": "sop_verified" if grounding else "unavailable", "prior_artifacts": _artifact_digest(artifacts),
               "agent_cards": {key: MessageToDict(card, preserving_proto_field_name=True) for key, card in cards.items()},
               "handoff_budget_remaining": remaining, "failed_handoffs": failures}
    messages: list[dict[str, Any]] = [{"role": "system", "content": orchestrator_system_prompt()},
                                     {"role": "user", "content": json.dumps(context)}]
    for _ in range(2):
        response = chat_completion(messages, tools, "required")
        calls = response.get("tool_calls", [])
        try:
            if not isinstance(calls, list) or len(calls) != 1:
                raise ValueError()
            name = calls[0]["function"]["name"]
            arguments = json.loads(calls[0]["function"]["arguments"])
            schema = next(tool["function"] for tool in tools if tool["function"]["name"] == name)
            if not isinstance(arguments, dict) or set(arguments) != set(schema["parameters"]["required"]):
                raise ValueError()
            if any(not isinstance(value, str) or not value.strip() for value in arguments.values()):
                raise ValueError()
            if name == "delegate_team" and arguments["target_agent_id"] not in cards:
                raise ValueError()
            if not grounding and name != "search_grounding":
                raise ValueError("Required SOP evidence is missing")
            return name, arguments
        except (TypeError, ValueError, KeyError, StopIteration):
            messages.append({"role": "user", "content": "Choose exactly one available capability with all required non-empty string arguments. Respect the handoff budget. " + ("Verified SOP evidence is missing: select search_grounding with a focused query before delegating or finishing." if not grounding else "Use the supplied verified SOP requirements.")})
    raise HarnessError("invalid_orchestration", "The Custom Extension Assistant could not produce a valid capability decision.")


def _rpt_event(result: dict[str, Any], final: bool = False) -> dict[str, Any]:
    return {"type": "rpt_final_decision_completed" if final else "rpt_decision_completed", "agent_id": "rpt-decision-agent",
            "decision": {key: result[key] for key in ("next_agent", "handoff_mode", "risk", "priority", "team_rankings", "grounded_state", "grounding_used")},
            "answers": result["answers"], "provider": result.get("provider"),
            "fallback_reason": result.get("fallback_reason")}


def _initial_extensions(request: str, grounding: str, artifacts: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    yield {"type": "rpt_decision_started", "agent_id": "rpt-decision-agent"}
    try:
        rpt = rpt_decide(request, grounding)
    except Exception:
        yield {"type": "rpt_decision_failed", "agent_id": "rpt-decision-agent", "code": "rpt_unavailable",
               "message": "The initial RPT assessment is unavailable. Check RPT and AI Core configuration."}
        yield {"type": "joule_handoff_skipped", "agent_id": "joule-work-agent", "reason": "rpt_unavailable",
               "message": "Joule handoff was skipped because the RPT assessment is unavailable."}
        return
    yield _rpt_event(rpt)
    if rpt["handoff_mode"] != "delegate_now":
        yield {"type": "joule_handoff_skipped", "agent_id": "joule-work-agent", "reason": rpt["handoff_mode"],
               "message": "Joule handoff was deferred by the RPT assessment."}
        return
    yield {"type": "joule_card_verification_started", "agent_id": "joule-work-agent"}
    try:
        verified = verify_card()
        yield {"type": "joule_card_verified", "agent_id": "joule-work-agent", "agent_label": "Joule Work Agent", "solution": verified["solution"], "card": verified["card"]}
        yield {"type": "joule_handoff_started", "agent_id": "joule-work-agent", "agent_label": "Joule Work Agent"}
        artifact = send_message(request, rpt, verified)
    except Exception:
        yield {"type": "joule_handoff_failed", "agent_id": "joule-work-agent", "code": "joule_unavailable",
               "message": "Joule connection is unavailable. Check the deployed Agent and CLI connection settings."}
        return
    artifacts.append({"team_id": "joule-work-agent", "finding": json.dumps(artifact["result"]), "read_only": True, "source": "joule_cli"})
    yield {"type": "joule_artifact_received", "agent_id": "joule-work-agent", "agent_label": "Joule Work Agent", "artifact": artifact}


def run_handoff_stream(request: str, history: list[dict[str, Any]], repository_id: str | None = None,
                       language: str = "en", context_id: str | None = None, settings_revision: int | None = None, prior_artifacts: list[dict[str, Any]] | None = None) -> Iterator[dict[str, Any]]:
    with settings_scope(read_revision(settings_revision)), agent_scope("orchestrator"):
        yield from _run_handoff_stream(request, history, repository_id, language, context_id, prior_artifacts)


def _run_handoff_stream(request: str, history: list[dict[str, Any]], repository_id: str | None = None,
                        language: str = "en", context_id: str | None = None, prior_artifacts: list[dict[str, Any]] | None = None) -> Iterator[dict[str, Any]]:
    max_handoffs = get_profile()["runtime"]["max_handoffs"]
    rpt_request = request + ("\nRecent conversation and human review input:\n" + json.dumps(_history_digest(history)) if history else "")
    context_id = context_id or str(uuid4())
    yield {"type": "field_handoff_received", "context_id": context_id, "handoff": {
        "source_agent_id": "field-agent", "target_agent_id": "orchestration-agent", "purpose": "operational_review", "request": request}}
    yield {"type": "harness_settings_applied", "settings_revision": current_settings()["revision"], "context_id": context_id}
    artifacts: list[dict[str, Any]] = list(prior_artifacts or [])
    failures: list[dict[str, Any]] = []
    grounding = ""
    sources: list[str] = []
    source_ids: list[str] = []
    grounding_ready = False
    extensions_started = False
    final_summary = ""
    termination = "completed"
    try:
        yield {"type": "agent_cards_discovery_started"}
        cards = asyncio.run(discover_cards())
        yield {"type": "agent_cards_discovered", "cards": {key: MessageToDict(card, preserving_proto_field_name=True) for key, card in cards.items()}}
        capability, sop_request = _decide(request, history, "", artifacts, cards, max_handoffs, failures)
        if capability != "search_grounding":
            raise HarnessError("sop_required", "The Custom Extension Assistant did not request required SOP evidence. The business review was not started.")
        query = sop_request["query"]
        yield {"type": "grounding_started", "query": query, "reason": sop_request["reason"]}
        try:
            retrieved = retrieve_context(query, repository_id=repository_id, language=language, require_sop=True)
            grounding = str(retrieved.get("context", "")).strip()
            sources = retrieved.get("sop_sources", [])
            if (not grounding or retrieved.get("metadata_available") is not True
                    or not isinstance(sources, list) or not sources
                    or any(not isinstance(source, str) or not source.strip() for source in sources)):
                raise ValueError("Missing verified SOP evidence")
        except Exception:
            message = "Required SOP evidence could not be verified. The business review was not started; check the SOP repository and retry."
            yield {"type": "grounding_failed", "code": "sop_unavailable", "message": message}
            raise HarnessError("sop_unavailable", message) from None
        grounding_ready = True
        source_ids = retrieved.get("sop_source_ids", [])
        yield {"type": "grounding_completed", "source": retrieved["source"], "metadata_available": True,
               "message": "Applicable SOP evidence verified.", "context_preview": grounding, "sop_sources": sources,
               "sop_source_ids": source_ids}
        extensions_started = True
        yield from _initial_extensions(rpt_request, grounding, artifacts)
        for step in range(1, max_handoffs + 2):
            name, arguments = _decide(request, history, grounding, artifacts, cards, max_handoffs - step + 1,
                                      failures)
            observation = {"completed_work": ["Received " + str(len(artifacts)) + " review Artifact(s)."],
                           "new_evidence": [artifact.get("finding", "")[:360] for artifact in artifacts[-2:]],
                           "unresolved_decisions": [arguments["reason"]], "available_capabilities": list(cards),
                           "decision_focus": [arguments["reason"]], "chat_summary": arguments["reason"],
                           "grounding_used": bool(grounding)}
            yield {"type": "orchestration_observation", "step": step, "observation": observation}
            decision = {"action": "complete" if name == "finish_review" else "delegate", "reason": arguments["reason"],
                        "target_agent_id": arguments.get("target_agent_id", "complete"), "purpose": arguments.get("purpose", "final_review")}
            yield {"type": "orchestration_decision", "step": step, "decision": decision}
            if name == "finish_review":
                final_summary = _generate_final_summary(
                    request, history, grounding, sources, source_ids, artifacts,
                    decision_summary=arguments["summary"], failures=failures)
                break
            target = arguments["target_agent_id"]
            team = next((team for team in get_profile()["agents"] if team["agent_id"] == target), {"agent_label": cards[target].name})
            payload = {"request": request, "purpose": arguments["purpose"], "history": _history_digest(history),
                       "grounding": grounding, "prior_artifacts": _artifact_digest(artifacts), "language": language,
                       "settings_revision": current_settings()["revision"]}
            envelope = handoff_envelope(target, payload)
            identity = {"step": step, "agent_id": target, "agent_label": team["agent_label"],
                        "handoff_id": envelope["handoff_id"], "context_id": context_id}
            yield {"type": "team_handoff_started", **identity, "handoff": envelope}
            try:
                for event in sync_stream(lambda: send_task(cards[target], envelope, context_id)):
                    event = {**identity, **event}
                    if event["type"] == "team_artifact_received":
                        artifacts.append(event["artifact"])
                        yield {"type": "artifact_received", **identity, "task_id": event["task_id"],
                               "record": {"step": step, "producer": target, "artifact": event["artifact"]}}
                    else:
                        if event["type"] == "subagent_message_delta":
                            event["stream_id"] = envelope["handoff_id"] + ":specialist:" + str(event.get("sub_step", 0))
                        elif event["type"] == "team_message_delta":
                            event["stream_id"] = envelope["handoff_id"] + ":synthesis"
                        yield event
            except Exception as error:
                failure = {"type": "team_handoff_failed", **identity, **public_error(error)}
                failures.append(failure)
                yield failure
        if not final_summary:
            raise HarnessError("missing_final_response", "The Custom Extension Assistant did not produce a final response within the handoff limit.")
        if failures and not any(artifact.get("team_id") != "joule-work-agent" for artifact in artifacts):
            termination = "failed"
    except Exception as error:
        termination = "failed"
        failure = public_error(error)
        yield {"type": "error", **failure}
        final_summary = "The review could not be completed. " + failure["message"]
    if not extensions_started:
        yield {"type": "rpt_decision_started", "agent_id": "rpt-decision-agent"}
        yield {"type": "rpt_decision_failed", "agent_id": "rpt-decision-agent", "code": "sop_required",
               "message": "Initial RPT was not run because required SOP evidence was not established."}
        yield {"type": "joule_handoff_skipped", "agent_id": "joule-work-agent", "reason": "sop_required",
               "message": "Joule handoff requires verified SOP evidence."}
    summary_record = review_record(final_summary)
    final_summary = readable_review(final_summary)
    synthesis_artifact = None
    if termination == "completed":
        synthesis_artifact = _synthesis_artifact(final_summary, summary_record, context_id,
                                                grounding, sources, source_ids, artifacts)
        yield {"type": "orchestrator_artifact_created", "agent_id": "orchestration-agent",
               "context_id": context_id, "artifact": synthesis_artifact}
    yield {"type": "orchestrator_message_delta", "stream_id": "final-summary", "delta": final_summary}
    yield {"type": "rpt_final_decision_started", "agent_id": "rpt-decision-agent"}
    final_rpt = None
    try:
        if not grounding_ready:
            raise HarnessError("sop_required", "Required SOP evidence is unavailable.")
        final_rpt = rpt_decide(rpt_request, grounding, _artifact_digest(artifacts),
                               synthesis_artifact=synthesis_artifact)
    except Exception:
        yield {"type": "rpt_final_decision_failed", "agent_id": "rpt-decision-agent", "code": "sop_required" if not grounding_ready else "rpt_unavailable",
               "message": "The final RPT assessment is unavailable. " + ("Required SOP evidence was not established." if not grounding_ready else "Check RPT and AI Core configuration.")}
    else:
        yield _rpt_event(final_rpt, True)
    checkpoint = None
    if (termination == "completed" and current_settings().get("hitl_mode") == "require_input"
            and final_rpt and final_rpt["handoff_mode"] in {"request_evidence", "request_human_approval"}):
        try:
            from .human_review import pause_review
            checkpoint = pause_review(request, history, context_id, current_settings()["revision"], artifacts, final_rpt)
            termination = "input_required"
            yield {"type": "human_input_required", **checkpoint}
        except HarnessError as error:
            termination = "failed"
            yield {"type": "error", **public_error(error)}
    final = {"summary": final_summary, "summary_record": summary_record, "artifacts": artifacts, "rpt_decision": final_rpt,
             "synthesis_artifact": synthesis_artifact,
             "termination": {"state": termination}, "human_review": checkpoint, "grounding_used": bool(grounding), "failed_handoffs": failures}
    yield {"type": "field_response_delivered", "source": "orchestration-agent", "target": "field-agent", "message": final}
    yield {"type": "complete", "result": final}
