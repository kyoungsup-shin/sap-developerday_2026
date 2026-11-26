"""Default migration compatibility, configuration failures and runtime wiring."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import yaml
from django.test import SimpleTestCase

from gateway import harness_profile as profiles
from gateway import agent_network, team_runtime
from gateway.catalog import public_agents, public_prompts
from gateway.errors import HarnessError
from gateway.local_tools import SPECIALIST_DOMAINS, tool_ids_for_subagent
from gateway.tool_catalog import native_tool_schema, public_tools


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class HarnessProfileTests(SimpleTestCase):
    def test_default_preserves_pre_migration_public_contracts_and_prompts(self):
        # Captured from the original implementation before extracting configuration.
        values = {
            "agents": (public_agents(), "c65fef57dadf07be6cd096aa7ac060598f9921f515a8e9d01ca7f6aee85a1008"),
            "prompts": (public_prompts(), "4df279f7912baadde8e736340cb9f4f897df548aff0a34b788edfd47c45040ee"),
            "tools": (public_tools(), "899c829d37b840f1f56ee85d6398fca483eedd0c6db3d0b94068e70ef3e60183"),
            "schemas": ({item["name"]: native_tool_schema(item["name"]) for item in public_tools()}, "d943cec85796183db6f16916145d91ff21ef47e9745dda2d41d3767be24d59dc"),
            "permissions": ({name: {"domains": list(domains), "tools": list(tool_ids_for_subagent(name))} for name, domains in SPECIALIST_DOMAINS.items()}, "868d9833ad6497e9f060063c9921c566cd18a8a13091868ec8520b64632d65ec"),
        }
        for key, (value, expected) in values.items():
            with self.subTest(contract=key):
                self.assertEqual(digest(value), expected)

    def test_duplicate_and_unknown_references_are_rejected(self):
        original = profiles.get_profile()
        cases = []
        for key in ("agents", "specialists", "tools"):
            invalid = deepcopy(original)
            invalid[key].append(deepcopy(invalid[key][0]))
            cases.append(invalid)
        invalid = deepcopy(original)
        invalid["agents"][0]["sub_agents"] = ["Unknown Specialist"]
        cases.append(invalid)
        invalid = deepcopy(original)
        invalid["specialists"][0]["tools"] = ["unknown_tool"]
        cases.append(invalid)
        invalid = deepcopy(original)
        invalid["specialists"][0]["domains"] = ["unknown_domain"]
        cases.append(invalid)
        invalid = deepcopy(original)
        invalid["tools"][0]["name"] = "unimplemented_tool"
        cases.append(invalid)
        for invalid in cases:
            with self.subTest(invalid=cases.index(invalid)):
                with self.assertRaises(HarnessError) as failure:
                    profiles.validate_profile(invalid)
                self.assertEqual(failure.exception.code, "invalid_harness_profile")

    def test_invalid_budgets_timeouts_and_tool_contracts_are_rejected(self):
        original = profiles.get_profile()
        for key in ("max_handoffs", "max_tool_turns"):
            for value in (0, -1, True, 1.5, "3"):
                invalid = deepcopy(original)
                invalid["runtime"][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(HarnessError):
                    profiles.validate_profile(invalid)
        for value in (0, -1, True, float("nan"), float("inf"), "240"):
            invalid = deepcopy(original)
            invalid["runtime"]["timeouts"]["team_task"] = value
            with self.subTest(timeout=value), self.assertRaises(HarnessError):
                profiles.validate_profile(invalid)
        invalid = deepcopy(original)
        invalid["tools"][0]["inputs"][0]["name"] = "query"
        with self.assertRaises(HarnessError):
            profiles.validate_profile(invalid)

    def test_missing_resources_and_unsupported_identity_are_rejected(self):
        for field, value in (
            ("prompts", ["gateway/prompts/missing.toml"]),
            ("snapshots", "data/missing"),
            ("required_snapshots", ["missing.csv"]),
            ("rpt_config", "config/missing.yaml"),
            ("rpt_config", "../outside.yaml"),
        ):
            invalid = profiles.get_profile()
            invalid["resources"][field] = value
            with self.subTest(field=field), self.assertRaises(HarnessError):
                profiles.validate_profile(invalid)
        for key, value in (("id", "other"), ("schema_version", "unknown")):
            invalid = profiles.get_profile()
            invalid[key] = value
            with self.assertRaises(HarnessError):
                profiles.validate_profile(invalid)

    def test_missing_prompt_keys_and_invalid_placeholders_are_rejected(self):
        original_path = profiles._path
        original_roles = (profiles.BACKEND_ROOT / "gateway" / "prompts" / "roles.toml").read_text()
        for replacement, reason in ((None, "Prompt roles.team"), ("{unknown_parameter}", "role Prompt placeholders")):
            invalid = profiles.get_profile()
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "roles.toml"
                lines = [line for line in original_roles.splitlines() if not line.startswith("team = ")]
                if replacement is not None:
                    lines.append("team = " + json.dumps(replacement))
                path.write_text(chr(10).join(lines))
                def resolve(reference, field, **kwargs):
                    return path if reference == "gateway/prompts/roles.toml" else original_path(reference, field, **kwargs)
                with patch.object(profiles, "_path", side_effect=resolve), self.assertRaises(HarnessError) as failure:
                    profiles.validate_profile(invalid)
                self.assertIn(reason, str(failure.exception))

    def test_missing_or_malformed_profile_uses_safe_configuration_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.yaml"
            for content in (None, "secret: [confidential-token"):
                if content is not None:
                    path.write_text(content)
                with self.assertRaises(HarnessError) as failure:
                    profiles.load_profile(path)
                self.assertNotIn("confidential-token", str(failure.exception))

    def test_runtime_defaults_and_existing_environment_override(self):
        profile = profiles.get_profile()
        self.assertEqual(agent_network.MAX_HANDOFFS, profile["runtime"]["max_handoffs"])
        self.assertEqual(team_runtime.MAX_TOOL_TURNS, profile["runtime"]["max_tool_turns"])
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(profiles.runtime_timeout("team_task", "DEMO_TEAM_TASK_TIMEOUT"), 240)
            self.assertEqual(profiles.runtime_timeout("joule_cli", "JOULE_CLI_TIMEOUT_SECONDS"), 60)
        with patch.dict(os.environ, {"DEMO_TEAM_TASK_TIMEOUT": "0.03", "JOULE_CLI_TIMEOUT_SECONDS": "7"}):
            self.assertEqual(profiles.runtime_timeout("team_task", "DEMO_TEAM_TASK_TIMEOUT"), 0.03)
            self.assertEqual(profiles.runtime_timeout("joule_cli", "JOULE_CLI_TIMEOUT_SECONDS"), 7)
        for value in ("invalid", "0", "-1", "nan", "inf"):
            with patch.dict(os.environ, {"DEMO_TEAM_TASK_TIMEOUT": value}), self.assertRaises(HarnessError):
                profiles.runtime_timeout("team_task", "DEMO_TEAM_TASK_TIMEOUT")

    def test_inspection_api_returns_effective_settings_without_paths_or_secrets(self):
        with patch("gateway.views._load_repo_env"), patch.dict(os.environ, {
            "SAP_RPT_API_KEY": "never-public-rpt-key", "AICORE_CLIENT_SECRET": "never-public-client-secret",
            "DEMO_TEAM_TASK_TIMEOUT": "75", "JOULE_CLI_TIMEOUT_SECONDS": "12",
        }):
            response = self.client.get("/api/harness-profile")
        self.assertEqual(response.status_code, 200)
        value = response.json()
        self.assertEqual(value["id"], "fnb-default")
        self.assertEqual(len(value["agents"]), 12)
        self.assertEqual(value["runtime"]["timeouts"]["team_task"], 75)
        self.assertEqual(value["runtime"]["timeouts"]["joule_cli"], 12)
        for hidden in ("never-public-rpt-key", "never-public-client-secret", "resources", str(profiles.BACKEND_ROOT)):
            self.assertNotIn(hidden, response.content.decode())
        self.assertEqual(self.client.post("/api/harness-profile").status_code, 405)
        with patch("gateway.views.public_profile", side_effect=HarnessError("invalid_harness_profile", "Invalid Harness Profile.")):
            self.assertEqual(self.client.get("/api/harness-profile").status_code, 503)

    def test_cached_profile_cannot_be_mutated_through_inspection(self):
        profile = profiles.get_profile()
        profile["agents"][0]["agent_label"] = "Modified"
        public = profiles.public_profile()
        public["specialists"][0]["tools"].clear()
        self.assertNotEqual(profiles.get_profile()["agents"][0]["agent_label"], "Modified")
        self.assertTrue(profiles.get_profile()["specialists"][0]["tools"])

    def test_new_process_uses_edited_profile_for_both_runtimes_and_permissions(self):
        with tempfile.TemporaryDirectory(prefix="profile-wiring-") as directory:
            root = Path(directory) / "backend"
            for folder in ("gateway", "config"):
                shutil.copytree(profiles.BACKEND_ROOT / folder, root / folder, ignore=shutil.ignore_patterns("tests", "__pycache__"))
            shutil.copytree(profiles.BACKEND_ROOT / "data" / "snapshots", root / "data" / "snapshots")
            path = root / "config" / "harness" / "fnb-default.yaml"
            config = yaml.safe_load(path.read_text())
            config["runtime"]["max_handoffs"] = 2
            config["runtime"]["max_tool_turns"] = 4
            config["agents"][0]["agent_label"] = "Custom Facilities Team"
            config["specialists"][0]["tools"] = ["search_business_context"]
            config["tools"][0]["description"] = "Custom context lookup description."
            (root / "data" / "snapshots").rename(root / "data" / "custom-snapshots")
            config["resources"]["snapshots"] = "data/custom-snapshots"
            (root / "gateway" / "prompts" / "roles.toml").rename(root / "gateway" / "prompts" / "custom-roles.toml")
            config["resources"]["prompts"][0] = "gateway/prompts/custom-roles.toml"
            (root / "config" / "rpt_decision.yaml").rename(root / "config" / "custom-rpt.yaml")
            config["resources"]["rpt_config"] = "config/custom-rpt.yaml"
            path.write_text(yaml.safe_dump(config))
            script = """
import sys
from pathlib import Path
import yaml
sys.path.insert(0, sys.argv[1])
from gateway.agent_network import MAX_HANDOFFS
from gateway.team_runtime import MAX_TOOL_TURNS
from gateway.team_server import AGENT_CATALOG, build_card
from gateway.catalog import public_prompts
from gateway.local_tools import tool_ids_for_subagent, execute_authorized_tool
from gateway.harness_profile import get_profile
from gateway.data_catalog import public_data_snapshots
from gateway.rpt_decision import _CONFIG_PATH
from gateway.tool_catalog import native_tool_schema
assert MAX_HANDOFFS == 2 and MAX_TOOL_TURNS == 4
assert build_card(AGENT_CATALOG[0], 'http://localhost/agents/test').name == 'Custom Facilities Team'
assert 'Custom Facilities Team' in public_prompts()['team_agents'][0]['system_prompt']
assert tool_ids_for_subagent('Field Operations Specialist') == ('search_business_context',)
assert native_tool_schema('search_business_context')['function']['description'].startswith('Custom context lookup description.')
assert execute_authorized_tool('Field Operations Specialist', 'search_business_context', {'request_text': 'strawberry'})['result']['state'] == 'found'
assert len(public_data_snapshots()) == 4
assert _CONFIG_PATH.name == 'custom-rpt.yaml'
try:
    execute_authorized_tool('Field Operations Specialist', 'retrieve_business_evidence', {'context_id': 'CTX-EQP-CIP-SEAL'})
except ValueError:
    pass
else:
    raise AssertionError('Changed permission was not enforced')
snapshot = get_profile()
snapshot['runtime']['max_handoffs'] = 9
assert get_profile()['runtime']['max_handoffs'] == 2
profile_path = Path(sys.argv[1]) / 'config' / 'harness' / 'fnb-default.yaml'
updated = yaml.safe_load(profile_path.read_text())
updated['runtime']['max_handoffs'] = 7
profile_path.write_text(yaml.safe_dump(updated))
assert get_profile()['runtime']['max_handoffs'] == 2
"""
            result = subprocess.run([sys.executable, "-I", "-c", script, str(root)], cwd=directory, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
