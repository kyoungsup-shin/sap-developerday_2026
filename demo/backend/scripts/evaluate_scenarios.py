#!/usr/bin/env python3
"""Run the five demo scenarios against the live SSE API and score their traces."""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import queue
import re
import sys
import time
import uuid
from pathlib import Path
from collections.abc import Callable
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "demo" / "backend"))
from gateway.ai_core import _load_repo_env
from gateway.local_tools import specialist_domains, tool_ids_for_subagent
from gateway.harness_profile import get_profile
from gateway.harness_settings import settings_scope, read_revision, current_settings

SCENARIOS = (
    ("strawberry_order", "Additional order for existing raw materials", "Please place an additional order for strawberry concentrate."),
    ("cip_seal_kit", "Replenishment purchase for existing equipment consumables", "Please purchase a CIP pump mechanical seal kit."),
    ("lemon_profitability", "Business impact assessment for exchange-rate and raw-material price changes", "Please review how recent exchange-rate and raw-material price changes could affect the profitability of lemon carbonated beverages next quarter."),
    ("allulose_introduction", "Register and introduce a new raw material into production", "We plan to use allulose sweetener in the next production run. Please proceed with the required process."),
    ("cost_center_change", "Change the production-line cost center", "Please change the Cost Center for Beverage Line 1 starting next quarter."),
)
HANGUL = re.compile(r"[가-힣]")
SECRETS = re.compile(r"(?i)(bearer\s+|token[=:]\s*|password[=:]\s*)[^\s,;]+")


class StreamInterrupted(RuntimeError):
    """A transport failure retaining all SSE evidence received before it failed."""

    def __init__(self, events: list[dict[str, Any]], error: BaseException):
        super().__init__(str(error))
        self.events = events
        self.error = error


def sanitize_event(event: dict[str, Any]) -> dict[str, Any]:
    changed = False
    secrets = [os.getenv(key, "") for key in ("SAP_RPT_API_KEY", "AICORE_CLIENT_SECRET", "AICORE_CLIENT_ID") if len(os.getenv(key, "")) >= 8]
    def clean(value: Any) -> Any:
        nonlocal changed
        if isinstance(value, str):
            safe = SECRETS.sub("[REDACTED]", value)
            for secret in secrets:
                safe = safe.replace(secret, "[REDACTED]")
            changed = changed or safe != value
            return safe
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if str(key).lower() in {"client_secret", "access_token", "api_key", "authorization", "password"}:
                    result[key] = "[REDACTED]"
                    changed = True
                else:
                    result[key] = clean(item)
            return result
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value
    safe = clean(event)
    if changed:
        safe["redacted_secrets"] = True
    return safe


def event_stream(base_url: str, request_text: str, timeout: int, on_event: Callable[[dict[str, Any]], None] | None = None, settings_revision: int | None = None) -> list[dict[str, Any]]:
    payload = {"message": request_text, "session_id": f"evaluation-{uuid.uuid4()}", "language": "en"}
    if settings_revision is not None:
        payload["settings_revision"] = settings_revision
    events: list[dict[str, Any]] = []
    # A silent stream means a downstream synchronous call is wedged. Keep the
    # evaluator moving so the remaining scenarios still receive a result.
    try:
        with requests.post(f"{base_url.rstrip('/')}/api/chat/stream", json=payload, stream=True, timeout=(15, min(timeout, 30))) as response:
            response.raise_for_status()
            response.encoding = "utf-8"
            event_type = "update"
            # Avoid requests' default buffering: it conceals partial SSE evidence.
            for raw in response.iter_lines(chunk_size=1, decode_unicode=True):
                if raw is None:
                    continue
                if raw.startswith("event: "):
                    event_type = raw[7:].strip()
                elif raw.startswith("data: "):
                    try:
                        data = json.loads(raw[6:])
                    except json.JSONDecodeError:
                        data = {"message": "Invalid SSE JSON", "diagnostic": raw[6:][:300]}
                    event = sanitize_event({"type": event_type, "data": data, "at": time.time()})
                    events.append(event)
                    if on_event:
                        on_event(event)
                elif not raw:
                    event_type = "update"
    except (requests.RequestException, TimeoutError, OSError) as error:
        raise StreamInterrupted(events, error) from error
    return events


def _stream_worker(result_queue: Any, base_url: str, request_text: str, timeout: int, settings_revision: int | None = None) -> None:
    try:
        event_stream(base_url, request_text, timeout, lambda event: result_queue.put({"kind": "event", "event": event}), settings_revision=settings_revision)
        result_queue.put({"kind": "done"})
    except StreamInterrupted as error:
        result_queue.put({"kind": "done", "transport_error": str(error.error)})
    except BaseException as error:
        result_queue.put({"kind": "done", "transport_error": str(error)})


def run_with_timeout(seconds: int, base_url: str, request_text: str, settings_revision: int | None = None) -> tuple[list[dict[str, Any]], str | None]:
    """Use a child process so a blocked socket cannot defeat the wall-clock limit."""
    context = multiprocessing.get_context("fork")
    result_queue = context.Queue(maxsize=1)
    worker = context.Process(target=_stream_worker, args=(result_queue, base_url, request_text, seconds, settings_revision))
    worker.start()
    events: list[dict[str, Any]] = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = result_queue.get(timeout=min(0.25, deadline - time.monotonic()))
        except queue.Empty:
            if not worker.is_alive():
                break
            continue
        if result.get("kind") == "event":
            events.append(result["event"])
            continue
        worker.join(1)
        return events, result.get("transport_error")
    if worker.is_alive():
        worker.terminate()
        worker.join(5)
        return events, f"Scenario did not complete within {seconds} seconds."
    return events, f"Stream worker exited without an evaluation result (exit code {worker.exitcode})."


def context_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        if isinstance(value.get("CONTEXT_ID"), str):
            found.add(value["CONTEXT_ID"])
        for item in value.values():
            found |= context_ids(item)
    elif isinstance(value, list):
        for item in value:
            found |= context_ids(item)
    return found


def compact_tool(event: dict[str, Any]) -> dict[str, Any]:
    data = event["data"]
    result = data.get("result", {})
    return {
        "specialist": data.get("subagent_label"),
        "name": data.get("tool"),
        "arguments": data.get("arguments", {}),
        "domains": data.get("domains", []),
        "state": result.get("state") if isinstance(result, dict) else None,
        "context_ids": sorted(context_ids(result)),
    }


def check(name: str, passed: bool, evidence: str, weight: int) -> dict[str, Any]:
    return {"name": name, "passed": passed, "evidence": evidence, "weight": weight}


def score_scenario(scenario_id: str, title: str, request_text: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    domains = {item["name"]: tuple(item["domains"]) for item in get_profile()["specialists"]}
    types = [str(event["type"]) for event in events]
    tools = [compact_tool(event) for event in events if event["type"] == "tool_observation"]
    errors = [str(event["data"].get("message", "")) for event in events if event["type"] == "error"]
    final_deltas = [str(event["data"].get("delta", "")) for event in events if event["type"] == "orchestrator_message_delta"]
    final_answer = "".join(final_deltas).strip()
    final_rpt = next((event["data"].get("decision") for event in reversed(events) if event["type"] == "rpt_final_decision_completed"), None)
    rpt_status = {}
    for stage, terminal_types in (("initial", {"rpt_decision_completed", "rpt_decision_failed"}), ("final", {"rpt_final_decision_completed", "rpt_final_decision_failed"})):
        terminal = next((event for event in reversed(events) if event["type"] in terminal_types), None)
        rpt_status[stage] = {"event": terminal["type"] if terminal else "missing",
                             "provider": terminal["data"].get("provider") if terminal else None,
                             "reason": (terminal["data"].get("fallback_reason") or terminal["data"].get("message")) if terminal else None}
    joule_events = [event for event in events if str(event["type"]).startswith("joule_")]
    tool_names = [str(tool["name"]) for tool in tools]
    valid_tools = bool(tools)
    source_bound = True
    for event in events:
        if event["type"] != "tool_observation":
            continue
        data = event["data"]
        name, specialist, arguments = data.get("tool"), data.get("subagent_label"), data.get("arguments", {})
        parameter = "request_text" if name == "search_business_context" else "context_id"
        valid_tools = valid_tools and specialist in domains
        valid_tools = valid_tools and name in (tool_ids_for_subagent(specialist) if specialist in domains else ())
        valid_tools = valid_tools and isinstance(arguments, dict) and set(arguments) == {parameter} and isinstance(arguments.get(parameter), str) and bool(arguments.get(parameter, "").strip())
        if name == "retrieve_business_evidence" and specialist in domains:
            valid_tools = valid_tools and data.get("domains") == list(domains[specialist])
        result = data.get("result", {})
        source_bound = source_bound and isinstance(result, dict) and result.get("read_only") is True
    resolved_contexts = {context for tool in tools if tool["name"] == "search_business_context" and tool["state"] == "found" for context in tool["context_ids"]}
    used_contexts = {str(tool["arguments"].get("context_id")) for tool in tools if isinstance(tool["arguments"], dict) and tool["arguments"].get("context_id")}
    unauthorized_contexts = used_contexts - resolved_contexts
    initial_rpt_type = "rpt_decision_completed" if "rpt_decision_completed" in types else "rpt_decision_failed"
    final_rpt_type = "rpt_final_decision_completed" if "rpt_final_decision_completed" in types else "rpt_final_decision_failed"
    required_order = ("grounding_started", "grounding_completed", initial_rpt_type, "team_handoff_started", "delegation_selected",
                      "artifact_received", "orchestrator_message_delta", final_rpt_type, "complete")
    positions = {event_type: types.index(event_type) for event_type in required_order if event_type in types}
    ordered = all(kind in positions for kind in required_order) and all(positions[left] < positions[right] for left, right in zip(required_order, required_order[1:]))
    ordered = ordered and types.count("grounding_started") == 1 and types.count("grounding_completed") == 1
    if "grounding_started" in types:
        grounding_terminal = "grounding_completed" if "grounding_completed" in types else "grounding_failed"
        ordered = ordered and grounding_terminal in types and types.index("grounding_started") < types.index(grounding_terminal)
    complete_result = next((event["data"].get("result", {}) for event in reversed(events) if event["type"] == "complete"), {})
    terminated = complete_result.get("termination", {}).get("state") == "completed"
    generated = [str(event["data"].get("delta", "")) for event in events if str(event["type"]).endswith("message_delta")]
    generated.extend(str(event["data"].get("decision", {}).get("grounded_state", "")) for event in events if event["type"] in {"rpt_decision_completed", "rpt_final_decision_completed"})
    english_generated = not any(HANGUL.search(text) for text in generated)
    duration = round(events[-1]["at"] - events[0]["at"], 3) if len(events) > 1 else 0.0

    tool_checks = [
        check("LLM Tool contracts are executable", valid_tools and not any("requires a non-empty" in error or "unauthorized Tool" in error for error in errors), "; ".join(errors) or ("No valid Tool observation." if not valid_tools else "No raw Tool-contract error events."), 10),
        check("Tool Context IDs originate from resolution", valid_tools and not unauthorized_contexts, f"Resolved={sorted(resolved_contexts)}; used={sorted(used_contexts)}", 10),
        check("At least one read-only Tool observation was produced", valid_tools, f"Tools={tool_names}", 10),
    ]
    grounding_checks = [
        check("Required source-bound SOP Grounding precedes the business review", types.count("grounding_started") == 1 and types.count("grounding_completed") == 1 and ordered and any(event["data"].get("metadata_available") is True and event["data"].get("sop_sources") and event["data"].get("context_preview") for event in events if event["type"] == "grounding_completed"), f"Grounding searches={types.count('grounding_started')}; completed={types.count('grounding_completed')}", 10),
        check("Source-bound business context reached collaboration", source_bound and "orchestration_observation" in types and "artifact_received" in types and bool(resolved_contexts), f"Resolved={sorted(resolved_contexts)}; artifacts={types.count('artifact_received')}; source_bound={source_bound}", 10),
    ]
    collaboration_checks = [
        check("Delegation completed", "delegation_selected" in types and "artifact_received" in types, f"Delegations={types.count('delegation_selected')}; artifacts={types.count('artifact_received')}", 10),
        check("Controlled handoff sequence completed", ordered and terminated and not errors, f"Required={required_order}; termination={complete_result.get('termination')}; errors={errors}", 10),
    ]
    chat_checks = [
        check("Final Chat answer is present", bool(final_answer), final_answer[:280] or "No final answer event.", 10),
        check("Generated Chat answers are English", bool(final_answer) and english_generated, "No Hangul in generated Chat/RPT text." if final_answer and english_generated else "Missing final answer or Hangul detected.", 10),
    ]
    rpt_checks = [
        check("Initial RPT lifecycle completed", "rpt_decision_completed" in types or "rpt_decision_failed" in types, "Initial RPT lifecycle event present.", 5),
        check("Final RPT lifecycle and completion are present", ("rpt_final_decision_completed" in types or "rpt_final_decision_failed" in types) and "complete" in types, f"Final RPT={final_rpt is not None}; complete={'complete' in types}", 5),
    ]

    scenario_checks: list[dict[str, Any]] = []
    sop_result = next((event["data"] for event in events if event["type"] == "grounding_completed"), {})
    sop_context = sop_result.get("context_preview", "")
    sop_ids = sop_result.get("sop_source_ids", [])
    handoffs = [event["data"].get("handoff", {}).get("input", {}) for event in events if event["type"] == "team_handoff_started"]
    scenario_checks.extend([
        check("Verified SOP context reaches every Team handoff", bool(sop_context) and bool(handoffs) and all(payload.get("grounding") == sop_context for payload in handoffs), f"Team handoffs={len(handoffs)}; SOP context characters={len(sop_context)}", 0),
        check("Final Chat cites a verified SOP source", bool(sop_ids) and any(identifier in final_answer for identifier in sop_ids), f"Verified SOP IDs={sop_ids}", 0),
    ])
    answer_lower = final_answer.lower()
    if scenario_id == "strawberry_order":
        scenario_checks.append(check("Procurement or supply evidence supports the order review", any(domain in {"procurement", "supply"} for tool in tools for domain in tool["domains"]), f"Domains={[tool['domains'] for tool in tools]}", 0))
    elif scenario_id == "cip_seal_kit":
        scenario_checks.append(check("Facility and purchase-readiness evidence support the equipment review", any("facility" in tool["domains"] for tool in tools) and any(domain in {"procurement", "supply"} for tool in tools for domain in tool["domains"]), f"Domains={[tool['domains'] for tool in tools]}", 0))
    elif scenario_id == "lemon_profitability":
        scenario_checks.extend([
            check("Lemon product Context was resolved", "CTX-PROD-LEMON" in resolved_contexts, f"Resolved={sorted(resolved_contexts)}", 0),
            check("Cost evidence and profitability calculation ran", "retrieve_business_evidence" in tool_names and "calculate_profitability_scenarios" in tool_names, f"Tools={tool_names}", 0),
            check("Final Chat answer cites scenario metrics", bool(re.search(r"(?:KRW|margin|profit|%|[0-9]{2,})", final_answer, re.I)), final_answer[:280] or "No final answer.", 0),
        ])
    elif scenario_id == "allulose_introduction":
        scenario_checks.append(check("Answer preserves readiness or approval boundary", bool(re.search(r"not(?: scale-up| production)? ready|do not proceed|pending|approval|unresolved|confirm", answer_lower)), final_answer[:280] or "No final answer.", 0))
    elif scenario_id == "cost_center_change":
        scenario_checks.append(check("Financial-control evidence is retrieved and answer does not claim an applied change", any("financial_control" in tool["domains"] for tool in tools) and not bool(re.search(r"cost center .* (was|has been) changed", answer_lower)), f"Domains={[tool['domains'] for tool in tools]}; answer={final_answer[:160]}", 0))

    categories = {
        "tool_a2a": tool_checks, "grounding_context": grounding_checks, "agent_collaboration": collaboration_checks, "chat_quality": chat_checks, "rpt_completion": rpt_checks,
    }
    if scenario_id == "lemon_profitability":
        calculations = [event["data"].get("result", {}) for event in events if event["type"] == "tool_observation" and event["data"].get("tool") == "calculate_profitability_scenarios"]
        calculation_ok = any(result.get("state") == "calculated" and result.get("scenarios") for result in calculations)
        answer_numbers = final_answer.replace(",", "")
        metrics_ok = calculation_ok and any(all(str(item.get("quarter_profit", "")) in answer_numbers or str(round(float(item.get("quarter_profit", 0)))) in answer_numbers for item in result.get("scenarios", [])) for result in calculations)
        scenario_checks[-1] = check("Final Chat cites available base and stress profit figures", metrics_ok, final_answer[:500], 0)
        if calculations and any("scenario_basis" in result for result in calculations):
            # Accept an explicit zero rate or equivalent exclusion of stress
            # inputs from the base case; do not reject a correct paraphrase.
            base_rate_clear = bool(re.search(r"(?:\b(?:zero|no|without)\b[^.]{0,80}\b(?:inflation|increase|uplift)\b|(?<![\d.])0(?:\.0+)?\s*%|stress inputs (?:were|are) not applied to (?:the )?base)", final_answer, re.I))
            rates_ok = all(rate in answer_numbers for rate in ("1.08", "1.16", "12")) and base_rate_clear
            scenario_checks.append(check("Final Chat distinguishes base and stress FX/inflation inputs", rates_ok, final_answer[:500], 0))
        if not calculation_ok:
            for item in tool_checks:
                item["passed"] = False
                item["evidence"] = "Profitability calculation is missing after resolvable product context."
        if not metrics_ok:
            for item in chat_checks:
                item["passed"] = False
                item["evidence"] = "Final answer omits available scenario profit figures."
    score = sum(item["weight"] for items in categories.values() for item in items if item["passed"])
    security_ok = not any(event.get("redacted_secrets") or SECRETS.search(json.dumps(event["data"], ensure_ascii=False)) for event in events)
    joule_target = current_settings().get("joule", {})
    joule_configured = bool(joule_target.get("solution_id", os.getenv("JOULE_SOLUTION_ID", "")).strip() and joule_target.get("asset_name", os.getenv("JOULE_ASSET_NAME", "")).strip())
    return {
        "id": scenario_id, "title": title, "request": request_text, "score": score, "passed": score == 100 and security_ok and not errors and terminated and english_generated and all(item["passed"] for item in scenario_checks),
        "categories": categories, "scenario_checks": scenario_checks, "events": {"count": len(events), "types": types, "duration_seconds": duration}, "sse_trace": events,
        "tool_trace": tools, "final_chat_answer": final_answer, "final_rpt": final_rpt, "rpt_status": rpt_status,
        "agent_trace": [{"type": event["type"], "agent_id": event["data"].get("agent_id"), "task_id": event["data"].get("task_id"), "handoff_id": event["data"].get("handoff_id"), "step": event["data"].get("step"), "at": event["at"]} for event in events if event["type"] in {"team_handoff_started", "delegation_selected", "subagent_started", "subagent_completed", "artifact_received"}],
        "joule": {"configured": joule_configured, "events": [event["type"] for event in joule_events], "status": "verified" if any(event["type"] == "joule_artifact_received" for event in joule_events) else "not_configured" if not joule_configured else "failed" if any(event["type"] == "joule_handoff_failed" for event in joule_events) else "skipped" if any(event["type"] == "joule_handoff_skipped" for event in joule_events) else "not_requested", "reason": "Joule target settings are absent." if not joule_configured else next((event["data"].get("message", "") for event in reversed(joule_events) if event["type"] in {"joule_handoff_failed", "joule_handoff_skipped"}), "")},
        "security": {"no_unredacted_secret_pattern": security_ok},
    }


def apply_evaluation_rules(result: dict[str, Any], case: dict[str, Any], config: dict[str, Any]) -> None:
    for category, checks in result["categories"].items():
        original = sum(item["weight"] for item in checks)
        for item in checks:
            item["weight"] = item["weight"] / original * config["weights"][category] if original else 0
    tools = {item["name"] for item in result["tool_trace"]}
    contexts = {identity for item in result["tool_trace"] for identity in item["context_ids"]}
    result["scenario_checks"].extend([
        check("Configured required Tools executed", set(case["required_tools"]) <= tools, str(sorted(tools)), 0),
        check("Configured Context IDs resolved", set(case["required_contexts"]) <= contexts, str(sorted(contexts)), 0),
        check("Configured answer evidence is present", all(text.lower() in result["final_chat_answer"].lower() for text in case["answer_contains"]), result["final_chat_answer"][:300], 0),
    ])
    result["score"] = round(sum(item["weight"] for checks in result["categories"].values() for item in checks if item["passed"]), 2)
    types = result["events"]["types"]
    terminal = next((event["data"].get("result", {}) for event in reversed(result["sse_trace"]) if event["type"] == "complete"), {})
    mandatory = bool(result["final_chat_answer"]) and terminal.get("termination", {}).get("state") == "completed"
    mandatory = mandatory and any(kind in types for kind in ("rpt_decision_completed", "rpt_decision_failed")) and any(kind in types for kind in ("rpt_final_decision_completed", "rpt_final_decision_failed"))
    mandatory = mandatory and not any(event["type"] == "error" for event in result["sse_trace"])
    mandatory = mandatory and not any(HANGUL.search(str(event["data"].get("delta", ""))) for event in result["sse_trace"] if event["type"].endswith("message_delta"))
    result["passed"] = mandatory and result["security"]["no_unredacted_secret_pattern"] and result["score"] >= config["minimum_score"] and all(item["passed"] for item in result["scenario_checks"])


def markdown_report(report: dict[str, Any]) -> str:
    lines = ["# Five-Scenario Live Evaluation", "", f"Overall score: **{report['overall_score']:.1f}/100**", "", "| Scenario | Score | Result | Tools |", "|---|---:|---|---|"]
    for result in report["scenarios"]:
        transport = f"; transport: {result['transport_error']}" if result.get("transport_error") else ""
        tool_names = ", ".join(str(tool.get("name") or "unknown") for tool in result["tool_trace"]) or "None"
        lines.append(f"| {result['title']} | {result['score']}/100 | {'PASS' if result['passed'] else 'FAIL'} | {tool_names}{transport} |")
    lines.extend(["", "## Findings", ""])
    for result in report["scenarios"]:
        if result.get("error"):
            lines.extend([f"### {result['title']}", f"- Evaluation transport failure: {result['error']}"])
            continue
        failures = [item for group in result["categories"].values() for item in group if not item["passed"]] + [item for item in result["scenario_checks"] if not item["passed"]]
        if failures:
            lines.append(f"### {result['title']}")
            if result.get("transport_error"):
                lines.append(f"- Evaluation transport failure after partial trace: {result['transport_error']}")
            lines.extend(f"- {item['name']}: {item['evidence']}" for item in failures)
    lines.extend(["", "## Joule A2A Environment", ""])
    for result in report["scenarios"]:
        lines.append(f"- {result['id']}: {result['joule']['status']} — {result['joule'].get('reason', '')}")
    lines.extend(["", "## Scenario evidence", ""])
    for result in report["scenarios"]:
        lines.extend([f"### {result['title']}", "", f"Duration: {result['events']['duration_seconds']} seconds; {result['events']['count']} SSE events.", "",
                      "Tool trace: " + json.dumps(result["tool_trace"], ensure_ascii=False), "",
                      "Final Chat:", "", result["final_chat_answer"] or "No final Chat answer.", "",
                      "Final RPT: " + json.dumps(result["final_rpt"], ensure_ascii=False), "",
                      "RPT providers and lifecycle: " + json.dumps(result.get("rpt_status", {}), ensure_ascii=False), ""])
    lines.extend(["## Prioritized remediation", ""])
    defects = list(dict.fromkeys(item["name"] for result in report["scenarios"]
                   for group in result["categories"].values() for item in group if not item["passed"]))
    defects.extend(item["name"] for result in report["scenarios"] for item in result["scenario_checks"] if not item["passed"] and item["name"] not in defects)
    lines.extend(f"{index}. Investigate: {name}. See scenario evidence above." for index, name in enumerate(defects, 1))
    if not defects:
        lines.append("No scenario defects detected in this run. Joule availability remains a separate environment observation.")
    return "\n".join(lines) + "\n"


def write_json_report(directory: Path, value: dict[str, Any]) -> None:
    temporary = directory / "report.tmp"
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(directory / "five_scenario_report.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "demo" / "backend" / "data" / "evaluations")
    parser.add_argument("--replay-report", type=Path, help="Rescore saved SSE traces without calling Agents or providers.")
    parser.add_argument("--rerun-scenario", action="append", choices=[item[0] for item in SCENARIOS], default=[], help="With --replay-report, rerun selected scenarios live and retain the others' evidence.")
    parser.add_argument("--suite-config", type=Path)
    parser.add_argument("--settings-revision", type=int)
    args = parser.parse_args()
    _load_repo_env()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    replay = json.loads(args.replay_report.read_text(encoding="utf-8")) if args.replay_report else None
    config = json.loads(args.suite_config.read_text()) if args.suite_config else None
    if config:
        from gateway.harness_evaluation import validate_evaluation
        config = validate_evaluation(config)
    cases = [(case["id"], case["title"], case["request"]) for case in config["scenarios"]] if config else SCENARIOS
    for scenario_id, title, request_text in cases:
        print(json.dumps({"scenario": scenario_id, "status": "started"}), flush=True)
        try:
            if replay and scenario_id not in args.rerun_scenario:
                recorded = next(item for item in replay["scenarios"] if item["id"] == scenario_id)
                events, transport_error = recorded["sse_trace"], recorded.get("transport_error")
            else:
                events, transport_error = run_with_timeout(args.timeout, args.base_url, request_text, args.settings_revision)
            with settings_scope(read_revision(args.settings_revision)):
                result = score_scenario(scenario_id, title, request_text, events)
            if config:
                apply_evaluation_rules(result, next(case for case in config["scenarios"] if case["id"] == scenario_id), config)
            result["evidence_origin"] = "recorded_trace" if replay and scenario_id not in args.rerun_scenario else "live_run"
            if transport_error:
                result["passed"] = False
                result["transport_error"] = transport_error
            results.append(result)
        except Exception as error:  # Keep the suite reporting after a single live failure.
            results.append({"id": scenario_id, "title": title, "request": request_text, "score": 0, "passed": False, "error": "Evaluation failed: " + type(error).__name__,
                            "categories": {}, "scenario_checks": [], "events": {"count": 0, "duration_seconds": 0}, "sse_trace": [], "final_chat_answer": "", "final_rpt": None,
                            "tool_trace": [], "joule": {"status": "not_evaluated", "events": []}})
        print(json.dumps({"scenario": scenario_id, "score": results[-1]["score"], "passed": results[-1]["passed"]}), flush=True)
        partial = {"generated_at_epoch": time.time(), "base_url": args.base_url, "settings_revision": args.settings_revision, "running": len(results) < len(cases), "scenarios": results,
                   "overall_score": sum(item["score"] for item in results) / len(results)}
        write_json_report(args.output_dir, partial)
    report = {"generated_at_epoch": time.time(), "base_url": replay.get("base_url", args.base_url) if replay else args.base_url, "settings_revision": args.settings_revision, "replayed_from": str(args.replay_report) if replay else None, "scenarios": results, "overall_score": sum(item["score"] for item in results) / len(results)}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json_report(args.output_dir, report)
    (args.output_dir / "five_scenario_report.md").write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({"overall_score": report["overall_score"], "output_dir": str(args.output_dir)}, ensure_ascii=False))
    return 0 if all(item.get("passed") for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
