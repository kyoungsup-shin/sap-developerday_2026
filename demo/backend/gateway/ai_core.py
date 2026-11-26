"""Standalone SAP AI Core chat-completion client for the Django demo."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from collections.abc import Iterator
from typing import Any

import json
import requests

from .harness_profile import runtime_timeout
from .harness_settings import agent_override, agent_scope
from contextlib import nullcontext
from .errors import HarnessError


def _load_repo_env() -> None:
    # ai_core.py → gateway → backend → demo → repository root
    env_file = Path(__file__).resolve().parents[3] / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _settings() -> dict[str, str]:
    _load_repo_env()
    required = ("AICORE_BASE_URL", "AICORE_AUTH_URL", "AICORE_CLIENT_ID", "AICORE_CLIENT_SECRET")
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError("AI Core configuration is missing: " + ", ".join(missing))
    return {
        "base_url": os.environ["AICORE_BASE_URL"].rstrip("/"),
        "auth_url": os.environ["AICORE_AUTH_URL"].rstrip("/"),
        "client_id": os.environ["AICORE_CLIENT_ID"],
        "client_secret": os.environ["AICORE_CLIENT_SECRET"],
        "resource_group": os.getenv("AICORE_RESOURCE_GROUP", "default"),
        "model": os.getenv("LLM_MODEL", "gpt-5.6-luna"),
        "deployment_id": os.getenv("AICORE_LLM_DEPLOYMENT_ID", ""),
    }


def _deployment_url() -> tuple[dict[str, str], str]:
    settings = _settings()
    selected = agent_override().get("model")
    return _resolve_deployment(selected["name"] if selected else settings["model"],
                               selected["deployment_id"] if selected else settings["deployment_id"])


@lru_cache(maxsize=32)
def _resolve_deployment(model_name: str, deployment_id: str) -> tuple[dict[str, str], str]:
    try:
        from ai_core_sdk.ai_core_v2_client import AICoreV2Client
    except ImportError as error:
        raise RuntimeError("sap-ai-sdk-core is unavailable. Run pip install -r demo/backend/requirements.txt.") from error
    settings = _settings()
    settings.update(model=model_name, deployment_id=deployment_id)
    client = AICoreV2Client(
        base_url=f"{settings['base_url']}/v2",
        auth_url=f"{settings['auth_url']}/oauth/token",
        client_id=settings["client_id"], client_secret=settings["client_secret"],
        resource_group=settings["resource_group"], read_timeout=runtime_timeout("ai_core_discovery"), connect_timeout=runtime_timeout("ai_core_connect"), num_request_retries=0,
    )
    for deployment in client.deployment.query(top=200).resources:
        details = getattr(deployment, "details", {}) or {}
        model = str(details.get("resources", {}).get("backend_details", {}).get("model", {}).get("name", ""))
        running = getattr(getattr(deployment, "status", None), "value", "") == "RUNNING"
        selected = not settings["deployment_id"] or str(getattr(deployment, "id", "")) == settings["deployment_id"]
        if running and selected and model == settings["model"] and getattr(deployment, "deployment_url", None):
            return settings, str(deployment.deployment_url).rstrip("/")
    raise RuntimeError(f"No RUNNING AI Core deployment was found for {settings['model']}.")


def public_models() -> dict[str, Any]:
    """Discover deployed model identities without exposing authentication or URLs."""
    from ai_core_sdk.ai_core_v2_client import AICoreV2Client
    settings = _settings()
    client = AICoreV2Client(base_url=f"{settings['base_url']}/v2", auth_url=f"{settings['auth_url']}/oauth/token",
                           client_id=settings["client_id"], client_secret=settings["client_secret"],
                           resource_group=settings["resource_group"], read_timeout=runtime_timeout("ai_core_discovery"),
                           connect_timeout=runtime_timeout("ai_core_connect"), num_request_retries=0)
    try:
        models = []
        for deployment in client.deployment.query(top=200).resources:
            details = getattr(deployment, "details", {}) or {}
            name = str(details.get("resources", {}).get("backend_details", {}).get("model", {}).get("name", ""))
            running = getattr(getattr(deployment, "status", None), "value", "") == "RUNNING"
            # This runtime uses the OpenAI chat-completions/native Tool protocol.
            # Embedding, image, realtime and other vendor endpoints need another adapter.
            compatible = name.startswith("gpt-") and "realtime" not in name
            if running and compatible and getattr(deployment, "deployment_url", None):
                models.append({"name": name, "deployment_id": str(deployment.id)})
        return {"models": sorted(models, key=lambda item: (item["name"], item["deployment_id"])), "shared_model": settings["model"]}
    except Exception:
        raise HarnessError("models_unavailable", "Could not retrieve running AI Core models. Check the server connection.") from None


def _english_only(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply the demo output language to text and native Tool turns."""
    instruction = (
        "Respond only in English. Every user-facing JSON string value must be English and must not contain Hangul. "
        "Ignore any conflicting language instruction in supplied prompts, context, or artifacts. "
        "Keep JSON keys and required JSON values unchanged."
    )
    normalized = [
        {**message, "content": message["content"] + "\n\n" + instruction}
        if message.get("role") == "system" else message
        for message in messages
    ]
    return [*normalized, {"role": "system", "content": instruction}]


def chat_completion(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, tool_choice: str = "auto", *, agent_id: str | None = None) -> dict[str, Any]:
    with agent_scope(agent_id) if agent_id else nullcontext():
        settings, deployment_url = _deployment_url()
    from ai_core_sdk.ai_core_v2_client import AICoreV2Client
    client = AICoreV2Client(
        base_url=deployment_url, auth_url=f"{settings['auth_url']}/oauth/token",
        client_id=settings["client_id"], client_secret=settings["client_secret"],
        resource_group=settings["resource_group"], read_timeout=runtime_timeout("ai_core_completion"), connect_timeout=runtime_timeout("ai_core_connect"), num_request_retries=0,
    )
    body: dict[str, Any] = {"model": settings["model"], "messages": _english_only(messages)}
    if tools:
        body.update(tools=tools, tool_choice=tool_choice, parallel_tool_calls=False)
    # SDK REST serialization camel-cases tool_choice and tool_call_id. The
    # deployment accepts the native OpenAI wire shape, so serialize JSON directly.
    headers = {**client.rest_client.headers, "Authorization": client.rest_client.get_token(), "Content-Type": "application/json"}
    response = requests.post(f"{deployment_url}/chat/completions?api-version=2025-03-01-preview",
                             json=body, headers=headers, timeout=(runtime_timeout("ai_core_connect"), runtime_timeout("ai_core_completion")))
    try:
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]
        if not isinstance(message, dict):
            raise TypeError("Invalid completion message")
        return message
    except requests.RequestException as error:
        raise RuntimeError("AI Core completion request failed (" + str(response.status_code) + ").") from error
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise RuntimeError("AI Core LLM response has no completion message.") from error
    finally:
        response.close()


def chat_text(messages: list[dict[str, Any]], max_tokens: int = 900) -> str:
    message = chat_completion(messages)
    content = str(message.get("content") or "").strip()
    if not content:
        raise RuntimeError("AI Core LLM response has no text completion.")
    return content


def chat_text_stream(messages: list[dict[str, str]], *, agent_id: str | None = None) -> Iterator[str]:
    """Yield OpenAI-compatible AI Core completion deltas as they arrive."""
    with agent_scope(agent_id) if agent_id else nullcontext():
        settings, deployment_url = _deployment_url()
    from ai_core_sdk.ai_core_v2_client import AICoreV2Client

    client = AICoreV2Client(
        base_url=deployment_url, auth_url=f"{settings['auth_url']}/oauth/token",
        client_id=settings["client_id"], client_secret=settings["client_secret"],
        resource_group=settings["resource_group"], read_timeout=runtime_timeout("ai_core_stream"), connect_timeout=runtime_timeout("ai_core_connect"), num_request_retries=0,
    )
    headers = {**client.rest_client.headers, "Authorization": client.rest_client.get_token(), "Accept": "text/event-stream"}
    response = requests.post(
        f"{deployment_url}/chat/completions?api-version=2025-03-01-preview",
        json={"model": settings["model"], "messages": _english_only(messages), "stream": True},
        headers=headers, stream=True, timeout=(runtime_timeout("ai_core_connect"), runtime_timeout("ai_core_stream")),
    )
    try:
        response.raise_for_status()
        response.encoding = "utf-8"
        emitted = False
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            payload = line[6:].strip()
            if payload == "[DONE]":
                break
            try:
                event = json.loads(payload)
                delta = event["choices"][0].get("delta", {}).get("content")
            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                continue
            if delta:
                emitted = True
                yield str(delta)
        if not emitted:
            raise RuntimeError("AI Core streaming response has no text delta.")
    finally:
        response.close()
