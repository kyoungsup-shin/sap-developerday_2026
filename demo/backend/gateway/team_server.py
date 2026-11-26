"""Run the demo-owned shared Team HTTP server: python -m gateway.team_server."""
from __future__ import annotations

import asyncio
import os
from typing import Any

from a2a.helpers import get_data_parts, new_data_message, new_data_part, new_task
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, TaskState
from google.protobuf.json_format import MessageToDict
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .a2a_contract import validate_handoff
from .ai_core import _load_repo_env
from .catalog import AGENT_CATALOG
from .harness_profile import runtime_timeout, get_profile
from .errors import HarnessError, public_error
from .team_runtime import run_team
from .harness_settings import settings_scope, read_revision, agent_scope


def build_card(team: dict[str, Any], base_url: str) -> AgentCard:
    return AgentCard(name=team["agent_label"], description=team["description"], version="1.0.0",
        supported_interfaces=[AgentInterface(url=base_url + "/", protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=True), default_input_modes=["text/plain", "application/json"],
        default_output_modes=["text/plain", "application/json"],
        skills=[AgentSkill(id=team["skill_id"], name=team["agent_label"], description=team["description"],
                           tags=team["tags"], examples=team["examples"])])


def _next(iterator: Any) -> dict[str, Any] | None:
    return next(iterator, None)


class TeamExecutor(AgentExecutor):
    def __init__(self, team: dict[str, Any]):
        self.team = team

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await event_queue.enqueue_event(new_task(context.task_id, context.context_id, TaskState.TASK_STATE_SUBMITTED))
        iterator = None
        try:
            parts = get_data_parts(context.message.parts)
            if len(parts) != 1:
                raise HarnessError("invalid_handoff", "Exactly one structured handoff DataPart is required.")
            envelope = parts[0]
            payload = validate_handoff(envelope, self.team["agent_id"])
            with settings_scope(read_revision(payload.get("settings_revision"))), agent_scope(self.team["agent_id"]):
                iterator = run_team(self.team, payload)
                async with asyncio.timeout(runtime_timeout("team_task", "DEMO_TEAM_TASK_TIMEOUT")):
                    while (event := await asyncio.to_thread(_next, iterator)) is not None:
                        if event["type"] == "team_artifact":
                            artifact = event["artifact"]
                            artifact.update(task_id=context.task_id, handoff_id=envelope["handoff_id"], context_id=context.context_id)
                            await updater.add_artifact([new_data_part(artifact)], name="Team review", last_chunk=True)
                        else:
                            event.update(agent_id=self.team["agent_id"], agent_label=self.team["agent_label"],
                                         task_id=context.task_id, context_id=context.context_id, handoff_id=envelope["handoff_id"])
                            await updater.update_status(TaskState.TASK_STATE_WORKING, new_data_message({"demo_event": event}))
                await updater.complete()
        except TimeoutError:
            await updater.failed(new_data_message({"error": {"code": "team_timeout", "message": "The Team review exceeded its time limit."}}))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await updater.failed(new_data_message({"error": public_error(error, "The Team review failed. Check AI Core configuration and retry.")}))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.update_status(TaskState.TASK_STATE_CANCELED)


class RegisteredTeamExecutor(AgentExecutor):
    def __init__(self, target: str):
        self.target = target

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        try:
            parts = get_data_parts(context.message.parts)
            if len(parts) != 1:
                raise HarnessError("invalid_handoff", "Exactly one handoff is required.")
            payload = validate_handoff(parts[0], self.target)
            with settings_scope(read_revision(payload.get("settings_revision"))):
                team = next((item for item in get_profile()["agents"] if item["agent_id"] == self.target), None)
                if team is None:
                    raise HarnessError("unknown_team", "The Team is not registered in this settings revision.")
                await TeamExecutor(team).execute(context, event_queue)
        except Exception as error:
            await event_queue.enqueue_event(new_task(context.task_id, context.context_id, TaskState.TASK_STATE_SUBMITTED))
            await TaskUpdater(event_queue, context.task_id, context.context_id).failed(new_data_message({"error": public_error(error)}))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await TaskUpdater(event_queue, context.task_id, context.context_id).update_status(TaskState.TASK_STATE_CANCELED)


def create_app(base_url: str | None = None) -> Starlette:
    _load_repo_env()
    base_url = (base_url or os.getenv("DEMO_TEAM_BASE_URL", "http://127.0.0.1:8091")).rstrip("/")
    applications: dict[str, Starlette] = {}
    async def dispatch(scope: Any, receive: Any, send: Any) -> None:
        target = scope["path_params"]["agent_id"]
        if target not in applications:
            team = next((item for item in get_profile()["agents"] if item["agent_id"] == target), None)
            if team is None:
                # A previously discovered Card can still address a pinned older revision.
                team = {"agent_label": target, "description": "Registered Team", "skill_id": target, "tags": ["a2a"], "examples": ["Review evidence"]}
            store = InMemoryTaskStore()
            card = build_card(team, base_url + "/agents/" + target)
            handler = DefaultRequestHandler(RegisteredTeamExecutor(target), store, card)
            async def card_endpoint(request: Any) -> JSONResponse:
                try:
                    revision = request.query_params.get("settings_revision")
                    if revision is not None and (not revision.isdecimal() or int(revision) >= 2**53):
                        raise ValueError()
                    with settings_scope(read_revision(int(revision) if revision is not None else None)):
                        current = next((item for item in get_profile()["agents"] if item["agent_id"] == target), None)
                except (ValueError, HarnessError):
                    return JSONResponse({"error": "Settings revision unavailable"}, status_code=422)
                if current is None:
                    return JSONResponse({"error": "Team not registered"}, status_code=404)
                return JSONResponse(MessageToDict(build_card(current, base_url + "/agents/" + target)))
            applications[target] = Starlette(routes=[Route("/.well-known/agent-card.json", card_endpoint),
                                                     *create_jsonrpc_routes(handler, rpc_url="/")])
        await applications[target](scope, receive, send)
    return Starlette(routes=[Route("/healthz", lambda request: JSONResponse({"status": "ok", "teams": len(get_profile()["agents"])})),
                             Mount("/agents/{agent_id}", app=dispatch)])


if __name__ == "__main__":
    import uvicorn
    _load_repo_env()
    uvicorn.run(create_app(), host=os.getenv("DEMO_TEAM_HOST", "127.0.0.1"), port=int(os.getenv("DEMO_TEAM_PORT", "8091")))
