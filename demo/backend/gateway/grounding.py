"""Read-only AI Core Custom Repository Grounding for the A2A demo."""
from __future__ import annotations

import os
import json
from typing import Any
from urllib.parse import quote

import requests

from .ai_core import _settings
from .harness_profile import runtime_timeout
from .harness_settings import current_settings
from .prompt_resources import get_prompt
from .errors import HarnessError


def _orchestration_url(settings: dict[str, str]) -> str:
    configured = os.getenv("AICORE_ORCHESTRATION_DEPLOYMENT_URL", "").rstrip("/")
    if configured:
        return configured
    from ai_core_sdk.ai_core_v2_client import AICoreV2Client

    client = AICoreV2Client(
        base_url=f"{settings['base_url']}/v2", auth_url=f"{settings['auth_url']}/oauth/token",
        client_id=settings["client_id"], client_secret=settings["client_secret"],
        resource_group=settings["resource_group"], read_timeout=runtime_timeout("grounding_discovery"), connect_timeout=runtime_timeout("ai_core_connect"), num_request_retries=0,
    )
    for deployment in client.deployment.query(top=200).resources:
        scenario = str(getattr(deployment, "scenario_id", "") or getattr(deployment, "scenarioId", ""))
        running = getattr(getattr(deployment, "status", None), "value", "") == "RUNNING"
        if running and scenario == "orchestration" and getattr(deployment, "deployment_url", None):
            return str(deployment.deployment_url).rstrip("/")
    raise RuntimeError("No RUNNING orchestration deployment was found.")


def _value(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)


def validated_sop_review(content: str, evidence: str) -> tuple[str, list[str]]:
    """Accept only a source-bound, applicable SOP review, never a generic fallback."""
    fence = chr(96) * 3
    try:
        value = json.loads(content.strip().removeprefix(fence + "json").removeprefix(fence).removesuffix(fence).strip())
    except (ValueError, TypeError):
        raise HarnessError("sop_unavailable", "Applicable SOP evidence could not be verified. The business review was not started.") from None
    if (not evidence.strip() or not isinstance(value, dict) or value.get("sop_found") is not True
            or not isinstance(value.get("context"), str) or not value["context"].strip()
            or not isinstance(value.get("sources"), list) or not value["sources"]
            or any(not isinstance(source, str) or not source.strip() or source.strip().casefold() not in evidence.casefold()
                   for source in value["sources"])):
        raise HarnessError("sop_unavailable", "No applicable, source-bound SOP evidence was found. The business review was not started.")
    return value["context"].strip(), list(dict.fromkeys(source.strip() for source in value["sources"]))


def retrieve_context(query: str, repository_id: str | None = None, language: str = "en", concise_answer: bool = False, require_sop: bool = False) -> dict[str, Any]:
    """Retrieve context from the configured vector repository without any mutation."""
    settings = _settings()
    repository_id = (repository_id or current_settings().get("grounding_repository", os.getenv("GROUNDING_REPOSITORY_ID", ""))).strip()
    if not repository_id:
        raise RuntimeError("GROUNDING_REPOSITORY_ID is not configured in the repository root .env file.")
    try:
        from gen_ai_hub.orchestration_v2.models.config import ModuleConfig, OrchestrationConfig
        from gen_ai_hub.orchestration_v2.models.document_grounding import (
            DocumentGroundingConfig, DocumentGroundingFilter, DocumentGroundingPlaceholders, GroundingModuleConfig,
        )
        from gen_ai_hub.orchestration_v2.models.llm_model_details import LLMModelDetails
        from gen_ai_hub.orchestration_v2.models.message import SystemMessage, UserMessage
        from gen_ai_hub.orchestration_v2.models.template import PromptTemplatingModuleConfig, Template
        from gen_ai_hub.orchestration_v2.service import OrchestrationService
    except ImportError as error:
        raise RuntimeError("sap-ai-sdk-gen is unavailable. Install demo/backend/requirements.txt.") from error

    grounding = GroundingModuleConfig(config=DocumentGroundingConfig(
        filters=[DocumentGroundingFilter(id="CustomRepository", data_repository_type="vector", data_repositories=[repository_id])],
        placeholders=DocumentGroundingPlaceholders(input=["user_query"], output="grounding_context"),
    ))
    prompt = PromptTemplatingModuleConfig(
        prompt=Template(template=[
            SystemMessage(content=get_prompt("grounding.sop_system_en" if require_sop else "grounding.answer_system_en" if concise_answer else "grounding.system_en")),
            UserMessage(content=get_prompt("grounding.user")),
        ]),
        model=LLMModelDetails(name=settings["model"], params={"max_tokens": 160 if concise_answer else 1600}),
    )
    service = OrchestrationService(
        api_url=_orchestration_url(settings),
        config=OrchestrationConfig(modules=ModuleConfig(prompt_templating=prompt, grounding=grounding)),
    )
    response = service.run(placeholder_values={"user_query": query.strip()})
    context = str(response.final_result.choices[0].message.content or "").strip()
    intermediate = _value(response, "intermediate_results")
    trace = _value(intermediate, "grounding")
    sop_sources: list[str] = []
    sop_source_ids: list[str] = []
    if require_sop:
        evidence = str(_value(_value(trace, "data"), "grounding_result") or "")
        context, sop_sources = validated_sop_review(context, evidence)
        sop_source_ids = [f"SOP-{index:02d}" for index in range(1, len(sop_sources) + 1)]
        for source, identifier in sorted(zip(sop_sources, sop_source_ids), key=lambda item: len(item[0]), reverse=True):
            context = context.replace(source, identifier)
        context = context[:15000] + "\n\nSOP sources: " + "; ".join(sop_source_ids)
    return {
        "context": context[:300] if concise_answer else context[:16000],
        "source": "Configured vector repository",
        "metadata_available": trace is not None,
        "message": str(_value(trace, "message") or "Grounding context retrieved."),
        "sop_sources": sop_sources,
        "sop_source_ids": sop_source_ids,
    }


def public_grounding_config() -> dict[str, Any]:
    """Expose only grounding availability; repository configuration stays server-side."""
    _settings()  # Loads the repository root .env before reading the ID.
    repository_id = current_settings().get("grounding_repository", os.getenv("GROUNDING_REPOSITORY_ID", "")).strip()
    return {
        "configured": bool(repository_id),
    }


def list_repository_documents(repository_id: str | None = None) -> list[dict[str, str]]:
    """List document identifiers from a Custom Repository without exposing chunks."""
    settings = _settings()
    collection_id = (repository_id or current_settings().get("grounding_repository", os.getenv("GROUNDING_REPOSITORY_ID", ""))).strip()
    if not collection_id:
        raise RuntimeError("GROUNDING_REPOSITORY_ID is not configured in the repository root .env file.")
    try:
        from ai_core_sdk.ai_core_v2_client import AICoreV2Client
    except ImportError as error:
        raise RuntimeError("sap-ai-sdk-core is unavailable. Install demo/backend/requirements.txt.") from error
    client = AICoreV2Client(
        base_url=f"{settings['base_url']}/v2", auth_url=f"{settings['auth_url']}/oauth/token",
        client_id=settings["client_id"], client_secret=settings["client_secret"],
        resource_group=settings["resource_group"], read_timeout=runtime_timeout("grounding_documents"), connect_timeout=runtime_timeout("ai_core_connect"), num_request_retries=0,
    )
    response = requests.get(
        f"{settings['base_url']}/v2/lm/document-grounding/vector/collections/{quote(collection_id, safe='')}/documents",
        headers={
            "Authorization": client.rest_client.get_token(),
            "AI-Resource-Group": settings["resource_group"],
            "Accept": "application/json",
        }, timeout=runtime_timeout("grounding_documents"),
    )
    response.raise_for_status()
    payload = response.json()
    resources = payload.get("resources", payload.get("documents", [])) if isinstance(payload, dict) else payload
    if not isinstance(resources, list):
        return []
    documents: list[dict[str, str]] = []
    for item in resources:
        if not isinstance(item, dict):
            continue
        identifier = str(item.get("id") or item.get("documentId") or item.get("name") or "Document")
        metadata = item.get("metadata")
        if isinstance(metadata, list):
            for entry in metadata:
                if isinstance(entry, dict) and entry.get("key") == "id":
                    values = entry.get("value", [])
                    if isinstance(values, list) and values:
                        identifier = str(values[0])
        documents.append({"id": identifier, "name": str(item.get("name") or identifier)})
    return documents
