"""Read-only metadata for the CSV snapshots used by the A2A tool registry."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


from .harness_profile import resource_path
from .local_tools import read_snapshot

_DATA_DIR = resource_path("snapshots")
_DATA_PRODUCT = "F&B Operations Reference Snapshot"
_DATASET_DESCRIPTIONS_EN = {
    "business_context": ("Business Context", "Demo entity identifiers and aliases used for Context resolution."),
    "operations_evidence": ("Operations Evidence", "Fictional role-scoped purchasing, inventory, equipment, readiness, and control records."),
    "product_cost_assumption": ("Product Costing", "Documented fictional price, volume, variable cost, FX, and inflation scenario inputs."),
    "approval_matrix": ("Finance Control", "Approval criteria and approver roles for purchasing and budget requests."),
    "equipment_master": ("Asset & Maintenance", "Equipment identifiers, locations, statuses, and core attributes."),
    "maintenance_work_order": ("Asset & Maintenance", "Maintenance request and work-order record statuses."),
    "equipment_bom": ("Asset & Maintenance", "BOM relationships for equipment assemblies and replacement parts."),
    "material_stock": ("Procurement & Supply", "Material inventory and available-quantity snapshots."),
    "purchase_requisition": ("Procurement & Supply", "Purchase requisition items, quantities, and statuses."),
    "purchase_quote": ("Procurement & Supply", "Supplier quotation and commercial-term snapshots."),
    "supplier_master": ("Procurement & Supply", "Supplier master data and qualification status."),
    "production_plan": ("Manufacturing Planning", "Production plans and material and line readiness by planning period."),
    "production_evidence": ("Manufacturing Execution", "Evidence records for production execution and line operations."),
    "quality_evidence": ("Quality Management", "Quality review, testing, and inspection evidence."),
    "quality_release_status": ("Quality Management", "Quality-release record status."),
    "opex_budget": ("Finance Control", "Operating-expense budget and cost-allocation snapshots."),
    "cost_center_master": ("Finance Control", "Cost-center master data and responsible organizations."),
    "erp_change_request": ("ERP & Master Data", "ERP change requests and readiness status."),
    "erp_data_mapping": ("ERP & Master Data", "ERP field mappings and validation prerequisites."),
    "ehs_evidence": ("EHS", "Safety, environmental, chemical, and work-permit review evidence."),
    "hr_workforce_evidence": ("Workforce", "Workforce, training, qualification, and attendance evidence."),
    "rnd_evidence": ("R&D", "Product, formulation-development, and scale-up evidence."),
    "process_evidence": ("Process Engineering", "Process conditions, yield, change, and validation evidence."),
}


def _view_name(name: str) -> str:
    return "Z_A2A_" + Path(name).stem.upper()


def _product_metadata(name: str) -> dict[str, str]:
    stem = Path(name).stem
    fallback = (
        "F&B Operations",
        f"Read-only operational snapshot for the {stem.replace('_', ' ')} business domain.",
    )
    domain, description = _DATASET_DESCRIPTIONS_EN.get(
        stem,
        fallback,
    )
    return {
        "product_name": _DATA_PRODUCT,
        "domain": domain,
        "description": description,
        "owner": domain,
        "refresh": "Demo static snapshot",
    }


def public_data_snapshots(*, language: str = "en") -> list[dict[str, Any]]:
    if not resource_path("snapshots").is_dir():
        raise RuntimeError(f"A2A CSV snapshot directory was not found: {_DATA_DIR}")
    snapshots: list[dict[str, Any]] = []
    for path in sorted(resource_path("snapshots").glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, [])
            row_count = len(read_snapshot(path.name))
        snapshots.append({
            "name": path.name,
            "view_name": _view_name(path.name),
            "rows": row_count,
            "columns": header,
            "mode": "read-only",
            "source": "Demo sample snapshots",
            **_product_metadata(path.name),
        })
    return snapshots


def public_data_snapshot(name: str, *, limit: int = 100, language: str = "en") -> dict[str, Any]:
    filename = Path(name).name
    if filename != name or not filename.endswith(".csv"):
        raise ValueError("Invalid CSV snapshot name.")
    path = resource_path("snapshots") / filename
    if not path.is_file():
        raise FileNotFoundError("CSV snapshot was not found.")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        rows = read_snapshot(filename)[:limit]
    return {
        "name": filename,
        "view_name": _view_name(filename),
        "columns": columns,
        "rows": rows,
        "limit": limit,
        "mode": "read-only",
        **_product_metadata(filename),
    }
