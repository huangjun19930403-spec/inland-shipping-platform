"""Curate production vessel seed data from TMS and high-value inland archives."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TMS_FILE = Path("/Users/hj/Downloads/船舶数据.csv")
DEFAULT_HIGH_VALUE_FILE = Path("/Users/hj/Downloads/高价值内河船舶档案.csv")
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "scripts" / "seed_data"
DEFAULT_ADMIN_REGION_FILE = (
    PROJECT_ROOT / "scripts" / "seed_data" / "admin_region" / "admin_region_raw.json"
)
DEFAULT_FREIGHT_FILE = PROJECT_ROOT / "scripts" / "seed_data" / "freight" / "tms_freights.json"
OUTPUT_FILE = Path("vessel") / "production_vessels.json"

CURATED_DATE = date(2026, 5, 15)
CURATED_AT = "2026-05-15T00:00:00"

PRODUCTION_SOURCE_TMS = "TMS"
PRODUCTION_SOURCE_HIGH_VALUE = "HIGH_VALUE_INLAND"
PRODUCTION_SOURCE_MERGED = "TMS_HIGH_VALUE"

VALID_SHIP_TYPE_CODES = {
    "DRY_BULK",
    "GENERAL_CARGO",
    "SELF_UNLOADING_SAND",
    "BULK_CEMENT",
    "CONTAINER",
    "BULK_CONTAINER",
    "MULTI_PURPOSE",
    "OIL_TANKER",
    "CHEMICAL_TANKER",
    "ENGINEERING",
    "TUG",
    "OTHER",
}

NUMERIC_LIMITS: dict[str, tuple[float, float]] = {
    "deadweight_ton": (1, 50000),
    "reference_load_ton": (1, 50000),
    "total_tonnage": (1, 100000),
    "net_tonnage": (1, 100000),
    "length_m": (5, 300),
    "width_m": (1.5, 60),
    "depth_m": (0.5, 25),
    "design_draft_m": (0.1, 20),
    "max_draft_m": (0.1, 20),
    "design_speed_kn": (0.1, 40),
    "engine_power_kw": (1, 10000),
}

SHIP_TYPE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("CHEMICAL_TANKER", ("化学品", "化学")),
    ("OIL_TANKER", ("油船", "油品", "成品油", "液货")),
    ("BULK_CEMENT", ("散装水泥", "水泥")),
    ("SELF_UNLOADING_SAND", ("自卸砂", "自卸")),
    ("BULK_CONTAINER", ("集散两用", "散改集")),
    ("CONTAINER", ("集装箱",)),
    ("MULTI_PURPOSE", ("多用途", "杂货", "件杂")),
    ("ENGINEERING", ("工程", "挖泥", "起重", "打桩", "疏浚")),
    ("TUG", ("拖", "推")),
    ("DRY_BULK", ("散货", "干散", "干货")),
)

TMS_TYPE_CODE_MAP = {
    "1": "GENERAL_CARGO",
    "2": "CONTAINER",
    "0": "OTHER",
}


def _norm(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.upper() == "NULL":
        return ""
    return text


def _compact_name(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def _contains_cjk(value: Any) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(value or "")))


def _looks_non_chinese_identifier(value: str) -> bool:
    text = str(value or "").strip()
    if not text or _contains_cjk(text):
        return False
    compact = re.sub(r"[\s._\-/]+", "", text)
    return bool(compact) and bool(re.fullmatch(r"[A-Za-z0-9]+", compact))


def _is_placeholder(value: str) -> bool:
    text = value.strip()
    if not text:
        return True
    if text in {"-", "--", "---", "/", "_", "__", "—", "——", "无", "未知"}:
        return True
    return bool(re.fullmatch(r"[-_/—\s]+", text))


def _digits(value: Any) -> str:
    return "".join(ch for ch in _norm(value) if ch.isdigit())


def _valid_mmsi(value: Any) -> str:
    text = _digits(value)
    return text if len(text) == 9 else ""


def _number(value: Any) -> float | None:
    text = _norm(value)
    if not text:
        return None
    try:
        number = float(text.replace(",", ""))
    except ValueError:
        return None
    return number if number == number else None


def _clean_number(value: Any, field_name: str, report: dict[str, Any]) -> float | None:
    number = _number(value)
    if number is None:
        return None
    lower, upper = NUMERIC_LIMITS[field_name]
    if lower <= number <= upper:
        return round(number, 2)
    report["invalid_numeric_values"][field_name] += 1
    return None


def _clean_int(value: Any, *, lower: int, upper: int, field_name: str, report: dict[str, Any]) -> int | None:
    number = _number(value)
    if number is None:
        return None
    integer = int(number)
    if lower <= integer <= upper:
        return integer
    report["invalid_numeric_values"][field_name] += 1
    return None


def _first_text(rows: list[dict[str, Any]], keys: list[str]) -> str | None:
    for row in rows:
        for key in keys:
            value = _norm(row.get(key))
            if value:
                return value
    return None


def _unique_texts(rows: list[dict[str, Any]], keys: list[str]) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for row in rows:
        for key in keys:
            value = _norm(row.get(key))
            normalized = _compact_name(value)
            if value and not _is_placeholder(value) and normalized not in seen:
                seen.add(normalized)
                values.append(value)
    return values


def _source_trace(prefix: str, values: list[str]) -> str | None:
    values = [value for value in values if value]
    if not values:
        return None
    return f"{prefix}:{','.join(values[:8])}"[:128]


def _parse_tms_date(value: Any) -> date | None:
    text = _norm(value)
    if not text:
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _parse_high_value_date(value: Any) -> date | None:
    text = _norm(value)
    if not text:
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _building_year(tms_rows: list[dict[str, Any]], high_value_rows: list[dict[str, Any]]) -> int | None:
    for row in high_value_rows:
        year = _clean_year(row.get("建造年份"))
        if year:
            return year
        parsed = _parse_high_value_date(row.get("建造日期"))
        if parsed and _clean_year(parsed.year):
            return parsed.year
    for row in tms_rows:
        parsed = _parse_tms_date(row.get("build_date"))
        if parsed and _clean_year(parsed.year):
            return parsed.year
    return None


def _clean_year(value: Any) -> int | None:
    number = _number(value)
    if number is None:
        return None
    year = int(number)
    return year if 1900 <= year <= CURATED_DATE.year else None


def _ship_age(building_year: int | None) -> int | None:
    if not building_year:
        return None
    return max(0, CURATED_DATE.year - building_year)


def _mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = _digits(phone)
    if len(digits) < 7:
        return "***"
    return f"{digits[:3]}****{digits[-4:]}"


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> Any:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _strip_empty(value: Any) -> Any:
    if isinstance(value, dict):
        stripped = {
            key: _strip_empty(item)
            for key, item in value.items()
            if item not in (None, "", [], {})
        }
        return {key: item for key, item in stripped.items() if item not in (None, "", [], {})}
    if isinstance(value, list):
        return [_strip_empty(item) for item in value if item not in (None, "", [], {})]
    return value


def _admin_name_keys(name: str) -> set[str]:
    keys = {name}
    for suffix in ("市", "地区", "自治州", "盟", "县", "区"):
        if name.endswith(suffix):
            keys.add(name[: -len(suffix)])
    return {key for key in keys if key}


def build_admin_city_index(admin_rows: list[dict[str, Any]]) -> dict[str, str]:
    """Map city and district names to a single city code when unambiguous."""

    candidates: dict[str, set[str]] = defaultdict(set)
    for row in admin_rows:
        code = str(row.get("adcode") or row.get("code") or "")
        level = str(row.get("level") or "").lower()
        name = _norm(row.get("name"))
        short_name = _norm(row.get("short_name"))
        if not code or not name:
            continue

        level_value: int | None = None
        if level in {"city"}:
            level_value = 2
        elif level in {"district", "county"}:
            level_value = 3
        else:
            try:
                level_value = int(level)
            except ValueError:
                level_value = None

        city_code = ""
        if level_value == 2:
            city_code = code
        elif level_value == 3:
            city_code = str(row.get("city_code") or row.get("parent_code") or "")
        if not city_code:
            continue

        for value in (name, short_name):
            for key in _admin_name_keys(value):
                candidates[key].add(city_code)

    return {key: next(iter(values)) for key, values in candidates.items() if len(values) == 1}


def _registry_city_code(
    high_value_rows: list[dict[str, Any]],
    admin_city_index: dict[str, str],
) -> tuple[str | None, str | None, str | None]:
    for row in high_value_rows:
        for key in ("船籍港", "原始注册地"):
            raw = _norm(row.get(key))
            if not raw or set(raw) <= {"-", "_", "/", "—"}:
                continue
            for candidate in _admin_name_keys(raw):
                code = admin_city_index.get(candidate)
                if code:
                    return code, raw, key
    raw_home_port = _first_text(high_value_rows, ["船籍港"])
    return None, raw_home_port, None


def _infer_ship_type(tms_rows: list[dict[str, Any]], high_value_rows: list[dict[str, Any]]) -> str:
    for text in _unique_texts(high_value_rows, ["船舶类型"]):
        for code, patterns in SHIP_TYPE_PATTERNS:
            if any(pattern in text for pattern in patterns):
                return code

    tms_type = _first_text(tms_rows, ["ship_type"])
    if tms_type in TMS_TYPE_CODE_MAP:
        mapped = TMS_TYPE_CODE_MAP[tms_type]
        if mapped != "OTHER":
            return mapped

    combined_name = " ".join(_unique_texts(tms_rows + high_value_rows, ["name", "船舶中文名"]))
    for code, patterns in SHIP_TYPE_PATTERNS:
        if any(pattern in combined_name for pattern in patterns):
            return code
    return "OTHER"


def _pick_name(
    mmsi: str,
    tms_rows: list[dict[str, Any]],
    high_value_rows: list[dict[str, Any]],
    freight_ship_names: set[str],
) -> str | None:
    tms_names = _unique_texts(tms_rows, ["name"])
    high_value_names = _unique_texts(high_value_rows, ["船舶中文名", "原始中文名"])
    freight_normalized = {_compact_name(name) for name in freight_ship_names}

    for name in tms_names:
        if _compact_name(name) in freight_normalized:
            return name
    if tms_names:
        counts = Counter(_norm(row.get("name")) for row in tms_rows if _norm(row.get("name")))
        tms_name = sorted(tms_names, key=lambda item: (-counts[item], item))[0]
        chinese_high_value_names = [name for name in high_value_names if _contains_cjk(name)]
        if chinese_high_value_names and _looks_non_chinese_identifier(tms_name):
            return chinese_high_value_names[0]
        return tms_name
    if high_value_names:
        return high_value_names[0]
    return None


def _pick_number(
    source_rows: list[tuple[str, dict[str, Any], str]],
    field_name: str,
    report: dict[str, Any],
) -> float | None:
    for _source, row, key in source_rows:
        value = _clean_number(row.get(key), field_name, report)
        if value is not None:
            return value
    return None


def _build_capacity(
    tms_rows: list[dict[str, Any]],
    high_value_rows: list[dict[str, Any]],
    report: dict[str, Any],
) -> dict[str, Any]:
    hv = [(PRODUCTION_SOURCE_HIGH_VALUE, row, "") for row in high_value_rows]
    tms = [(PRODUCTION_SOURCE_TMS, row, "") for row in tms_rows]

    def rows_with_key(rows: list[tuple[str, dict[str, Any], str]], key: str) -> list[tuple[str, dict[str, Any], str]]:
        return [(source, row, key) for source, row, _ in rows]

    return {
        "deadweight_ton": _pick_number(
            rows_with_key(hv, "载重吨(t)") + rows_with_key(tms, "deadweight_tonnage"),
            "deadweight_ton",
            report,
        ),
        "reference_load_ton": _pick_number(
            rows_with_key(hv, "载重吨(t)") + rows_with_key(tms, "deadweight_tonnage"),
            "reference_load_ton",
            report,
        ),
        "total_tonnage": _pick_number(
            rows_with_key(hv, "总吨") + rows_with_key(tms, "total_tonnage"),
            "total_tonnage",
            report,
        ),
        "net_tonnage": _pick_number(
            rows_with_key(hv, "净吨") + rows_with_key(tms, "net_tonnage"),
            "net_tonnage",
            report,
        ),
        "length_m": _pick_number(
            rows_with_key(hv, "船长(m)") + rows_with_key(tms, "length"),
            "length_m",
            report,
        ),
        "width_m": _pick_number(
            rows_with_key(hv, "船宽(m)") + rows_with_key(tms, "beam"),
            "width_m",
            report,
        ),
        "depth_m": _pick_number(
            rows_with_key(hv, "型深(m)") + rows_with_key(tms, "depth"),
            "depth_m",
            report,
        ),
        "design_draft_m": _pick_number(
            rows_with_key(hv, "吃水(m)") + rows_with_key(tms, "draft_full"),
            "design_draft_m",
            report,
        ),
        "max_draft_m": _pick_number(
            rows_with_key(hv, "满载吃水(m)") + rows_with_key(tms, "draft_full"),
            "max_draft_m",
            report,
        ),
        "design_speed_kn": _pick_number(
            rows_with_key(hv, "航速(节)"),
            "design_speed_kn",
            report,
        ),
        "hold_count": None,
        "teu_capacity": _clean_int(
            _first_text(high_value_rows, ["箱位数"]) or _first_text(tms_rows, ["container_capacity"]),
            lower=0,
            upper=5000,
            field_name="teu_capacity",
            report=report,
        ),
    }


def _build_info(
    tms_rows: list[dict[str, Any]],
    high_value_rows: list[dict[str, Any]],
    report: dict[str, Any],
) -> dict[str, Any]:
    building_year = _building_year(tms_rows, high_value_rows)
    return {
        "building_year": building_year,
        "builder_name": _first_text(high_value_rows, ["造船厂", "重建造船厂"])
        or _first_text(tms_rows, ["shipyard", "manufacturer"]),
        "build_place": _first_text(high_value_rows, ["建造地"]),
        "hull_material_code": _hull_material_code(
            _first_text(high_value_rows, ["船体材质"]) or _first_text(tms_rows, ["hull_material"])
        ),
        "engine_power_kw": _pick_number(
            [(PRODUCTION_SOURCE_HIGH_VALUE, row, "主机功率(kW)") for row in high_value_rows]
            + [(PRODUCTION_SOURCE_TMS, row, "power") for row in tms_rows],
            "engine_power_kw",
            report,
        ),
    }


def _hull_material_code(value: str | None) -> str | None:
    if not value:
        return None
    if "钢" in value:
        return "STEEL"
    return value[:64]


def _build_contacts(tms_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contacts: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in tms_rows:
        name = _norm(row.get("contact_name")) or "TMS联系人"
        phone = _norm(row.get("contact_phone")) or None
        wechat = _norm(row.get("contact_wechat")) or None
        if not phone and not wechat and name == "TMS联系人":
            continue
        key = (name, phone or "", wechat or "")
        if key in seen:
            continue
        seen.add(key)
        contacts.append(
            {
                "contact_scope_code": "GENERAL",
                "contact_name": name,
                "contact_role_code": "BUSINESS_CONTACT",
                "mobile_phone": phone,
                "wechat": wechat,
                "is_primary": len(contacts) == 0,
                "is_available": True,
                "verified_status_code": "UNVERIFIED",
                "source_type_code": PRODUCTION_SOURCE_TMS,
                "source_trace_id": _source_trace("TMS_SHIP_ID", [_norm(row.get("ship_id"))]),
                "remark": "TMS production vessel contact.",
            }
        )
    return contacts


def _completeness(row: dict[str, Any]) -> tuple[float, int]:
    keys = [
        row.get("mmsi"),
        row.get("ship_name"),
        row.get("ship_type_code"),
        row.get("registry_city_code"),
        (row.get("capacity") or {}).get("deadweight_ton"),
        (row.get("capacity") or {}).get("length_m"),
        (row.get("capacity") or {}).get("width_m"),
        (row.get("build") or {}).get("building_year"),
        row.get("contacts"),
    ]
    missing = sum(1 for value in keys if value in (None, "", []))
    return round((len(keys) - missing) / len(keys) * 100, 2), missing


def _summary(
    row: dict[str, Any],
    *,
    conflict_count: int,
    uncertainty_notes: list[str],
) -> dict[str, Any]:
    completeness, missing = _completeness(row)
    capacity = row.get("capacity") or {}
    build = row.get("build") or {}
    contacts = row.get("contacts") or []
    primary_contact = contacts[0] if contacts else {}
    data_quality_score = max(0, completeness - conflict_count * 5)
    if data_quality_score >= 85:
        quality_level = "HIGH"
    elif data_quality_score >= 60:
        quality_level = "MEDIUM"
    else:
        quality_level = "LOW"

    return {
        "ship_name": row.get("ship_name"),
        "current_mmsi": row.get("mmsi"),
        "ship_type_code": row.get("ship_type_code"),
        "ship_type_name": row.get("ship_type_name"),
        "deadweight_ton": capacity.get("deadweight_ton"),
        "length_m": capacity.get("length_m"),
        "width_m": capacity.get("width_m"),
        "design_draft_m": capacity.get("design_draft_m"),
        "building_year": build.get("building_year"),
        "ship_age": _ship_age(build.get("building_year")),
        "primary_owner_name": None,
        "primary_operator_name": None,
        "primary_contact_name": primary_contact.get("contact_name"),
        "primary_contact_phone_masked": _mask_phone(primary_contact.get("mobile_phone")),
        "contact_available": bool(contacts),
        "profile_completeness_rate": completeness,
        "data_quality_score": round(data_quality_score, 2),
        "data_quality_level": quality_level,
        "identity_confidence_level": "HIGH" if row.get("source_type_code") == PRODUCTION_SOURCE_MERGED else "MEDIUM",
        "contact_trust_level": "MEDIUM" if contacts else "UNKNOWN",
        "subject_consistency_level": "UNKNOWN",
        "quality_issue_count": missing + conflict_count,
        "missing_field_count": missing,
        "conflict_count": conflict_count,
        "risk_level": "UNKNOWN",
        "risk_evidence_summary_json": [],
        "certificate_missing_count": 0,
        "certificate_expiring_count": 0,
        "certificate_expired_count": 0,
        "latest_position_time": None,
        "latest_city_code": None,
        "latest_city_name": None,
        "ais_freshness_level": "UNKNOWN",
        "ais_unavailable_reason": "生产船舶 seed 不生成模拟 AIS 位置。",
        "analysis_sample_tags_json": [],
        "analysis_sample_tags_key": None,
        "data_sources_json": row.get("data_sources"),
        "uncertainty_notes_json": uncertainty_notes,
        "source_layer": "PROFILE_SUMMARY",
        "coverage_rate": completeness,
        "summary_status_code": "READY",
        "summary_version": "ROUND_05_V1",
        "refreshed_at": CURATED_AT,
        "source_updated_at": None,
        "last_verified_at": None,
    }


def _freight_ship_names(path: Path) -> set[str]:
    payload = _read_json(path)
    if isinstance(payload, dict):
        rows = payload.get("freights") or payload.get("data") or []
    else:
        rows = payload if isinstance(payload, list) else []
    return {
        _norm(row.get("normalized_ship_name") or row.get("source_ship_name"))
        for row in rows
        if isinstance(row, dict) and _norm(row.get("normalized_ship_name") or row.get("source_ship_name"))
    }


def _group_sources(
    tms_rows: list[dict[str, Any]],
    high_value_rows: list[dict[str, Any]],
    report: dict[str, Any],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"tms": [], "high_value": []})

    for row in tms_rows:
        mmsi = _valid_mmsi(row.get("mmsi"))
        ais_code = _valid_mmsi(row.get("ais_code"))
        if mmsi and ais_code and mmsi != ais_code:
            report["excluded"]["tms_mmsi_ais_conflict"] += 1
            continue
        canonical = mmsi or ais_code
        if not canonical:
            report["excluded"]["tms_invalid_mmsi"] += 1
            continue
        grouped[canonical]["tms"].append(row)

    for row in high_value_rows:
        mmsi = _valid_mmsi(row.get("MMSI(AIS通信码)"))
        if not mmsi:
            report["excluded"]["high_value_invalid_mmsi"] += 1
            continue
        grouped[mmsi]["high_value"].append(row)

    return grouped


def _source_type(tms_rows: list[dict[str, Any]], high_value_rows: list[dict[str, Any]]) -> str:
    if tms_rows and high_value_rows:
        return PRODUCTION_SOURCE_MERGED
    if tms_rows:
        return PRODUCTION_SOURCE_TMS
    return PRODUCTION_SOURCE_HIGH_VALUE


def _data_sources(tms_rows: list[dict[str, Any]], high_value_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    if tms_rows:
        sources.append(
            {
                "source_type_code": PRODUCTION_SOURCE_TMS,
                "record_count": len(tms_rows),
                "source_trace_ids": _unique_texts(tms_rows, ["ship_id"])[:20],
            }
        )
    if high_value_rows:
        sources.append(
            {
                "source_type_code": PRODUCTION_SOURCE_HIGH_VALUE,
                "record_count": len(high_value_rows),
                "source_trace_ids": _unique_texts(high_value_rows, ["平台唯一ID(aisId)"])[:20],
            }
        )
    return sources


def _extra_identifiers(
    tms_rows: list[dict[str, Any]],
    high_value_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    identifiers: list[dict[str, Any]] = []

    for value in _unique_texts(tms_rows, ["ship_code"]):
        identifiers.append(
            {
                "identifier_type_code": "TMS_SHIP_CODE",
                "identifier_value": value,
                "source_type_code": PRODUCTION_SOURCE_TMS,
                "source_trace_id": _source_trace("TMS_SHIP_ID", _unique_texts(tms_rows, ["ship_id"])),
                "confidence_score": 90,
            }
        )
    for key, identifier_type in (("IMO号", "IMO"), ("呼号", "CALL_SIGN")):
        for value in _unique_texts(high_value_rows, [key]):
            if identifier_type == "IMO" and not re.fullmatch(r"\d{7}", value):
                continue
            if identifier_type == "CALL_SIGN" and len(value) < 2:
                continue
            identifiers.append(
                {
                    "identifier_type_code": identifier_type,
                    "identifier_value": value,
                    "source_type_code": PRODUCTION_SOURCE_HIGH_VALUE,
                    "source_trace_id": _source_trace(
                        "HIGH_VALUE_AIS_ID",
                        _unique_texts(high_value_rows, ["平台唯一ID(aisId)"]),
                    ),
                    "confidence_score": 90,
                }
            )
    return identifiers


def _name_history(
    ship_name: str,
    tms_rows: list[dict[str, Any]],
    high_value_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    names: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source, rows, keys in (
        (PRODUCTION_SOURCE_TMS, tms_rows, ["name"]),
        (PRODUCTION_SOURCE_HIGH_VALUE, high_value_rows, ["船舶中文名", "原始中文名"]),
    ):
        for name in _unique_texts(rows, keys):
            key = _compact_name(name)
            if key in seen:
                continue
            seen.add(key)
            names.append(
                {
                    "ship_name": name,
                    "source_type_code": source,
                    "is_current": _compact_name(ship_name) == key,
                }
            )
    return names


def _registration(
    high_value_rows: list[dict[str, Any]],
    *,
    registry_city_code: str | None,
    home_port_name: str | None,
) -> dict[str, Any]:
    nationality = _first_text(high_value_rows, ["国籍"])
    province = _first_text(high_value_rows, ["所属省份"])
    inspection_org = _first_text(high_value_rows, ["机构名称"])
    registration = {
        "registry_city_code": registry_city_code,
        "ship_registry_no": None,
        "home_port_code": registry_city_code,
        "home_port_name": home_port_name,
        "flag_code": "CN" if nationality == "中国" else None,
        "mmsi_issuing_authority": None,
        "inspection_org": inspection_org,
    }
    if province:
        registration["source_province_name"] = province
    return registration


def curate_vessels(
    tms_rows: list[dict[str, Any]],
    high_value_rows: list[dict[str, Any]],
    *,
    admin_rows: list[dict[str, Any]],
    freight_ship_names: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    report: dict[str, Any] = {
        "input": {
            "tms_rows": len(tms_rows),
            "high_value_rows": len(high_value_rows),
        },
        "excluded": Counter(),
        "invalid_numeric_values": Counter(),
        "duplicate_mmsi": {},
        "source_distribution": Counter(),
        "ship_type_distribution": Counter(),
        "registry_city_matched": 0,
        "registry_city_unmatched": 0,
        "freight_ship_names": len(freight_ship_names),
        "freight_ship_names_matched": 0,
        "freight_ship_names_unmatched_samples": [],
    }
    grouped = _group_sources(tms_rows, high_value_rows, report)
    admin_city_index = build_admin_city_index(admin_rows)
    freight_name_normalized = {_compact_name(name) for name in freight_ship_names}
    vessel_name_normalized: set[str] = set()
    vessels: list[dict[str, Any]] = []

    report["duplicate_mmsi"] = {
        "tms_values": sum(1 for value in grouped.values() if len(value["tms"]) > 1),
        "high_value_values": sum(1 for value in grouped.values() if len(value["high_value"]) > 1),
    }

    for mmsi in sorted(grouped):
        tms_bucket = grouped[mmsi]["tms"]
        high_value_bucket = grouped[mmsi]["high_value"]
        source_type_code = _source_type(tms_bucket, high_value_bucket)
        ship_name = _pick_name(mmsi, tms_bucket, high_value_bucket, freight_ship_names)
        if not ship_name:
            report["excluded"]["missing_ship_name"] += 1
            continue

        registry_city_code, home_port_name, _registry_source = _registry_city_code(
            high_value_bucket, admin_city_index
        )
        if registry_city_code:
            report["registry_city_matched"] += 1
        else:
            report["registry_city_unmatched"] += 1

        ship_type_code = _infer_ship_type(tms_bucket, high_value_bucket)
        if ship_type_code not in VALID_SHIP_TYPE_CODES:
            ship_type_code = "OTHER"

        conflict_count = 0
        uncertainty_notes: list[str] = []
        all_names = _unique_texts(tms_bucket + high_value_bucket, ["name", "船舶中文名", "原始中文名"])
        if len({_compact_name(name) for name in all_names}) > 1:
            conflict_count += 1
            uncertainty_notes.append("同一 MMSI 存在多个船名，已保留名称历史。")
        if not registry_city_code and home_port_name:
            uncertainty_notes.append("船籍港未唯一匹配行政区划，仅保留原始船籍港名称。")

        capacity = _build_capacity(tms_bucket, high_value_bucket, report)
        build = _build_info(tms_bucket, high_value_bucket, report)
        contacts = _build_contacts(tms_bucket)
        data_sources = _data_sources(tms_bucket, high_value_bucket)
        name_history = _name_history(ship_name, tms_bucket, high_value_bucket)
        row = {
            "identity_code": f"VI-MMSI-{mmsi}",
            "profile_code": f"VP-MMSI-{mmsi}",
            "mmsi": mmsi,
            "ship_name": ship_name,
            "ship_name_en": _first_text(tms_bucket, ["english_name"])
            or _first_text(high_value_bucket, ["船舶英文名", "原始英文名"]),
            "ship_type_code": ship_type_code,
            "ship_type_name": _first_text(high_value_bucket, ["船舶类型"]),
            "registry_city_code": registry_city_code,
            "home_port_name": home_port_name,
            "source_type_code": source_type_code,
            "names": name_history if len(name_history) > 1 else [],
            "extra_identifiers": _extra_identifiers(tms_bucket, high_value_bucket),
            "registration": _registration(
                high_value_bucket,
                registry_city_code=registry_city_code,
                home_port_name=home_port_name,
            ),
            "capacity": capacity,
            "build": build,
            "contacts": contacts,
        }
        if conflict_count:
            row["conflict_count"] = conflict_count
        if uncertainty_notes:
            row["uncertainty_notes"] = uncertainty_notes
        vessels.append(_strip_empty(row))
        report["source_distribution"][source_type_code] += 1
        report["ship_type_distribution"][ship_type_code] += 1
        vessel_name_normalized.update(_compact_name(name) for name in all_names)

    matched_freight_names = freight_name_normalized & vessel_name_normalized
    report["freight_ship_names_matched"] = len(matched_freight_names)
    report["freight_ship_names_unmatched_samples"] = sorted(
        name for name in freight_ship_names if _compact_name(name) not in matched_freight_names
    )[:20]
    report["output"] = {"production_vessels": len(vessels)}
    report["excluded"] = dict(report["excluded"])
    report["invalid_numeric_values"] = dict(report["invalid_numeric_values"])
    report["source_distribution"] = dict(report["source_distribution"])
    report["ship_type_distribution"] = dict(report["ship_type_distribution"])
    return vessels, report


def validate_curated_vessels(vessels: list[dict[str, Any]]) -> None:
    mmsis: set[str] = set()
    identity_codes: set[str] = set()
    profile_codes: set[str] = set()
    for row in vessels:
        mmsi = str(row.get("mmsi") or "")
        if not re.fullmatch(r"\d{9}", mmsi):
            raise ValueError(f"invalid MMSI in curated vessel: {mmsi!r}")
        if mmsi in mmsis:
            raise ValueError(f"duplicate MMSI in curated vessel: {mmsi}")
        mmsis.add(mmsi)
        identity_code = str(row.get("identity_code") or "")
        profile_code = str(row.get("profile_code") or "")
        if not identity_code or len(identity_code) > 32:
            raise ValueError(f"invalid identity_code: {identity_code!r}")
        if not profile_code or len(profile_code) > 32:
            raise ValueError(f"invalid profile_code: {profile_code!r}")
        if identity_code in identity_codes:
            raise ValueError(f"duplicate identity_code: {identity_code}")
        if profile_code in profile_codes:
            raise ValueError(f"duplicate profile_code: {profile_code}")
        identity_codes.add(identity_code)
        profile_codes.add(profile_code)
        ship_type_code = row.get("ship_type_code")
        if ship_type_code not in VALID_SHIP_TYPE_CODES:
            raise ValueError(f"unknown ship_type_code: {ship_type_code!r}")
        if row.get("source_type_code") not in {
            PRODUCTION_SOURCE_TMS,
            PRODUCTION_SOURCE_HIGH_VALUE,
            PRODUCTION_SOURCE_MERGED,
        }:
            raise ValueError(f"unknown source_type_code: {row.get('source_type_code')!r}")
        text = json.dumps(row, ensure_ascii=False)
        for banned in ("LOCAL_SAMPLE", "SEED_AIS_CURRENT", "seed 模拟", "候选分析样例"):
            if banned in text:
                raise ValueError(f"production vessel seed contains banned token: {banned}")


def write_curated(vessels: list[dict[str, Any]], output_root: Path) -> Path:
    output_path = output_root / OUTPUT_FILE
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(vessels, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    return output_path


def _json_default(value: Any) -> Any:
    if isinstance(value, Counter):
        return dict(value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tms-vessels", type=Path, default=DEFAULT_TMS_FILE)
    parser.add_argument("--high-value-vessels", type=Path, default=DEFAULT_HIGH_VALUE_FILE)
    parser.add_argument("--admin-regions", type=Path, default=DEFAULT_ADMIN_REGION_FILE)
    parser.add_argument("--freights", type=Path, default=DEFAULT_FREIGHT_FILE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--write-curated", action="store_true")
    args = parser.parse_args()

    tms_rows = _read_csv(args.tms_vessels)
    high_value_rows = _read_csv(args.high_value_vessels)
    admin_rows_payload = _read_json(args.admin_regions)
    admin_rows = admin_rows_payload if isinstance(admin_rows_payload, list) else admin_rows_payload.get("regions", [])
    freight_ship_names = _freight_ship_names(args.freights)
    vessels, report = curate_vessels(
        tms_rows,
        high_value_rows,
        admin_rows=admin_rows,
        freight_ship_names=freight_ship_names,
    )
    validate_curated_vessels(vessels)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    if args.write_curated:
        output_path = write_curated(vessels, args.output_root)
        print(f"Wrote curated production vessel seed: {output_path}")


if __name__ == "__main__":
    main()
