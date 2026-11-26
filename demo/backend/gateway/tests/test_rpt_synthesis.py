"""Final synthesis reaches RPT's task state without changing initial assessment."""
import json
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from gateway.agent_network import _synthesis_artifact
from gateway import rpt_decision as rpt


SUMMARY = "Under SOP-01, base profit is USD 101,856 and stress profit is USD 85,021.44. The decrease is USD 16,834.56; approval remains unresolved."
EVIDENCE = [{"team_id": "finance-business-planning-team", "task_id": "finance-task", "handoff_id": "finance-handoff",
             "context_id": "test-session", "finding": SUMMARY, "context_ids": ["CTX-PROD-LEMON"],
             "calculations": [{"base_profit": 101856, "stress_profit": 85021.44, "profit_decrease": 16834.56}]}]
SOP = "Confirm financial assumptions and approval. SOP sources: SOP-01"


def synthesis():
    return _synthesis_artifact(SUMMARY, None, "test-session", SOP, ["finance-sop.md"], ["SOP-01"], EVIDENCE)


class RPTSynthesisTests(SimpleTestCase):
    def test_final_prompt_contains_synthesis_and_original_calculation_evidence(self):
        artifact = synthesis()
        with patch.object(rpt, "chat_text", return_value=SUMMARY) as model:
            state = rpt._grounded_state("Review lemon profitability", SOP, EVIDENCE, artifact)
        messages = model.call_args.args[0]
        self.assertIn("Reconcile the synthesis", messages[0]["content"])
        final = json.loads(messages[1]["content"].split("Orchestrator final Synthesis Artifact:\n", 1)[1])
        self.assertEqual(final["artifact_id"], artifact["artifact_id"])
        self.assertEqual(final["summary"], SUMMARY)
        self.assertEqual(final["sop_source_ids"], ["SOP-01"])
        self.assertEqual(final["source_artifact_references"][0]["task_id"], "finance-task")
        self.assertNotIn("source_artifacts", final)
        self.assertIn('"calculations":', messages[1]["content"])
        self.assertIn("85021.44", messages[1]["content"])
        self.assertEqual(state, SUMMARY)

    def test_initial_and_legacy_final_inputs_remain_supported(self):
        with patch.object(rpt, "chat_text", return_value="Initial request state.") as model:
            rpt._grounded_state("Review lemon profitability", SOP)
        self.assertNotIn("Orchestrator final Synthesis Artifact", model.call_args.args[0][1]["content"])
        with patch.object(rpt, "chat_text", return_value="Final legacy state.") as model:
            rpt._grounded_state("Review lemon profitability", SOP, EVIDENCE)
        self.assertTrue(model.call_args.args[0][1]["content"].endswith("Orchestrator final Synthesis Artifact:\nnull"))

    def test_provider_request_uses_state_generated_from_final_synthesis(self):
        answers = {"next_agent": {"choice": "finance-business-planning-team"}, "handoff_mode": {"choice": "request_evidence"},
                   "risk": {"choice": "low"}, "priority": {"score": 1}}
        response = Mock()
        response.json.return_value = {"answers": answers}
        with patch.object(rpt, "_load_repo_env"), patch.dict("os.environ", {"SAP_RPT_API_KEY": "test-only-key"}), \
             patch.object(rpt, "chat_text", return_value=SUMMARY), patch.object(rpt.requests, "post", return_value=response) as post, \
             patch.object(rpt, "_team_rankings", return_value=[]):
            result = rpt.decide("Review lemon profitability", SOP, EVIDENCE, synthesis_artifact=synthesis())
        self.assertEqual(post.call_args.kwargs["json"]["state"], SUMMARY)
        self.assertEqual(post.call_args.kwargs["json"]["model"], "sap-rpt-1.6")
        self.assertEqual(result["grounded_state"], SUMMARY)
        self.assertEqual(result["provider"], "sap_rpt_decision_api")

    def test_invalid_synthesis_is_rejected_before_model_or_provider_calls(self):
        with patch.object(rpt, "chat_text") as model, patch.object(rpt.requests, "post") as post:
            with self.assertRaisesRegex(RuntimeError, "final Synthesis Artifact is invalid"):
                rpt._grounded_state("Review", SOP, [], {"artifact_id": "invalid", "parts": []})
        model.assert_not_called()
        post.assert_not_called()
