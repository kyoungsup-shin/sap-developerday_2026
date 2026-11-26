"""Contract tests independent of credentials and lesson runtime/resources."""
import asyncio
import json
import re
import socket
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import uvicorn
from django.test import SimpleTestCase
from a2a.helpers import get_data_parts, new_data_part
from a2a.types import Artifact
from google.protobuf.json_format import ParseDict

from gateway import agent_network as network
from gateway.ai_core import chat_completion
from gateway.a2a_contract import SCHEMA_VERSION, validate_handoff
from gateway.a2a_transport import discover_cards, handoff_envelope, send_task, sync_stream
from gateway.catalog import AGENT_CATALOG, public_prompts
from gateway.data_catalog import public_data_snapshots
from gateway.errors import HarnessError
from gateway.local_tools import execute_authorized_tool, tool_ids_for_subagent
from gateway.team_runtime import artifact_digest, select_specialists, specialist_review
from gateway.team_server import build_card, create_app
from gateway.tool_catalog import public_tools


def completion(name, arguments, call_id="call-1"):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}


def payload():
    return {"request": "Review lemon beverage profitability.", "purpose": "Calculate next-quarter impact",
            "history": [], "prior_artifacts": [], "grounding": "Verify documented approval and technical compatibility. SOP sources: SOP-01", "language": "en"}


def sop():
    return {"context": "Verify documented approval and technical compatibility. SOP sources: SOP-01", "source": "vector:test",
            "metadata_available": True, "message": "Retrieved", "sop_sources": ["maintenance.md"], "sop_source_ids": ["SOP-01"]}


def rpt():
    return {"next_agent": "finance-business-planning-team", "handoff_mode": "request_evidence", "risk": "low",
            "priority": "1", "team_rankings": [], "grounded_state": "Review evidence", "grounding_used": False, "answers": {}}


def card_for(target):
    return build_card(next(team for team in AGENT_CATALOG if team["agent_id"] == target), "http://127.0.0.1:8091/agents/" + target)


class ToolContractTests(SimpleTestCase):
    def test_public_contracts_and_metadata_are_english(self):
        self.assertEqual([tool["name"] for tool in public_tools()], ["search_business_context", "retrieve_business_evidence", "calculate_profitability_scenarios"])
        self.assertEqual(self.client.get("/api/tools").status_code, 200)
        self.assertIsNone(re.search(r"[가-힣]", str([public_tools(), public_prompts(), public_data_snapshots()])))

    def test_non_english_input_language_is_rejected(self):
        self.assertEqual(self.client.get("/api/data-snapshots?language=ko").status_code, 422)
        self.assertEqual(self.client.post("/api/chat/stream", data=json.dumps({"message": "test", "language": "ko"}), content_type="application/json").status_code, 422)

    def test_role_scoped_evidence_does_not_expose_other_domains(self):
        for specialist, domain in [("Facilities Engineering Specialist", "facility"), ("Procurement Specialist", "procurement"), ("Inventory and Supply Specialist", "supply")]:
            result = execute_authorized_tool(specialist, "retrieve_business_evidence", {"context_id": "CTX-EQP-CIP-SEAL"})
            self.assertEqual(result["domains"], [domain])
            self.assertEqual(list(result["result"]["evidence_by_domain"]), [domain])
            self.assertEqual(result["result"]["state"], "found")

    def test_unauthorized_calculation_is_blocked(self):
        with self.assertRaises(ValueError):
            execute_authorized_tool("Procurement Specialist", "calculate_profitability_scenarios", {"context_id": "CTX-PROD-LEMON"})

    def test_lookup_is_entity_search_without_agent_routing(self):
        result = execute_authorized_tool("Procurement Specialist", "search_business_context", {"request_text": "Please purchase a CIP pump mechanical seal kit."})["result"]
        self.assertEqual(result["matches"][0]["CONTEXT_ID"], "CTX-EQP-CIP-SEAL")
        self.assertNotIn("next_agent", result)

    def test_profitability_uses_documented_demo_assumptions(self):
        result = execute_authorized_tool("Profitability and Cost Specialist", "calculate_profitability_scenarios", {"context_id": "CTX-PROD-LEMON"})["result"]
        self.assertEqual(result["scenarios"][0]["quarter_profit"], 101856)
        self.assertEqual(result["scenarios"][1]["quarter_profit"], 85021.44)
        self.assertAlmostEqual(result["profit_change"], -16834.56)
        self.assertEqual(result["scenarios"][0]["raw_material_increase_percent"], 0)
        self.assertEqual(result["scenarios"][1]["raw_material_increase_percent"], 12)
        self.assertEqual(result["attribution"]["fx_only_profit_decrease"], 6144)
        self.assertEqual(result["attribution"]["raw_material_only_profit_decrease"], 9953.28)
        self.assertEqual(result["attribution"]["interaction_profit_decrease"], 737.28)
        self.assertTrue(result["read_only"])

    def test_empty_extra_and_unknown_arguments_are_blocked(self):
        for arguments in [{}, {"context_id": " "}, {"context_id": "unknown"}, {"context_id": "CTX-PROD-LEMON", "domain": "finance"}]:
            with self.assertRaises(ValueError):
                execute_authorized_tool("Procurement Specialist", "retrieve_business_evidence", arguments)

    def test_team_llm_chooses_registered_specialists_and_goals(self):
        team = AGENT_CATALOG[0]
        valid = completion("delegate_specialists", {"delegations": [{"agent": "Facilities Engineering Specialist", "goal": "Confirm compatible seal kit"}]})
        with patch("gateway.team_runtime.chat_completion", side_effect=[completion("other", {}), valid]) as chat:
            selected = select_specialists(team, payload())
        self.assertEqual(selected[0]["agent"], "Facilities Engineering Specialist")
        self.assertEqual(chat.call_count, 2)
        self.assertEqual(chat.call_args.args[1][0]["function"]["name"], "delegate_specialists")

    def test_unregistered_specialist_is_not_replaced_with_fixed_route(self):
        invalid = completion("delegate_specialists", {"delegations": [{"agent": "Unknown", "goal": "Review"}]})
        with patch("gateway.team_runtime.chat_completion", return_value=invalid):
            with self.assertRaises(HarnessError):
                select_specialists(AGENT_CATALOG[0], payload())

    def test_team_selection_receives_financial_control_capability_boundaries(self):
        team = next(team for team in AGENT_CATALOG if team["agent_id"] == "finance-business-planning-team")
        response = completion("delegate_specialists", {"delegations": [{"agent": "Budget and Management Accounting Specialist", "goal": "Review Cost Center controls"}]})
        with patch("gateway.team_runtime.chat_completion", return_value=response) as chat:
            select_specialists(team, payload())
        context = json.loads(chat.call_args.args[0][1]["content"])
        capabilities = {item["agent"]: item["authorized_evidence_domains"] for item in context["available_specialists"]}
        self.assertEqual(capabilities["Budget and Management Accounting Specialist"], ["financial_control"])
        self.assertNotIn("financial_control", capabilities["Profitability and Cost Specialist"])

    def test_native_tool_calls_keep_result_ids_and_do_not_repeat_execution(self):
        calls = [completion("search_business_context", {"request_text": "lemon"}, "lookup"),
                 completion("retrieve_business_evidence", {"context_id": "CTX-PROD-LEMON"}, "read-1"),
                 completion("retrieve_business_evidence", {"context_id": " CTX-PROD-LEMON "}, "read-2")]
        with patch("gateway.team_runtime.chat_completion", side_effect=calls), patch("gateway.team_runtime.chat_text_stream", return_value=iter(["Evidence-backed review."])) as summary, \
             patch("gateway.team_runtime.execute_authorized_tool", wraps=execute_authorized_tool) as execute:
            events = list(specialist_review("Profitability and Cost Specialist", "Review costs", payload(), []))
        observations = [event for event in events if event["type"] == "tool_observation"]
        self.assertEqual(len(observations), 2)
        self.assertEqual(execute.call_count, 2)
        tool_messages = [message for message in summary.call_args.args[0] if message["role"] == "tool"]
        self.assertEqual([message["tool_call_id"] for message in tool_messages], ["lookup", "read-1", "read-2"])
        self.assertEqual(tool_messages[1]["content"], tool_messages[2]["content"])

    def test_invalid_context_is_repaired_without_raw_errors(self):
        calls = [completion("retrieve_business_evidence", {"context_id": "CTX-PROD-LEMON"}),
                 completion("search_business_context", {"request_text": "lemon"}), {"role": "assistant", "content": "Cost evidence still needed."}]
        with patch("gateway.team_runtime.chat_completion", side_effect=calls):
            events = list(specialist_review("Profitability and Cost Specialist", "Review", payload(), []))
        self.assertEqual(len([event for event in events if event["type"] == "tool_observation"]), 1)
        self.assertNotIn("requires a non-empty", str(events))
        self.assertIn("tool_input_rejected", [event["type"] for event in events])

    def test_native_profitability_chain_runs_within_three_tool_turns(self):
        calls = [completion("search_business_context", {"request_text": "lemon"}),
                 completion("retrieve_business_evidence", {"context_id": "CTX-PROD-LEMON"}),
                 completion("calculate_profitability_scenarios", {"context_id": "CTX-PROD-LEMON"})]
        with patch("gateway.team_runtime.chat_completion", side_effect=calls), patch("gateway.team_runtime.chat_text_stream", return_value=iter(["Base profit USD 101856; stress USD 85021.44."])):
            events = list(specialist_review("Profitability and Cost Specialist", "Calculate", payload(), []))
        self.assertEqual(len([event for event in events if event["type"] == "tool_observation"]), 3)
        self.assertEqual(events[-1]["artifact"]["tool_calls"][-1]["result"]["state"], "calculated")

    def test_artifact_digest_preserves_calculations_but_excludes_nested_trace(self):
        result = artifact_digest([{"team_id": "finance", "finding": "Profit", "calculations": [{"quarter_profit": 101856}], "delegated_findings": [{"tool_calls": [{"result": "x" * 10000}]}]}])
        self.assertEqual(result[0]["calculations"][0]["quarter_profit"], 101856)
        self.assertNotIn("tool_calls", str(result))

    def test_demo_runtime_has_no_lesson_dependencies(self):
        root = Path(__file__).resolve().parents[1]
        for path in root.rglob("*.py"):
            if path == Path(__file__).resolve():
                continue
            source = path.read_text()
            self.assertNotIn("src.agent_to_agent", source, str(path))
            self.assertNotIn("4_agent_patterns", source, str(path))
        self.assertTrue(all(item["source"] == "Demo sample snapshots" for item in public_data_snapshots()))

    def test_resources_execute_in_an_isolated_directory_without_notebooks(self):
        backend = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(prefix="demo-a2a-isolation-") as directory:
            isolated = Path(directory) / "backend"
            shutil.copytree(backend / "gateway", isolated / "gateway", ignore=shutil.ignore_patterns("tests", "__pycache__"))
            shutil.copytree(backend / "data" / "snapshots", isolated / "data" / "snapshots")
            shutil.copytree(backend / "config", isolated / "config", ignore=shutil.ignore_patterns("__pycache__"))
            script = "import sys; sys.path.insert(0, sys.argv[1]); from gateway.catalog import public_prompts; from gateway.local_tools import execute_authorized_tool; assert len(public_prompts()['team_agents']) == 12; assert execute_authorized_tool('Procurement Specialist', 'search_business_context', {'request_text':'strawberry'})['result']['state'] == 'found'"
            result = subprocess.run([sys.executable, "-I", "-c", script, str(isolated)], cwd=directory, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_native_completion_preserves_wire_parameter_and_tool_result_keys(self):
        settings = {"base_url": "https://ai.invalid", "auth_url": "https://auth.invalid", "client_id": "test", "client_secret": "test", "resource_group": "default", "model": "test"}
        messages = [{"role": "assistant", "content": None, "tool_calls": completion("lookup", {})["tool_calls"]},
                    {"role": "tool", "tool_call_id": "call-1", "content": "{}"}]
        with patch("gateway.ai_core._deployment_url", return_value=(settings, "https://deployment.invalid")), patch("ai_core_sdk.ai_core_v2_client.AICoreV2Client"), patch("gateway.ai_core.requests.post") as post:
            post.return_value.json.return_value = {"choices": [{"message": {"role": "assistant", "content": "Done"}}]}
            chat_completion(messages, [{"type": "function", "function": {"name": "lookup"}}], "auto")
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["tool_choice"], "auto")
        self.assertEqual(body["messages"][1]["tool_call_id"], "call-1")
        self.assertNotIn("toolChoice", body)


class HarnessFlowTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        summary = patch.object(network, "_generate_final_summary", side_effect=lambda *args, **kwargs: kwargs["decision_summary"])
        summary.start()
        self.addCleanup(summary.stop)

    def test_final_synthesis_is_a2a_compatible_and_preserves_evidence(self):
        evidence = [{"team_id": "finance-business-planning-team", "task_id": "finance-task",
                     "handoff_id": "finance-handoff", "context_id": "session-one",
                     "finding": "Base profit USD 101,856; stress profit USD 85,021.44.",
                     "context_ids": ["CTX-PROD-LEMON"],
                     "calculations": [{"base_profit": 101856, "stress_profit": 85021.44}]}]
        summary = "Under SOP-01, profit decreases by USD 16,834.56."
        value = network._synthesis_artifact(summary, {"summary": summary}, "session-one",
                                           sop()["context"], sop()["sop_sources"], sop()["sop_source_ids"], evidence)
        artifact = ParseDict(value, Artifact())
        self.assertTrue(artifact.artifact_id)
        self.assertEqual(artifact.parts[0].text, summary)
        data = get_data_parts(artifact.parts)[0]
        self.assertEqual(data["producer"], "orchestration-agent")
        self.assertEqual(data["context_id"], "session-one")
        self.assertTrue(data["read_only"])
        self.assertEqual(data["source_artifacts"], evidence)
        self.assertEqual(data["sop_sources"], sop()["sop_sources"])
        self.assertEqual(data["sop_source_ids"], sop()["sop_source_ids"])

    def test_a2a_bridge_preserves_burst_events_past_queue_capacity(self):
        async def burst():
            for index in range(600):
                yield {"type": "test_status", "index": index}
        events = list(sync_stream(burst))
        self.assertEqual([event["index"] for event in events], list(range(600)))

    def test_required_grounding_precedes_review_and_final_rpt_follows_chat(self):
        decisions = [("search_grounding", {"query": "Equipment inspection SOP", "reason": "SOP required"}), ("finish_review", {"summary": "No equipment identity was provided; please supply it.", "reason": "Need scope"})]
        with patch.object(network, "discover_cards", return_value={"fb-facilities-team": card_for("fb-facilities-team")}), patch.object(network, "_decide", side_effect=decisions) as decide, patch.object(network, "rpt_decide", return_value=rpt()) as assess, patch.object(network, "retrieve_context", return_value=sop()) as retrieve:
            events = list(network.run_handoff_stream("Review equipment", [], context_id="session-one"))
        types = [event["type"] for event in events]
        retrieve.assert_called_once()
        self.assertTrue(retrieve.call_args.kwargs["require_sop"])
        self.assertLess(types.index("grounding_completed"), types.index("rpt_decision_started"))
        self.assertEqual(decide.call_args.args[2], sop()["context"])
        self.assertTrue(all(call.args[1] == sop()["context"] for call in assess.call_args_list))
        self.assertLess(types.index("orchestrator_message_delta"), types.index("rpt_final_decision_completed"))
        self.assertEqual(types[-1], "complete")
        self.assertEqual(events[-1]["result"]["termination"]["state"], "completed")
        created = next(event for event in events if event["type"] == "orchestrator_artifact_created")
        self.assertLess(types.index("orchestrator_artifact_created"), types.index("orchestrator_message_delta"))
        self.assertEqual(created["artifact"], events[-1]["result"]["synthesis_artifact"])
        self.assertEqual(get_data_parts(ParseDict(created["artifact"], Artifact()).parts)[0]["summary"], events[-1]["result"]["summary"])
        self.assertEqual(assess.call_args.args[2], [])
        self.assertEqual(assess.call_args.kwargs["synthesis_artifact"], created["artifact"])
        self.assertNotIn("synthesis_artifact", assess.call_args_list[0].kwargs)

    def test_focused_grounding_is_selected_once_by_llm(self):
        decisions = [("search_grounding", {"query": "Seal replacement SOP", "reason": "Need procedure"}), ("finish_review", {"summary": "Verify sanitation.", "reason": "SOP sufficient"})]
        with patch.object(network, "discover_cards", return_value={}), patch.object(network, "_decide", side_effect=decisions), patch.object(network, "rpt_decide", return_value=rpt()), patch.object(network, "retrieve_context", return_value=sop()) as retrieve:
            events = list(network.run_handoff_stream("Review SOP", []))
        self.assertEqual(retrieve.call_args.args[0], "Seal replacement SOP")
        self.assertEqual(retrieve.call_count, 1)
        self.assertIn("grounding_completed", [event["type"] for event in events])

    def test_failed_card_still_terminates_without_secret_leak(self):
        with patch.object(network, "discover_cards", side_effect=RuntimeError("Bearer sensitive-token")), patch.object(network, "rpt_decide", side_effect=RuntimeError("Bad credentials client-secret")):
            events = list(network.run_handoff_stream("Review", []))
        self.assertNotIn("sensitive-token", str(events))
        self.assertNotIn("client-secret", str(events))
        self.assertEqual(events[-1]["result"]["termination"]["state"], "failed")
        self.assertIn("rpt_final_decision_failed", [event["type"] for event in events])

    def test_max_handoffs_redelegation_and_artifact_order(self):
        target = "fb-facilities-team"
        def decide(*args):
            if not args[2]:
                return ("search_grounding", {"query": "Equipment review SOP", "reason": "SOP required"})
            return ("delegate_team", {"target_agent_id": target, "purpose": "Review " + str(args[5]), "reason": "Need evidence"}) if args[5] else ("finish_review", {"summary": "Evidence reviewed.", "reason": "Budget reached"})
        def stream(factory):
            yield {"type": "delegation_selected", "delegations": ["Facilities Engineering Specialist"]}
            yield {"type": "team_artifact_received", "task_id": str(uuid4()), "artifact": {"team_id": target, "finding": "Evidence", "read_only": True}}
        with patch.object(network, "discover_cards", return_value={target: card_for(target)}), patch.object(network, "_decide", side_effect=decide), patch.object(network, "rpt_decide", return_value=rpt()), patch.object(network, "retrieve_context", return_value=sop()), patch.object(network, "sync_stream", side_effect=stream):
            events = list(network.run_handoff_stream("Review", [], context_id="same-context"))
        handoffs = [event for event in events if event["type"] == "team_handoff_started"]
        self.assertEqual(len(handoffs), 3)
        self.assertEqual(len({event["handoff_id"] for event in handoffs}), 3)
        self.assertEqual({event["context_id"] for event in handoffs}, {"same-context"})
        self.assertEqual(events[-1]["result"]["summary"], "Evidence reviewed.")
        self.assertTrue(all(event["handoff"]["input"]["grounding"] == sop()["context"] for event in handoffs))

    def test_llm_corrects_early_delegation_and_selects_its_own_sop_query(self):
        target = "fb-facilities-team"
        responses = [completion("delegate_team", {"target_agent_id": target, "purpose": "Inspect", "reason": "Relevant role"}),
                     completion("search_grounding", {"query": "Which seal inspection and approval evidence is required?", "reason": "SOP must precede review"})]
        with patch.object(network, "chat_completion", side_effect=responses) as model:
            name, arguments = network._decide("Review a pump", [], "", [], {target: card_for(target)}, 3, [])
        self.assertEqual(name, "search_grounding")
        self.assertEqual(arguments["query"], "Which seal inspection and approval evidence is required?")
        self.assertEqual(model.call_count, 2)

    def test_sop_failure_or_missing_evidence_never_starts_team_or_joule(self):
        for result in (None, {**sop(), "context": ""}, {**sop(), "sop_sources": []}, {**sop(), "metadata_available": False}):
            with patch.object(network, "discover_cards", return_value={}), patch.object(network, "_decide", return_value=("search_grounding", {"query": "SOP", "reason": "Required"})), patch.object(network, "retrieve_context", return_value=result, side_effect=RuntimeError("Bearer secret-token") if result is None else None), patch.object(network, "rpt_decide") as assess, patch.object(network, "sync_stream") as task, patch.object(network, "verify_card") as card:
                events = list(network.run_handoff_stream("Review", []))
            assess.assert_not_called()
            task.assert_not_called()
            card.assert_not_called()
            self.assertIn("grounding_failed", [event["type"] for event in events])
            self.assertNotIn("secret-token", str(events))
            self.assertEqual(events[-1]["result"]["termination"]["state"], "failed")
            self.assertNotIn("orchestrator_artifact_created", [event["type"] for event in events])
            self.assertIsNone(events[-1]["result"]["synthesis_artifact"])

    def test_direct_team_handoff_cannot_omit_sop_context(self):
        value = payload()
        value["grounding"] = ""
        with self.assertRaises(HarnessError) as caught:
            validate_handoff(handoff_envelope("fb-facilities-team", value), "fb-facilities-team")
        self.assertEqual(caught.exception.code, "sop_required")


class HTTPA2ATests(SimpleTestCase):
    """Actual SDK HTTP discovery and streaming, with only model execution stubbed."""
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.socket = socket.socket()
        cls.socket.bind(("127.0.0.1", 0))
        cls.base_url = "http://127.0.0.1:" + str(cls.socket.getsockname()[1])
        cls.server = uvicorn.Server(uvicorn.Config(create_app(cls.base_url), log_level="critical", lifespan="off"))
        cls.thread = threading.Thread(target=lambda: cls.server.run(sockets=[cls.socket]), daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 5
        while not cls.server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        if not cls.server.started:
            raise RuntimeError("Test HTTP server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(5)
        cls.socket.close()
        super().tearDownClass()

    def cards(self):
        with patch.dict("os.environ", {"DEMO_TEAM_BASE_URL": self.base_url}):
            return asyncio.run(discover_cards())

    def test_all_twelve_cards_are_discovered_via_http(self):
        cards = self.cards()
        self.assertEqual(len(cards), 12)
        self.assertTrue(all(card.capabilities.streaming for card in cards.values()))

    def test_real_task_status_artifact_and_context_round_trip(self):
        target = "fb-facilities-team"
        def runtime(team, request):
            yield {"type": "delegation_started"}
            yield {"type": "delegation_selected", "delegations": ["Facilities Engineering Specialist"]}
            yield {"type": "subagent_message_delta", "sub_step": 1, "subagent_label": "Facilities Engineering Specialist", "delta": "Compatible kit confirmed."}
            yield {"type": "team_message_delta", "delta": "Review complete."}
            yield {"type": "team_artifact", "artifact": {"team_id": target, "finding": "Compatible kit confirmed.", "read_only": True}}
        cards = self.cards()
        envelope = handoff_envelope(target, payload())
        async def collect():
            return [event async for event in send_task(cards[target], envelope, "http-session")]
        with patch("gateway.team_server.run_team", side_effect=runtime):
            events = asyncio.run(collect())
        types = [event["type"] for event in events]
        self.assertLess(types.index("delegation_selected"), types.index("subagent_message_delta"))
        self.assertLess(types.index("subagent_message_delta"), types.index("team_message_delta"))
        artifact = events[-1]["artifact"]
        self.assertEqual(artifact["context_id"], "http-session")
        self.assertEqual(artifact["handoff_id"], envelope["handoff_id"])
        self.assertTrue(artifact["task_id"])
        self.assertEqual(events[-1]["type"], "team_artifact_received")

    def test_wrong_target_fails_before_runtime_and_returns_no_artifact(self):
        cards = self.cards()
        envelope = handoff_envelope("fb-procurement-team", payload())
        async def collect():
            return [event async for event in send_task(cards["fb-facilities-team"], envelope, "http-session")]
        with patch("gateway.team_server.run_team") as runtime:
            with self.assertRaises(HarnessError):
                asyncio.run(collect())
        runtime.assert_not_called()

    def test_server_failure_does_not_return_artifact_or_credentials(self):
        cards = self.cards()
        async def collect():
            return [event async for event in send_task(cards["fb-facilities-team"], handoff_envelope("fb-facilities-team", payload()), "http-session")]
        with patch("gateway.team_server.run_team", side_effect=RuntimeError("password=secret")):
            with self.assertRaises(HarnessError) as failure:
                asyncio.run(collect())
        self.assertNotIn("secret", str(failure.exception))

    def test_timeout_does_not_turn_partial_work_into_an_artifact(self):
        cards = self.cards()
        def stalled(team, request):
            time.sleep(0.15)
            yield {"type": "team_artifact", "artifact": {"team_id": team["agent_id"], "finding": "Too late", "read_only": True}}
        async def collect():
            return [event async for event in send_task(cards["fb-facilities-team"], handoff_envelope("fb-facilities-team", payload()), "timeout-session")]
        with patch.dict("os.environ", {"DEMO_TEAM_TASK_TIMEOUT": "0.03"}), patch("gateway.team_server.run_team", side_effect=stalled):
            with self.assertRaises(HarnessError):
                asyncio.run(collect())
