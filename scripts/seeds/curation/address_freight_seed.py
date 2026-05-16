"""Curate production transport node and TMS freight seed data.

The input CSV files are operational exports. They are intentionally read only:
only curated result JSON files are written when ``--write-curated`` is passed.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.seeds.curation.commodity_seed import (
    EXCLUDED_TMS_COMMODITY_NAMES,
    build_commodity_term_index,
    load_seed_standards,
    normalize_commodity_name,
)


SEED_DATA_ROOT = PROJECT_ROOT / "scripts" / "seed_data"
DEFAULT_ADMIN_REGIONS_FILE = SEED_DATA_ROOT / "admin_region" / "admin_region_raw.json"
DEFAULT_COMMODITY_STANDARDS_FILE = (
    SEED_DATA_ROOT / "commodity" / "commodity_standards.json"
)

ADDRESS_OUTPUT = Path("address") / "transport_nodes.json"
REGION_OUTPUT = Path("address") / "business_regions.json"
FREIGHT_OUTPUT = Path("freight") / "tms_freights.json"

NULL_TEXTS = {"", "NULL", "null", "None", "NONE", "无", "nan", "NaN"}
DIRECT_MUNICIPALITIES = {"北京市", "天津市", "上海市", "重庆市"}
REASONABLE_TIME_FROM = datetime(2024, 1, 1)
REASONABLE_TIME_TO = datetime(2026, 5, 15, 23, 59, 59)

NODE_TYPE_MAP = {
    "码头": "TERMINAL",
    "厂区": "TERMINAL",
    "闸口": "LOCK",
    "锚地": "ANCHORAGE",
    "服务区": "LOGISTICS_PARK",
    "加油站": "OTHER",
}

REGION_GROUPS = [
    {
        "code": "REGION_TMS_YANGTZE_DELTA",
        "name": "TMS 长三角内河节点区",
        "short_name": "长三角",
        "description": "覆盖上海、江苏、浙江的 TMS 地址节点和历史运单端点。",
        "province_codes": {"310000", "320000", "330000"},
    },
    {
        "code": "REGION_TMS_WANJIANG",
        "name": "TMS 皖江散货节点区",
        "short_name": "皖江",
        "description": "覆盖安徽沿江及周边 TMS 地址节点和历史运单端点。",
        "province_codes": {"340000"},
    },
    {
        "code": "REGION_TMS_MIDDLE_YANGTZE",
        "name": "TMS 长江中游节点区",
        "short_name": "长江中游",
        "description": "覆盖湖北、湖南、江西的 TMS 地址节点和历史运单端点。",
        "province_codes": {"420000", "430000", "360000"},
    },
    {
        "code": "REGION_TMS_NORTH_INLAND",
        "name": "TMS 华北华中内河节点区",
        "short_name": "华北华中",
        "description": "覆盖河南、山东等北向内河与大宗散货关联节点。",
        "province_codes": {"410000", "370000"},
    },
    {
        "code": "REGION_TMS_UPPER_YANGTZE",
        "name": "TMS 长江上游节点区",
        "short_name": "长江上游",
        "description": "覆盖川渝云贵等长江上游及西南方向节点。",
        "province_codes": {"500000", "510000", "520000", "530000"},
    },
    {
        "code": "REGION_TMS_SOUTHEAST_COASTAL",
        "name": "TMS 东南沿海联运节点区",
        "short_name": "东南沿海",
        "description": "覆盖福建等东南沿海与内河联运节点。",
        "province_codes": {"350000"},
    },
]


@dataclass(frozen=True)
class AdminRegionInfo:
    code: str
    name: str
    province_code: str
    province_name: str
    city_code: str
    city_name: str
    level: str


@dataclass
class CurationReport:
    address_rows: int = 0
    unique_address_codes: int = 0
    unique_address_names: int = 0
    duplicate_address_names: int = 0
    node_count: int = 0
    merged_node_groups: int = 0
    address_city_count: int = 0
    missing_admin_cities: list[str] = field(default_factory=list)
    waybill_rows: int = 0
    waybill_groups: int = 0
    freight_count: int = 0
    endpoint_unique_count: int = 0
    endpoint_exact_count: int = 0
    endpoint_alias_count: int = 0
    endpoint_unmatched_count: int = 0
    skipped_reason_counts: dict[str, int] = field(default_factory=dict)
    skipped_examples: dict[str, list[str]] = field(default_factory=dict)
    commodity_unmatched_names: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing_admin_cities and not self.commodity_unmatched_names


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text in NULL_TEXTS else text


def _is_blank(value: Any) -> bool:
    return _clean(value) == ""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_json(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _decimal(value: Any) -> Decimal | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _float(value: Any) -> float | None:
    number = _decimal(value)
    return float(number) if number is not None else None


def _normalize_node_text(value: str | None) -> str:
    text = _clean(value)
    if not text:
        return ""
    text = re.sub(r"[\s·•,，。.;；:：'\"“”‘’\-_/\\]+", "", text)
    text = text.replace("（", "(").replace("）", ")")
    suffixes = [
        "有限责任公司",
        "股份有限公司",
        "集团有限公司",
        "有限公司",
        "分公司",
        "公司",
        "码头",
        "港务",
        "港区",
        "作业区",
        "水上加油站",
    ]
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[: -len(suffix)]
                changed = True
    return text.lower()


def _extract_parenthetical_terms(value: str) -> list[str]:
    terms: list[str] = []
    for item in re.findall(r"[（(]([^（）()]+)[）)]", value or ""):
        for part in re.split(r"[/、,，;；]", item):
            part = _clean(part)
            if part:
                terms.append(part)
    return terms


def _short_name(name: str) -> str:
    text = re.sub(r"[（(].*?[）)]", "", name).strip()
    for suffix in ["有限责任公司", "股份有限公司", "集团有限公司", "有限公司"]:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text[:64] or name[:64]


def _haversine_km(
    lng_a: float | None,
    lat_a: float | None,
    lng_b: float | None,
    lat_b: float | None,
) -> float:
    if None in {lng_a, lat_a, lng_b, lat_b}:
        return math.inf
    radius = 6371.0088
    phi_a, phi_b = math.radians(lat_a), math.radians(lat_b)
    delta_phi = math.radians(lat_b - lat_a)
    delta_lambda = math.radians(lng_b - lng_a)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _parse_time(value: Any) -> str | None:
    text = _clean(value)
    if not text:
        return None
    for pattern in ("%Y/%m/%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(text, pattern)
        except ValueError:
            continue
        if REASONABLE_TIME_FROM <= parsed <= REASONABLE_TIME_TO:
            return parsed.isoformat(sep=" ")
        return None
    return None


def _polygon_from_bbox(bbox: list[float]) -> dict[str, Any]:
    min_lng, min_lat, max_lng, max_lat = bbox
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [min_lng, min_lat],
                [max_lng, min_lat],
                [max_lng, max_lat],
                [min_lng, max_lat],
                [min_lng, min_lat],
            ]
        ],
    }


def _load_admin_regions(path: Path) -> dict[str, AdminRegionInfo]:
    rows = _load_json(path)
    province_by_code = {
        str(row["adcode"]): str(row["name"])
        for row in rows
        if row.get("level") == "province"
    }
    by_name: dict[str, AdminRegionInfo] = {}
    for row in rows:
        name = str(row.get("name") or "").strip()
        level = str(row.get("level") or "").strip()
        code = str(row.get("adcode") or row.get("code") or "").strip()
        if not name or not code or level not in {"city", "province"}:
            continue
        if level == "province" and name not in DIRECT_MUNICIPALITIES:
            continue
        province_code = str(row.get("province_code") or code)
        city_code = code if level == "city" else province_code
        by_name[name] = AdminRegionInfo(
            code=code,
            name=name,
            province_code=province_code,
            province_name=province_by_code.get(province_code, name),
            city_code=city_code,
            city_name=name,
            level=level,
        )
    return by_name


def _region_code_for_province(province_code: str) -> str:
    for group in REGION_GROUPS:
        if province_code in group["province_codes"]:
            return group["code"]
    return "REGION_TMS_OTHER_INLAND"


def _node_capabilities(node_type_code: str) -> tuple[list[str], list[str], list[str]]:
    if node_type_code == "LOCK":
        return ["PASSAGE"], [], []
    if node_type_code == "ANCHORAGE":
        return ["PASSAGE"], [], []
    if node_type_code == "LOGISTICS_PARK":
        return ["COMPREHENSIVE", "TRANSFER"], ["BULK", "GENERAL_CARGO"], ["CRANE", "MANUAL"]
    if node_type_code == "OTHER":
        return ["COMPREHENSIVE"], ["BULK"], ["OTHER"]
    return (
        ["LOADING", "UNLOADING", "TRANSFER"],
        ["BULK", "TON_BAG", "GENERAL_CARGO"],
        ["GRAB", "CONVEYOR", "CRANE"],
    )


def _canonical_cluster_code(rows: list[dict[str, Any]]) -> str:
    return sorted(rows, key=lambda row: (row["address_code"], row["source_id"]))[0][
        "address_code"
    ]


def build_transport_nodes(
    address_rows: list[dict[str, str]],
    waybill_rows: list[dict[str, str]],
    *,
    admin_regions_path: Path = DEFAULT_ADMIN_REGIONS_FILE,
) -> tuple[list[dict[str, Any]], dict[str, AdminRegionInfo], CurationReport]:
    admin_by_city = _load_admin_regions(admin_regions_path)
    endpoint_counter = Counter()
    for row in waybill_rows:
        origin = _clean(row.get("装货地"))
        destination = _clean(row.get("卸货地"))
        if origin:
            endpoint_counter[origin] += 1
        if destination:
            endpoint_counter[destination] += 1

    report = CurationReport()
    report.address_rows = len(address_rows)
    report.unique_address_codes = len({_clean(row.get("address_code")) for row in address_rows})
    names = [_clean(row.get("name")) for row in address_rows if _clean(row.get("name"))]
    report.unique_address_names = len(set(names))
    report.duplicate_address_names = sum(
        1 for _, count in Counter(names).items() if count > 1
    )
    address_cities = sorted({_clean(row.get("city")) for row in address_rows if _clean(row.get("city"))})
    report.address_city_count = len(address_cities)
    report.missing_admin_cities = [city for city in address_cities if city not in admin_by_city]

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in address_rows:
        name = _clean(row.get("name"))
        address_code = _clean(row.get("address_code"))
        city_name = _clean(row.get("city"))
        address_type = _clean(row.get("address_type"))
        city = admin_by_city.get(city_name)
        if not name or not address_code or city is None:
            continue
        node_type_code = NODE_TYPE_MAP.get(address_type, "OTHER")
        grouped[(name, city.city_code, node_type_code)].append(
            {
                "source_id": _clean(row.get("id")),
                "address_code": address_code,
                "name": name,
                "address_type": address_type,
                "node_type_code": node_type_code,
                "city": city,
                "address": _clean(row.get("address_location")) or None,
                "longitude": _float(row.get("longitude")),
                "latitude": _float(row.get("latitude")),
            }
        )

    nodes: list[dict[str, Any]] = []
    for (_, _, _), rows in grouped.items():
        clusters: list[list[dict[str, Any]]] = []
        for row in sorted(rows, key=lambda item: (item["address_code"], item["source_id"])):
            placed = False
            for cluster in clusters:
                representative = cluster[0]
                if (
                    _haversine_km(
                        row["longitude"],
                        row["latitude"],
                        representative["longitude"],
                        representative["latitude"],
                    )
                    <= 3
                ):
                    cluster.append(row)
                    placed = True
                    break
            if not placed:
                clusters.append([row])

        for cluster in clusters:
            canonical = sorted(
                cluster,
                key=lambda item: (
                    -endpoint_counter[item["name"]],
                    item["address_code"],
                    item["source_id"],
                ),
            )[0]
            city = canonical["city"]
            node_type_code = canonical["node_type_code"]
            categories, packaging, handling = _node_capabilities(node_type_code)
            aliases = [
                {
                    "alias_name": canonical["name"],
                    "alias_type_code": "COMMON_ALIAS",
                    "source_type_code": "TMS",
                    "is_primary": True,
                }
            ]
            for term in _extract_parenthetical_terms(canonical["name"]):
                aliases.append(
                    {
                        "alias_name": term,
                        "alias_type_code": "COMMON_ALIAS",
                        "source_type_code": "TMS",
                        "is_primary": False,
                    }
                )
            nodes.append(
                {
                    "code": _canonical_cluster_code(cluster),
                    "name": canonical["name"],
                    "short_name": _short_name(canonical["name"]),
                    "node_type_code": node_type_code,
                    "province_code": city.province_code,
                    "province_name": city.province_name,
                    "city_code": city.city_code,
                    "city_name": city.city_name,
                    "city_region_code": city.code,
                    "district_code": None,
                    "business_region_code": _region_code_for_province(city.province_code),
                    "address": canonical["address"],
                    "longitude": canonical["longitude"],
                    "latitude": canonical["latitude"],
                    "status": 1,
                    "lifecycle_status_code": "ACTIVE",
                    "sort_order": 0,
                    "is_hot_node": False,
                    "aliases": aliases,
                    "business_categories": categories,
                    "packaging_forms": packaging,
                    "handling_modes": handling,
                    "profile": {
                        "business_nature_code": "TMS_ADDRESS_NODE",
                        "channel_depth_m": None,
                        "max_draft_m": None,
                        "berth_count": None,
                        "annual_throughput_ton": None,
                        "open_hours_desc": None,
                        "ext_json": {
                            "source_type": "TMS_ADDRESS",
                            "source_ids": sorted({item["source_id"] for item in cluster if item["source_id"]}),
                            "source_address_codes": sorted({item["address_code"] for item in cluster}),
                            "source_address_types": sorted({item["address_type"] for item in cluster}),
                            "merged_source_count": len(cluster),
                        },
                    },
                    "source": {
                        "source_type_code": "TMS",
                        "source_address_codes": sorted({item["address_code"] for item in cluster}),
                        "source_ids": sorted({item["source_id"] for item in cluster if item["source_id"]}),
                        "merge_policy": "same_name_city_type_within_3km",
                    },
                }
            )
            if len(cluster) > 1:
                report.merged_node_groups += 1

    nodes.sort(key=lambda item: (-endpoint_counter[item["name"]], item["city_code"], item["code"]))
    for index, node in enumerate(nodes, start=1):
        node["sort_order"] = index
        node["is_hot_node"] = index <= 80 or endpoint_counter[node["name"]] >= 20
    report.node_count = len(nodes)
    return nodes, admin_by_city, report


def _candidate_score(endpoint: str, node: dict[str, Any]) -> tuple[int, str | None]:
    normalized_endpoint = _normalize_node_text(endpoint)
    if not normalized_endpoint:
        return 0, None

    candidate_terms = [node["name"], node.get("short_name")]
    candidate_terms.extend(alias["alias_name"] for alias in node.get("aliases") or [])
    candidate_terms.extend(_extract_parenthetical_terms(node["name"]))
    best_score = 0
    best_basis: str | None = None
    for term in candidate_terms:
        term = _clean(term)
        if not term:
            continue
        normalized_term = _normalize_node_text(term)
        if not normalized_term:
            continue
        score = 0
        if endpoint == term:
            score = 100
        elif normalized_endpoint == normalized_term:
            score = 95
        elif term in _extract_parenthetical_terms(node["name"]) and normalized_endpoint == normalized_term:
            score = 92
        elif normalized_endpoint in normalized_term or normalized_term in normalized_endpoint:
            shortest = min(len(normalized_endpoint), len(normalized_term))
            if shortest >= 4:
                score = 82
        if score > best_score:
            best_score = score
            best_basis = term
    return best_score, best_basis


def _build_endpoint_matches(
    nodes: list[dict[str, Any]],
    waybill_rows: list[dict[str, str]],
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    endpoints = sorted(
        {
            value
            for row in waybill_rows
            for value in [_clean(row.get("装货地")), _clean(row.get("卸货地"))]
            if value
        }
    )
    exact_owner: dict[str, set[str]] = defaultdict(set)
    for node in nodes:
        exact_owner[node["name"]].add(node["code"])

    matches: dict[str, dict[str, Any]] = {}
    stats = Counter()
    for endpoint in endpoints:
        exact_codes = exact_owner.get(endpoint) or set()
        if len(exact_codes) == 1:
            matches[endpoint] = {
                "node_code": next(iter(exact_codes)),
                "match_kind": "EXACT_NAME",
                "match_level_code": "NODE",
                "score": 100,
                "basis": endpoint,
            }
            stats["exact"] += 1
            continue

        scored: list[tuple[int, str, str | None]] = []
        for node in nodes:
            score, basis = _candidate_score(endpoint, node)
            if score >= 80:
                scored.append((score, node["code"], basis))
        scored.sort(reverse=True)
        if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
            score, code, basis = scored[0]
            matches[endpoint] = {
                "node_code": code,
                "match_kind": "NORMALIZED_ALIAS",
                "match_level_code": "NODE",
                "score": score,
                "basis": basis,
            }
            stats["alias"] += 1
        else:
            stats["unmatched"] += 1
    stats["unique"] = len(endpoints)
    return matches, dict(stats)


def _add_endpoint_aliases(
    nodes: list[dict[str, Any]],
    endpoint_matches: dict[str, dict[str, Any]],
) -> None:
    nodes_by_code = {node["code"]: node for node in nodes}
    existing_by_code = {
        node["code"]: {_normalize_node_text(alias["alias_name"]) for alias in node.get("aliases") or []}
        for node in nodes
    }
    for endpoint, match in endpoint_matches.items():
        if match["match_kind"] == "EXACT_NAME":
            continue
        node = nodes_by_code.get(match["node_code"])
        if node is None:
            continue
        normalized = _normalize_node_text(endpoint)
        if not normalized or normalized in existing_by_code[node["code"]]:
            continue
        node.setdefault("aliases", []).append(
            {
                "alias_name": endpoint,
                "alias_type_code": "COMMON_ALIAS",
                "source_type_code": "TMS",
                "is_primary": False,
            }
        )
        existing_by_code[node["code"]].add(normalized)


def _remove_cross_node_duplicate_aliases(nodes: list[dict[str, Any]]) -> None:
    owners: dict[str, set[str]] = defaultdict(set)
    for node in nodes:
        for alias in node.get("aliases") or []:
            normalized = _normalize_node_text(alias.get("alias_name"))
            if normalized:
                owners[normalized].add(node["code"])

    ambiguous_terms = {term for term, codes in owners.items() if len(codes) > 1}
    for node in nodes:
        kept: list[dict[str, Any]] = []
        for alias in node.get("aliases") or []:
            normalized = _normalize_node_text(alias.get("alias_name"))
            if normalized in ambiguous_terms:
                continue
            kept.append(alias)
        for index, alias in enumerate(kept):
            alias["is_primary"] = index == 0
        node["aliases"] = kept


def _core_signature(row: dict[str, str]) -> tuple[str, ...]:
    keys = [
        "船舶名称",
        "货品名称",
        "装货地",
        "卸货地",
        "预计装货吨位",
        "实际装货吨位",
        "实际卸货吨位",
        "到达装货港时间",
        "离开装货港时间",
        "到达卸货港时间",
        "卸货完成时间",
        "单价",
    ]
    return tuple(_clean(row.get(key)) for key in keys)


def _normal_ship_name(value: str) -> str:
    return "".join(value.strip().split()).upper()


def _freight_number(waybill_code: str) -> str:
    suffix = waybill_code[2:] if waybill_code.upper().startswith("YD") else waybill_code
    return f"FR-TMS-{suffix}"[:32]


def _skip(
    skipped: Counter,
    examples: dict[str, list[str]],
    reason: str,
    waybill_code: str,
) -> None:
    skipped[reason] += 1
    bucket = examples.setdefault(reason, [])
    if len(bucket) < 20:
        bucket.append(waybill_code)


def build_freights(
    waybill_rows: list[dict[str, str]],
    nodes: list[dict[str, Any]],
    endpoint_matches: dict[str, dict[str, Any]],
    *,
    standards_path: Path = DEFAULT_COMMODITY_STANDARDS_FILE,
) -> tuple[list[dict[str, Any]], Counter, dict[str, list[str]], list[str]]:
    standards = load_seed_standards(standards_path)
    commodity_index, duplicate_terms = build_commodity_term_index(standards)
    if duplicate_terms:
        raise RuntimeError(f"commodity seed has duplicate terms: {duplicate_terms}")
    standards_by_code = {row["code"]: row for row in standards}
    node_by_code = {row["code"]: row for row in nodes}

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in waybill_rows:
        code = _clean(row.get("运单编码"))
        if code:
            grouped[code].append(row)

    skipped: Counter = Counter()
    examples: dict[str, list[str]] = {}
    freights: list[dict[str, Any]] = []
    unmatched_commodities: set[str] = set()

    for waybill_code, rows in sorted(grouped.items()):
        signatures = {_core_signature(row) for row in rows}
        if len(signatures) > 1:
            _skip(skipped, examples, "CORE_FIELD_CONFLICT", waybill_code)
            continue
        row = rows[0]
        raw_commodity = _clean(row.get("货品名称"))
        raw_origin = _clean(row.get("装货地"))
        raw_destination = _clean(row.get("卸货地"))
        if not raw_commodity or not raw_origin or not raw_destination:
            _skip(skipped, examples, "NULL_KEY_FIELD", waybill_code)
            continue
        if raw_commodity in EXCLUDED_TMS_COMMODITY_NAMES:
            _skip(skipped, examples, "EXCLUDED_COMMODITY", waybill_code)
            continue
        commodity_code = commodity_index.get(normalize_commodity_name(raw_commodity))
        if commodity_code is None:
            unmatched_commodities.add(raw_commodity)
            _skip(skipped, examples, "UNMATCHED_COMMODITY", waybill_code)
            continue
        origin_match = endpoint_matches.get(raw_origin)
        destination_match = endpoint_matches.get(raw_destination)
        if origin_match is None:
            _skip(skipped, examples, "UNMATCHED_ORIGIN_NODE", waybill_code)
            continue
        if destination_match is None:
            _skip(skipped, examples, "UNMATCHED_DESTINATION_NODE", waybill_code)
            continue
        origin_node = node_by_code[origin_match["node_code"]]
        destination_node = node_by_code[destination_match["node_code"]]

        unit_prices = {
            value
            for value in (_decimal(item.get("单价")) for item in rows)
            if value is not None
        }
        if len(unit_prices) > 1:
            _skip(skipped, examples, "UNIT_PRICE_CONFLICT", waybill_code)
            continue
        total_price = sum((_decimal(item.get("结算金额")) or Decimal("0")) for item in rows)
        estimated = (
            _decimal(row.get("实际卸货吨位"))
            or _decimal(row.get("实际装货吨位"))
            or _decimal(row.get("预计装货吨位"))
        )
        if estimated is None:
            _skip(skipped, examples, "MISSING_TONNAGE", waybill_code)
            continue

        packaging_form_code = (
            "TON_BAG" if "吨包" in raw_commodity or "吨袋" in raw_commodity else "BULK"
        )
        ship_name = _clean(row.get("船舶名称"))
        freight = {
            "freight_no": _freight_number(waybill_code),
            "source_type_code": "TMS",
            "source_channel_code": "TMS_API",
            "source_ref_no": waybill_code,
            "raw_commodity_name": raw_commodity,
            "raw_tonnage_text": _clean(row.get("实际卸货吨位"))
            or _clean(row.get("实际装货吨位"))
            or _clean(row.get("预计装货吨位")),
            "raw_origin_text": raw_origin,
            "raw_destination_text": raw_destination,
            "cargo_title": f"{raw_origin}至{raw_destination}{raw_commodity}",
            "cargo_description": (
                f"TMS历史运单；船舶={ship_name or '未知'}；"
                f"来源运单={waybill_code}；费用类型="
                f"{','.join(sorted({_clean(item.get('费用类型')) for item in rows if _clean(item.get('费用类型'))}))}"
            ),
            "commodity_standard_code": commodity_code,
            "commodity_standard_name": standards_by_code[commodity_code]["name"],
            "commodity_match_level_code": "STANDARD",
            "packaging_form_code": packaging_form_code,
            "estimated_tonnage": _decimal_text(estimated),
            "min_tonnage": None,
            "max_tonnage": None,
            "unit_price": _decimal_text(next(iter(unit_prices))) if unit_prices else None,
            "total_price": _decimal_text(total_price),
            "price_unit": "元/吨",
            "settlement_method_code": None,
            "origin_node_code": origin_node["code"],
            "destination_node_code": destination_node["code"],
            "origin_match_level_code": "NODE",
            "destination_match_level_code": "NODE",
            "origin_province_code": origin_node["province_code"],
            "origin_city_code": origin_node["city_code"],
            "origin_district_code": origin_node.get("district_code"),
            "destination_province_code": destination_node["province_code"],
            "destination_city_code": destination_node["city_code"],
            "destination_district_code": destination_node.get("district_code"),
            "origin_region_code": origin_node["business_region_code"],
            "destination_region_code": destination_node["business_region_code"],
            "loading_time_from": _parse_time(row.get("到达装货港时间")),
            "loading_time_to": _parse_time(row.get("离开装货港时间")),
            "unloading_time_from": _parse_time(row.get("到达卸货港时间")),
            "unloading_time_to": _parse_time(row.get("卸货完成时间")),
            "publisher_org_name": "TMS历史运单",
            "status_code": "CLOSED",
            "published_at": _parse_time(row.get("离开装货港时间")),
            "expired_at": None,
            "confirmed_at": _parse_time(row.get("卸货完成时间")),
            "hall_status_code": "NOT_LISTED",
            "hall_published_at": None,
            "hall_unpublished_at": None,
            "hall_visible_until": None,
            "source_ship_name": ship_name or None,
            "normalized_ship_name": _normal_ship_name(ship_name) if ship_name else None,
        }
        freights.append(freight)

    freights.sort(key=lambda item: item["freight_no"])
    return freights, skipped, examples, sorted(unmatched_commodities)


def build_business_regions(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes_by_region: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        nodes_by_region[node["business_region_code"]].append(node)

    group_by_code = {group["code"]: group for group in REGION_GROUPS}
    group_by_code["REGION_TMS_OTHER_INLAND"] = {
        "code": "REGION_TMS_OTHER_INLAND",
        "name": "TMS 其他内河联运节点区",
        "short_name": "其他内河",
        "description": "覆盖未归入主要通道分组的 TMS 地址节点。",
        "province_codes": set(),
    }

    regions: list[dict[str, Any]] = []
    for code, region_nodes in sorted(nodes_by_region.items()):
        group = group_by_code[code]
        lngs = [node["longitude"] for node in region_nodes if node.get("longitude") is not None]
        lats = [node["latitude"] for node in region_nodes if node.get("latitude") is not None]
        if lngs and lats:
            bbox = [
                round(min(lngs) - 0.1, 6),
                round(min(lats) - 0.1, 6),
                round(max(lngs) + 0.1, 6),
                round(max(lats) + 0.1, 6),
            ]
        else:
            bbox = [100.0, 20.0, 125.0, 36.0]
        city_codes = sorted({node["city_region_code"] for node in region_nodes})
        city_names = sorted({node["city_name"] for node in region_nodes})
        regions.append(
            {
                "code": code,
                "name": group["name"],
                "short_name": group["short_name"],
                "region_type_code": "SHIPPING_ANALYSIS_REGION",
                "description": group["description"],
                "city_region_codes": city_codes,
                "city_names": city_names,
                "bbox": bbox,
                "geometry_json": _polygon_from_bbox(bbox),
                "boundary_source_type_code": "PLATFORM_DEFINED",
                "status": 1,
                "sort_order": len(regions) + 1,
            }
        )
    return regions


def curate(
    addresses: Path,
    waybills: Path,
    *,
    output_root: Path = SEED_DATA_ROOT,
    write_curated: bool = False,
    admin_regions_path: Path = DEFAULT_ADMIN_REGIONS_FILE,
    standards_path: Path = DEFAULT_COMMODITY_STANDARDS_FILE,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], CurationReport]:
    address_rows = _read_csv(addresses)
    waybill_rows = _read_csv(waybills)
    nodes, _admin_by_city, report = build_transport_nodes(
        address_rows,
        waybill_rows,
        admin_regions_path=admin_regions_path,
    )
    endpoint_matches, endpoint_stats = _build_endpoint_matches(nodes, waybill_rows)
    _add_endpoint_aliases(nodes, endpoint_matches)
    _remove_cross_node_duplicate_aliases(nodes)
    regions = build_business_regions(nodes)
    freights, skipped, examples, unmatched_commodities = build_freights(
        waybill_rows,
        nodes,
        endpoint_matches,
        standards_path=standards_path,
    )

    report.waybill_rows = len(waybill_rows)
    report.waybill_groups = len({_clean(row.get("运单编码")) for row in waybill_rows if _clean(row.get("运单编码"))})
    report.freight_count = len(freights)
    report.endpoint_unique_count = endpoint_stats.get("unique", 0)
    report.endpoint_exact_count = endpoint_stats.get("exact", 0)
    report.endpoint_alias_count = endpoint_stats.get("alias", 0)
    report.endpoint_unmatched_count = endpoint_stats.get("unmatched", 0)
    report.skipped_reason_counts = dict(sorted(skipped.items()))
    report.skipped_examples = examples
    report.commodity_unmatched_names = unmatched_commodities

    if write_curated:
        outputs = {
            REGION_OUTPUT: regions,
            ADDRESS_OUTPUT: nodes,
            FREIGHT_OUTPUT: freights,
        }
        for relative, payload in outputs.items():
            path = output_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    return regions, nodes, freights, report


def _print_report(report: CurationReport) -> None:
    print(f"address_rows={report.address_rows}")
    print(f"unique_address_codes={report.unique_address_codes}")
    print(f"unique_address_names={report.unique_address_names}")
    print(f"duplicate_address_names={report.duplicate_address_names}")
    print(f"address_city_count={report.address_city_count}")
    print(f"node_count={report.node_count}")
    print(f"merged_node_groups={report.merged_node_groups}")
    print(f"missing_admin_cities={report.missing_admin_cities}")
    print(f"waybill_rows={report.waybill_rows}")
    print(f"waybill_groups={report.waybill_groups}")
    print(f"freight_count={report.freight_count}")
    print(
        "endpoint_match_counts="
        f"unique:{report.endpoint_unique_count},"
        f"exact:{report.endpoint_exact_count},"
        f"alias:{report.endpoint_alias_count},"
        f"unmatched:{report.endpoint_unmatched_count}"
    )
    print(f"skipped_reason_counts={report.skipped_reason_counts}")
    print(f"skipped_examples={report.skipped_examples}")
    print(f"commodity_unmatched_names={report.commodity_unmatched_names}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Curate production address node and TMS freight seed data."
    )
    parser.add_argument("--addresses", required=True, type=Path, help="TMS address CSV path")
    parser.add_argument("--waybills", required=True, type=Path, help="TMS waybill CSV path")
    parser.add_argument(
        "--output-root",
        default=SEED_DATA_ROOT,
        type=Path,
        help="Seed data output root; defaults to scripts/seed_data",
    )
    parser.add_argument(
        "--write-curated",
        action="store_true",
        help="Write curated production JSON files. Without this flag, only prints a report.",
    )
    args = parser.parse_args()

    _, _, _, report = curate(
        args.addresses,
        args.waybills,
        output_root=args.output_root,
        write_curated=args.write_curated,
    )
    _print_report(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
