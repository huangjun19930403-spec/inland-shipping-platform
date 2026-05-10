"""Redline checks for the vessel asset center cleanup batches."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "inland-shipping-platform"
FRONTEND_SRC = ROOT / "frontend" / "src"


def _iter_files(base: Path, suffixes: tuple[str, ...]) -> list[Path]:
    return [
        path
        for path in base.rglob("*")
        if path.is_file()
        and path.suffix in suffixes
        and "node_modules" not in path.parts
        and "dist" not in path.parts
    ]


def _contains(pattern: str, files: list[Path], *, regex: bool = False) -> list[Path]:
    matches: list[Path] = []
    compiled = re.compile(pattern) if regex else None
    for path in files:
        text = path.read_text(encoding="utf-8")
        found = bool(compiled.search(text)) if compiled else pattern in text
        if found:
            matches.append(path)
    return matches


def _get_route_side_effects(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    findings: list[str] = []
    blocks = re.split(r"\n(?=@router\.)", text)
    for block in blocks:
        first = block.splitlines()[0] if block.splitlines() else ""
        if not first.startswith("@router.get"):
            continue
        if "sync_tasks(" in block or "sync_tasks_command(" in block or ".commit(" in block:
            findings.append(first.strip())
    return findings


def _migration_number(path: Path) -> int | None:
    match = re.match(r"(\d+)_", path.name)
    return int(match.group(1)) if match else None


def main() -> int:
    failures: list[str] = []
    frontend_files = _iter_files(FRONTEND_SRC, (".ts", ".vue"))
    backend_files = _iter_files(BACKEND / "app" / "modules" / "vessel", (".py",))
    vessel_root = BACKEND / "app" / "modules" / "vessel"
    ledger = BACKEND / "docs" / "vessel_asset_center_issue_ledger.md"
    ledger_text = ledger.read_text(encoding="utf-8") if ledger.exists() else ""

    if (FRONTEND_SRC / "api" / "vesselLegacy.ts").exists():
        failures.append("frontend/src/api/vesselLegacy.ts must not exist")

    legacy_imports = _contains("vesselLegacy", frontend_files)
    if legacy_imports:
        failures.append("vesselLegacy references remain: " + ", ".join(str(path.relative_to(ROOT)) for path in legacy_imports))

    risk_guessing = _contains(r"risk_type_code\s*\.\s*includes", frontend_files, regex=True)
    if risk_guessing:
        failures.append("frontend risk action guessing remains: " + ", ".join(str(path.relative_to(ROOT)) for path in risk_guessing))

    candidate_page = FRONTEND_SRC / "modules" / "vessel" / "pages" / "VesselCandidateAnalysisPage.vue"
    if candidate_page.exists():
        text = candidate_page.read_text(encoding="utf-8")
        if "page_size: 200" in text or "page_size: 50" in text:
            failures.append("candidate analysis page still uses fixed production selector page sizes")

    route_findings: list[str] = []
    for path in sorted((BACKEND / "app" / "modules" / "vessel" / "routers").glob("*.py")):
        if path.name == "__init__.py":
            continue
        route_findings.extend(f"{path.name}:{finding}" for finding in _get_route_side_effects(path))
    if route_findings:
        failures.append("GET routes contain write side effects: " + ", ".join(route_findings))

    dangerous_calls = []
    for path in backend_files:
        if path.name == "repository.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "replace_many_by_profile(" in text or "delete_person_certificate(" in text:
            dangerous_calls.append(path.relative_to(ROOT))
    if dangerous_calls:
        failures.append("production code calls physical replace/delete paths: " + ", ".join(map(str, dangerous_calls)))

    required_domain_dirs = {
        "asset",
        "certificate",
        "relation",
        "recognition",
        "quality",
        "compliance",
        "ais",
        "profile_card",
    }
    missing_domain_services = sorted(
        name
        for name in required_domain_dirs
        if not (vessel_root / name / "service.py").exists() or not (vessel_root / name / "methods.py").exists()
    )
    if missing_domain_services:
        failures.append("vessel domain service/method modules missing: " + ", ".join(missing_domain_services))

    aggregate_domain_services: list[Path] = []
    for name in required_domain_dirs:
        service_path = vessel_root / name / "service.py"
        if not service_path.exists():
            continue
        text = service_path.read_text(encoding="utf-8")
        if "shared.aggregate" in text or "VesselDomainService" in text:
            aggregate_domain_services.append(service_path.relative_to(ROOT))
    if aggregate_domain_services:
        failures.append(
            "vessel domain services must declare their own mixin dependencies instead of inheriting the full aggregate: "
            + ", ".join(map(str, aggregate_domain_services))
        )

    service_boundary_files = [
        path
        for path in backend_files
        if path.parent.name in required_domain_dirs or path.parent.name == "services"
    ]
    dynamic_service_patterns = {
        "__getattr__": "__getattr__ fallback",
        "_delegate(": "_delegate helper",
        "setattr(Vessel": "dynamic setattr method export",
        "getattr(self._facade": "facade getattr dispatch",
        "getattr(self._core": "core getattr dispatch",
    }
    for pattern, label in dynamic_service_patterns.items():
        findings = _contains(pattern, service_boundary_files)
        if findings:
            failures.append(
                f"vessel domain services must not use {label}: "
                + ", ".join(str(path.relative_to(ROOT)) for path in findings)
            )

    aggregate_service = vessel_root / "service.py"
    if aggregate_service.exists():
        text = aggregate_service.read_text(encoding="utf-8")
        if "class VesselService(VesselDomainService)" not in text:
            failures.append("app/modules/vessel/service.py must remain a compatibility aggregate over split domain services")
        if "async def " in text or "def __init__" in text:
            failures.append("app/modules/vessel/service.py must not grow implementation methods again")

    governance_service = BACKEND / "app" / "modules" / "vessel" / "governance_service.py"
    if governance_service.exists():
        text = governance_service.read_text(encoding="utf-8")
        if 'verified_status_code = "APPROVED"' in text or "verified_status_code = 'APPROVED'" in text:
            failures.append("governance tasks must not approve vessel evidence directly; use audit center bridge")

    migration_files = sorted((BACKEND / "alembic" / "versions").glob("*.py"))
    if [path.name for path in migration_files] != ["0001_platform_current_schema.py"]:
        failures.append(
            "Alembic must remain a single V3 current-state baseline: "
            + ", ".join(path.name for path in migration_files)
        )
    if migration_files:
        baseline_text = migration_files[0].read_text(encoding="utf-8")
        if not re.search(r"down_revision(?:\s*:[^=]+)?\s*=\s*None", baseline_text):
            failures.append("Alembic baseline must use down_revision = None")
        legacy_table_patterns = [
            "ship_profile",
            "ship_owner",
            "ship_operation",
            "ship_certificate",
            "ship_import_",
            "stat_ship_",
            "cargo_channel",
            "stat_cargo_",
        ]
        legacy_hits = sorted(pattern for pattern in legacy_table_patterns if pattern in baseline_text)
        if legacy_hits:
            failures.append("Alembic baseline contains legacy table references: " + ", ".join(legacy_hits))
        if migration_files[0].name not in ledger_text:
            failures.append("current Alembic baseline must be recorded in vessel issue ledger")

    if failures:
        for failure in failures:
            print(f"REDLINE: {failure}")
        return 1
    print("vessel redline checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
