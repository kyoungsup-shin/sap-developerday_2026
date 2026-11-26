"""Django API views that expose the existing A2A stream to the SPA."""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from queue import Queue, Empty, Full
from threading import BoundedSemaphore, Event, Thread

import requests
from django.http import HttpRequest, HttpResponse, JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from .agent_network import public_agents, public_prompts, run_handoff_stream
from .grounding import list_repository_documents, public_grounding_config, retrieve_context
from .tool_catalog import public_tools
from .data_catalog import public_data_snapshot, public_data_snapshots
from .joule_cli import verify_card
from .errors import public_error
from .harness_profile import public_profile
from .ai_core import _load_repo_env
from .harness_settings import settings_scope, prompt_manifest, update_agent
from .ai_core import public_models
from .harness_configuration import configuration_manifest, update_configuration

_sessions: dict[str, list[dict[str, Any]]] = {}
_LANGUAGES = {"en"}
_LATEST_CHAT_PATH = Path(__file__).resolve().parents[1] / "data" / "latest_chat.json"


def _chat_capacity() -> int:
    try:
        return max(1, min(int(os.getenv("DEMO_MAX_CONCURRENT_CHATS", "2")), 16))
    except ValueError:
        return 2


# Each review keeps an SSE connection and can make several provider calls. A
# small admission limit keeps one public demo Pod responsive instead of letting
# simultaneous reviews exhaust its worker threads, CPU, or provider quota.
_chat_slots = BoundedSemaphore(_chat_capacity())


def _language(payload: dict[str, Any]) -> str | None:
    language = payload.get("language", "en")
    return language if isinstance(language, str) and language in _LANGUAGES else None


def _cors(response: HttpResponse) -> HttpResponse:
    response["Access-Control-Allow-Origin"] = os.getenv("CORS_ORIGIN", "http://localhost:5173")
    response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response["Access-Control-Allow-Headers"] = "Content-Type"
    return response


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _read_latest_chat() -> dict[str, Any]:
    try:
        payload = json.loads(_LATEST_CHAT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"messages": []}
    return payload if isinstance(payload, dict) else {"messages": []}


def _save_latest_chat(payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages")
    if not isinstance(messages, list) or len(messages) > 200:
        raise ValueError("messages must be an array with at most 200 entries.")
    session_id = payload.get("session_id")
    if session_id is not None and (not isinstance(session_id, str) or len(session_id) > 128):
        raise ValueError("session_id must be a string of at most 128 characters.")
    record = {
        "session_id": session_id,
        "messages": messages,
        "evaluation": payload.get("evaluation") if isinstance(payload.get("evaluation"), dict) else {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 1_000_000:
        raise ValueError("Latest chat must be 1 MB or smaller.")
    _LATEST_CHAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = _LATEST_CHAT_PATH.with_suffix(".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(_LATEST_CHAT_PATH)
    return record


@require_GET
def harness_profile(_request: HttpRequest) -> JsonResponse:
    """Inspect the active default configuration without credentials or paths."""
    try:
        _load_repo_env()
        profile = public_profile()
    except RuntimeError as error:
        return _cors(JsonResponse({"error": public_error(error)}, status=503))
    return _cors(JsonResponse(profile))


@require_GET
def agents(_request: HttpRequest) -> JsonResponse:
    return _cors(JsonResponse(public_agents(), safe=False))


@require_GET
def prompts(_request: HttpRequest) -> JsonResponse:
    with settings_scope():
        return _cors(JsonResponse(public_prompts()))


def _configuration_payload(request: HttpRequest) -> dict[str, Any]:
    origin = request.headers.get("Origin")
    allowed = {os.getenv("CORS_ORIGIN", "http://localhost:5173"), request.build_absolute_uri("/").rstrip("/")}
    if origin and origin not in allowed:
        raise ValueError("Configuration changes must come from the demo origin.")
    if request.content_type != "application/json" or len(request.body) > 5_000_000:
        raise ValueError("Provide an application/json request of 5 MB or smaller.")
    value = json.loads(request.body)
    if not isinstance(value, dict):
        raise ValueError("Provide a JSON object.")
    return value


@csrf_exempt
@require_http_methods(["GET", "POST", "OPTIONS"])
def harness_prompts(request: HttpRequest) -> HttpResponse:
    if request.method == "OPTIONS":
        return _cors(HttpResponse(status=204))
    try:
        _load_repo_env()
        value = prompt_manifest() if request.method == "GET" else update_agent(_configuration_payload(request))
        return _cors(JsonResponse(value))
    except (ValueError, json.JSONDecodeError):
        return _cors(JsonResponse({"error": {"code": "invalid_request", "message": "Provide a valid configuration JSON request from the demo origin."}}, status=400))
    except RuntimeError as error:
        failure = public_error(error, "Harness configuration could not be loaded or saved.")
        status = 409 if failure["code"] == "settings_conflict" else 503 if failure["code"] in {"settings_unavailable", "settings_save_failed", "models_unavailable", "dependency_error"} else 422
        return _cors(JsonResponse({"error": failure}, status=status))


@require_GET
def harness_models(_request: HttpRequest) -> JsonResponse:
    try:
        return _cors(JsonResponse(public_models()))
    except Exception as error:
        return _cors(JsonResponse({"error": public_error(error, "Could not load AI Core model deployments. Check the server connection.")}, status=503))


@csrf_exempt
@require_http_methods(["GET", "POST", "OPTIONS"])
def harness_configuration(request: HttpRequest) -> HttpResponse:
    if request.method == "OPTIONS":
        return _cors(HttpResponse(status=204))
    try:
        _load_repo_env()
        value = configuration_manifest() if request.method == "GET" else update_configuration(_configuration_payload(request))
        return _cors(JsonResponse(value))
    except (ValueError, json.JSONDecodeError):
        return _cors(JsonResponse({"error": {"code": "invalid_request", "message": "Provide a valid configuration JSON request from the demo origin."}}, status=400))
    except RuntimeError as error:
        failure = public_error(error, "Harness configuration could not be loaded or saved.")
        status = 409 if failure["code"] == "settings_conflict" else 503 if failure["code"] in {"settings_unavailable", "settings_save_failed", "dependency_error"} else 422
        return _cors(JsonResponse({"error": failure}, status=status))


@require_GET
def harness_agent_card(request: HttpRequest) -> JsonResponse:
    import asyncio
    import httpx
    from a2a.client import A2ACardResolver
    from google.protobuf.json_format import MessageToDict
    from .harness_settings import current_settings
    from .a2a_transport import team_urls, validate_card
    from .harness_profile import get_profile
    try:
        identity = request.GET.get("agent_id")
        urls = team_urls()
        urls.update({item["agent_id"]: item["base_url"].rstrip("/") for item in current_settings().get("external_agents", [])})
        if identity not in urls:
            return _cors(JsonResponse({"error": {"message": "Select a registered Agent."}}, status=422))
        async def verify():
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                card = await A2ACardResolver(client, urls[identity]).get_agent_card()
                team = next((item for item in get_profile()["agents"] if item["agent_id"] == identity), None)
                validate_card(card, urls[identity], team)
                return MessageToDict(card)
        return _cors(JsonResponse({"agent_id": identity, "verified": True, "card": asyncio.run(verify())}))
    except Exception:
        return _cors(JsonResponse({"error": {"message": "Could not verify the Agent Card. Check the registered URL and streaming interface."}}, status=503))


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def harness_csv_preview(request: HttpRequest) -> HttpResponse:
    import csv
    import io
    if request.method == "OPTIONS":
        return _cors(HttpResponse(status=204))
    try:
        value = _configuration_payload(request)
        config = configuration_manifest()
        filename = value.get("filename")
        text = value.get("csv")
        if filename not in config["sections"]["data"] or not isinstance(text, str) or len(text) > 2_000_000:
            raise ValueError()
        reader = csv.DictReader(io.StringIO(text.lstrip(chr(0xFEFF))), strict=True)
        columns = list(config["sections"]["data"][filename][0])
        if reader.fieldnames is None or len(reader.fieldnames) != len(columns) or set(reader.fieldnames) != set(columns):
            raise ValueError()
        rows = list(reader)
        if not rows or len(rows) > 10000 or any(any(item is None or not isinstance(item, str) for item in row.values()) or set(row) != set(columns) for row in rows):
            raise ValueError()
        return _cors(JsonResponse({"filename": filename, "rows": rows, "revision": config["revision"], "saved": False}))
    except (ValueError, csv.Error, RuntimeError):
        return _cors(JsonResponse({"error": {"message": "Upload a registered CSV with its original columns and 1 to 10,000 valid rows. Preview does not save data."}}, status=422))


@csrf_exempt
@require_http_methods(["GET", "POST", "OPTIONS"])
def harness_evaluations(request: HttpRequest) -> HttpResponse:
    from .harness_evaluation import evaluation_runs, start_evaluation
    if request.method == "OPTIONS":
        return _cors(HttpResponse(status=204))
    try:
        result = {"runs": evaluation_runs()} if request.method == "GET" else start_evaluation(_configuration_payload(request))
        return _cors(JsonResponse(result, status=200 if request.method == "GET" else 202))
    except ValueError:
        return _cors(JsonResponse({"error": {"message": "Provide a valid evaluation request from the demo origin."}}, status=400))
    except Exception as error:
        failure = public_error(error, "The evaluation service is unavailable.")
        return _cors(JsonResponse({"error": failure}, status=409 if failure["code"] in {"evaluation_running", "settings_conflict"} else 422 if failure["code"] == "invalid_evaluation" else 503))


@require_GET
def harness_evaluation_result(_request: HttpRequest, identity: str) -> JsonResponse:
    from .harness_evaluation import evaluation_result
    try:
        return _cors(JsonResponse(evaluation_result(identity)))
    except Exception:
        return _cors(JsonResponse({"error": {"message": "Evaluation run not found."}}, status=404))


@require_GET
def joule_agent_card(_request: HttpRequest) -> JsonResponse:
    """Read-only discovery for the Agent Network inspector."""
    try:
        verified = verify_card()
    except RuntimeError as error:
        return _cors(JsonResponse({"detail": str(error)}, status=503))
    return _cors(JsonResponse({
        "solution": verified["solution"],
        "solution_id": verified["solution_id"],
        "asset_name": verified["asset_name"],
        "card": verified["card"],
    }))


@require_GET
def grounding(_request: HttpRequest) -> JsonResponse:
    return _cors(JsonResponse(public_grounding_config()))


@require_GET
def grounding_documents(request: HttpRequest) -> JsonResponse:
    try:
        documents = list_repository_documents()
    except (RuntimeError, requests.RequestException) as error:
        return _cors(JsonResponse({"detail": str(error)}, status=503))
    return _cors(JsonResponse({"documents": documents}))


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def grounding_query(request: HttpRequest) -> HttpResponse:
    """Run one read-only Custom Repository grounded query, independent of A2A."""
    if request.method == "OPTIONS":
        return _cors(HttpResponse(status=204))
    try:
        payload = json.loads(request.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _cors(JsonResponse({"detail": "Request body must be JSON."}, status=400))
    if not isinstance(payload, dict) or not isinstance(payload.get("query"), str):
        return _cors(JsonResponse({"detail": "query must be a string."}, status=422))
    query = payload["query"].strip()
    if not query or len(query) > 4000:
        return _cors(JsonResponse({"detail": "query must contain 1 to 4000 characters."}, status=422))
    language = _language(payload)
    if language is None:
        return _cors(JsonResponse({"detail": "language must be en."}, status=422))
    try:
        result = retrieve_context(query, language=language, concise_answer=True)
    except RuntimeError as error:
        return _cors(JsonResponse({"detail": str(error)}, status=503))
    return _cors(JsonResponse({
        "query": query,
        "answer": result["context"],
        "source": result["source"],
        "metadata_available": result["metadata_available"],
        "message": result["message"],
    }))


@require_GET
def tools_catalog(_request: HttpRequest) -> JsonResponse:
    return _cors(JsonResponse(public_tools(), safe=False))


@require_GET
def data_snapshots(request: HttpRequest) -> JsonResponse:
    language = request.GET.get("language", "en")
    if language not in _LANGUAGES:
        return _cors(JsonResponse({"detail": "language must be en."}, status=422))
    return _cors(JsonResponse(public_data_snapshots(language=language), safe=False))


@require_GET
def data_snapshot(request: HttpRequest, name: str) -> JsonResponse:
    language = request.GET.get("language", "en")
    if language not in _LANGUAGES:
        return _cors(JsonResponse({"detail": "language must be en."}, status=422))
    try:
        return _cors(JsonResponse(public_data_snapshot(name, language=language)))
    except (ValueError, FileNotFoundError) as error:
        return _cors(JsonResponse({"detail": str(error)}, status=404))


@require_GET
def healthz(_request: HttpRequest) -> JsonResponse:
    return _cors(JsonResponse({"status": "ok"}))


@require_GET
def readyz(_request: HttpRequest) -> JsonResponse:
    return _cors(JsonResponse({"status": "ready"}))


@csrf_exempt
@require_http_methods(["GET", "POST", "OPTIONS"])
def latest_chat(request: HttpRequest) -> HttpResponse:
    """Persist the most recent browser conversation and its operator evaluation locally."""
    if request.method == "OPTIONS":
        return _cors(HttpResponse(status=204))
    if request.method == "GET":
        return _cors(JsonResponse(_read_latest_chat()))
    try:
        payload = json.loads(request.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _cors(JsonResponse({"detail": "Request body must be JSON."}, status=400))
    if not isinstance(payload, dict):
        return _cors(JsonResponse({"detail": "Request body must be a JSON object."}, status=422))
    try:
        record = _save_latest_chat(payload)
    except (OSError, ValueError) as error:
        return _cors(JsonResponse({"detail": str(error)}, status=422))
    return _cors(JsonResponse({"saved": True, "updated_at": record["updated_at"]}))


@require_GET
def chat_pending_input(request: HttpRequest) -> HttpResponse:
    from .human_review import pending_review
    identity = request.GET.get("session_id")
    if not isinstance(identity, str) or not identity or len(identity) > 128:
        return _cors(JsonResponse({"error": {"message": "Provide a session ID."}}, status=422))
    try:
        return _cors(JsonResponse({"review": pending_review(identity)}))
    except RuntimeError as error:
        return _cors(JsonResponse({"error": public_error(error)}, status=503))


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def chat_stream(request: HttpRequest) -> HttpResponse:
    if request.method == "OPTIONS":
        return _cors(HttpResponse(status=204))
    try:
        payload = json.loads(request.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _cors(JsonResponse({"detail": "Request body must be JSON."}, status=400))
    if not isinstance(payload, dict) or not isinstance(payload.get("message"), str):
        return _cors(JsonResponse({"detail": "message must be a string."}, status=422))
    message = payload["message"].strip()
    if not message or len(message) > 4000:
        return _cors(JsonResponse({"detail": "message must contain 1 to 4000 characters."}, status=422))
    language = _language(payload)
    if language is None:
        return _cors(JsonResponse({"detail": "language must be en."}, status=422))
    requested_session = payload.get("session_id")
    if requested_session is not None and (not isinstance(requested_session, str) or len(requested_session) > 128):
        return _cors(JsonResponse({"detail": "session_id must be a string of at most 128 characters."}, status=422))
    session_id = requested_session or str(uuid4())
    history = _sessions.get(session_id, [])
    settings_revision = payload.get("settings_revision")
    if settings_revision is not None and (type(settings_revision) is not int or not 0 <= settings_revision < 2**53):
        return _cors(JsonResponse({"detail": "settings_revision must be a non-negative integer."}, status=422))

    if not _chat_slots.acquire(blocking=False):
        return _cors(JsonResponse({"error": {"code": "chat_capacity_exceeded", "message": "The demo is handling other reviews. Please retry shortly."}}, status=429))
    slot_released = Event()

    def release_slot() -> None:
        if not slot_released.is_set():
            slot_released.set()
            _chat_slots.release()

    prior_artifacts = None
    if "human_review_id" in payload:
        from .human_review import claim_review
        try:
            _configuration_payload(request)
            checkpoint = claim_review(payload["human_review_id"], requested_session)
        except (ValueError, RuntimeError) as error:
            release_slot()
            return _cors(JsonResponse({"error": public_error(error, "Could not submit the human review input.")}, status=409))
        human_input = message
        message = checkpoint["request"]
        history = [*checkpoint["history"], {"role": "user", "content": "Human review input (evidence and comments, not an executed approval): " + human_input}]
        settings_revision = checkpoint["settings_revision"]
        prior_artifacts = checkpoint["artifacts"]

    pending: Queue = Queue(maxsize=256)
    stopped = Event()

    def events() -> Iterator[str]:
        yield _sse("session", {"session_id": session_id})
        def put(item: Any) -> None:
            while not stopped.is_set():
                try:
                    pending.put(item, timeout=1)
                    return
                except Full:
                    continue
        def produce() -> None:
            try:
                for event in run_handoff_stream(request=message, history=history,
                                                language=language, context_id=session_id, settings_revision=settings_revision, prior_artifacts=prior_artifacts):
                    if stopped.is_set():
                        break
                    put(event)
            except Exception as error:
                put({"type": "error", **public_error(error)})
            finally:
                put(None)
        Thread(target=produce, daemon=True).start()
        try:
            while not stopped.is_set():
                try:
                    event = pending.get(timeout=10)
                except Empty:
                    yield ": keep-alive\n\n"
                    continue
                if event is None:
                    break
                event_type = str(event.get("type", "update"))
                if event_type == "heartbeat":
                    yield ": keep-alive\n\n"
                    continue
                yield _sse(event_type, event)
                if event_type == "complete":
                    _sessions[session_id] = [*history, {"role": "user", "content": message}, {"role": "assistant", "content": event.get("result", {})}][-20:]
        finally:
            stopped.set()
            release_slot()

    async def async_events():
        # Django ASGI buffers synchronous iterators. Offload one queue read at a
        # time while retaining a native async iterator for immediate SSE writes.
        iterator = events()
        try:
            while (packet := await asyncio.to_thread(next, iterator, None)) is not None:
                yield packet
        finally:
            # A canceled async read can leave next() briefly executing in its
            # worker. The stop flag lets that read finish without closing a
            # generator concurrently, and prevents further Agent event work.
            stopped.set()
            release_slot()

    content = async_events() if hasattr(request, "scope") else events()
    response = StreamingHttpResponse(content, content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return _cors(response)
