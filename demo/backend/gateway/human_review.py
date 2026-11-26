"""Persist root review checkpoints; input starts a new, evidence-carrying reassessment."""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any

from .errors import HarnessError
from .harness_settings import state_directory


def _connection():
    directory = state_directory()
    directory.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(directory / "human_review.sqlite3", timeout=10)
    connection.execute("CREATE TABLE IF NOT EXISTS reviews (id TEXT PRIMARY KEY, context_id TEXT NOT NULL, state TEXT NOT NULL, document TEXT NOT NULL, created_at TEXT NOT NULL)")
    return connection


def pause_review(request: str, history: list, context_id: str, revision: int,
                 artifacts: list, decision: dict) -> dict[str, Any]:
    identity = uuid4().hex
    checkpoint = {"id": identity, "context_id": context_id, "settings_revision": revision,
                  "request": request, "history": history, "artifacts": artifacts, "decision": decision}
    try:
        with closing(_connection()) as connection, connection:
            connection.execute("UPDATE reviews SET state = 'superseded' WHERE context_id = ? AND state = 'pending'", (context_id,))
            connection.execute("INSERT INTO reviews VALUES (?, ?, 'pending', ?, ?)",
                               (identity, context_id, json.dumps(checkpoint), datetime.now(timezone.utc).isoformat()))
    except (OSError, sqlite3.Error):
        raise HarnessError("human_review_unavailable", "The human review checkpoint could not be saved. Retry the review.") from None
    return {"id": identity, "context_id": context_id, "settings_revision": revision, "handoff_mode": decision["handoff_mode"],
            "message": "Provide the requested evidence or human review comments to reassess this request. This input does not execute a business approval."}


def pending_review(context_id: str) -> dict | None:
    try:
        with closing(_connection()) as connection:
            row = connection.execute("SELECT document FROM reviews WHERE context_id = ? AND state = 'pending' ORDER BY created_at DESC LIMIT 1", (context_id,)).fetchone()
        if not row:
            return None
        value = json.loads(row[0])
        return {key: value[key] for key in ("id", "context_id", "settings_revision")} | {"handoff_mode": value["decision"]["handoff_mode"]}
    except (OSError, sqlite3.Error, ValueError):
        raise HarnessError("human_review_unavailable", "Human review storage is unavailable.") from None


def claim_review(identity: Any, context_id: Any) -> dict:
    if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}", identity) or not isinstance(context_id, str):
        raise HarnessError("invalid_human_review", "Provide an existing review checkpoint and its session.")
    try:
        with closing(_connection()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT document FROM reviews WHERE id = ? AND context_id = ? AND state = 'pending'", (identity, context_id)).fetchone()
            if not row:
                raise HarnessError("human_review_conflict", "This review input was already submitted or superseded. Reload the pending session.")
            value = json.loads(row[0])
            connection.execute("UPDATE reviews SET state = 'submitted' WHERE id = ?", (identity,))
            return value
    except (OSError, sqlite3.Error, ValueError):
        raise HarnessError("human_review_unavailable", "Human review storage is unavailable.") from None
