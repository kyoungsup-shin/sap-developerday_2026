"""Expand the local demo CSV snapshots to a realistic minimum sample size.

The two A2A demo variants intentionally use the same reference snapshots.  This
utility preserves all relationships used by the read-only tools while creating
additional dated records with unique record identifiers.
"""

from __future__ import annotations

import csv
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORIES = (
    ROOT / "4_agent_patterns/src/agent_to_agent/data/hana_raw",
    ROOT / "4_agent_patterns/src/agent_to_agent_advanced/data/hana_raw",
)
MINIMUM_ROWS = 30

# These fields identify a snapshot record.
IDENTIFIER_FIELDS = (
    "RECORD_ID", "WORK_ORDER_ID", "PURCHASE_REQUISITION_ID",
    "REQUEST_ID", "CHANGE_REQUEST_ID", "BUDGET_TRANSFER_ID",
    "COMMITMENT_ID", "SCHEDULE_ID", "QUOTE_ID", "PLAN_ID",
    "FORECAST_ID", "EVIDENCE_ID", "MAPPING_ID", "SCENARIO_ID",
    "BOM_CHANGE_ID", "MATERIAL_INTAKE_ID", "EQUIPMENT_ID",
)


def record_identifier(fieldnames: list[str]) -> str | None:
    for name in IDENTIFIER_FIELDS:
        if name in fieldnames:
            return name
    return None


TEXT_FIELDS = {
    "DISPLAY_NAME", "DESCRIPTION", "SUBJECT", "DETAILS", "OBSERVATION",
    "DIAGNOSIS", "RECOMMENDED_ACTION", "OPERATION_IMPACT", "RISK_NOTE",
}

STATUS_VARIANTS = {
    "REQUEST_STATUS": ("SUBMITTED", "IN_REVIEW", "APPROVED"),
    "APPROVAL_STATUS": ("PENDING_REVIEW", "APPROVED", "CONDITIONAL_APPROVAL"),
    "CHANGE_STATUS": ("IN_REVIEW", "SCHEDULED", "IMPLEMENTED"),
    "COMMITMENT_STATUS": ("PLANNED", "PARTIALLY_COMMITTED", "COMMITTED"),
    "RELEASE_STATUS": ("PENDING_TEST", "CONDITIONAL_RELEASE", "RELEASED"),
}


def shift_date(value: str, days: int) -> str:
    """Shift common snapshot date formats without changing their format."""
    try:
        if "T" in value:
            stamp = datetime.fromisoformat(value) + timedelta(days=days)
            return stamp.isoformat()
        if len(value) == 7:  # YYYY-MM
            year, month = map(int, value.split("-"))
            month += days // 7
            year += (month - 1) // 12
            month = (month - 1) % 12 + 1
            return f"{year:04d}-{month:02d}"
        return (date.fromisoformat(value) + timedelta(days=days)).isoformat()
    except ValueError:
        return value


def vary_row(row: dict[str, str], sequence: int) -> None:
    """Give generated snapshots a distinct, still plausible business state."""
    for field, value in tuple(row.items()):
        if not value:
            continue
        if field in STATUS_VARIANTS:
            row[field] = STATUS_VARIANTS[field][(sequence - 1) % 3]
        elif field in TEXT_FIELDS:
            phase = ("field verification", "alternative review", "risk assessment", "action planning")[sequence % 4]
            row[field] = f"{value} ({phase}, cycle {sequence})"
        elif field.endswith(("DATE", "FROM", "TO", "PERIOD")) or field == "SYNCED_AT":
            row[field] = shift_date(value, sequence * 3)
        elif (
            field not in {"FISCAL_YEAR", "SCENARIO_ORDER"}
            and any(token in field for token in ("AMOUNT", "QUANTITY", "PRICE", "RATE", "STOCK", "POINT", "DAYS"))
        ):
            try:
                number = float(value)
            except ValueError:
                continue
            adjusted = number * (1 + ((sequence % 7) - 3) * 0.035)
            row[field] = str(int(round(adjusted))) if value.isdigit() else f"{adjusted:.4f}"


def expand(rows: list[dict[str, str]], fieldnames: list[str]) -> list[dict[str, str]]:
    if not rows:
        return rows
    # Re-running the utility is idempotent: generated rows are never used as
    # seed data for another expansion.
    rows = [row for row in rows if row.get("DATA_SCOPE") != "LOCAL_DEMO_EXPANDED"]
    identifier = record_identifier(fieldnames)
    expanded = list(rows)
    sequence = 1
    while len(expanded) < MINIMUM_ROWS:
        source = rows[(sequence - 1) % len(rows)]
        row = deepcopy(source)
        suffix = f"-SIM-{sequence:02d}"
        if identifier and row.get(identifier):
            row[identifier] = f"{row[identifier]}{suffix}"
        elif "MATERIAL" in row and row["MATERIAL"]:
            # Master-data snapshots often have no technical record ID.
            row["MATERIAL"] = f"{row['MATERIAL']}{suffix}"
        elif "PRODUCT" in row and row["PRODUCT"]:
            row["PRODUCT"] = f"{row['PRODUCT']}{suffix}"
        # Expanded records must not contaminate calculations for the original
        # context (for example, the profitability tool expects one value per
        # scenario and forecast period).  Matching expanded context records are
        # created from business_context.csv using the same suffix.
        if "CONTEXT_ID" in row and row["CONTEXT_ID"]:
            row["CONTEXT_ID"] = f"{row['CONTEXT_ID']}{suffix}"
        vary_row(row, sequence)
        # A source provenance label makes synthetic demo rows unambiguous while
        # retaining the original scope columns consumed by the tools.
        if "DATA_SCOPE" in row:
            row["DATA_SCOPE"] = "LOCAL_DEMO_EXPANDED"
        expanded.append(row)
        sequence += 1
    return expanded


def main() -> None:
    canonical = DATA_DIRECTORIES[0]
    for path in sorted(canonical.glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            rows = expand(list(reader), fieldnames)
        for directory in DATA_DIRECTORIES:
            output = directory / path.name
            with output.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)


if __name__ == "__main__":
    main()
