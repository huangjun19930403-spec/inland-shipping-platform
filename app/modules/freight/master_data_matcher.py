"""Batch master-data matching for freight AI candidates."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.address import AdminRegion, NodeAlias, RegionCityRelation, TransportNode
from app.models.commodity import CommodityAlias, CommodityStandard


def _first(segment: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = segment.get(key)
        if value not in (None, ""):
            return value
    return None


PACKAGING_ONLY_COMMODITY_TEXTS = {"吨包", "吨袋"}


def _is_packaging_only_commodity_text(value: str) -> bool:
    return "".join(value.strip().lower().split()) in PACKAGING_ONLY_COMMODITY_TEXTS


class FreightMasterDataBatchMatcher:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._loaded = False
        self.standards: list[CommodityStandard] = []
        self.aliases: list[CommodityAlias] = []
        self.standard_by_id: dict[int, CommodityStandard] = {}
        self.nodes: list[TransportNode] = []
        self.node_aliases: list[NodeAlias] = []
        self.node_by_id: dict[int, TransportNode] = {}
        self.cities: list[AdminRegion] = []
        self.region_by_city_region_id: dict[int, int] = {}

    async def _load_once(self) -> None:
        if self._loaded:
            return
        self.standards = list(
            (
                await self.db.execute(
                    select(CommodityStandard).where(
                        CommodityStandard.deleted_at.is_(None),
                        CommodityStandard.is_active.is_(True),
                    )
                )
            ).scalars().all()
        )
        self.standard_by_id = {int(item.id): item for item in self.standards}
        standard_ids = list(self.standard_by_id)
        if standard_ids:
            self.aliases = list(
                (
                    await self.db.execute(
                        select(CommodityAlias).where(
                            CommodityAlias.is_enabled.is_(True),
                            CommodityAlias.commodity_standard_id.in_(standard_ids),
                        )
                    )
                ).scalars().all()
            )
        self.nodes = list((await self.db.execute(select(TransportNode).where(TransportNode.deleted_at.is_(None)))).scalars().all())
        self.node_by_id = {int(item.id): item for item in self.nodes}
        self.node_aliases = list((await self.db.execute(select(NodeAlias))).scalars().all())
        self.cities = list(
            (
                await self.db.execute(
                    select(AdminRegion).where(AdminRegion.level == 2, AdminRegion.status == 1)
                )
            ).scalars().all()
        )
        relations = list(
            (
                await self.db.execute(
                    select(RegionCityRelation).order_by(
                        RegionCityRelation.is_primary.desc(),
                        RegionCityRelation.sort_order.asc(),
                    )
                )
            ).scalars().all()
        )
        for relation in relations:
            self.region_by_city_region_id.setdefault(int(relation.city_region_id), int(relation.region_id))
        self._loaded = True

    async def match_segments(self, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        await self._load_once()
        return [self.match_segment(segment) for segment in segments]

    def match_segment(self, segment: dict[str, Any]) -> dict[str, Any]:
        commodity_name = str(_first(segment, "commodity_name", "cargo_name", "goods_name", "cargo") or "").strip()
        origin_text = str(_first(segment, "origin_text", "loading_place", "origin", "from") or "").strip()
        destination_text = str(_first(segment, "destination_text", "unloading_place", "destination", "to") or "").strip()
        commodity_id, commodity_score, commodity_level, commodity_options, commodity_basis = self.match_commodity(commodity_name)
        origin, origin_options, origin_basis = self.match_location(
            origin_text,
            str(_first(segment, "origin_match_level_code", "origin_level_code") or ""),
        )
        destination, destination_options, destination_basis = self.match_location(
            destination_text,
            str(_first(segment, "destination_match_level_code", "destination_level_code") or ""),
        )
        return {
            "commodity": {
                "id": commodity_id,
                "score": commodity_score,
                "level": commodity_level,
                "options": commodity_options,
                "basis": commodity_basis,
            },
            "origin": {"selected": origin, "options": origin_options, "basis": origin_basis},
            "destination": {"selected": destination, "options": destination_options, "basis": destination_basis},
        }

    def match_commodity(
        self, raw_name: str
    ) -> tuple[int | None, Decimal | None, str | None, list[dict[str, Any]], dict[str, Any]]:
        text = raw_name.strip()
        if not text:
            return None, None, None, [], {"status": "NO_TEXT"}
        if _is_packaging_only_commodity_text(text):
            return (
                None,
                Decimal("0.0"),
                "RAW",
                [{"level": "RAW", "name": text, "score": "0.0"}],
                {"status": "PACKAGING_ONLY", "text": text},
            )
        options: list[dict[str, Any]] = []
        for standard in self.standards:
            score = None
            level = None
            if text == standard.name or text == (standard.short_name or ""):
                score, level = Decimal("1.0"), "STANDARD"
            elif text in standard.name or standard.name in text:
                score, level = Decimal("0.82"), "STANDARD"
            if score is not None:
                priority_boost = Decimal(str(max(min(standard.recognition_priority or 50, 100), 0))) / Decimal("1000")
                score = min(score + priority_boost, Decimal("1.0"))
                options.append(
                    {
                        "id": int(standard.id),
                        "code": standard.code,
                        "name": standard.name,
                        "category_id": int(standard.category_id) if standard.category_id is not None else None,
                        "type_id": int(standard.type_id) if standard.type_id is not None else None,
                        "score": str(score),
                        "match_level_code": level,
                        "basis": "标准名称/简称",
                        "matched_text": text,
                    }
                )
        for alias in self.aliases:
            score = None
            alias_name = alias.alias_name or ""
            if text == alias_name:
                score = Decimal("1.0")
            elif text in alias_name or alias_name in text:
                score = Decimal("0.80")
            if score is None:
                continue
            standard = self.standard_by_id.get(int(alias.commodity_standard_id))
            if standard is None:
                continue
            weight_boost = Decimal(str(max(min(alias.match_weight or 80, 100), 0))) / Decimal("1000")
            priority_boost = Decimal(str(max(min(standard.recognition_priority or 50, 100), 0))) / Decimal("1000")
            score = min(score + weight_boost + priority_boost, Decimal("1.0"))
            options.append(
                {
                    "id": int(alias.commodity_standard_id),
                    "code": standard.code,
                    "name": standard.name,
                    "category_id": int(standard.category_id) if standard.category_id is not None else None,
                    "type_id": int(standard.type_id) if standard.type_id is not None else None,
                    "score": str(score),
                    "match_level_code": "ALIAS",
                    "basis": f"启用别名:{alias.alias_name}",
                    "alias_type_code": alias.alias_type_code,
                    "matched_text": alias.alias_name,
                }
            )
        dedup: dict[int, dict[str, Any]] = {}
        for option in sorted(options, key=lambda item: Decimal(str(item["score"])), reverse=True):
            dedup.setdefault(int(option["id"]), option)
        ordered = list(dedup.values())[:5]
        if not ordered:
            return None, Decimal("0.0"), "RAW", [{"level": "RAW", "name": text, "score": "0.0"}], {"status": "UNMATCHED", "text": text}
        first = ordered[0]
        return int(first["id"]), Decimal(str(first["score"])), str(first["match_level_code"]), ordered, {"status": "MATCHED", "text": text, "top": first}

    def match_location(
        self, raw_text: str, ai_level_code: str | None = None
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        text = raw_text.strip()
        if not text:
            return {}, [], {"status": "NO_TEXT"}
        ai_level = str(ai_level_code or "").strip().upper()
        if ai_level not in {"NODE", "CITY", "RAW"}:
            ai_level = ""
        exact_node_options: list[dict[str, Any]] = []
        strong_node_options: list[dict[str, Any]] = []
        weak_node_options: list[dict[str, Any]] = []
        city_options: list[dict[str, Any]] = []
        exact_city_options: list[dict[str, Any]] = []

        def make_node_option(node: TransportNode, *, score: Decimal, basis: str, strength: str) -> dict[str, Any]:
            return {
                "level": "NODE",
                "node_id": int(node.id),
                "node_name": node.name,
                "city_code": node.city_code,
                "province_code": node.province_code,
                "district_code": node.district_code,
                "region_id": self.region_by_city_region_id.get(int(node.city_region_id)),
                "score": str(score),
                "basis": basis,
                "match_strength": strength,
            }

        for node in self.nodes:
            names = [name for name in [node.name, node.short_name or ""] if name]
            if any(text == name for name in names):
                exact_node_options.append(make_node_option(node, score=Decimal("1.0"), basis=node.name, strength="EXACT"))
            elif any(name in text for name in names if len(name) >= 3):
                strong_node_options.append(make_node_option(node, score=Decimal("0.92"), basis=node.name, strength="NODE_NAME_IN_TEXT"))
            elif any(text in name for name in names if len(text) >= 2):
                weak_node_options.append(make_node_option(node, score=Decimal("0.72"), basis=node.name, strength="TEXT_IN_NODE_NAME"))
        for alias in self.node_aliases:
            alias_name = (alias.alias_name or "").strip()
            if not alias_name:
                continue
            node = self.node_by_id.get(int(alias.node_id))
            if node is None:
                continue
            if text == alias_name:
                exact_node_options.append(make_node_option(node, score=Decimal("1.0"), basis=alias_name, strength="ALIAS_EXACT"))
            elif alias_name in text and len(alias_name) >= 2:
                strong_node_options.append(make_node_option(node, score=Decimal("0.90"), basis=alias_name, strength="ALIAS_IN_TEXT"))
            elif text in alias_name and len(text) >= 2:
                weak_node_options.append(make_node_option(node, score=Decimal("0.72"), basis=alias_name, strength="TEXT_IN_ALIAS"))
        for city in self.cities:
            names = [name for name in [city.name, city.short_name or ""] if name]
            score = None
            strength = ""
            basis = city.name
            if any(text == name for name in names):
                score = Decimal("0.98")
                strength = "CITY_EXACT"
                basis = city.short_name if text == (city.short_name or "") else city.name
            elif city.name and city.name in text and len(city.name) >= 3:
                score = Decimal("0.78")
                strength = "CITY_NAME_IN_TEXT"
            elif city.short_name and city.short_name in text and len(city.short_name) >= 2:
                score = Decimal("0.76")
                strength = "CITY_SHORT_IN_TEXT"
                basis = city.short_name
            if score is None:
                continue
            option = {
                "level": "CITY",
                "node_id": None,
                "node_name": None,
                "city_code": city.code,
                "city_name": city.name,
                "province_code": city.province_code or city.code[:2].ljust(6, "0"),
                "district_code": None,
                "region_id": self.region_by_city_region_id.get(int(city.id)),
                "score": str(score),
                "basis": basis,
                "match_strength": strength,
            }
            city_options.append(option)
            if strength == "CITY_EXACT":
                exact_city_options.append(option)

        def order_options(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
            dedup: dict[tuple[str, Any, Any], dict[str, Any]] = {}
            for option in sorted(options, key=lambda item: Decimal(str(item["score"])), reverse=True):
                key = (str(option.get("level")), option.get("node_id"), option.get("city_code"))
                dedup.setdefault(key, option)
            return list(dedup.values())[:6]

        all_options = order_options(exact_node_options + strong_node_options + exact_city_options + city_options + weak_node_options)

        def normalize_node(first: dict[str, Any]) -> dict[str, Any]:
            return {
                "node_id": first.get("node_id"),
                "province_code": first.get("province_code"),
                "city_code": first.get("city_code"),
                "district_code": first.get("district_code"),
                "region_id": first.get("region_id"),
                "match_score": Decimal(str(first["score"])),
                "match_level_code": "NODE",
            }

        def normalize_city(first: dict[str, Any]) -> dict[str, Any]:
            return {
                "node_id": None,
                "province_code": first.get("province_code"),
                "city_code": first.get("city_code"),
                "district_code": None,
                "region_id": first.get("region_id"),
                "match_score": Decimal(str(first["score"])),
                "match_level_code": "CITY",
            }

        if exact_node_options:
            first = order_options(exact_node_options)[0]
            return normalize_node(first), all_options, {"status": "MATCHED_NODE", "text": text, "top": first, "ai_level": ai_level}
        if exact_city_options and ai_level != "NODE":
            first = order_options(exact_city_options)[0]
            return normalize_city(first), all_options, {"status": "MATCHED_CITY", "text": text, "top": first, "ai_level": ai_level}
        if strong_node_options and ai_level == "NODE":
            first = order_options(strong_node_options)[0]
            return normalize_node(first), all_options, {"status": "MATCHED_NODE_AI", "text": text, "top": first, "ai_level": ai_level}
        if city_options and ai_level in {"CITY", ""}:
            first = order_options(city_options)[0]
            return normalize_city(first), all_options, {"status": "MATCHED_CITY", "text": text, "top": first, "ai_level": ai_level}
        if strong_node_options:
            first = order_options(strong_node_options)[0]
            return normalize_node(first), all_options, {"status": "MATCHED_NODE_STRONG", "text": text, "top": first, "ai_level": ai_level}
        if city_options:
            first = order_options(city_options)[0]
            return normalize_city(first), all_options, {"status": "MATCHED_CITY", "text": text, "top": first, "ai_level": ai_level}
        return {"match_level_code": "RAW"}, all_options or [{"level": "RAW", "name": text, "score": "0.0"}], {"status": "UNMATCHED", "text": text, "ai_level": ai_level}
