"""Demo handoff envelope shared by the HTTP client and Team server."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from .errors import HarnessError

SCHEMA_VERSION = "demo.a2a.v1"


def validate_handoff(envelope: Any, target: str) -> dict[str, Any]:
    if not isinstance(envelope, dict) or envelope.get("schema_version") != SCHEMA_VERSION:
        raise HarnessError("invalid_handoff", "A supported Demo A2A envelope is required.")
    if envelope.get("source_agent_id") != "orchestration-agent" or envelope.get("target_agent_id") != target:
        raise HarnessError("invalid_target", "The handoff must address this registered Team.")
    try:
        UUID(envelope["handoff_id"])
        payload = envelope["input"]
        if not isinstance(payload, dict):
            raise ValueError()
        if any(not isinstance(payload.get(key), str) or not payload[key].strip() for key in ("request", "purpose")):
            raise ValueError()
        if envelope.get("purpose") != payload["purpose"]:
            raise ValueError()
        if len(payload["request"]) > 4000 or payload.get("language") != "en":
            raise ValueError()
        if not isinstance(payload.get("history", []), list) or not isinstance(payload.get("prior_artifacts", []), list):
            raise ValueError()
        if not isinstance(payload.get("grounding", ""), str):
            raise ValueError()
        if "settings_revision" in payload:
            revision = payload["settings_revision"]
            # SDK DataParts represent JSON numbers as doubles on the wire.
            if type(revision) not in (int, float) or not 0 <= revision < 2**53 or int(revision) != revision:
                raise ValueError()
            payload["settings_revision"] = int(revision)
        if len(str(payload)) > 200000:
            raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError):
        raise HarnessError("invalid_handoff", "The handoff contains invalid request context.") from None
    if not payload.get("grounding", "").strip():
        raise HarnessError("sop_required", "Verified SOP context is required before Team review.")
    return payload
