"""Vessel asset listing and query methods."""

from __future__ import annotations

from app.modules.vessel.asset.summary_methods import VesselAssetSummaryMixin
from app.modules.vessel.display_helpers import data_source_codes
from app.modules.vessel.shared import base as _base

globals().update({name: getattr(_base, name) for name in dir(_base) if not name.startswith("__")})


PROFILE_SEARCH_COLUMNS = (
    VesselProfile.vessel_profile_code,
    VesselProfile.ship_name,
    VesselProfile.ship_name_en,
    VesselProfile.current_mmsi,
    VesselOwnerPeriod.party_name,
    VesselOperatorPeriod.operator_name,
    VesselContact.contact_name,
    VesselContact.mobile_phone,
)

ASSET_SUMMARY_FIELDS = (
    "ship_name",
    "current_mmsi",
    "ship_type_code",
    "ship_type_name",
    "deadweight_ton",
    "length_m",
    "width_m",
    "design_draft_m",
    "building_year",
    "ship_age",
    "primary_owner_name",
    "primary_operator_name",
    "primary_contact_name",
    "contact_available",
)


class VesselAssetListMixin(VesselAssetSummaryMixin):
    """Asset list queries and list item assembly."""

    async def list_vessels(self, query) -> PageResponse[VesselListItemResponse]:
        stmt = self._profile_list_stmt(query)
        total, rows = await self._page_profiles(stmt, query, [VesselProfile.updated_at.desc(), VesselProfile.id.desc()])
        return PageResponse[VesselListItemResponse](
            total=total,
            page=query.page,
            page_size=query.page_size,
            items=await self._build_list_items(rows),
        )

    async def list_assets(self, query) -> VesselAssetPageResponse:
        stmt = self._profile_list_stmt(query, include_summary=True)
        total, rows = await self._page_profiles(stmt, query, self._asset_order_by(query))
        page_summary = await self._asset_query_summary(stmt)
        return VesselAssetPageResponse(
            total=total,
            page=query.page,
            page_size=query.page_size,
            items=await self._build_asset_items(rows),
            coverage_rate=page_summary["coverage_rate"],
            confidence_level=page_summary["confidence_level"],
            generated_at=page_summary["generated_at"],
            summary_status_counts=page_summary["summary_status_counts"],
            summarized_count=page_summary["summarized_count"],
            missing_summary_count=page_summary["missing_summary_count"],
            failed_summary_count=page_summary["failed_summary_count"],
            stale_summary_count=page_summary["stale_summary_count"],
            source_updated_at=page_summary["source_updated_at"],
            uncertainty_reasons=page_summary["uncertainty_reasons"],
        )

    async def _page_profiles(self, stmt: Any, query: Any, order_by: list[Any]) -> tuple[int, list[VesselProfile]]:
        total_subquery = stmt.with_only_columns(VesselProfile.id).group_by(VesselProfile.id).subquery()
        total = int((await self.db.execute(select(func.count()).select_from(total_subquery))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.group_by(VesselProfile.id)
                .order_by(*order_by)
                .offset((query.page - 1) * query.page_size)
                .limit(query.page_size)
            )
        ).scalars().all()
        return total, list(rows)

    def _profile_list_stmt(self, query: Any, *, include_summary: bool = False):
        owner_join = [VesselOwnerPeriod.vessel_profile_id == VesselProfile.id, VesselOwnerPeriod.is_current.is_(True)]
        operator_join = [VesselOperatorPeriod.vessel_profile_id == VesselProfile.id, VesselOperatorPeriod.is_current.is_(True)]
        contact_join = [VesselContact.vessel_profile_id == VesselProfile.id]
        if include_summary:
            owner_join += [VesselOwnerPeriod.end_date.is_(None), VesselOwnerPeriod.voided_at.is_(None)]
            operator_join += [VesselOperatorPeriod.end_date.is_(None), VesselOperatorPeriod.voided_at.is_(None)]
            contact_join += [VesselContact.is_current.is_(True), VesselContact.end_date.is_(None), VesselContact.voided_at.is_(None)]
        stmt = (
            select(VesselProfile)
            .outerjoin(VesselCapacityDimension, VesselCapacityDimension.vessel_profile_id == VesselProfile.id)
            .outerjoin(VesselBuildInfo, VesselBuildInfo.vessel_profile_id == VesselProfile.id)
            .outerjoin(VesselOwnerPeriod, and_(*owner_join))
            .outerjoin(VesselOperatorPeriod, and_(*operator_join))
            .outerjoin(VesselContact, and_(*contact_join))
            .where(VesselProfile.deleted_at.is_(None))
        )
        if include_summary:
            stmt = stmt.outerjoin(VesselProfileSummary, VesselProfileSummary.vessel_profile_id == VesselProfile.id)
        return self._apply_profile_filters(stmt, query, include_summary=include_summary)

    def _asset_profile_stmt(self, query: Any):
        return self._profile_list_stmt(query, include_summary=True)

    def _apply_profile_filters(self, stmt: Any, query: Any, *, include_summary: bool) -> Any:
        if getattr(query, "keyword", None):
            like_value = f"%{query.keyword.strip()}%"
            stmt = stmt.where(or_(*(column.ilike(like_value) for column in PROFILE_SEARCH_COLUMNS)))
        for attr, column, fuzzy in (
            ("mmsi", VesselProfile.current_mmsi, True),
            ("ship_name", VesselProfile.ship_name, True),
            ("ship_type_code", VesselProfile.ship_type_code, False),
            ("profile_status_code", VesselProfile.profile_status_code, False),
            ("business_region_id", VesselProfile.business_region_id, False),
            ("owner_name", VesselOwnerPeriod.party_name, True),
            ("operator_name", VesselOperatorPeriod.operator_name, True),
        ):
            value = getattr(query, attr, None)
            if value:
                stmt = stmt.where(column.ilike(f"%{value.strip()}%") if fuzzy else column == value)
        city_code = getattr(query, "registry_city_code", None) or getattr(query, "city_code", None)
        if city_code:
            city_clause = VesselProfile.registry_city_code == city_code
            stmt = stmt.where(or_(city_clause, VesselProfileSummary.latest_city_code == city_code) if include_summary else city_clause)
        if include_summary and getattr(query, "region_code", None):
            stmt = stmt.where(VesselProfileSummary.latest_city_code == query.region_code)
        for attr, column, op in (
            ("deadweight_min", VesselCapacityDimension.deadweight_ton, "ge"),
            ("deadweight_max", VesselCapacityDimension.deadweight_ton, "le"),
            ("length_min", VesselCapacityDimension.length_m, "ge"),
            ("length_max", VesselCapacityDimension.length_m, "le"),
            ("draft_min", VesselCapacityDimension.design_draft_m, "ge"),
            ("draft_max", VesselCapacityDimension.design_draft_m, "le"),
            ("updated_from", VesselProfile.updated_at, "ge"),
            ("updated_to", VesselProfile.updated_at, "le"),
        ):
            value = getattr(query, attr, None)
            if value is not None:
                stmt = stmt.where(column >= value if op == "ge" else column <= value)
        current_year = datetime.utcnow().year
        if getattr(query, "ship_age_min", None) is not None:
            stmt = stmt.where(VesselBuildInfo.building_year <= current_year - query.ship_age_min)
        if getattr(query, "ship_age_max", None) is not None:
            stmt = stmt.where(VesselBuildInfo.building_year >= current_year - query.ship_age_max)
        if getattr(query, "contact_available", None) is not None:
            stmt = stmt.where(VesselContact.is_available.is_(query.contact_available))
        return self._apply_asset_summary_filters(stmt, query) if include_summary else stmt

    def _apply_asset_summary_filters(self, stmt: Any, query: Any) -> Any:
        for attr, column in (
            ("quality_level", VesselProfileSummary.data_quality_level),
            ("risk_level", VesselProfileSummary.risk_level),
        ):
            stmt = self._apply_summary_filter(stmt, column, getattr(query, attr, None))
        freshness = getattr(query, "ais_freshness_level", None) or getattr(query, "freshness_level", None)
        stmt = self._apply_summary_filter(stmt, VesselProfileSummary.ais_freshness_level, freshness)
        status_code = getattr(query, "summary_status_code", None)
        if status_code == "MISSING":
            stmt = stmt.where(or_(VesselProfileSummary.id.is_(None), VesselProfileSummary.summary_status_code == "MISSING"))
        elif status_code == "STALE":
            stmt = stmt.where(or_(VesselProfileSummary.summary_status_code == "STALE", self._summary_stale_condition()))
        elif status_code in SUMMARY_READY_STATUSES:
            stmt = stmt.where(VesselProfileSummary.summary_status_code == status_code, not_(self._summary_stale_condition()))
        elif status_code:
            stmt = stmt.where(VesselProfileSummary.summary_status_code == status_code)
        if getattr(query, "source_layer", None):
            stmt = stmt.where(VesselProfileSummary.source_layer == query.source_layer)
        sample_tag = getattr(query, "analysis_sample_tag", None) or getattr(query, "sample_tag", None)
        return stmt.where(VesselProfileSummary.analysis_sample_tags_key.ilike(f"%|{sample_tag}|%")) if sample_tag else stmt

    def _apply_summary_filter(self, stmt: Any, column: Any, value: str | None) -> Any:
        if not value:
            return stmt
        if value == "UNKNOWN":
            return stmt.where(or_(VesselProfileSummary.id.is_(None), column == "UNKNOWN"))
        return stmt.where(column == value)

    def _asset_order_by(self, query: Any) -> list[Any]:
        default_order = [
            case(
                (VesselProfile.source_type_code == "TMS_HIGH_VALUE", 0),
                (VesselProfile.source_type_code == "TMS", 1),
                (VesselProfile.source_type_code == "HIGH_VALUE_INLAND", 2),
                else_=9,
            ).asc(),
            VesselProfileSummary.profile_completeness_rate.desc().nullslast(),
            VesselProfileSummary.data_quality_score.desc().nullslast(),
            case((VesselProfileSummary.contact_available.is_(True), 0), else_=1).asc(),
            VesselCapacityDimension.deadweight_ton.desc().nullslast(),
            VesselProfile.updated_at.desc(),
            VesselProfile.id.desc(),
        ]
        sort_orders = {
            "quality_score_asc": [VesselProfileSummary.data_quality_score.asc().nullslast()],
            "quality_score_desc": [VesselProfileSummary.data_quality_score.desc().nullslast()],
            "refreshed_at_desc": [VesselProfileSummary.refreshed_at.desc().nullslast()],
            "ais_time_desc": [VesselProfileSummary.latest_position_time.desc().nullslast()],
        }
        return sort_orders.get(getattr(query, "sort", None), default_order) + (
            [] if getattr(query, "sort", None) not in sort_orders else [VesselProfile.updated_at.desc(), VesselProfile.id.desc()]
        )

    async def _build_asset_items(self, profiles: list[VesselProfile]) -> list[VesselAssetListItemResponse]:
        if not profiles:
            return []
        ids = [row.id for row in profiles]
        base_items = await self._build_list_items(profiles)
        summaries = await self._map_by_profile(VesselProfileSummary, ids)
        counts = await self._active_quality_issue_counts(ids)
        label_map = await _load_label_map(self.db)
        items: list[VesselAssetListItemResponse] = []
        for item in base_items:
            summary = summaries.get(item.id)
            items.append(
                self._asset_item_from_summary(item, summary, counts.get(item.id, 0), label_map)
                if summary is not None
                else self._asset_item_without_summary(item, counts.get(item.id, 0), label_map)
            )
        return items

    def _asset_item_without_summary(
        self,
        item: VesselListItemResponse,
        quality_count: int,
        label_map: dict[str, dict[str, str]],
    ) -> VesselAssetListItemResponse:
        notes = ["摘要未生成，请刷新摘要后再用于资产分析"]
        if quality_count:
            notes.append(f"当前存在 {quality_count} 条未关闭质量问题")
        return VesselAssetListItemResponse(
            **item.model_dump(),
            profile_completeness_rate=None,
            data_quality_score=None,
            data_quality_level="UNKNOWN",
            identity_confidence_level="UNKNOWN",
            contact_trust_level="UNKNOWN",
            subject_consistency_level="UNKNOWN",
            quality_level="UNKNOWN",
            risk_level="UNKNOWN",
            ais_freshness_level="UNKNOWN",
            quality_issue_count=quality_count,
            analysis_sample_tags=[],
            data_sources=["VESSEL_PROFILE", "RELATION_LEDGER", "QUALITY_ISSUE"],
            uncertainty_notes=notes,
            summary_status_code="MISSING",
            summary_status_name=label_map.get("VESSEL_SUMMARY_STATUS", {}).get("MISSING"),
            evidence_updated_at=item.updated_at,
            explain_reason=notes[0],
            next_actions=self._asset_next_actions(
                item.id,
                summary_status_code="MISSING",
                quality_issue_count=quality_count,
                risk_level="UNKNOWN",
                ais_freshness_level="UNKNOWN",
                subject_consistency_level="UNKNOWN",
            ),
            evidence_gaps=self._asset_evidence_gaps(
                summary_status_code="MISSING",
                quality_issue_count=quality_count,
                certificate_missing_count=0,
                certificate_expired_count=0,
                ais_freshness_level="UNKNOWN",
                subject_consistency_level="UNKNOWN",
            ),
            source_object_anchor=f"VESSEL_PROFILE:{item.id}",
            workbench_group="ASSET",
        )

    def _asset_item_from_summary(
        self,
        item: VesselListItemResponse,
        summary: VesselProfileSummary,
        _quality_count: int,
        label_map: dict[str, dict[str, str]],
    ) -> VesselAssetListItemResponse:
        payload = item.model_dump()
        for key in ASSET_SUMMARY_FIELDS:
            value = getattr(summary, key, None)
            if value is not None:
                payload[key] = value
        payload["primary_contact_phone"] = summary.primary_contact_phone_masked
        summary_status_code = self._effective_summary_status(summary)
        uncertainty_notes = list(summary.uncertainty_notes_json or [])
        if summary_status_code == "STALE" and not any("过期" in item for item in uncertainty_notes):
            uncertainty_notes.append("摘要已过期，请刷新摘要后再用于资产分析")
        return VesselAssetListItemResponse(
            **payload,
            profile_completeness_rate=summary.profile_completeness_rate,
            data_quality_score=summary.data_quality_score,
            data_quality_level=summary.data_quality_level,
            identity_confidence_level=summary.identity_confidence_level,
            contact_trust_level=summary.contact_trust_level,
            subject_consistency_level=summary.subject_consistency_level,
            quality_level=summary.data_quality_level,
            risk_level=summary.risk_level,
            ais_freshness_level=summary.ais_freshness_level,
            quality_issue_count=summary.quality_issue_count,
            missing_field_count=summary.missing_field_count,
            conflict_count=summary.conflict_count,
            certificate_missing_count=summary.certificate_missing_count,
            certificate_expiring_count=summary.certificate_expiring_count,
            certificate_expired_count=summary.certificate_expired_count,
            latest_position_time=summary.latest_position_time,
            latest_city_code=summary.latest_city_code,
            latest_city_name=summary.latest_city_name,
            analysis_sample_tags=data_source_codes(summary.analysis_sample_tags_json),
            data_sources=data_source_codes(summary.data_sources_json),
            uncertainty_notes=uncertainty_notes,
            risk_evidence_summary=summary.risk_evidence_summary_json or [],
            summary_status_code=summary_status_code,
            summary_status_name=label_map.get("VESSEL_SUMMARY_STATUS", {}).get(summary_status_code),
            summary_version=summary.summary_version,
            source_layer=summary.source_layer,
            coverage_rate=summary.coverage_rate,
            refreshed_at=summary.refreshed_at,
            source_updated_at=summary.source_updated_at,
            refresh_error=summary.refresh_error,
            evidence_updated_at=summary.refreshed_at or summary.source_updated_at or item.updated_at,
            explain_reason=self._asset_explain_reason(summary_status_code, uncertainty_notes, summary),
            next_actions=self._asset_next_actions(
                item.id,
                summary_status_code=summary_status_code,
                quality_issue_count=summary.quality_issue_count,
                risk_level=summary.risk_level,
                ais_freshness_level=summary.ais_freshness_level,
                subject_consistency_level=summary.subject_consistency_level,
            ),
            evidence_gaps=self._asset_evidence_gaps(
                summary_status_code=summary_status_code,
                quality_issue_count=summary.quality_issue_count,
                certificate_missing_count=summary.certificate_missing_count,
                certificate_expired_count=summary.certificate_expired_count,
                ais_freshness_level=summary.ais_freshness_level,
                subject_consistency_level=summary.subject_consistency_level,
            ),
            source_object_anchor=f"VESSEL_PROFILE:{item.id}",
            workbench_group="ASSET",
        )

    @staticmethod
    def _asset_explain_reason(summary_status_code: str, uncertainty_notes: list[str], summary: VesselProfileSummary) -> str | None:
        if uncertainty_notes:
            return uncertainty_notes[0]
        if summary.quality_issue_count:
            return f"当前存在 {summary.quality_issue_count} 条未关闭质量问题。"
        if summary.risk_level in {"HIGH", "MEDIUM", "UNKNOWN"}:
            return f"合规风险等级为 {summary.risk_level}，需要查看风险证据和缺口。"
        if summary_status_code in {"MISSING", "STALE", "FAILED", "PARTIAL"}:
            return "资产摘要不可直接作为高可信结论使用，需要刷新或补齐来源。"
        return None

    def _asset_next_actions(
        self,
        vessel_id: int,
        *,
        summary_status_code: str,
        quality_issue_count: int,
        risk_level: str,
        ais_freshness_level: str,
        subject_consistency_level: str,
    ) -> list[VesselRecommendedAction]:
        actions: list[VesselRecommendedAction] = []
        specs = (
            (quality_issue_count, "OPEN_QUALITY", "处理质量问题", "/vessels/quality", "QUALITY", {"vessel_id": vessel_id, "status_code": "OPEN"}, "查看该船未关闭质量问题，修复后重新校验。"),
            (risk_level in {"HIGH", "MEDIUM", "UNKNOWN"}, "OPEN_COMPLIANCE", "查看合规证明链", f"/vessels/{vessel_id}/compliance", "RISK", None, "查看风险信号、证据缺口和复核入口。"),
            (subject_consistency_level in {"LOW", "UNKNOWN"}, "OPEN_RELATIONS", "补齐主体结论", f"/vessels/{vessel_id}/relations", "EVIDENCE", None, "主体关系与证据结论统一在主体关系页维护。"),
            (ais_freshness_level in {"STALE", "EXPIRED", "UNKNOWN"}, "OPEN_AIS", "核对 AIS", "/vessels/ais-situation", "AIS", {"vessel_id": vessel_id}, "核对 AIS 最新位置、MMSI 映射和轨迹可用性。"),
            (summary_status_code in {"MISSING", "STALE", "FAILED", "PARTIAL"}, "REFRESH_SUMMARY", "刷新摘要", f"/vessels/{vessel_id}/profile-card", "ASSET", None, "摘要会重算质量、主体、证书和 AIS 可信状态；失败时需查看错误原因。"),
        )
        for enabled, action_type, label, target_path, group, payload, description in specs:
            if not enabled:
                continue
            actions.append(
                VesselRecommendedAction(
                    action_type=action_type,
                    label=label,
                    target_path=target_path,
                    target_object_type="VESSEL_PROFILE",
                    target_object_id=str(vessel_id),
                    source_object_anchor=f"VESSEL_PROFILE:{vessel_id}",
                    workbench_group=group,
                    payload=payload,
                    description=description,
                )
            )
        return actions[:3]

    @staticmethod
    def _asset_evidence_gaps(
        *,
        summary_status_code: str,
        quality_issue_count: int,
        certificate_missing_count: int,
        certificate_expired_count: int,
        ais_freshness_level: str,
        subject_consistency_level: str,
    ) -> list[str]:
        return [
            label
            for enabled, label in (
                (summary_status_code in {"MISSING", "STALE", "FAILED", "PARTIAL"}, "资产摘要"),
                (quality_issue_count, "质量问题重新校验"),
                (subject_consistency_level in {"LOW", "UNKNOWN"}, "主体关系结论"),
                (certificate_missing_count or certificate_expired_count, "证书有效证据"),
                (ais_freshness_level in {"STALE", "EXPIRED", "UNKNOWN"}, "AIS 最新观测"),
            )
            if enabled
        ]

    async def _build_list_items(self, profiles: list[VesselProfile]) -> list[VesselListItemResponse]:
        if not profiles:
            return []
        ids = [row.id for row in profiles]
        label_map = await _load_label_map(self.db)
        city_map = await _load_city_map(self.db, [row.registry_city_code for row in profiles if row.registry_city_code])
        region_map = await _load_region_map(self.db, [row.business_region_id for row in profiles if row.business_region_id])
        capacities = await self._map_by_profile(VesselCapacityDimension, ids)
        builds = await self._map_by_profile(VesselBuildInfo, ids)
        owners = await self._first_by_profile(VesselOwnerPeriod, ids)
        operators = await self._first_by_profile(VesselOperatorPeriod, ids)
        contacts = await self._first_by_profile(VesselContact, ids)
        items: list[VesselListItemResponse] = []
        for profile in profiles:
            base = _profile_response(profile, label_map=label_map, city_map=city_map, region_map=region_map).model_dump()
            capacity = capacities.get(profile.id)
            build = builds.get(profile.id)
            contact = contacts.get(profile.id)
            items.append(
                VesselListItemResponse(
                    **base,
                    building_year=getattr(build, "building_year", None),
                    ship_age=_ship_age(getattr(build, "building_year", None)),
                    deadweight_ton=capacity.deadweight_ton if capacity else None,
                    length_m=capacity.length_m if capacity else None,
                    width_m=capacity.width_m if capacity else None,
                    design_draft_m=capacity.design_draft_m if capacity else None,
                    size_text=_size_text(capacity),
                    primary_owner_name=getattr(owners.get(profile.id), "party_name", None),
                    primary_operator_name=getattr(operators.get(profile.id), "operator_name", None),
                    primary_contact_name=getattr(contact, "contact_name", None),
                    primary_contact_phone=getattr(contact, "mobile_phone", None),
                    contact_available=getattr(contact, "is_available", None),
                )
            )
        return items
