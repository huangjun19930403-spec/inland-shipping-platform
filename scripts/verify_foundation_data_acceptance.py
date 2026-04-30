"""基础数据生产级关键链路只读验收。"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

import sqlalchemy as sa
from fastapi.routing import APIRoute
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal, engine
from app.core.security import get_current_user
from app.models.address import AdminRegion, AdminRegionBoundary, NavigationConstraintPoint, Region, RegionBoundaryVersion, TransportNode
from app.models.commodity import CommodityStandard
from app.models.common import CodeSequence
from app.models.dictionary import StdDict, StdDictItem
from app.modules.address.service import AdminRegionService, BusinessRegionService
from app.modules.commodity.service import CommodityStandardService
from main import app


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


FOUNDATION_PREFIXES = (
    "/api/v1/commodity",
    "/api/v1/address",
    "/api/v1/dictionary",
)


async def _table_columns(table_name: str) -> set[str]:
    async with engine.begin() as conn:
        return await conn.run_sync(
            lambda sync_conn: {column["name"] for column in sa.inspect(sync_conn).get_columns(table_name)}
        )


def _route_requires_auth(route: APIRoute) -> bool:
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        if dep.call is get_current_user:
            return True
        stack.extend(dep.dependencies)
    return False


def _result(name: str, ok: bool, detail: str) -> CheckResult:
    return CheckResult(name=name, ok=ok, detail=detail)


def _is_renderable_geojson(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    geometry_type = str(value.get("type") or "")
    if geometry_type == "Polygon":
        return bool(value.get("coordinates"))
    if geometry_type == "MultiPolygon":
        return bool(value.get("coordinates"))
    if geometry_type == "Feature":
        return _is_renderable_geojson(value.get("geometry"))
    if geometry_type == "FeatureCollection":
        features = value.get("features")
        return isinstance(features, list) and any(
            isinstance(feature, dict) and _is_renderable_geojson(feature.get("geometry"))
            for feature in features
        )
    return False


async def verify() -> list[CheckResult]:
    results: list[CheckResult] = []

    columns = await _table_columns("commodity_standard")
    results.append(
        _result(
            "commodity main unit column renamed",
            "main_unit_code" in columns and "main_unit" not in columns,
            ", ".join(sorted(columns)),
        )
    )

    unauthenticated = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        path = route.path
        if path.startswith(FOUNDATION_PREFIXES) and not _route_requires_auth(route):
            unauthenticated.append(path)
    results.append(
        _result(
            "foundation routes require login",
            not unauthenticated,
            "none" if not unauthenticated else ", ".join(sorted(set(unauthenticated))),
        )
    )

    async with AsyncSessionLocal() as session:
        sequence_codes = {
            row[0]
            for row in (
                await session.execute(
                    select(CodeSequence.biz_code).where(
                        CodeSequence.biz_code.in_(
                            [
                                "COMMODITY_STANDARD_CODE",
                                "REGION_CODE",
                                "NODE_CODE",
                                "NAV_CONSTRAINT_POINT_CODE",
                            ]
                        ),
                        CodeSequence.is_enabled.is_(True),
                    )
                )
            ).all()
        }
        results.append(
            _result(
                "foundation code sequences available",
                sequence_codes
                == {
                    "COMMODITY_STANDARD_CODE",
                    "REGION_CODE",
                    "NODE_CODE",
                    "NAV_CONSTRAINT_POINT_CODE",
                },
                ", ".join(sorted(sequence_codes)),
            )
        )

        dict_rows = (
            await session.execute(
                select(StdDict.dict_code, StdDictItem.item_code, StdDictItem.item_name)
                .join(StdDictItem, StdDictItem.dict_id == StdDict.id)
                .where(
                    StdDict.dict_code.in_(["COMMODITY_UNIT", "DANGEROUS_GOODS_LEVEL"]),
                    StdDict.status == 1,
                    StdDictItem.status == 1,
                )
            )
        ).all()
        unit_names = {code: name for dict_code, code, name in dict_rows if dict_code == "COMMODITY_UNIT"}
        danger_names = {code: name for dict_code, code, name in dict_rows if dict_code == "DANGEROUS_GOODS_LEVEL"}
        results.append(
            _result(
                "commodity unit dictionary labels",
                {"TON", "CUBIC_METER", "PIECE", "BOX", "TRUCK", "VOYAGE", "OTHER"}.issubset(unit_names),
                str(unit_names),
            )
        )
        results.append(
            _result(
                "dangerous goods dictionary labels",
                {"NON_DANGEROUS", "CLASS_1", "CLASS_9"}.issubset(danger_names),
                str(danger_names),
            )
        )

        option_rows = (
            await session.execute(
                select(StdDict.dict_code, StdDictItem.item_code, StdDictItem.item_name)
                .join(StdDictItem, StdDictItem.dict_id == StdDict.id)
                .where(
                    StdDict.dict_code.in_(
                        [
                            "PACKAGING_FORM",
                            "TRANSPORT_MODE_ELEMENT",
                            "SHIP_TYPE",
                            "NODE_TYPE",
                            "HANDLING_MODE",
                            "VALUE_TYPE",
                        ]
                    ),
                    StdDict.status == 1,
                    StdDictItem.status == 1,
                )
            )
        ).all()
        option_names = {}
        for dict_code, item_code, item_name in option_rows:
            option_names.setdefault(dict_code, {})[item_code] = item_name
        results.append(
            _result(
                "commodity rule and attribute dictionaries have Chinese labels",
                all(
                    option_names.get(dict_code, {}).get(item_code)
                    for dict_code, item_code in [
                        ("PACKAGING_FORM", "BULK"),
                        ("TRANSPORT_MODE_ELEMENT", "WATER"),
                        ("SHIP_TYPE", "BULK_CARRIER"),
                        ("NODE_TYPE", "PORT"),
                        ("HANDLING_MODE", "GRAB"),
                        ("VALUE_TYPE", "STRING"),
                    ]
                ),
                str({key: sorted(value)[:3] for key, value in option_names.items()}),
            )
        )

        bad_units = (
            await session.scalar(
                select(func.count())
                .select_from(CommodityStandard)
                .where(CommodityStandard.main_unit_code.notin_(list(unit_names.keys())))
            )
            or 0
        )
        results.append(_result("commodity standards use unit codes", bad_units == 0, f"bad_units={bad_units}"))

        sample_standard = await session.scalar(select(CommodityStandard).limit(1))
        standard_has_label = sample_standard is None or unit_names.get(sample_standard.main_unit_code)
        results.append(
            _result(
                "commodity standard unit label resolvable",
                bool(standard_has_label),
                "no standards" if sample_standard is None else f"{sample_standard.code}:{sample_standard.main_unit_code}",
            )
        )
        seeded_standard = await session.scalar(
            select(CommodityStandard).where(CommodityStandard.code == "STD_SAND_STONE_AGGREGATE")
        )
        detail_ok = True
        detail_text = "no seeded standard"
        if seeded_standard is not None:
            detail = await CommodityStandardService(session).get_standard_detail(seeded_standard.id)
            detail_ok = all(
                [
                    any(item.name for item in detail.packaging_forms),
                    any(item.name for item in detail.transport_modes),
                    any(item.name for item in detail.ship_type_rules),
                    any(item.name for item in detail.node_type_rules),
                    any(item.name for item in detail.handling_mode_rules),
                    not any(
                        attr.attribute_value_type_code and not attr.attribute_value_type_name
                        for attr in detail.attributes
                    ),
                ]
            )
            detail_text = (
                f"packaging={len(detail.packaging_forms)}, "
                f"transport={len(detail.transport_modes)}, "
                f"ship={len(detail.ship_type_rules)}, "
                f"node={len(detail.node_type_rules)}, "
                f"handling={len(detail.handling_mode_rules)}"
            )
        results.append(_result("commodity standard detail returns structured Chinese rules", detail_ok, detail_text))

        node = await session.scalar(select(TransportNode).limit(1))
        node_region_ok = True
        node_detail = "no nodes"
        if node is not None:
            city = await session.scalar(select(AdminRegion).where(AdminRegion.code == node.city_code))
            district_ok = True
            if node.district_code:
                district_ok = bool(await session.scalar(select(AdminRegion.id).where(AdminRegion.code == node.district_code)))
            node_region_ok = city is not None and int(city.id) == int(node.city_region_id) and district_ok
            node_detail = f"{node.code}:{node.city_code}/{node.city_region_id}"
        results.append(_result("node admin labels and city relation resolvable", node_region_ok, node_detail))

        counts = {
            "regions": await session.scalar(select(func.count()).select_from(Region)),
            "nodes": await session.scalar(select(func.count()).select_from(TransportNode)),
            "constraints": await session.scalar(select(func.count()).select_from(NavigationConstraintPoint)),
            "standards": await session.scalar(select(func.count()).select_from(CommodityStandard)),
        }
        results.append(_result("foundation sample data exists", all((value or 0) > 0 for value in counts.values()), str(counts)))

        admin_boundary_row = await session.scalar(
            select(AdminRegionBoundary)
            .where(AdminRegionBoundary.is_current.is_(True))
            .order_by(AdminRegionBoundary.id.asc())
            .limit(1)
        )
        admin_boundary_ok = True
        admin_boundary_detail = "no admin boundary seed"
        if admin_boundary_row is not None:
            admin_region = await session.scalar(select(AdminRegion).where(AdminRegion.id == admin_boundary_row.admin_region_id))
            if admin_region is None:
                admin_boundary_ok = False
                admin_boundary_detail = f"orphan boundary={admin_boundary_row.id}"
            else:
                current = await AdminRegionService(session).get_current_boundary(admin_region.code)
                admin_boundary_ok = bool(
                    current
                    and current.boundary_source_type_name
                    and _is_renderable_geojson(current.geometry_json)
                )
                admin_boundary_detail = (
                    f"{admin_region.code}:"
                    f"{current.boundary_source_type_code if current else '-'}:"
                    f"{current.geometry_json.get('type') if current else '-'}"
                )
        results.append(_result("admin region current boundary returns GeoJSON", admin_boundary_ok, admin_boundary_detail))

        admin_boundary_payloads = (
            await session.execute(select(AdminRegionBoundary.geometry_json))
        ).scalars().all()
        legacy_admin_wkt = sum(
            1
            for geometry in admin_boundary_payloads
            if isinstance(geometry, dict) and geometry.get("wkt")
        )
        results.append(
            _result(
                "admin boundary seed stores renderable GeoJSON",
                legacy_admin_wkt == 0,
                f"legacy_wkt_wrappers={legacy_admin_wkt}",
            )
        )

        business_boundary_row = await session.scalar(
            select(RegionBoundaryVersion)
            .where(RegionBoundaryVersion.is_current.is_(True))
            .order_by(RegionBoundaryVersion.id.asc())
            .limit(1)
        )
        business_boundary_ok = True
        business_boundary_detail = "no business boundary seed"
        if business_boundary_row is not None:
            current = await BusinessRegionService(session).get_current_region_boundary(business_boundary_row.region_id)
            business_boundary_ok = bool(
                current
                and current.boundary_source_type_name
                and _is_renderable_geojson(current.geometry_json)
            )
            business_boundary_detail = (
                f"region={business_boundary_row.region_id}:"
                f"{current.boundary_source_type_code if current else '-'}:"
                f"{current.geometry_json.get('type') if current else '-'}"
            )
        results.append(_result("business region current boundary returns GeoJSON", business_boundary_ok, business_boundary_detail))

    return results


def main() -> None:
    results = asyncio.run(verify())
    failed = [item for item in results if not item.ok]
    for item in results:
        status = "OK" if item.ok else "FAIL"
        print(f"[{status}] {item.name}: {item.detail}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
