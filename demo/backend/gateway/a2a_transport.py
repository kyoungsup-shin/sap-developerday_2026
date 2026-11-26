"""SDK-based discovery and streaming A2A transport; no Team executor imports."""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Iterator
from queue import Queue, Empty, Full
from threading import Thread, Event
from typing import Any
from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import get_data_parts, get_text_parts, new_data_part, new_text_message
from a2a.types import AgentCard, Artifact, Role, SendMessageRequest, TaskState
from google.protobuf.json_format import MessageToDict, ParseDict

from .a2a_contract import SCHEMA_VERSION
from .ai_core import _load_repo_env
from .catalog import AGENT_CATALOG
from .harness_profile import runtime_timeout, get_profile
from .errors import HarnessError
from .harness_settings import current_settings


def team_urls() -> dict[str, str]:
    _load_repo_env()
    base = os.getenv("DEMO_TEAM_BASE_URL", "http://127.0.0.1:8091").rstrip("/")
    return {team["agent_id"]: base + "/agents/" + team["agent_id"] for team in get_profile()["agents"]}


def validate_card(card: AgentCard, base: str, team: dict[str, Any] | None = None) -> None:
    expected = base.rstrip("/") + "/"
    if (not card.name.strip() or not card.description.strip() or not card.capabilities.streaming
            or not card.skills or not card.supported_interfaces
            or any(interface.url != expected or interface.protocol_binding != "JSONRPC"
                   or interface.protocol_version != "1.0" for interface in card.supported_interfaces)):
        raise HarnessError("invalid_agent_card", "The Agent Card must advertise its registered JSON-RPC streaming interface and skills.")
    if team and (card.name != team["agent_label"] or "application/json" not in card.default_input_modes
                 or "application/json" not in card.default_output_modes
                 or not any(skill.id == team["skill_id"] for skill in card.skills)):
        raise HarnessError("invalid_agent_card", "The Team Card does not match its registered name, skill or data contract.")


async def discover_cards() -> dict[str, AgentCard]:
    urls = team_urls()
    async with httpx.AsyncClient(timeout=runtime_timeout("a2a_connect"), follow_redirects=False) as client:
        async def resolve(team: dict[str, Any]) -> tuple[str, AgentCard]:
            target = team["agent_id"]
            try:
                card = await A2ACardResolver(client, urls[target]).get_agent_card(
                    http_kwargs={"params": {"settings_revision": current_settings()["revision"]}})
                validate_card(card, urls[target], team)
                return target, card
            except Exception:
                raise HarnessError("card_discovery_failed", "Could not verify the Demo Team Agent Cards. Start the shared Team server and check DEMO_TEAM_BASE_URL.") from None
        cards = dict(await asyncio.gather(*(resolve(team) for team in get_profile()["agents"])))
        for registered in current_settings().get("external_agents", []):
            if not registered["enabled"]:
                continue
            try:
                base = registered["base_url"].rstrip("/")
                card = await A2ACardResolver(client, base).get_agent_card()
                validate_card(card, base)
                cards[registered["agent_id"]] = card
            except Exception:
                raise HarnessError("external_card_failed", "Could not verify an enabled external Agent Card. Check its registered connection or disable it.") from None
        return cards


def handoff_envelope(target: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "handoff_id": str(uuid4()), "source_agent_id": "orchestration-agent",
            "target_agent_id": target, "purpose": payload["purpose"], "input": payload}


def external_artifact(artifact: Artifact, previous: dict[str, Any] | None = None, append: bool = False) -> dict[str, Any]:
    combined = Artifact()
    if append and previous:
        ParseDict(previous["parts"], combined)
        combined.parts.extend(artifact.parts)
    else:
        combined.CopyFrom(artifact)
    return {"parts": MessageToDict(combined, preserving_proto_field_name=True),
            "text": "".join(get_text_parts(combined.parts)), "data": get_data_parts(combined.parts)}


async def send_task(card: AgentCard, envelope: dict[str, Any], context_id: str) -> AsyncIterator[dict[str, Any]]:
    external = envelope["target_agent_id"] not in {item["agent_id"] for item in get_profile()["agents"]}
    text = "Review request: " + envelope["input"]["purpose"]
    if external:
        text += " Respond in English. Perform a read-only review; do not execute purchases, approvals or data changes. Request: " + envelope["input"]["request"] + " SOP evidence: " + envelope["input"]["grounding"]
    message = new_text_message(text, context_id=context_id, role=Role.ROLE_USER)
    message.parts.add().CopyFrom(new_data_part(envelope))
    task = None
    artifacts: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    try:
        timeout = runtime_timeout("team_task", "DEMO_TEAM_TASK_TIMEOUT")
        async with asyncio.timeout(timeout + 10), httpx.AsyncClient(timeout=httpx.Timeout(timeout + 10, connect=runtime_timeout("a2a_connect"))) as http:
            client = await create_client(card, ClientConfig(streaming=True, httpx_client=http, supported_protocol_bindings=["JSONRPC"]))
            try:
                async for response in client.send_message(SendMessageRequest(message=message)):
                    if response.HasField("task"):
                        task = response.task
                        for artifact in task.artifacts:
                            data = get_data_parts(artifact.parts)
                            if external:
                                artifacts[artifact.artifact_id] = external_artifact(artifact)
                            elif data:
                                artifacts[artifact.artifact_id] = data[0]
                        status = task.status
                    elif response.HasField("status_update"):
                        if task is None:
                            raise HarnessError("invalid_task", "Team status arrived without a Task.")
                        if response.status_update.task_id != task.id or response.status_update.context_id != context_id:
                            raise HarnessError("invalid_task", "The Team status has a mismatched Task identity.")
                        task.status.CopyFrom(response.status_update.status)
                        status = task.status
                    elif response.HasField("artifact_update"):
                        update = response.artifact_update
                        if task is None or update.task_id != task.id or update.context_id != context_id:
                            raise HarnessError("invalid_artifact", "The Team Artifact has a mismatched Task identity.")
                        data = get_data_parts(update.artifact.parts)
                        if external:
                            artifacts[update.artifact.artifact_id] = external_artifact(update.artifact, artifacts.get(update.artifact.artifact_id), update.append)
                        elif data:
                            artifacts[update.artifact.artifact_id] = data[0]
                        continue
                    else:
                        continue
                    if task.context_id != context_id:
                        raise HarnessError("invalid_context", "The Team returned a mismatched conversation context.")
                    view = MessageToDict(task, preserving_proto_field_name=True)
                    signature = json.dumps(view.get("status", {}), sort_keys=True)
                    if signature not in seen:
                        seen.add(signature)
                        yield {"type": "a2a_task_update", "task": view, "task_id": task.id}
                        for data in get_data_parts(status.message.parts):
                            event = data.get("demo_event") if isinstance(data, dict) else None
                            if isinstance(event, dict) and not external:
                                event["task_id"] = task.id
                                yield event
                if task is None or task.status.state != TaskState.TASK_STATE_COMPLETED:
                    details = get_data_parts(task.status.message.parts) if task else []
                    error = next((item.get("error") for item in details if isinstance(item, dict) and isinstance(item.get("error"), dict)), {})
                    raise HarnessError("team_task_failed", "The Team Task failed" + (": " + str(error.get("code")) if error.get("code") else "."))
                if external and artifacts:
                    finding = " ".join(item["text"] or json.dumps(item["data"], ensure_ascii=False) for item in artifacts.values())
                    artifacts = {"external": {"team_id": envelope["target_agent_id"], "finding": finding, "read_only": True,
                                              "external_artifacts": list(artifacts.values()), "task_id": task.id, "context_id": context_id,
                                              "handoff_id": envelope["handoff_id"]}}
                if len(artifacts) != 1:
                    raise HarnessError("invalid_artifact", "The completed Team Task must return one review Artifact.")
                artifact = next(iter(artifacts.values()))
                if (not isinstance(artifact, dict) or artifact.get("team_id") != envelope["target_agent_id"]
                        or artifact.get("read_only") is not True or not isinstance(artifact.get("finding"), str) or not artifact["finding"].strip()):
                    raise HarnessError("invalid_artifact", "The Team returned an invalid review Artifact.")
                if external:
                    yield {"type": "team_message_delta", "delta": artifact["finding"]}
                yield {"type": "team_artifact_received", "artifact": artifact, "task_id": task.id}
            finally:
                await client.close()
    except HarnessError:
        raise
    except TimeoutError:
        raise HarnessError("team_timeout", "The Team Task exceeded its time limit.") from None
    except Exception:
        raise HarnessError("a2a_transport_failed", "The A2A Team connection failed. Check the shared Team server.") from None


def sync_stream(factory: Any) -> Iterator[dict[str, Any]]:
    """Bridge an async HTTP stream to Django without buffering lifecycle events."""
    queue: Queue = Queue(maxsize=256)
    closed = Event()
    loop = asyncio.new_event_loop()
    async def publish(item: Any) -> None:
        while not closed.is_set():
            try:
                queue.put_nowait(item)
                return
            except Full:
                await asyncio.sleep(0.01)
    async def consume() -> None:
        try:
            async for item in factory():
                await publish(item)
        except asyncio.CancelledError:
            pass
        except Exception as error:
            await publish(error)
        finally:
            await publish(None)
    task = loop.create_task(consume())
    def run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(task)
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
    thread = Thread(target=run, daemon=True)
    thread.start()
    try:
        while True:
            try:
                item = queue.get(timeout=10)
            except Empty:
                yield {"type": "heartbeat"}
                continue
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        closed.set()
        if thread.is_alive() and not loop.is_closed():
            loop.call_soon_threadsafe(task.cancel)
