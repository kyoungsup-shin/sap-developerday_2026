"""Final text generation uses review evidence rather than completion acknowledgements."""
import json
from unittest.mock import patch

from a2a.helpers import get_data_parts
from a2a.types import Artifact
from django.test import SimpleTestCase
from google.protobuf.json_format import ParseDict

from gateway import agent_network as network
from gateway.errors import HarnessError
from gateway.harness_settings import settings_scope
from gateway.tests.test_tool_contract import rpt, sop


DRAFT = "Great! I am ready to prepare a quotation from your inputs."
SUMMARY = ("The draft quotation supports 800 kg at USD 4.80/kg (DEMO-PR-101). "
           "Confirm inventory, delivery requirements and purchasing approval under SOP-01; no order was placed.")
EVIDENCE = [{"team_id": "fb-procurement-team", "finding": "Draft quotation: 800 kg at USD 4.80/kg, DEMO-PR-101.",
             "context_ids": ["CTX-RM-STRAWBERRY"], "read_only": True,
             "calculations": [{"base_profit": 101856, "stress_profit": 85021.44, "difference": -16834.56}]}]


class FinalSummaryTests(SimpleTestCase):
    def test_generation_receives_request_history_sop_figures_and_role_override(self):
        with settings_scope({"revision": 0, "agents": {"orchestrator": {"prompt": "Use a concise procurement review."}}}), patch.object(network, "chat_completion", return_value={"content": SUMMARY}) as model:
            result = network._generate_final_summary(
                "Review the order", [{"role": "user", "content": "Requested quantity is 800 kg."}],
                sop()["context"], sop()["sop_sources"], sop()["sop_source_ids"], EVIDENCE, DRAFT, [])
        self.assertEqual(result, SUMMARY)
        messages = model.call_args.args[0]
        self.assertEqual(messages[0]["content"], "Use a concise procurement review.")
        self.assertIn("not a greeting", messages[1]["content"])
        context = json.loads(messages[2]["content"])
        self.assertEqual(context["decision_draft"], DRAFT)
        self.assertEqual(context["sop_source_ids"], ["SOP-01"])
        self.assertEqual(context["conversation_history"][0]["content"], "Requested quantity is 800 kg.")
        self.assertEqual(context["completed_artifacts"][0]["calculations"], EVIDENCE[0]["calculations"])
        self.assertEqual(model.call_args.kwargs, {"agent_id": "orchestrator"})

    def test_empty_invalid_or_failed_model_response_is_safe_and_not_draft_fallback(self):
        for response in ({"content": ""}, {"content": None}, {"content": {}}, {"content": SUMMARY, "tool_calls": [{}]}, RuntimeError("Bearer private-token")):
            with patch.object(network, "chat_completion", return_value=response, side_effect=response if isinstance(response, Exception) else None):
                with self.assertRaises(HarnessError) as caught:
                    network._generate_final_summary("Review", [], sop()["context"], [], [], EVIDENCE, DRAFT, [])
            self.assertEqual(caught.exception.code, "final_summary_unavailable")
            self.assertNotIn("private-token", str(caught.exception))

    def test_generated_summary_is_shared_by_chat_artifact_final_rpt_and_completion(self):
        decisions = [("search_grounding", {"query": "Purchasing SOP", "reason": "Required procedure"}),
                     ("finish_review", {"summary": DRAFT, "reason": "Review complete"})]
        with patch.object(network, "discover_cards", return_value={}), patch.object(network, "_decide", side_effect=decisions), patch.object(network, "retrieve_context", return_value=sop()), patch.object(network, "rpt_decide", return_value=rpt()) as assess, patch.object(network, "chat_completion", return_value={"content": SUMMARY}) as model:
            events = list(network.run_handoff_stream("Review the order", [], prior_artifacts=EVIDENCE))
        model.assert_called_once()
        kinds = [event["type"] for event in events]
        self.assertLess(kinds.index("orchestration_decision"), kinds.index("orchestrator_message_delta"))
        self.assertLess(kinds.index("orchestrator_message_delta"), kinds.index("rpt_final_decision_completed"))
        self.assertEqual(kinds[-1], "complete")
        final = events[-1]["result"]
        self.assertEqual(final["summary"], SUMMARY)
        chat = next(event for event in events if event["type"] == "orchestrator_message_delta")
        self.assertEqual(chat["delta"], SUMMARY)
        self.assertEqual(get_data_parts(ParseDict(final["synthesis_artifact"], Artifact()).parts)[0]["summary"], SUMMARY)
        self.assertEqual(assess.call_args.kwargs["synthesis_artifact"], final["synthesis_artifact"])
        self.assertNotIn(DRAFT, str(events))

    def test_generation_failure_still_finishes_rpt_lifecycle_and_stream(self):
        decisions = [("search_grounding", {"query": "Purchasing SOP", "reason": "Required"}),
                     ("finish_review", {"summary": DRAFT, "reason": "Review complete"})]
        with patch.object(network, "discover_cards", return_value={}), patch.object(network, "_decide", side_effect=decisions), patch.object(network, "retrieve_context", return_value=sop()), patch.object(network, "rpt_decide", return_value=rpt()), patch.object(network, "chat_completion", side_effect=RuntimeError("private-token")):
            events = list(network.run_handoff_stream("Review the order", []))
        self.assertEqual(events[-1]["result"]["termination"]["state"], "failed")
        self.assertIsNone(events[-1]["result"]["synthesis_artifact"])
        self.assertIn("rpt_final_decision_completed", [event["type"] for event in events])
        self.assertNotIn(DRAFT, str(events))
        self.assertNotIn("private-token", str(events))
