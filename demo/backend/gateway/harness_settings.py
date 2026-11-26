"""Immutable runtime revisions, stored once and shared across both services."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager, closing
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from string import Formatter
from typing import Any, Iterator

from .errors import HarnessError

_snapshot: ContextVar[dict[str, Any] | None] = ContextVar("harness_snapshot", default=None)
_agent: ContextVar[str] = ContextVar("harness_agent", default="orchestrator")


def state_directory() -> Path:
    default = Path(__file__).resolve().parents[1] / "data" / "harness_state"
    return Path(os.getenv("DEMO_HARNESS_STATE_DIR", str(default))).resolve()


def read_revision(revision: int | None = None) -> dict[str, Any]:
    if revision == 0:
        return {"revision": 0, "agents": {}}
    path = state_directory() / "settings.sqlite3"
    if not path.exists():
        if revision is not None:
            raise HarnessError("settings_revision_unavailable", "The requested Harness settings revision is unavailable.")
        return {"revision": 0, "agents": {}}
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)) as connection:
            row = connection.execute("SELECT version, document FROM revisions " +
                                     ("ORDER BY version DESC LIMIT 1" if revision is None else "WHERE version = ?"),
                                     () if revision is None else (revision,)).fetchone()
        if not row:
            if revision is not None:
                raise HarnessError("settings_revision_unavailable", "The requested Harness settings revision is unavailable.")
            return {"revision": 0, "agents": {}}
        return {**json.loads(row[1]), "revision": row[0]}
    except (sqlite3.Error, OSError, ValueError):
        raise HarnessError("settings_unavailable", "Harness settings storage is unavailable.") from None


def current_settings() -> dict[str, Any]:
    return deepcopy(_snapshot.get() or read_revision())


@contextmanager
def settings_scope(snapshot: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
    value = deepcopy(snapshot if snapshot is not None else read_revision())
    token = _snapshot.set(value)
    try:
        yield value
    finally:
        _snapshot.reset(token)


@contextmanager
def agent_scope(agent_id: str) -> Iterator[None]:
    token = _agent.set(agent_id)
    try:
        yield
    finally:
        _agent.reset(token)


def agent_override(agent_id: str | None = None) -> dict[str, Any]:
    return current_settings().get("agents", {}).get(agent_id or _agent.get(), {})


def effective_prompt(agent_id: str, default: str, **bindings: str) -> str:
    value = agent_override(agent_id).get("prompt")
    return value.format(**bindings) if value is not None else default


def validate_prompt(text: Any, role: str) -> None:
    if not isinstance(text, str) or not text.strip() or len(text) > 64000:
        raise HarnessError("invalid_prompt", "The system prompt must contain 1 to 64,000 characters.")
    allowed = {"team": {"agent_label", "description"}, "specialist": {"specialist"}, "orchestrator": set()}[role]
    try:
        for _, field, spec, conversion in Formatter().parse(text):
            if field is not None and (field not in allowed or spec or conversion):
                raise ValueError()
    except ValueError:
        raise HarnessError("invalid_prompt_variables", "Use only this role's supported template variables. Escape literal braces as {{ and }}.") from None


def save_revision(document: dict[str, Any], expected: int) -> dict[str, Any]:
    """Compare-and-save in a single transaction; old revisions remain readable."""
    if type(expected) is not int or expected < 0:
        raise HarnessError("invalid_revision", "expected_revision must be a non-negative integer.")
    value = {key: item for key, item in document.items() if key != "revision"}
    encoded = json.dumps(value, ensure_ascii=False)
    if len(encoded.encode()) > 5_000_000:
        raise HarnessError("settings_too_large", "Harness settings must be 5 MB or smaller.")
    try:
        directory = state_directory()
        directory.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(directory / "settings.sqlite3", timeout=10)) as connection, connection:
            connection.execute("CREATE TABLE IF NOT EXISTS revisions (version INTEGER PRIMARY KEY, document TEXT NOT NULL, created_at TEXT NOT NULL)")
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT COALESCE(MAX(version), 0) FROM revisions").fetchone()[0]
            if current != expected:
                raise HarnessError("settings_conflict", "Settings changed since this page loaded. Reload before saving.")
            version = current + 1
            connection.execute("INSERT INTO revisions VALUES (?, ?, ?)",
                               (version, encoded, datetime.now(timezone.utc).isoformat()))
        return {**value, "revision": version}
    except (sqlite3.Error, OSError):
        raise HarnessError("settings_save_failed", "Harness settings could not be saved. The previous revision is preserved.") from None


def prompt_manifest(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    from .catalog import public_prompts
    with settings_scope(snapshot) as current:
        catalog = public_prompts(defaults_only=True)
        entries = [{**catalog["orchestrator"], "agent_id": "orchestrator", "role": "orchestrator"}]
        entries += [{**item, "role": "team"} for item in catalog["team_agents"]]
        entries += [{**item, "role": "specialist"} for item in catalog["specialist_agents"]]
        # The shared model name is public; authentication settings are never returned.
        shared_model = os.getenv("LLM_MODEL", "gpt-5.6-luna")
        for entry in entries:
            override = current.get("agents", {}).get(entry["agent_id"], {})
            entry["default_prompt"] = entry.pop("system_prompt")
            entry["prompt"] = override.get("prompt", entry["default_prompt"])
            entry["model"] = override.get("model")
            entry["customized"] = bool(override)
            entry["variables"] = {"team": ["agent_label", "description"], "specialist": ["specialist"], "orchestrator": []}[entry["role"]]
        return {"revision": current["revision"], "shared_model": shared_model, "agents": entries,
                "application": "New requests use this revision; running requests keep their original revision."}


def update_agent(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) - {"agent_id", "prompt", "model", "expected_revision"}:
        raise HarnessError("invalid_settings", "Provide an Agent, prompt or model, and expected_revision.")
    if not ({"prompt", "model"} & set(payload)):
        raise HarnessError("invalid_settings", "Provide a prompt or model change.")
    snapshot = read_revision()
    manifest = prompt_manifest(snapshot)
    entry = next((item for item in manifest["agents"] if item["agent_id"] == payload.get("agent_id")), None)
    if entry is None:
        raise HarnessError("unknown_agent", "Select a registered Harness Agent.")
    override = deepcopy(snapshot.get("agents", {}).get(entry["agent_id"], {}))
    if "prompt" in payload:
        if payload["prompt"] is None:
            override.pop("prompt", None)
        else:
            validate_prompt(payload["prompt"], entry["role"])
            override["prompt"] = payload["prompt"]
    if "model" in payload:
        model = payload["model"]
        if model is None:
            override.pop("model", None)
        else:
            if not isinstance(model, dict) or set(model) != {"name", "deployment_id"} or any(not isinstance(model.get(key), str) or not model[key].strip() for key in model):
                raise HarnessError("invalid_model", "Select a running AI Core model deployment.")
            from .ai_core import public_models
            if model not in public_models()["models"]:
                raise HarnessError("invalid_model", "The selected model deployment is not running or available.")
            override["model"] = model
    snapshot.setdefault("agents", {})
    if override:
        snapshot["agents"][entry["agent_id"]] = override
    else:
        snapshot["agents"].pop(entry["agent_id"], None)
    return prompt_manifest(save_revision(snapshot, payload.get("expected_revision")))
