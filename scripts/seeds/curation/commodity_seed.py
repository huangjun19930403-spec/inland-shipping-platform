"""Read-only coverage checks for curated commodity production seed data."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
COMMODITY_SEED_DIR = PROJECT_ROOT / "scripts" / "seed_data" / "commodity"
DEFAULT_STANDARDS_FILE = COMMODITY_SEED_DIR / "commodity_standards.json"

EXCLUDED_TMS_COMMODITY_NAMES = {
    "测试货品001--其他",
    "测试货品002--杂货",
    "吨包",
    "吨袋",
}


@dataclass(frozen=True)
class CommodityCoverageReport:
    input_path: Path
    row_count: int
    unique_count: int
    covered_count: int
    excluded_count: int
    unmatched_names: list[str]
    duplicate_terms: dict[str, list[str]]
    type_distribution: dict[str, int]

    @property
    def ok(self) -> bool:
        return not self.unmatched_names and not self.duplicate_terms


def normalize_commodity_name(value: str | None) -> str:
    return "".join(str(value or "").strip().lower().split())


def load_seed_standards(path: Path = DEFAULT_STANDARDS_FILE) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_tms_commodity_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _standard_terms(row: dict[str, Any]) -> list[str]:
    values = [row.get("name"), row.get("short_name")]
    for alias in row.get("aliases") or []:
        if isinstance(alias, dict):
            values.append(alias.get("alias_name"))
        else:
            values.append(alias)
    return [str(value).strip() for value in values if str(value or "").strip()]


def build_commodity_term_index(
    standards: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    owners: dict[str, str] = {}
    owner_sets: dict[str, set[str]] = defaultdict(set)
    for row in standards:
        code = str(row.get("code") or "").strip()
        if not code:
            continue
        for term in _standard_terms(row):
            normalized = normalize_commodity_name(term)
            if not normalized:
                continue
            owners.setdefault(normalized, code)
            owner_sets[normalized].add(code)

    duplicate_terms = {
        term: sorted(codes) for term, codes in owner_sets.items() if len(codes) > 1
    }
    return owners, duplicate_terms


def build_coverage_report(
    input_path: Path,
    *,
    standards_path: Path = DEFAULT_STANDARDS_FILE,
) -> CommodityCoverageReport:
    rows = load_tms_commodity_rows(input_path)
    names = sorted({str(row.get("name") or "").strip() for row in rows if row.get("name")})
    type_distribution = Counter(str(row.get("type") or "").strip() for row in rows)
    term_index, duplicate_terms = build_commodity_term_index(
        load_seed_standards(standards_path)
    )
    unmatched = [
        name
        for name in names
        if name not in EXCLUDED_TMS_COMMODITY_NAMES
        and normalize_commodity_name(name) not in term_index
    ]
    covered_count = sum(
        1
        for name in names
        if name not in EXCLUDED_TMS_COMMODITY_NAMES
        and normalize_commodity_name(name) in term_index
    )
    excluded_count = sum(1 for name in names if name in EXCLUDED_TMS_COMMODITY_NAMES)
    return CommodityCoverageReport(
        input_path=input_path,
        row_count=len(rows),
        unique_count=len(names),
        covered_count=covered_count,
        excluded_count=excluded_count,
        unmatched_names=unmatched,
        duplicate_terms=duplicate_terms,
        type_distribution=dict(sorted(type_distribution.items())),
    )


def _print_report(report: CommodityCoverageReport) -> None:
    print(f"input={report.input_path}")
    print(f"rows={report.row_count}")
    print(f"unique_names={report.unique_count}")
    print(f"covered_names={report.covered_count}")
    print(f"excluded_names={report.excluded_count}")
    print(f"type_distribution={report.type_distribution}")
    print(f"unmatched_names={report.unmatched_names}")
    print(f"duplicate_terms={report.duplicate_terms}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate TMS commodity names against curated production seed data."
    )
    parser.add_argument("--input", required=True, type=Path, help="TMS commodity CSV path")
    parser.add_argument(
        "--standards",
        default=DEFAULT_STANDARDS_FILE,
        type=Path,
        help="Curated commodity standards JSON path",
    )
    args = parser.parse_args()

    report = build_coverage_report(args.input, standards_path=args.standards)
    _print_report(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
