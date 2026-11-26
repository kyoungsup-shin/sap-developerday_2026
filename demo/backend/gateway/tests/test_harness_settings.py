"""Versioned edits, concurrency, model selection and pinned A2A execution."""
import asyncio
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from gateway import harness_settings as settings
from gateway import ai_core
from gateway.catalog import AGENT_CATALOG, public_prompts, team_system_prompt, specialist_system_prompt, orchestrator_system_prompt
from gateway.errors import HarnessError
from gateway.tests import test_tool_contract as contracts
from gateway.tests.test_tool_contract import payload
from gateway.a2a_transport import handoff_envelope, send_task


class SettingsTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(os.environ, {"DEMO_HARNESS_STATE_DIR": self.directory.name})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def save(self, agent, prompt, revision=0, **kwargs):
        return settings.update_agent({"agent_id": agent, "prompt": prompt, "expected_revision": revision, **kwargs})

    def test_all_agents_have_defaults_and_saved_edits_are_role_specific(self):
        manifest = settings.prompt_manifest()
        self.assertEqual(manifest["revision"], 0)
        self.assertEqual(len(manifest["agents"]), 39)
        self.save("orchestrator", "Use the evidence to answer concisely.")
        self.assertEqual(orchestrator_system_prompt(), "Use the evidence to answer concisely.")
        self.assertNotIn("Use the evidence to answer concisely.", team_system_prompt(AGENT_CATALOG[0]))
        self.save(AGENT_CATALOG[0]["agent_id"], "You are {agent_label}. {description}", 1)
        self.assertIn(AGENT_CATALOG[0]["agent_label"], team_system_prompt(AGENT_CATALOG[0]))
        self.save("specialist:Field Operations Specialist", "{specialist} must cite sources.", 2)
        self.assertEqual(specialist_system_prompt("Field Operations Specialist"), "Field Operations Specialist must cite sources.")
        self.assertEqual(settings.read_revision(1)["agents"], {"orchestrator": {"prompt": "Use the evidence to answer concisely."}})

    def test_literal_braces_and_invalid_inputs(self):
        settings.validate_prompt('Return {{"summary":"English"}}.', "orchestrator")
        for agent, prompt in (("orchestrator", ""), ("orchestrator", "{unknown}"), (AGENT_CATALOG[0]["agent_id"], "{agent_label.secret}"), ("orchestrator", "{"), ("unknown", "Review")):
            with self.subTest(agent=agent, prompt=prompt), self.assertRaises(HarnessError):
                self.save(agent, prompt)
        self.assertEqual(settings.read_revision()["revision"], 0)

    def test_conflict_and_failure_preserve_the_saved_revision(self):
        self.save("orchestrator", "Original saved review.")
        with self.assertRaises(HarnessError) as failure:
            self.save("orchestrator", "Stale overwrite.", 0)
        self.assertEqual(failure.exception.code, "settings_conflict")
        with patch("gateway.harness_settings.sqlite3.connect", side_effect=PermissionError("private-path")), self.assertRaises(HarnessError) as failed:
            settings.save_revision({"agents": {}}, 1)
        self.assertNotIn("private-path", str(failed.exception))
        self.assertEqual(orchestrator_system_prompt(), "Original saved review.")
        self.assertEqual(settings.read_revision()["revision"], 1)

    def test_concurrent_saves_have_one_winner(self):
        self.save("orchestrator", "Baseline.")
        def save(text):
            try:
                return self.save("orchestrator", text, 1)["revision"]
            except HarnessError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, ("First edit.", "Second edit.")))
        self.assertCountEqual(results, [2, "settings_conflict"])

    def test_request_snapshot_survives_a_concurrent_edit_and_propagates_to_thread(self):
        self.save("orchestrator", "Revision one.")
        with settings.settings_scope() as original:
            self.save("orchestrator", "Revision two.", 1)
            self.assertEqual(orchestrator_system_prompt(), "Revision one.")
            async def worker():
                return await asyncio.to_thread(orchestrator_system_prompt)
            self.assertEqual(asyncio.run(worker()), "Revision one.")
            self.assertEqual(original["revision"], 1)
        self.assertEqual(orchestrator_system_prompt(), "Revision two.")

    def test_reset_restores_defaults_and_models_are_validated(self):
        before = orchestrator_system_prompt()
        model = {"name": "test-model", "deployment_id": "deployment-a"}
        with patch("gateway.ai_core.public_models", return_value={"models": [model]}):
            self.save("orchestrator", "Custom review.", model=model)
        with settings.agent_scope("orchestrator"), patch("gateway.ai_core._settings", return_value={"model": "shared", "deployment_id": "shared-deployment"}), patch("gateway.ai_core._resolve_deployment", return_value=({}, "url")) as resolve:
            ai_core._deployment_url()
            resolve.assert_called_once_with("test-model", "deployment-a")
        settings.update_agent({"agent_id": "orchestrator", "prompt": None, "model": None, "expected_revision": 1})
        self.assertEqual(orchestrator_system_prompt(), before)
        self.assertEqual(settings.read_revision()["agents"], {})
        with patch("gateway.ai_core.public_models", return_value={"models": []}), self.assertRaises(HarnessError):
            self.save("orchestrator", "Review.", 2, model=model)

    def test_editor_api_validates_origin_and_reports_errors_without_leaks(self):
        with patch("gateway.views._load_repo_env"):
            response = self.client.get("/api/harness/prompts")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(str(Path(self.directory.name)), response.content.decode())
        change = {"agent_id": "orchestrator", "prompt": "Review evidence.", "expected_revision": 0}
        response = self.client.post("/api/harness/prompts", data=json.dumps(change), content_type="application/json", HTTP_ORIGIN="https://unrelated.invalid")
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/harness/prompts", data=json.dumps(change), content_type="application/json", HTTP_ORIGIN="http://localhost:5173")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["revision"], 1)
        self.assertEqual(self.client.post("/api/harness/prompts", data=json.dumps(change), content_type="application/json").status_code, 409)
        with patch("gateway.views.public_models", side_effect=RuntimeError("secret-client-token")):
            response = self.client.get("/api/harness/models")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret-client-token", response.content.decode())


class SettingsHTTPTests(contracts.HTTPA2ATests):
    """Same real SDK HTTP server with an isolated shared revision store."""
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(os.environ, {"DEMO_HARNESS_STATE_DIR": self.directory.name})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_http_team_uses_requested_revision_instead_of_latest(self):
        target = AGENT_CATALOG[0]["agent_id"]
        settings.update_agent({"agent_id": target, "prompt": "Pinned Team prompt.", "expected_revision": 0})
        settings.update_agent({"agent_id": target, "prompt": "Latest Team prompt.", "expected_revision": 1})
        cards = self.cards()
        request = {**payload(), "settings_revision": 1}
        seen = []
        def runtime(team, value):
            seen.append(team_system_prompt(team))
            yield {"type": "team_artifact", "artifact": {"team_id": target, "finding": "Review complete", "read_only": True}}
        async def collect():
            return [event async for event in send_task(cards[target], handoff_envelope(target, request), "revision-session")]
        with patch("gateway.team_server.run_team", side_effect=runtime):
            events = asyncio.run(collect())
        self.assertEqual(seen, ["Pinned Team prompt."])
        self.assertEqual(events[-1]["type"], "team_artifact_received")

    def test_unknown_revision_fails_without_an_artifact(self):
        target = AGENT_CATALOG[0]["agent_id"]
        cards = self.cards()
        async def collect():
            return [event async for event in send_task(cards[target], handoff_envelope(target, {**payload(), "settings_revision": 999}), "missing-revision")]
        with patch("gateway.team_server.run_team") as runtime, self.assertRaises(HarnessError):
            asyncio.run(collect())
        runtime.assert_not_called()
