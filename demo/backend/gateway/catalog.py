"""Profile-backed Team identities and exact demo-owned role prompts."""
from typing import Any

from .harness_profile import get_profile
from .prompt_resources import get_prompt, render_prompt
from .harness_settings import effective_prompt, current_settings

ORCHESTRATOR_PROMPT_KEY = "demo.orchestrator"
REVIEW_STYLE = get_prompt("roles.review")
SPECIALIST_REVIEW_STYLE = get_prompt("roles.specialist_review")
TEAM_REVIEW_STYLE = get_prompt("roles.team_review")
FINAL_REVIEW_STYLE = get_prompt("roles.final_review")
AGENT_CATALOG = tuple(get_profile()["agents"])
ORCHESTRATOR_SYSTEM_PROMPT = get_prompt("roles.orchestrator")


def orchestrator_system_prompt() -> str:
    return effective_prompt("orchestrator", get_prompt("roles.orchestrator"))


def team_system_prompt(team: dict[str, Any], *, defaults_only: bool = False) -> str:
    bindings = {"agent_label": team["agent_label"], "description": team["description"]}
    default = render_prompt("roles.team", **bindings)
    return default if defaults_only else effective_prompt(team["agent_id"], default, **bindings)


def specialist_system_prompt(subagent: str, *, defaults_only: bool = False) -> str:
    default = render_prompt("roles.specialist", specialist=subagent)
    return default if defaults_only else effective_prompt("specialist:" + subagent, default, specialist=subagent)


def public_prompts(*, defaults_only: bool = False) -> dict[str, Any]:
    registered = get_profile()["agents"]
    specialists = [
        specialist
        for team in registered
        for specialist in team["sub_agents"]
    ]
    return {
        "orchestrator": {"label": "Custom Extension Assistant", "prompt_key": ORCHESTRATOR_PROMPT_KEY, "system_prompt": get_prompt("roles.orchestrator") if defaults_only else orchestrator_system_prompt()},
        "team_agents": [
            {"agent_id": team["agent_id"], "label": team["agent_label"], "prompt_key": f"demo.team.{team['agent_id']}", "system_prompt": team_system_prompt(team, defaults_only=defaults_only)}
            for team in registered
        ],
        "specialist_agents": [
            {"agent_id": f"specialist:{specialist}", "label": specialist, "prompt_key": f"demo.specialist.{specialist}", "system_prompt": specialist_system_prompt(specialist, defaults_only=defaults_only)}
            for specialist in specialists
        ],
    }


def public_agents() -> list[dict[str, Any]]:
    keys = ("agent_id", "agent_label", "skill_id", "description", "sub_agents", "tags", "examples")
    local = [{key: team[key] for key in keys} for team in get_profile()["agents"]]
    external = [{"agent_id": item["agent_id"], "agent_label": item["label"], "skill_id": "external_a2a",
                 "description": "Registered external A2A Agent", "sub_agents": [], "tags": ["a2a", "external"], "examples": []}
                for item in current_settings().get("external_agents", []) if item["enabled"]]
    return local + external
