"""Evaluation acceptance gates: required SOP Grounding and terminal evidence."""
import importlib.util
from pathlib import Path

from django.test import SimpleTestCase

spec = importlib.util.spec_from_file_location("demo_evaluator", Path(__file__).resolve().parents[2] / "scripts" / "evaluate_scenarios.py")
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)


def trace():
    items = [
        ("grounding_started", {}), ("grounding_completed", {"metadata_available": True, "sop_sources": ["procurement.md"], "sop_source_ids": ["SOP-01"], "context_preview": "Confirm the approval requirements."}), ("rpt_decision_completed", {}),
        ("orchestration_observation", {"observation": {"grounding_used": False}}),
        ("team_handoff_started", {"agent_id": "fb-procurement-team", "handoff": {"input": {"grounding": "Confirm the approval requirements."}}}),
        ("delegation_selected", {"delegations": ["Procurement Specialist"]}),
        ("tool_observation", {"subagent_label": "Procurement Specialist", "tool": "search_business_context", "arguments": {"request_text": "strawberry"}, "domains": [], "result": {"state": "found", "matches": [{"CONTEXT_ID": "CTX-RM-STRAWBERRY"}], "read_only": True}}),
        ("tool_observation", {"subagent_label": "Procurement Specialist", "tool": "retrieve_business_evidence", "arguments": {"context_id": "CTX-RM-STRAWBERRY"}, "domains": ["procurement"], "result": {"state": "found", "read_only": True}}),
        ("artifact_received", {}), ("orchestrator_message_delta", {"delta": "Under SOP-01, replenishment remains a proposal awaiting approval."}),
        ("rpt_final_decision_completed", {"decision": {"risk": "low"}}),
        ("complete", {"result": {"termination": {"state": "completed"}}}),
    ]
    return [{"type": kind, "data": data, "at": float(index)} for index, (kind, data) in enumerate(items)]


class EvaluatorTests(SimpleTestCase):
    def score(self, events, scenario="strawberry_order"):
        return evaluator.score_scenario(scenario, "Test", "Review", events)

    def test_required_sop_grounding_and_completed_review_pass(self):
        result = self.score(trace())
        self.assertEqual(result["score"], 100)
        self.assertTrue(result["passed"])

    def test_missing_or_late_sop_grounding_never_passes(self):
        events = [event for event in trace() if not event["type"].startswith("grounding_")]
        self.assertFalse(self.score(events)["passed"])
        events = trace()
        grounded = events.pop(1)
        events.insert(4, grounded)
        self.assertFalse(self.score(events)["passed"])

    def test_grounding_without_verified_sources_never_passes(self):
        events = trace()
        next(event for event in events if event["type"] == "grounding_completed")["data"]["sop_sources"] = []
        self.assertFalse(self.score(events)["passed"])

    def test_missing_final_chat_or_rpt_never_passes(self):
        for omitted in ("orchestrator_message_delta", "rpt_final_decision_completed", "complete"):
            self.assertFalse(self.score([event for event in trace() if event["type"] != omitted])["passed"])

    def test_sop_must_reach_every_team_and_final_answer(self):
        events = trace()
        next(event for event in events if event["type"] == "team_handoff_started")["data"]["handoff"]["input"]["grounding"] = ""
        self.assertFalse(self.score(events)["passed"])
        events = trace()
        next(event for event in events if event["type"] == "orchestrator_message_delta")["data"]["delta"] = "Replenishment remains a proposal awaiting approval."
        self.assertFalse(self.score(events)["passed"])

    def test_rpt_fallback_provider_is_preserved_separately_from_decision(self):
        events = trace()
        next(event for event in events if event["type"] == "rpt_final_decision_completed")["data"].update({"provider": "ai_core_rpt_fallback", "fallback_reason": "SAP RPT Decision API request failed (404)."})
        result = self.score(events)
        self.assertEqual(result["rpt_status"]["final"]["provider"], "ai_core_rpt_fallback")
        self.assertIn("404", result["rpt_status"]["final"]["reason"])

    def test_unauthorized_tool_and_non_english_text_never_pass(self):
        events = trace()
        next(event for event in events if event["type"] == "tool_observation")["data"]["tool"] = "purchase_material"
        self.assertFalse(self.score(events)["passed"])
        events = trace()
        next(event for event in events if event["type"] == "orchestrator_message_delta")["data"]["delta"] = "검토 완료"
        self.assertFalse(self.score(events)["passed"])

    def test_resolvable_lemon_without_calculation_loses_tool_and_chat_points(self):
        events = trace()
        next(event for event in events if event["type"] == "tool_observation")["data"]["result"]["matches"][0]["CONTEXT_ID"] = "CTX-PROD-LEMON"
        result = self.score(events, "lemon_profitability")
        self.assertFalse(result["passed"])
        self.assertLessEqual(result["score"], 50)

    def test_allulose_readiness_boundary_accepts_concise_blocking_language(self):
        for answer in (
            "Allulose is not scale-up ready; formulation and process trials are incomplete. No production run occurred.",
            "Do not proceed with allulose in production. Complete the material and process review first.",
        ):
            events = trace()
            next(event for event in events if event["type"] == "orchestrator_message_delta")["data"]["delta"] = answer + " Apply SOP-01."
            self.assertTrue(self.score(events, "allulose_introduction")["passed"])

    def test_allulose_answer_without_readiness_boundary_does_not_pass(self):
        events = trace()
        next(event for event in events if event["type"] == "orchestrator_message_delta")["data"]["delta"] = "Use allulose in the next production run."
        self.assertFalse(self.score(events, "allulose_introduction")["passed"])
