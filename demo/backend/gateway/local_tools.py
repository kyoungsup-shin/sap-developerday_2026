"""Demo-native role-scoped CSV lookup and profitability calculation."""
from __future__ import annotations

import csv
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from .harness_profile import get_profile, resource_path
from .tool_catalog import native_tool_schema
from .harness_settings import current_settings

DATA_DIR = resource_path("snapshots")
_SPECIALISTS = {item["name"]: item for item in get_profile()["specialists"]}
SPECIALIST_DOMAINS = {name: tuple(item["domains"]) for name, item in _SPECIALISTS.items()}


def read_snapshot(name: str) -> list[dict[str, str]]:
    if Path(name).name != name or not name.endswith(".csv"):
        raise ValueError("Invalid snapshot name.")
    override = current_settings().get("datasets", {}).get(name)
    if override is not None:
        return override
    with (resource_path("snapshots") / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def normalized_arguments(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return {key: normalized_arguments(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalized_arguments(item) for item in value]
    return value


def tool_ids_for_subagent(subagent: str) -> tuple[str, ...]:
    specialists = {item["name"]: item for item in get_profile()["specialists"]}
    if subagent not in specialists:
        raise ValueError("Unknown Specialist identity.")
    return tuple(specialists[subagent]["tools"])


def specialist_domains(subagent: str) -> tuple[str, ...]:
    specialists = {item["name"]: item for item in get_profile()["specialists"]}
    if subagent not in specialists:
        raise ValueError("Unknown Specialist identity.")
    return tuple(specialists[subagent]["domains"])


def tool_schemas_for_subagent(subagent: str) -> list[dict[str, Any]]:
    schemas = [native_tool_schema(name) for name in tool_ids_for_subagent(subagent)]
    for schema in schemas:
        if schema["function"]["name"] == "retrieve_business_evidence":
            schema["function"]["description"] += " Authorized domains: " + ", ".join(specialist_domains(subagent)) + "."
    return schemas


def _search(request_text: str) -> dict[str, Any]:
    query = " ".join(request_text.casefold().split())
    matches = []
    for row in read_snapshot("business_context.csv"):
        candidates = [row["NAME"], row["CONTEXT_ID"], row["ENTITY_ID"], *row["ALIASES"].split("|")]
        if any(re.search(r"(?<!\w)" + re.escape(alias.casefold()) + r"(?!\w)", query) for alias in candidates):
            matches.append(row)
    return {"state": "found" if matches else "not_found", "matches": matches,
            "source": "Demo sample snapshots", "read_only": True,
            "note": "Entity lookup only; this search does not route Agents."}


def _evidence(subagent: str, context_id: str) -> dict[str, Any]:
    domains = specialist_domains(subagent)
    rows = read_snapshot("operations_evidence.csv")
    result = {}
    for domain in domains:
        selected = [row for row in rows if row["CONTEXT_ID"] == context_id and row["DOMAIN"] == domain]
        datasets: dict[str, Any] = {"operations_evidence": selected}
        if domain == "cost_driver":
            datasets["product_cost_assumption"] = [row for row in read_snapshot("product_cost_assumption.csv") if row["CONTEXT_ID"] == context_id]
        if domain == "financial_control":
            datasets["cost_center_master"] = [row for row in read_snapshot("cost_center_master.csv") if row["CONTEXT_ID"] == context_id]
        result[domain] = {"state": "found" if any(datasets.values()) else "not_found", "datasets": datasets,
                          "source": "Demo sample snapshots", "read_only": True}
    return {"state": "found" if any(item["state"] == "found" for item in result.values()) else "not_found",
            "CONTEXT_ID": context_id, "evidence_by_domain": result, "read_only": True}


def _money(number: Decimal) -> float:
    return float(number.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _profitability(context_id: str) -> dict[str, Any]:
    records = [row for row in read_snapshot("product_cost_assumption.csv") if row["CONTEXT_ID"] == context_id]
    if not records:
        return {"state": "not_found", "CONTEXT_ID": context_id, "scenarios": [], "read_only": True}
    row = records[0]
    d = lambda key: Decimal(row[key])
    price, volume, fixed = d("SELLING_PRICE"), d("QUARTER_VOLUME"), d("FIXED_COST_USD")
    scenarios = []
    for name, fx, increase in [("base", d("BASE_FX_USD_EUR"), Decimal(0)),
                                ("stress", d("STRESS_FX_USD_EUR"), d("RAW_MATERIAL_INCREASE_PCT") / 100)]:
        variable = d("IMPORTED_COST_EUR") * fx * (1 + increase) + d("LOCAL_VARIABLE_COST_USD")
        margin = price - variable
        scenarios.append({"scenario": name, "fx_usd_per_eur": float(fx), "raw_material_increase_percent": float(increase * 100),
                          "unrounded_unit_cost": str(variable), "unit_cost": _money(variable),
                          "unit_contribution": _money(margin), "quarter_profit": _money(margin * volume - fixed),
                          "break_even_units": int((fixed / margin).to_integral_value(rounding="ROUND_CEILING")) if margin > 0 else None})
    fx_effect = d("IMPORTED_COST_EUR") * (d("STRESS_FX_USD_EUR") - d("BASE_FX_USD_EUR")) * volume
    raw_effect = d("IMPORTED_COST_EUR") * d("BASE_FX_USD_EUR") * d("RAW_MATERIAL_INCREASE_PCT") / 100 * volume
    interaction = d("IMPORTED_COST_EUR") * (d("STRESS_FX_USD_EUR") - d("BASE_FX_USD_EUR")) * d("RAW_MATERIAL_INCREASE_PCT") / 100 * volume
    return {"state": "calculated", "CONTEXT_ID": context_id, "currency": row["CURRENCY"], "period": row["PERIOD"],
            "assumptions": row, "scenarios": scenarios,
            "profit_change": _money(Decimal(str(scenarios[1]["quarter_profit"])) - Decimal(str(scenarios[0]["quarter_profit"]))),
            "profit_decrease_percent": _money((fx_effect + raw_effect + interaction) / Decimal(str(scenarios[0]["quarter_profit"])) * 100) if scenarios[0]["quarter_profit"] > 0 else None,
            "attribution": {"fx_only_profit_decrease": _money(fx_effect), "raw_material_only_profit_decrease": _money(raw_effect),
                            "interaction_profit_decrease": _money(interaction), "combined_profit_decrease": _money(fx_effect + raw_effect + interaction)},
            "scenario_basis": "Base uses the base FX with zero raw-material inflation. Stress applies both the stress FX and the stated raw-material increase. Attribution includes their interaction.",
            "formula": "quarter_profit = (selling_price - imported_cost_eur * FX * (1 + raw_material_increase) - local_variable_cost) * volume - fixed_cost",
            "source": "Demo product_cost_assumption.csv", "read_only": True}


def execute_authorized_tool(subagent: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in tool_ids_for_subagent(subagent):
        raise ValueError("Tool is not authorized for this Specialist.")
    parameter = "request_text" if name == "search_business_context" else "context_id"
    arguments = normalized_arguments(arguments)
    if not isinstance(arguments, dict) or set(arguments) != {parameter} or not isinstance(arguments.get(parameter), str) or not arguments[parameter]:
        raise ValueError("Provide the required non-empty " + parameter + " string only.")
    value = arguments[parameter]
    if name != "search_business_context" and value not in {row["CONTEXT_ID"] for row in read_snapshot("business_context.csv")}:
        raise ValueError("Use a Context ID returned by entity lookup or prior evidence.")
    if name == "search_business_context":
        result = _search(value)
        domains: list[str] = []
    elif name == "retrieve_business_evidence":
        result = _evidence(subagent, value)
        domains = list(specialist_domains(subagent))
    else:
        result = _profitability(value)
        domains = ["cost_driver", "business_outlook"]
    return {"name": name, "arguments": arguments, "domains": domains, "result": result}
