"""Persistent, bounded live evaluations using the existing scenario evaluator."""
from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4
from typing import Any

from .errors import HarnessError
from .harness_settings import read_revision

_lock = threading.Lock()
_active: dict[str, subprocess.Popen] = {}
_CATEGORIES = {"tool_a2a": 30, "grounding_context": 20, "agent_collaboration": 20, "chat_quality": 20, "rpt_completion": 10}


def evaluation_defaults() -> dict[str, Any]:
    from scripts.evaluate_scenarios import SCENARIOS
    return {"timeout_seconds": 300, "minimum_score": 100, "weights": dict(_CATEGORIES),
            "scenarios": [{"id": identity, "title": title, "request": request, "required_tools": [], "required_contexts": [], "answer_contains": []} for identity, title, request in SCENARIOS]}


def validate_evaluation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"timeout_seconds", "minimum_score", "weights", "scenarios"}:
        raise HarnessError("invalid_evaluation", "Preserve the registered evaluation configuration fields.")
    if type(value["timeout_seconds"]) is not int or not 10 <= value["timeout_seconds"] <= 900:
        raise HarnessError("invalid_evaluation", "Scenario timeout must be between 10 and 900 seconds.")
    if type(value["minimum_score"]) not in (int, float) or not 0 <= value["minimum_score"] <= 100:
        raise HarnessError("invalid_evaluation", "Minimum score must be between 0 and 100.")
    weights = value["weights"]
    if not isinstance(weights, dict) or set(weights) != set(_CATEGORIES) or any(type(item) not in (int, float) or not 0 <= item <= 100 for item in weights.values()) or sum(weights.values()) != 100:
        raise HarnessError("invalid_evaluation", "The five category weights must total 100 points.")
    cases = value["scenarios"]
    if not isinstance(cases, list) or not 1 <= len(cases) <= 20:
        raise HarnessError("invalid_evaluation", "Configure between 1 and 20 scenarios.")
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"id", "title", "request", "required_tools", "required_contexts", "answer_contains"}:
            raise HarnessError("invalid_evaluation", "Each scenario requires its identity, request and assertion lists.")
        if not isinstance(case["id"], str) or not re.fullmatch(r"[a-z0-9_-]{1,80}", case["id"]) or case["id"] in ids:
            raise HarnessError("invalid_evaluation", "Scenario IDs must be unique lowercase identifiers.")
        ids.add(case["id"])
        if any(not isinstance(case[key], str) or not case[key].strip() for key in ("title", "request")) or len(case["request"]) > 4000:
            raise HarnessError("invalid_evaluation", "Each scenario needs a title and a request of at most 4,000 characters.")
        for field in ("required_tools", "required_contexts", "answer_contains"):
            if not isinstance(case[field], list) or any(not isinstance(item, str) or not item.strip() for item in case[field]):
                raise HarnessError("invalid_evaluation", "Scenario assertions must be lists of non-empty strings.")
    return value


def report_directory() -> Path:
    return Path(os.getenv("DEMO_EVALUATION_DIR", str(Path(__file__).resolve().parents[1] / "data" / "evaluations"))).resolve()


def _job_directory(identity: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", identity):
        raise HarnessError("unknown_evaluation", "Select an existing evaluation run.")
    return report_directory() / ("studio-" + identity)


def _write_status(directory: Path, value: dict[str, Any]) -> None:
    temporary = directory / "status.tmp"
    temporary.write_text(json.dumps(value))
    temporary.replace(directory / "status.json")


def start_evaluation(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) - {"scenario_ids", "expected_revision"}:
        raise HarnessError("invalid_evaluation", "Provide scenario_ids or run the configured suite.")
    snapshot = read_revision()
    if "expected_revision" in payload and (type(payload["expected_revision"]) is not int or payload["expected_revision"] != snapshot["revision"]):
        raise HarnessError("settings_conflict", "Settings changed since this page loaded. Reload before starting an evaluation.")
    config = validate_evaluation(snapshot.get("evaluation") or evaluation_defaults())
    selected = payload.get("scenario_ids")
    if selected is not None:
        if not isinstance(selected, list) or not selected or any(not isinstance(item, str) for item in selected) or len(selected) != len(set(selected)) or any(identity not in {item["id"] for item in config["scenarios"]} for identity in selected):
            raise HarnessError("invalid_evaluation", "Select registered scenario IDs.")
        config = {**config, "scenarios": [item for item in config["scenarios"] if item["id"] in selected]}
    with _lock:
        if any(process.poll() is None for process in _active.values()):
            raise HarnessError("evaluation_running", "An evaluation is already running. Wait for its results.")
        report_directory().mkdir(parents=True, exist_ok=True)
        lease = (report_directory() / ".runner.lock").open("a+")
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lease.close()
            raise HarnessError("evaluation_running", "An evaluation is already running. Wait for its results.") from None
        identity = uuid4().hex
        directory = _job_directory(identity)
        directory.mkdir(parents=True)
        (directory / "suite.json").write_text(json.dumps(config))
        state = {"id": identity, "state": "running", "revision": snapshot["revision"], "started_at": time.time(), "scenario_count": len(config["scenarios"])}
        _write_status(directory, state)
        script = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_scenarios.py"
        command = [sys.executable, str(script), "--base-url", os.getenv("DEMO_EVALUATION_BASE_URL", "http://127.0.0.1:8080"),
                   "--timeout", str(config["timeout_seconds"]), "--output-dir", str(directory),
                   "--suite-config", str(directory / "suite.json"), "--settings-revision", str(snapshot["revision"])]
        try:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, pass_fds=(lease.fileno(),))
        except OSError:
            lease.close()
            _write_status(directory, {**state, "state": "failed", "message": "The evaluator could not be started."})
            raise HarnessError("evaluation_unavailable", "The evaluator could not be started.") from None
        state["process_id"] = process.pid
        _write_status(directory, state)
        _active[identity] = process
    def monitor():
        try:
            process.wait(timeout=len(config["scenarios"]) * (config["timeout_seconds"] + 10) + 60)
            try:
                report = json.loads((directory / "five_scenario_report.json").read_text())
                finished = "completed" if len(report["scenarios"]) == len(config["scenarios"]) and not report.get("running") else "failed"
            except (OSError, ValueError, KeyError):
                finished = "failed"
        except subprocess.TimeoutExpired:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
            finished = "failed"
        with _lock:
            _write_status(directory, {**state, "state": finished, "finished_at": time.time()})
            _active.pop(identity, None)
            lease.close()
    threading.Thread(target=monitor, daemon=True).start()
    return {key: item for key, item in state.items() if key != "process_id"}


def evaluation_result(identity: str) -> dict[str, Any]:
    directory = _job_directory(identity)
    try:
        value = json.loads((directory / "status.json").read_text())
    except (OSError, ValueError):
        raise HarnessError("unknown_evaluation", "The evaluation run was not found.") from None
    report = directory / "five_scenario_report.json"
    if report.exists():
        try:
            value["report"] = json.loads(report.read_text())
        except (OSError, ValueError):
            # A report can be replaced while the reader polls.
            pass
    if value["state"] == "running" and identity not in _active:
        try:
            process_id = value.get("process_id", 0)
            if process_id <= 0:
                raise ProcessLookupError()
            os.kill(process_id, 0)
        except (ProcessLookupError, PermissionError):
            report_value = value.get("report", {})
            value["state"] = "completed" if len(report_value.get("scenarios", [])) == value["scenario_count"] and not report_value.get("running") else "interrupted"
            if value["state"] == "interrupted":
                value["message"] = "The evaluator stopped during this run. Partial evidence is retained."
            _write_status(directory, value)
    value.pop("process_id", None)
    return value


def evaluation_runs() -> list[dict[str, Any]]:
    paths = sorted(report_directory().glob("studio-*/status.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return [{key: item for key, item in evaluation_result(path.parent.name.removeprefix("studio-")).items() if key != "report"} for path in paths[:30]]
