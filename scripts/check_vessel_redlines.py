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

    service_fallbacks = _contains("__getattr__", _iter_files(BACKEND / "app" / "modules" / "vessel" / "services", (".py",)))
    if service_fallbacks:
        failures.append("vessel domain services must expose explicit methods, no __getattr__ fallback: " + ", ".join(str(path.relative_to(ROOT)) for path in service_fallbacks))

    governance_service = BACKEND / "app" / "modules" / "vessel" / "governance_service.py"
    if governance_service.exists():
        text = governance_service.read_text(encoding="utf-8")
        if 'verified_status_code = "APPROVED"' in text or "verified_status_code = 'APPROVED'" in text:
            failures.append("governance tasks must not approve vessel evidence directly; use audit center bridge")

    migration_helper_pattern = re.compile(r"_has_table|_has_column|_add_column_if_missing|_create_index_if_missing")
    migration_findings = []
    untracked_migration_docs = []
    for path in sorted((BACKEND / "alembic" / "versions").glob("*.py")):
        number = _migration_number(path)
        if number is None or number < 36:
            continue
        text = path.read_text(encoding="utf-8")
        if migration_helper_pattern.search(text) and "MIGRATION_COMPATIBILITY_REASON:" not in text:
            migration_findings.append(path.relative_to(ROOT))
        if "vessel_" in text and path.name not in ledger_text:
            untracked_migration_docs.append(path.relative_to(ROOT))
    if migration_findings:
        failures.append("new patch-style migrations require MIGRATION_COMPATIBILITY_REASON comments: " + ", ".join(map(str, migration_findings)))
    if untracked_migration_docs:
        failures.append("new vessel migrations must be recorded in vessel issue ledger: " + ", ".join(map(str, untracked_migration_docs)))

    if failures:
        for failure in failures:
            print(f"REDLINE: {failure}")
        return 1
    print("vessel redline checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
