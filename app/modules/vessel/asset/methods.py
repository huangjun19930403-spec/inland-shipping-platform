"""Implementation methods for the vessel asset domain."""

from __future__ import annotations

from app.modules.vessel.shared import base as _base

globals().update({name: getattr(_base, name) for name in dir(_base) if not name.startswith("__")})


class VesselAssetMixin:
    """Implementation methods for the vessel asset domain."""

    async def list_vessels(self, query) -> PageResponse[VesselListItemResponse]:
        stmt = (
            select(VesselProfile)
            .outerjoin(VesselCapacityDimension, VesselCapacityDimension.vessel_profile_id == VesselProfile.id)
            .outerjoin(VesselBuildInfo, VesselBuildInfo.vessel_profile_id == VesselProfile.id)
            .outerjoin(
                VesselOwnerPeriod,
                and_(VesselOwnerPeriod.vessel_profile_id == VesselProfile.id, VesselOwnerPeriod.is_current.is_(True)),
            )
            .outerjoin(
                VesselOperatorPeriod,
                and_(VesselOperatorPeriod.vessel_profile_id == VesselProfile.id, VesselOperatorPeriod.is_current.is_(True)),
            )
            .outerjoin(VesselContact, VesselContact.vessel_profile_id == VesselProfile.id)
            .where(VesselProfile.deleted_at.is_(None))
        )
        if query.keyword:
            like_value = f"%{query.keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    VesselProfile.vessel_profile_code.ilike(like_value),
                    VesselProfile.ship_name.ilike(like_value),
                    VesselProfile.ship_name_en.ilike(like_value),
                    VesselProfile.current_mmsi.ilike(like_value),
                    VesselOwnerPeriod.party_name.ilike(like_value),
                    VesselOperatorPeriod.operator_name.ilike(like_value),
                    VesselContact.contact_name.ilike(like_value),
                    VesselContact.mobile_phone.ilike(like_value),
                )
            )
        if query.mmsi:
            stmt = stmt.where(VesselProfile.current_mmsi.ilike(f"%{query.mmsi.strip()}%"))
        if query.ship_name:
            stmt = stmt.where(VesselProfile.ship_name.ilike(f"%{query.ship_name.strip()}%"))
        if query.ship_type_code:
            stmt = stmt.where(VesselProfile.ship_type_code == query.ship_type_code)
        if query.profile_status_code:
            stmt = stmt.where(VesselProfile.profile_status_code == query.profile_status_code)
        city_code = query.registry_city_code or query.city_code
        if city_code:
            stmt = stmt.where(VesselProfile.registry_city_code == city_code)
        if query.business_region_id:
            stmt = stmt.where(VesselProfile.business_region_id == query.business_region_id)
        if query.deadweight_min is not None:
            stmt = stmt.where(VesselCapacityDimension.deadweight_ton >= query.deadweight_min)
        if query.deadweight_max is not None:
            stmt = stmt.where(VesselCapacityDimension.deadweight_ton <= query.deadweight_max)
        current_year = datetime.utcnow().year
        if query.ship_age_min is not None:
            stmt = stmt.where(VesselBuildInfo.building_year <= current_year - query.ship_age_min)
        if query.ship_age_max is not None:
            stmt = stmt.where(VesselBuildInfo.building_year >= current_year - query.ship_age_max)
        if query.length_min is not None:
            stmt = stmt.where(VesselCapacityDimension.length_m >= query.length_min)
        if query.length_max is not None:
            stmt = stmt.where(VesselCapacityDimension.length_m <= query.length_max)
        if query.draft_min is not None:
            stmt = stmt.where(VesselCapacityDimension.design_draft_m >= query.draft_min)
        if query.draft_max is not None:
            stmt = stmt.where(VesselCapacityDimension.design_draft_m <= query.draft_max)
        if query.owner_name:
            stmt = stmt.where(VesselOwnerPeriod.party_name.ilike(f"%{query.owner_name.strip()}%"))
        if query.operator_name:
            stmt = stmt.where(VesselOperatorPeriod.operator_name.ilike(f"%{query.operator_name.strip()}%"))
        if query.contact_available is not None:
            stmt = stmt.where(VesselContact.is_available.is_(query.contact_available))
        if query.updated_from:
            stmt = stmt.where(VesselProfile.updated_at >= query.updated_from)
        if query.updated_to:
            stmt = stmt.where(VesselProfile.updated_at <= query.updated_to)

        total_subquery = stmt.with_only_columns(VesselProfile.id).group_by(VesselProfile.id).subquery()
        total = int((await self.db.execute(select(func.count()).select_from(total_subquery))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.group_by(VesselProfile.id)
                .order_by(VesselProfile.updated_at.desc(), VesselProfile.id.desc())
                .offset((query.page - 1) * query.page_size)
                .limit(query.page_size)
            )
        ).scalars().all()
        return PageResponse[VesselListItemResponse](
            total=total,
            page=query.page,
            page_size=query.page_size,
            items=await self._build_list_items(list(rows)),
        )

    async def list_assets(self, query) -> VesselAssetPageResponse:
        stmt = self._asset_profile_stmt(query)
        total_subquery = stmt.with_only_columns(VesselProfile.id).group_by(VesselProfile.id).subquery()
        total = int((await self.db.execute(select(func.count()).select_from(total_subquery))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.group_by(VesselProfile.id)
                .order_by(*self._asset_order_by(query))
                .offset((query.page - 1) * query.page_size)
                .limit(query.page_size)
            )
        ).scalars().all()
        items = await self._build_asset_items(list(rows))
        page_summary = await self._asset_query_summary(stmt)
        return VesselAssetPageResponse(
            total=total,
            page=query.page,
            page_size=query.page_size,
            items=items,
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

    async def asset_summary(self) -> VesselAssetSummaryResponse:
        generated_at = datetime.utcnow()
        total_profiles = int(
            await self.db.scalar(select(func.count(VesselProfile.id)).where(VesselProfile.deleted_at.is_(None))) or 0
        )
        summary_total = int(
            await self.db.scalar(
                select(func.count(VesselProfileSummary.id))
                .join(VesselProfile, VesselProfile.id == VesselProfileSummary.vessel_profile_id)
                .where(VesselProfile.deleted_at.is_(None))
            )
            or 0
        )
        label_map = await _load_label_map(self.db)
        missing_without_row = max(0, total_profiles - summary_total)
        quality_distribution = await self._summary_distribution(
            VesselProfileSummary.data_quality_level,
            "VESSEL_CONFIDENCE_LEVEL",
            label_map,
            missing_unknown=missing_without_row,
        )
        risk_distribution = await self._summary_distribution(
            VesselProfileSummary.risk_level,
            "VESSEL_RISK_LEVEL",
            label_map,
            missing_unknown=missing_without_row,
        )
        ais_distribution = await self._summary_distribution(
            VesselProfileSummary.ais_freshness_level,
            "VESSEL_AIS_FRESHNESS_LEVEL",
            label_map,
            missing_unknown=missing_without_row,
        )
        status_distribution = await self._summary_status_distribution(label_map, missing_without_row=missing_without_row)
        status_counts = {item.code: item.count for item in status_distribution}
        missing_summary_count = status_counts.get("MISSING", 0)
        failed_summary_count = status_counts.get("FAILED", 0)
        stale_summary_count = status_counts.get("STALE", 0)
        summarized_count = max(0, total_profiles - missing_summary_count)
        coverage_rate = _percent(summarized_count, total_profiles)
        confidence_level = _coverage_confidence_level(coverage_rate, failed_summary_count)
        return VesselAssetSummaryResponse(
            total_profiles=total_profiles,
            summarized_count=summarized_count,
            missing_summary_count=missing_summary_count,
            failed_summary_count=failed_summary_count,
            stale_summary_count=stale_summary_count,
            coverage_rate=coverage_rate,
            confidence_level=confidence_level,
            generated_at=generated_at,
            quality_distribution=quality_distribution,
            risk_distribution=risk_distribution,
            ais_freshness_distribution=ais_distribution,
            summary_status_distribution=status_distribution,
        )

    async def refresh_vessel_summary(self, vessel_id: int) -> VesselAssetListItemResponse:
        profile = await self._require_profile(vessel_id)
        try:
            await self._upsert_vessel_summary(profile)
        except Exception as exc:  # noqa: BLE001
            logger.warning("vessel summary refresh failed for profile %s: %s", vessel_id, exc)
            await self.db.rollback()
            profile = await self._require_profile(vessel_id)
            await self._mark_vessel_summary_failed(profile, str(exc))
        await self.db.commit()
        return (await self._build_asset_items([profile]))[0]

    async def refresh_vessel_summaries_batch(self, body: VesselSummaryRefreshBatchRequest) -> VesselSummaryRefreshBatchResponse:
        seen: set[int] = set()
        vessel_ids = [int(vessel_id) for vessel_id in body.vessel_ids if not (int(vessel_id) in seen or seen.add(int(vessel_id)))]
        results: list[VesselSummaryRefreshBatchItemResponse] = []
        for vessel_id in vessel_ids:
            ship_name: str | None = None
            try:
                profile = await self._require_profile(vessel_id)
                before = (await self._build_asset_items([profile]))[0]
                ship_name = before.ship_name
                after = await self.refresh_vessel_summary(vessel_id)
                diff = self._summary_refresh_diff(before, after)
                failure_reason = after.refresh_error or None
                results.append(
                    VesselSummaryRefreshBatchItemResponse(
                        vessel_id=vessel_id,
                        ship_name=after.ship_name,
                        success=failure_reason is None,
                        summary_diff=diff,
                        refresh_failure_reason=failure_reason,
                        item=after,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                await self.db.rollback()
                results.append(
                    VesselSummaryRefreshBatchItemResponse(
                        vessel_id=vessel_id,
                        ship_name=ship_name,
                        success=False,
                        refresh_failure_reason=str(exc)[:1000],
                    )
                )
        success_count = sum(1 for item in results if item.success)
        return VesselSummaryRefreshBatchResponse(
            total=len(results),
            success_count=success_count,
            failed_count=len(results) - success_count,
            items=results,
        )

    def _summary_refresh_diff(
        self,
        before: VesselAssetListItemResponse,
        after: VesselAssetListItemResponse,
    ) -> list[VesselSummaryRefreshDiffResponse]:
        fields = [
            ("summary_status_code", "摘要状态"),
            ("data_quality_level", "数据质量"),
            ("risk_level", "风险等级"),
            ("ais_freshness_level", "AIS 新鲜度"),
            ("quality_issue_count", "质量问题数"),
            ("certificate_missing_count", "缺失证书数"),
            ("certificate_expiring_count", "临期证书数"),
            ("certificate_expired_count", "过期证书数"),
            ("coverage_rate", "覆盖率"),
            ("refresh_error", "失败原因"),
        ]
        diffs: list[VesselSummaryRefreshDiffResponse] = []
        for field_name, label in fields:
            old_value = getattr(before, field_name, None)
            new_value = getattr(after, field_name, None)
            if old_value == new_value:
                continue
            diffs.append(
                VesselSummaryRefreshDiffResponse(
                    field_name=field_name,
                    before=None if old_value is None else str(old_value),
                    after=None if new_value is None else str(new_value),
                    message=f"{label}从 {old_value if old_value not in (None, '') else '-'} 变为 {new_value if new_value not in (None, '') else '-'}",
                )
            )
        if not diffs:
            diffs.append(VesselSummaryRefreshDiffResponse(field_name="summary", message="摘要刷新完成，核心指标暂无变化。"))
        return diffs

    async def _refresh_summary_best_effort(self, vessel_id: int) -> None:
        try:
            profile = await self._require_profile(vessel_id)
            await self._upsert_vessel_summary(profile)
            await self.db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("best-effort vessel summary refresh failed for profile %s: %s", vessel_id, exc)
            await self.db.rollback()
            try:
                profile = await self._require_profile(vessel_id)
                await self._mark_vessel_summary_failed(profile, str(exc))
                await self.db.commit()
            except Exception as mark_exc:  # noqa: BLE001
                logger.warning("mark vessel summary failed state failed for profile %s: %s", vessel_id, mark_exc)
                await self.db.rollback()

    def _asset_profile_stmt(self, query: Any):
        owner_join = and_(
            VesselOwnerPeriod.vessel_profile_id == VesselProfile.id,
            VesselOwnerPeriod.is_current.is_(True),
            VesselOwnerPeriod.end_date.is_(None),
            VesselOwnerPeriod.voided_at.is_(None),
        )
        operator_join = and_(
            VesselOperatorPeriod.vessel_profile_id == VesselProfile.id,
            VesselOperatorPeriod.is_current.is_(True),
            VesselOperatorPeriod.end_date.is_(None),
            VesselOperatorPeriod.voided_at.is_(None),
        )
        contact_join = and_(
            VesselContact.vessel_profile_id == VesselProfile.id,
            VesselContact.is_current.is_(True),
            VesselContact.end_date.is_(None),
            VesselContact.voided_at.is_(None),
        )
        stmt = (
            select(VesselProfile)
            .outerjoin(VesselCapacityDimension, VesselCapacityDimension.vessel_profile_id == VesselProfile.id)
            .outerjoin(VesselBuildInfo, VesselBuildInfo.vessel_profile_id == VesselProfile.id)
            .outerjoin(VesselOwnerPeriod, owner_join)
            .outerjoin(VesselOperatorPeriod, operator_join)
            .outerjoin(VesselContact, contact_join)
            .outerjoin(VesselProfileSummary, VesselProfileSummary.vessel_profile_id == VesselProfile.id)
            .where(VesselProfile.deleted_at.is_(None))
        )
        if getattr(query, "keyword", None):
            like_value = f"%{query.keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    VesselProfile.vessel_profile_code.ilike(like_value),
                    VesselProfile.ship_name.ilike(like_value),
                    VesselProfile.ship_name_en.ilike(like_value),
                    VesselProfile.current_mmsi.ilike(like_value),
                    VesselOwnerPeriod.party_name.ilike(like_value),
                    VesselOperatorPeriod.operator_name.ilike(like_value),
                    VesselContact.contact_name.ilike(like_value),
                    VesselContact.mobile_phone.ilike(like_value),
                )
            )
        if getattr(query, "mmsi", None):
            stmt = stmt.where(VesselProfile.current_mmsi.ilike(f"%{query.mmsi.strip()}%"))
        if getattr(query, "ship_name", None):
            stmt = stmt.where(VesselProfile.ship_name.ilike(f"%{query.ship_name.strip()}%"))
        if getattr(query, "ship_type_code", None):
            stmt = stmt.where(VesselProfile.ship_type_code == query.ship_type_code)
        if getattr(query, "profile_status_code", None):
            stmt = stmt.where(VesselProfile.profile_status_code == query.profile_status_code)
        city_code = getattr(query, "registry_city_code", None) or getattr(query, "city_code", None)
        if city_code:
            stmt = stmt.where(or_(VesselProfile.registry_city_code == city_code, VesselProfileSummary.latest_city_code == city_code))
        if getattr(query, "region_code", None):
            stmt = stmt.where(VesselProfileSummary.latest_city_code == query.region_code)
        if getattr(query, "business_region_id", None):
            stmt = stmt.where(VesselProfile.business_region_id == query.business_region_id)
        if getattr(query, "deadweight_min", None) is not None:
            stmt = stmt.where(VesselCapacityDimension.deadweight_ton >= query.deadweight_min)
        if getattr(query, "deadweight_max", None) is not None:
            stmt = stmt.where(VesselCapacityDimension.deadweight_ton <= query.deadweight_max)
        current_year = datetime.utcnow().year
        if getattr(query, "ship_age_min", None) is not None:
            stmt = stmt.where(VesselBuildInfo.building_year <= current_year - query.ship_age_min)
        if getattr(query, "ship_age_max", None) is not None:
            stmt = stmt.where(VesselBuildInfo.building_year >= current_year - query.ship_age_max)
        if getattr(query, "length_min", None) is not None:
            stmt = stmt.where(VesselCapacityDimension.length_m >= query.length_min)
        if getattr(query, "length_max", None) is not None:
            stmt = stmt.where(VesselCapacityDimension.length_m <= query.length_max)
        if getattr(query, "draft_min", None) is not None:
            stmt = stmt.where(VesselCapacityDimension.design_draft_m >= query.draft_min)
        if getattr(query, "draft_max", None) is not None:
            stmt = stmt.where(VesselCapacityDimension.design_draft_m <= query.draft_max)
        if getattr(query, "owner_name", None):
            stmt = stmt.where(VesselOwnerPeriod.party_name.ilike(f"%{query.owner_name.strip()}%"))
        if getattr(query, "operator_name", None):
            stmt = stmt.where(VesselOperatorPeriod.operator_name.ilike(f"%{query.operator_name.strip()}%"))
        if getattr(query, "contact_available", None) is not None:
            stmt = stmt.where(VesselContact.is_available.is_(query.contact_available))
        if getattr(query, "updated_from", None):
            stmt = stmt.where(VesselProfile.updated_at >= query.updated_from)
        if getattr(query, "updated_to", None):
            stmt = stmt.where(VesselProfile.updated_at <= query.updated_to)
        stmt = self._apply_summary_filter(stmt, VesselProfileSummary.data_quality_level, getattr(query, "quality_level", None))
        stmt = self._apply_summary_filter(stmt, VesselProfileSummary.risk_level, getattr(query, "risk_level", None))
        freshness = getattr(query, "ais_freshness_level", None) or getattr(query, "freshness_level", None)
        stmt = self._apply_summary_filter(stmt, VesselProfileSummary.ais_freshness_level, freshness)
        status_code = getattr(query, "summary_status_code", None)
        if status_code:
            if status_code == "MISSING":
                stmt = stmt.where(or_(VesselProfileSummary.id.is_(None), VesselProfileSummary.summary_status_code == "MISSING"))
            elif status_code == "STALE":
                stmt = stmt.where(or_(VesselProfileSummary.summary_status_code == "STALE", self._summary_stale_condition()))
            elif status_code in SUMMARY_READY_STATUSES:
                stmt = stmt.where(
                    VesselProfileSummary.summary_status_code == status_code,
                    not_(self._summary_stale_condition()),
                )
            else:
                stmt = stmt.where(VesselProfileSummary.summary_status_code == status_code)
        source_layer = getattr(query, "source_layer", None)
        if source_layer:
            stmt = stmt.where(VesselProfileSummary.source_layer == source_layer)
        sample_tag = getattr(query, "analysis_sample_tag", None) or getattr(query, "sample_tag", None)
        if sample_tag:
            stmt = stmt.where(VesselProfileSummary.analysis_sample_tags_key.ilike(f"%|{sample_tag}|%"))
        return stmt

    def _apply_summary_filter(self, stmt: Any, column: Any, value: str | None) -> Any:
        if not value:
            return stmt
        if value == "UNKNOWN":
            return stmt.where(or_(VesselProfileSummary.id.is_(None), column == "UNKNOWN"))
        return stmt.where(column == value)

    def _asset_order_by(self, query: Any) -> list[Any]:
        sort = getattr(query, "sort", None)
        if sort == "quality_score_asc":
            return [VesselProfileSummary.data_quality_score.asc().nullslast(), VesselProfile.updated_at.desc(), VesselProfile.id.desc()]
        if sort == "quality_score_desc":
            return [VesselProfileSummary.data_quality_score.desc().nullslast(), VesselProfile.updated_at.desc(), VesselProfile.id.desc()]
        if sort == "refreshed_at_desc":
            return [VesselProfileSummary.refreshed_at.desc().nullslast(), VesselProfile.updated_at.desc(), VesselProfile.id.desc()]
        if sort == "ais_time_desc":
            return [VesselProfileSummary.latest_position_time.desc().nullslast(), VesselProfile.updated_at.desc(), VesselProfile.id.desc()]
        return [VesselProfile.updated_at.desc(), VesselProfile.id.desc()]

    async def _summary_distribution(
        self,
        column: Any,
        dict_code: str,
        label_map: dict[str, dict[str, str]],
        *,
        missing_unknown: int = 0,
        missing_code: str = "UNKNOWN",
    ) -> list[VesselAssetDistributionItemResponse]:
        rows = (
            await self.db.execute(
                select(column, func.count(VesselProfileSummary.id))
                .join(VesselProfile, VesselProfile.id == VesselProfileSummary.vessel_profile_id)
                .where(VesselProfile.deleted_at.is_(None))
                .group_by(column)
            )
        ).all()
        counts: dict[str, int] = {str(code or missing_code): int(count or 0) for code, count in rows}
        if missing_unknown:
            counts[missing_code] = counts.get(missing_code, 0) + missing_unknown
        return [
            VesselAssetDistributionItemResponse(
                code=code,
                name=label_map.get(dict_code, {}).get(code),
                count=count,
            )
            for code, count in sorted(counts.items())
            if count
        ]

    def _summary_stale_condition(self) -> Any:
        return and_(
            VesselProfileSummary.summary_status_code.in_(SUMMARY_READY_STATUSES),
            VesselProfileSummary.source_updated_at.is_not(None),
            VesselProfileSummary.refreshed_at.is_not(None),
            VesselProfileSummary.source_updated_at > VesselProfileSummary.refreshed_at,
        )

    def _summary_effective_status_expr(self) -> Any:
        return case(
            (VesselProfileSummary.id.is_(None), "MISSING"),
            (self._summary_stale_condition(), "STALE"),
            else_=VesselProfileSummary.summary_status_code,
        )

    def _effective_summary_status(self, summary: VesselProfileSummary) -> str:
        if (
            summary.summary_status_code in SUMMARY_READY_STATUSES
            and summary.source_updated_at is not None
            and summary.refreshed_at is not None
            and summary.source_updated_at > summary.refreshed_at
        ):
            return "STALE"
        return summary.summary_status_code

    async def _summary_status_distribution(
        self,
        label_map: dict[str, dict[str, str]],
        *,
        missing_without_row: int = 0,
    ) -> list[VesselAssetDistributionItemResponse]:
        status_expr = self._summary_effective_status_expr()
        rows = (
            await self.db.execute(
                select(status_expr, func.count(VesselProfile.id))
                .outerjoin(VesselProfileSummary, VesselProfileSummary.vessel_profile_id == VesselProfile.id)
                .where(VesselProfile.deleted_at.is_(None))
                .group_by(status_expr)
            )
        ).all()
        counts: dict[str, int] = {str(code or "MISSING"): int(count or 0) for code, count in rows}
        if missing_without_row:
            counts["MISSING"] = max(counts.get("MISSING", 0), missing_without_row)
        return [
            VesselAssetDistributionItemResponse(
                code=code,
                name=label_map.get("VESSEL_SUMMARY_STATUS", {}).get(code),
                count=count,
            )
            for code, count in sorted(counts.items())
            if count
        ]

    async def _asset_query_summary(self, stmt: Any) -> dict[str, Any]:
        generated_at = datetime.utcnow()
        subquery = (
            stmt.with_only_columns(
                VesselProfile.id.label("profile_id"),
                VesselProfileSummary.id.label("summary_id"),
                self._summary_effective_status_expr().label("summary_status_code"),
                VesselProfileSummary.source_updated_at.label("source_updated_at"),
            )
            .group_by(VesselProfile.id)
            .subquery()
        )
        total = int((await self.db.scalar(select(func.count()).select_from(subquery))) or 0)
        status_rows = (
            await self.db.execute(
                select(subquery.c.summary_status_code, func.count(subquery.c.profile_id))
                .select_from(subquery)
                .group_by(subquery.c.summary_status_code)
            )
        ).all()
        status_counts = {str(code or "MISSING"): int(count or 0) for code, count in status_rows}
        missing_count = status_counts.get("MISSING", 0)
        failed_count = status_counts.get("FAILED", 0)
        stale_count = status_counts.get("STALE", 0)
        summarized_count = max(0, total - missing_count)
        coverage_rate = _percent(summarized_count, total)
        source_updated_at = await self.db.scalar(select(func.max(subquery.c.source_updated_at)).select_from(subquery))
        uncertainty_reasons: list[str] = []
        if total == 0:
            uncertainty_reasons.append("当前筛选无船舶资产样本")
        if missing_count:
            uncertainty_reasons.append(f"筛选结果中 {missing_count} 条摘要未生成")
        if failed_count:
            uncertainty_reasons.append(f"筛选结果中 {failed_count} 条摘要生成失败")
        if stale_count:
            uncertainty_reasons.append(f"筛选结果中 {stale_count} 条摘要已过期")
        if coverage_rate < Decimal("100.00") and total:
            uncertainty_reasons.append("筛选结果覆盖率不足 100%，分析结论需结合缺失样本判断")
        return {
            "coverage_rate": coverage_rate,
            "confidence_level": _coverage_confidence_level(coverage_rate, failed_count),
            "generated_at": generated_at,
            "summary_status_counts": status_counts,
            "summarized_count": summarized_count,
            "missing_summary_count": missing_count,
            "failed_summary_count": failed_count,
            "stale_summary_count": stale_count,
            "source_updated_at": source_updated_at,
            "uncertainty_reasons": uncertainty_reasons,
        }

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
            if summary is None:
                quality_count = counts.get(item.id, 0)
                notes = ["摘要未生成，请刷新摘要后再用于资产分析"]
                if quality_count:
                    notes.append(f"当前存在 {quality_count} 条未关闭质量问题")
                items.append(
                    VesselAssetListItemResponse(
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
                )
                continue
            payload = item.model_dump()
            for key in [
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
            ]:
                value = getattr(summary, key, None)
                if value is not None:
                    payload[key] = value
            payload["primary_contact_phone"] = summary.primary_contact_phone_masked
            summary_status_code = self._effective_summary_status(summary)
            uncertainty_notes = list(summary.uncertainty_notes_json or [])
            if summary_status_code == "STALE" and not any("过期" in item for item in uncertainty_notes):
                uncertainty_notes.append("摘要已过期，请刷新摘要后再用于资产分析")
            items.append(
                VesselAssetListItemResponse(
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
                    analysis_sample_tags=summary.analysis_sample_tags_json or [],
                    data_sources=summary.data_sources_json or [],
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
            )
        return items

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
        if quality_issue_count:
            actions.append(
                VesselRecommendedAction(
                    action_type="OPEN_QUALITY",
                    label="处理质量问题",
                    target_path="/vessels/quality",
                    target_object_type="VESSEL_PROFILE",
                    target_object_id=str(vessel_id),
                    source_object_anchor=f"VESSEL_PROFILE:{vessel_id}",
                    workbench_group="QUALITY",
                    payload={"vessel_id": vessel_id, "status_code": "OPEN"},
                    description="查看该船未关闭质量问题，修复后重新校验。",
                )
            )
        if risk_level in {"HIGH", "MEDIUM", "UNKNOWN"}:
            actions.append(
                VesselRecommendedAction(
                    action_type="OPEN_COMPLIANCE",
                    label="查看合规证明链",
                    target_path=f"/vessels/{vessel_id}/compliance",
                    target_object_type="VESSEL_PROFILE",
                    target_object_id=str(vessel_id),
                    source_object_anchor=f"VESSEL_PROFILE:{vessel_id}",
                    workbench_group="RISK",
                    description="查看风险信号、证据缺口和复核入口。",
                )
            )
        if subject_consistency_level in {"LOW", "UNKNOWN"}:
            actions.append(
                VesselRecommendedAction(
                    action_type="OPEN_RELATIONS",
                    label="补齐主体结论",
                    target_path=f"/vessels/{vessel_id}/relations",
                    target_object_type="VESSEL_PROFILE",
                    target_object_id=str(vessel_id),
                    source_object_anchor=f"VESSEL_PROFILE:{vessel_id}",
                    workbench_group="EVIDENCE",
                    description="主体关系与证据结论统一在主体关系页维护。",
                )
            )
        if ais_freshness_level in {"STALE", "EXPIRED", "UNKNOWN"}:
            actions.append(
                VesselRecommendedAction(
                    action_type="OPEN_AIS",
                    label="核对 AIS",
                    target_path="/vessels/ais-situation",
                    target_object_type="VESSEL_PROFILE",
                    target_object_id=str(vessel_id),
                    source_object_anchor=f"VESSEL_PROFILE:{vessel_id}",
                    workbench_group="AIS",
                    payload={"vessel_id": vessel_id},
                    description="核对 AIS 最新位置、MMSI 映射和轨迹可用性。",
                )
            )
        if summary_status_code in {"MISSING", "STALE", "FAILED", "PARTIAL"}:
            actions.append(
                VesselRecommendedAction(
                    action_type="REFRESH_SUMMARY",
                    label="刷新摘要",
                    target_path=f"/vessels/{vessel_id}/profile-card",
                    target_object_type="VESSEL_PROFILE",
                    target_object_id=str(vessel_id),
                    source_object_anchor=f"VESSEL_PROFILE:{vessel_id}",
                    workbench_group="ASSET",
                    description="摘要会重算质量、主体、证书和 AIS 可信状态；失败时需查看错误原因。",
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
        gaps: list[str] = []
        if summary_status_code in {"MISSING", "STALE", "FAILED", "PARTIAL"}:
            gaps.append("资产摘要")
        if quality_issue_count:
            gaps.append("质量问题重新校验")
        if subject_consistency_level in {"LOW", "UNKNOWN"}:
            gaps.append("主体关系结论")
        if certificate_missing_count or certificate_expired_count:
            gaps.append("证书有效证据")
        if ais_freshness_level in {"STALE", "EXPIRED", "UNKNOWN"}:
            gaps.append("AIS 最新观测")
        return gaps

    async def _upsert_vessel_summary(self, profile: VesselProfile) -> VesselProfileSummary:
        now = datetime.utcnow()
        payload = await self._summary_payload(profile, now)
        row = await self.db.scalar(select(VesselProfileSummary).where(VesselProfileSummary.vessel_profile_id == profile.id))
        if row is None:
            row = VesselProfileSummary(vessel_profile_id=profile.id, created_at=now, updated_at=now, **payload)
            self.db.add(row)
        else:
            for key, value in payload.items():
                setattr(row, key, value)
            row.updated_at = now
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def _mark_vessel_summary_failed(self, profile: VesselProfile, error: str) -> VesselProfileSummary:
        now = datetime.utcnow()
        row = await self.db.scalar(select(VesselProfileSummary).where(VesselProfileSummary.vessel_profile_id == profile.id))
        if row is None:
            row = VesselProfileSummary(
                vessel_profile_id=profile.id,
                ship_name=profile.ship_name,
                current_mmsi=profile.current_mmsi,
                ship_type_code=profile.ship_type_code,
                data_quality_level="UNKNOWN",
                identity_confidence_level="UNKNOWN",
                contact_trust_level="UNKNOWN",
                subject_consistency_level="UNKNOWN",
                risk_level="UNKNOWN",
                ais_freshness_level="UNKNOWN",
                summary_status_code="FAILED",
                summary_version=SUMMARY_VERSION,
                data_sources_json=["VESSEL_PROFILE"],
                uncertainty_notes_json=["摘要生成失败"],
                refresh_error=error[:1000],
                created_at=now,
                updated_at=now,
            )
            self.db.add(row)
        else:
            row.summary_status_code = "FAILED"
            row.refresh_error = error[:1000]
            row.updated_at = now
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def _summary_payload(self, profile: VesselProfile, now: datetime) -> dict[str, Any]:
        label_map = await _load_label_map(self.db)
        capacity = await self.repo.get_one_by_profile(VesselCapacityDimension, profile.id)
        build = await self.repo.get_one_by_profile(VesselBuildInfo, profile.id)
        owner = await self._summary_primary_relation(VesselOwnerPeriod, profile.id)
        operator = await self._summary_primary_relation(VesselOperatorPeriod, profile.id)
        contact = await self._summary_primary_relation(VesselContact, profile.id)
        certificates = await self._summary_certificates(profile.id)
        source_updated_at = await self._summary_source_updated_at(profile.id, profile, capacity, build, owner, operator, contact, *certificates)
        facts = {
            "ship_name": profile.ship_name,
            "current_mmsi": profile.current_mmsi,
            "ship_type_code": profile.ship_type_code,
            "deadweight_ton": getattr(capacity, "deadweight_ton", None),
            "length_m": getattr(capacity, "length_m", None),
            "width_m": getattr(capacity, "width_m", None),
            "design_draft_m": getattr(capacity, "design_draft_m", None),
            "primary_owner_name": getattr(owner, "party_name", None),
            "primary_operator_name": getattr(operator, "operator_name", None),
            "primary_contact_name": getattr(contact, "contact_name", None),
            "certificate_evidence": bool(certificates),
        }
        missing_fields = [key for key, _ in SUMMARY_REQUIRED_FIELDS if not facts.get(key)]
        await self._sync_summary_missing_issues(profile.id, missing_fields)
        active_issues = await self._summary_active_issues(profile.id)
        severity_counts = defaultdict(int)
        issue_type_counts = defaultdict(int)
        for issue in active_issues:
            severity_counts[issue.severity_code] += 1
            issue_type_counts[issue.issue_type_code] += 1
        completeness = _percent(len(SUMMARY_REQUIRED_FIELDS) - len(missing_fields), len(SUMMARY_REQUIRED_FIELDS))
        quality_score = max(
            Decimal("0.00"),
            completeness
            - Decimal(str(severity_counts.get("HIGH", 0) * 20))
            - Decimal(str(severity_counts.get("MEDIUM", 0) * 10))
            - Decimal(str(severity_counts.get("LOW", 0) * 5)),
        ).quantize(Decimal("0.01"))
        data_quality_level = _level_from_score(quality_score)
        identity_level = self._summary_identity_level(profile, issue_type_counts)
        contact_trust_level = self._summary_contact_trust_level(contact)
        subject_level = self._summary_subject_consistency_level(owner, operator)
        risk_payload = self._summary_certificate_risk(certificates, active_issues)
        formal_risk_payload = await self._formal_risk_summary(profile.id)
        if formal_risk_payload.get("has_formal_signals"):
            risk_payload = formal_risk_payload
        ais_payload = await self._summary_ais_payload(profile, now)
        tags = self._summary_sample_tags(data_quality_level, risk_payload["risk_level"], ais_payload["ais_freshness_level"], contact_trust_level, severity_counts)
        data_sources = ["VESSEL_PROFILE", "RELATION_LEDGER", "CERTIFICATE_LEDGER", "QUALITY_ISSUE"]
        if ais_payload["latest_position_time"] is not None:
            data_sources.append("ES_REALTIME")
        notes: list[str] = []
        if missing_fields:
            labels = {key: label for key, label in SUMMARY_REQUIRED_FIELDS}
            notes.append("缺失字段：" + "、".join(labels.get(key, key) for key in missing_fields))
        notes.append(
            "合规风险来源：Round 5 风险信号"
            if formal_risk_payload.get("has_formal_signals")
            else "证书风险为 Round 3 轻量账本口径，正式规则未刷新时仅作预规则提示"
        )
        if ais_payload["ais_unavailable_reason"]:
            notes.append(ais_payload["ais_unavailable_reason"])
        status = "PARTIAL" if ais_payload["ais_unavailable_reason"] else "READY"
        return {
            "ship_name": profile.ship_name,
            "current_mmsi": profile.current_mmsi,
            "ship_type_code": profile.ship_type_code,
            "ship_type_name": label_map.get("SHIP_TYPE", {}).get(profile.ship_type_code),
            "deadweight_ton": getattr(capacity, "deadweight_ton", None),
            "length_m": getattr(capacity, "length_m", None),
            "width_m": getattr(capacity, "width_m", None),
            "design_draft_m": getattr(capacity, "design_draft_m", None),
            "building_year": getattr(build, "building_year", None),
            "ship_age": _ship_age(getattr(build, "building_year", None)),
            "primary_owner_name": getattr(owner, "party_name", None),
            "primary_operator_name": getattr(operator, "operator_name", None),
            "primary_contact_name": getattr(contact, "contact_name", None),
            "primary_contact_phone_masked": _mask_phone(getattr(contact, "mobile_phone", None)),
            "contact_available": getattr(contact, "is_available", None),
            "profile_completeness_rate": completeness,
            "data_quality_score": quality_score,
            "data_quality_level": data_quality_level,
            "identity_confidence_level": identity_level,
            "contact_trust_level": contact_trust_level,
            "subject_consistency_level": subject_level,
            "quality_issue_count": len(active_issues),
            "missing_field_count": len(missing_fields),
            "conflict_count": issue_type_counts.get("MMSI_CONFLICT", 0),
            "risk_level": risk_payload["risk_level"],
            "risk_evidence_summary_json": risk_payload["risk_evidence_summary"],
            "certificate_missing_count": risk_payload["certificate_missing_count"],
            "certificate_expiring_count": risk_payload["certificate_expiring_count"],
            "certificate_expired_count": risk_payload["certificate_expired_count"],
            "latest_position_time": ais_payload["latest_position_time"],
            "latest_city_code": ais_payload["latest_city_code"],
            "latest_city_name": ais_payload["latest_city_name"],
            "ais_freshness_level": ais_payload["ais_freshness_level"],
            "ais_unavailable_reason": ais_payload["ais_unavailable_reason"],
            "analysis_sample_tags_json": tags,
            "analysis_sample_tags_key": _tag_key(tags),
            "data_sources_json": data_sources,
            "uncertainty_notes_json": notes,
            "source_layer": "PROFILE_SUMMARY",
            "coverage_rate": completeness,
            "summary_status_code": status,
            "summary_version": SUMMARY_VERSION,
            "refreshed_at": now,
            "source_updated_at": source_updated_at,
            "last_verified_at": getattr(contact, "last_verified_at", None),
            "refresh_error": None,
        }

    async def _summary_primary_relation(self, model: type[Any], vessel_id: int) -> Any | None:
        stmt = (
            select(model)
            .where(
                model.vessel_profile_id == vessel_id,
                model.is_current.is_(True),
                model.voided_at.is_(None),
                model.end_date.is_(None),
            )
            .order_by(model.is_primary.desc() if hasattr(model, "is_primary") else model.id.asc(), model.id.asc())
            .limit(1)
        )
        return await self.db.scalar(stmt)

    async def _summary_certificates(self, vessel_id: int) -> list[VesselCertificate]:
        rows = (
            await self.db.execute(
                select(VesselCertificate).where(
                    VesselCertificate.vessel_profile_id == vessel_id,
                    VesselCertificate.voided_at.is_(None),
                )
            )
        ).scalars().all()
        return list(rows)

    async def _summary_active_issues(self, vessel_id: int) -> list[VesselDataQualityIssue]:
        rows = (
            await self.db.execute(
                select(VesselDataQualityIssue).where(
                    VesselDataQualityIssue.vessel_profile_id == vessel_id,
                    VesselDataQualityIssue.status_code.in_(ACTIVE_ISSUE_STATUSES),
                )
            )
        ).scalars().all()
        return list(rows)

    async def _summary_source_updated_at(self, vessel_id: int, *rows: Any) -> datetime | None:
        values = [getattr(row, "updated_at", None) for row in rows if row is not None]
        latest_quality = await self.db.scalar(
            select(func.max(VesselDataQualityIssue.updated_at)).where(VesselDataQualityIssue.vessel_profile_id == vessel_id)
        )
        if latest_quality is not None:
            values.append(latest_quality)
        return max((value for value in values if value is not None), default=None)

    async def _sync_summary_missing_issues(self, vessel_id: int, missing_fields: list[str]) -> None:
        missing_set = set(missing_fields)
        for field_name, _ in SUMMARY_REQUIRED_FIELDS:
            if field_name in {"primary_owner_name", "primary_operator_name", "primary_contact_name"}:
                relation_type = {
                    "primary_owner_name": "OWNER",
                    "primary_operator_name": "OPERATOR",
                    "primary_contact_name": "CONTACT",
                }[field_name]
                if field_name in missing_set:
                    await self._upsert_quality_issue(
                        issue_type_code="PRIMARY_RELATION_MISSING",
                        profile_id=vessel_id,
                        object_type="profile",
                        object_id=vessel_id,
                        field_name=field_name,
                        normalized_key=f"profile|{vessel_id}|{relation_type}",
                        evidence_source="VESSEL_SUMMARY_REFRESH",
                        severity_code="MEDIUM",
                        impact_scope=[{"relation_type": relation_type, "vessel_profile_id": vessel_id}],
                    )
                else:
                    await self._resolve_summary_issue(
                        "PRIMARY_RELATION_MISSING",
                        vessel_id,
                        "profile",
                        vessel_id,
                        field_name,
                        f"profile|{vessel_id}|{relation_type}",
                    )
                continue
            if field_name in missing_set:
                await self._upsert_quality_issue(
                    issue_type_code="PROFILE_FIELD_MISSING",
                    profile_id=vessel_id,
                    object_type="profile",
                    object_id=vessel_id,
                    field_name=field_name,
                    normalized_key=f"profile|{vessel_id}|{field_name}",
                    evidence_source="VESSEL_SUMMARY_REFRESH",
                    severity_code="MEDIUM",
                    impact_scope=[{"field_name": field_name, "vessel_profile_id": vessel_id}],
                )
            else:
                await self._resolve_summary_issue(
                    "PROFILE_FIELD_MISSING",
                    vessel_id,
                    "profile",
                    vessel_id,
                    field_name,
                    f"profile|{vessel_id}|{field_name}",
                )
        await self.db.flush()

    async def _resolve_summary_issue(
        self,
        issue_type_code: str,
        profile_id: int,
        object_type: str,
        object_id: str | int | None,
        field_name: str | None,
        normalized_key: str,
    ) -> None:
        fingerprint = _quality_fingerprint(issue_type_code, profile_id, object_type, object_id, field_name, normalized_key)
        rows = (
            await self.db.execute(
                select(VesselDataQualityIssue).where(
                    VesselDataQualityIssue.fingerprint == fingerprint,
                    VesselDataQualityIssue.status_code.in_(ACTIVE_ISSUE_STATUSES),
                )
            )
        ).scalars().all()
        now = datetime.utcnow()
        for row in rows:
            row.status_code = "RESOLVED"
            row.resolved_at = now
            row.resolved_evidence = "VESSEL_SUMMARY_REFRESH"

    def _summary_identity_level(self, profile: VesselProfile, issue_type_counts: dict[str, int]) -> str:
        if issue_type_counts.get("MMSI_CONFLICT", 0):
            return "LOW"
        if not profile.current_mmsi:
            return "UNKNOWN"
        if profile.identity_status_code == "LINKED":
            return "HIGH"
        if profile.identity_status_code in {"CANDIDATE", "UNLINKED"}:
            return "MEDIUM"
        if profile.identity_status_code == "CONFLICT":
            return "LOW"
        return "MEDIUM"

    def _summary_contact_trust_level(self, contact: Any | None) -> str:
        if contact is None:
            return "UNKNOWN"
        if not getattr(contact, "is_available", True):
            return "LOW"
        if getattr(contact, "verified_status_code", None) == "VERIFIED":
            return "HIGH"
        if getattr(contact, "last_verified_at", None) is not None:
            return "MEDIUM"
        return "MEDIUM"

    def _summary_subject_consistency_level(self, owner: Any | None, operator: Any | None) -> str:
        if owner is None and operator is None:
            return "UNKNOWN"
        if owner is None or operator is None:
            return "LOW"
        if getattr(owner, "verified_status_code", None) == "VERIFIED" and getattr(operator, "verified_status_code", None) == "VERIFIED":
            return "HIGH"
        return "MEDIUM"

    def _summary_certificate_risk(
        self,
        certificates: list[VesselCertificate],
        active_issues: list[VesselDataQualityIssue],
    ) -> dict[str, Any]:
        today = date.today()
        expiring_limit = today + timedelta(days=30)
        current_by_type: dict[str, list[VesselCertificate]] = defaultdict(list)
        expired_count = 0
        expiring_count = 0
        evidence: list[dict[str, Any]] = [{"source": "CERTIFICATE_LEDGER_PRE_RULE"}]
        for cert in certificates:
            cert_type = cert.certificate_type_code or "UNKNOWN"
            current_by_type[cert_type].append(cert)
        missing_types = [code for code in REQUIRED_VESSEL_CERTIFICATE_TYPES if code not in current_by_type]
        insufficient_types: list[str] = []
        complete_required_certs: list[VesselCertificate] = []
        for code in REQUIRED_VESSEL_CERTIFICATE_TYPES:
            rows = current_by_type.get(code, [])
            complete_rows = [cert for cert in rows if self._certificate_has_complete_evidence(cert)]
            if rows and not complete_rows:
                insufficient_types.append(code)
            complete_required_certs.extend(complete_rows)
        for cert in complete_required_certs:
            if cert.is_long_term_valid:
                continue
            if cert.valid_to is None:
                continue
            if cert.valid_to < today:
                expired_count += 1
            elif cert.valid_to <= expiring_limit:
                expiring_count += 1
        high_quality_issues = [item for item in active_issues if item.severity_code == "HIGH"]
        if expired_count:
            risk_level = "HIGH"
        elif expiring_count or missing_types:
            risk_level = "MEDIUM"
        elif insufficient_types or high_quality_issues:
            risk_level = "UNKNOWN"
        elif len(complete_required_certs) >= len(REQUIRED_VESSEL_CERTIFICATE_TYPES):
            risk_level = "LOW"
        else:
            risk_level = "UNKNOWN"
        evidence.append(
            {
                "missing_certificate_type_codes": missing_types,
                "insufficient_certificate_type_codes": insufficient_types,
                "expired_count": expired_count,
                "expiring_count": expiring_count,
            }
        )
        return {
            "risk_level": risk_level,
            "risk_evidence_summary": evidence,
            "certificate_missing_count": len(missing_types),
            "certificate_expiring_count": expiring_count,
            "certificate_expired_count": expired_count,
        }

    def _certificate_has_complete_evidence(self, cert: VesselCertificate) -> bool:
        return (
            getattr(cert, "verify_status_code", None) == "VERIFIED"
            and bool(getattr(cert, "certificate_no", None))
            and (bool(getattr(cert, "is_long_term_valid", False)) or getattr(cert, "valid_to", None) is not None)
        )

    def _summary_sample_tags(
        self,
        data_quality_level: str,
        risk_level: str,
        ais_freshness_level: str,
        contact_trust_level: str,
        severity_counts: dict[str, int],
    ) -> list[str]:
        tags: list[str] = []
        if data_quality_level == "HIGH" and not severity_counts.get("HIGH"):
            tags.append("HIGH_QUALITY_PROFILE")
        if ais_freshness_level in {"FRESH", "RECENT"}:
            tags.append("ACTIVE_SAMPLE")
        if risk_level == "LOW":
            tags.append("LOW_RISK_SAMPLE")
        if contact_trust_level in {"HIGH", "MEDIUM"}:
            tags.append("CONTACT_REFERENCEABLE")
        return tags

    def _summary_json_list(self, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

    async def create_vessel(self, payload, *, operator_id: int | None = None) -> VesselProfileResponse:
        await self._assert_active_mmsi_available(payload.mmsi, evidence_source="CREATE_VESSEL")
        code = await CodeSequenceService(self.db).next_code("VESSEL_PROFILE_CODE")
        entity = await self.repo.create_profile(
            {
                "vessel_profile_code": code,
                "ship_name": payload.ship_name.strip(),
                "current_mmsi": payload.mmsi,
                "profile_status_code": "ACTIVE",
                "identity_status_code": "UNLINKED",
                "source_type_code": payload.source_type_code,
                "audit_status": "PENDING",
            }
        )
        await self.repo.add_name_history(entity.id, entity.ship_name)
        await self.repo.add_identifier_history(entity.id, "MMSI", entity.current_mmsi)
        await self._add_change_event(entity.id, "CREATE", "新增船舶档案", None, _row_dict(entity), operator_id)
        await self.db.commit()
        await self._refresh_summary_best_effort(entity.id)
        return await self._build_profile_response(entity.id)

    async def update_profile(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselProfileResponse:
        profile = await self._require_profile(vessel_id)
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        before = _row_dict(profile)
        if "ship_name" in updates:
            updates["ship_name"] = updates["ship_name"].strip()
        new_status = updates.get("profile_status_code", profile.profile_status_code)
        new_mmsi = updates.get("current_mmsi", profile.current_mmsi)
        becoming_active = profile.profile_status_code != ACTIVE_PROFILE_STATUS and new_status == ACTIVE_PROFILE_STATUS
        mmsi_changing = "current_mmsi" in updates and new_mmsi != before.get("current_mmsi")
        if new_status == ACTIVE_PROFILE_STATUS and (becoming_active or mmsi_changing):
            await self._assert_active_mmsi_available(
                new_mmsi,
                exclude_vessel_id=vessel_id,
                attempted_profile_id=vessel_id,
                evidence_source="UPDATE_PROFILE",
            )
        row = await self.repo.update_profile(vessel_id, updates)
        if row is None:
            raise NotFoundError("VesselProfile", vessel_id)
        if "ship_name" in updates and updates["ship_name"] != before.get("ship_name"):
            await self.repo.add_name_history(vessel_id, updates["ship_name"])
        if "current_mmsi" in updates and updates["current_mmsi"] != before.get("current_mmsi"):
            await self._close_current_mmsi_history(vessel_id, before.get("current_mmsi"))
            await self.repo.add_identifier_history(vessel_id, "MMSI", updates["current_mmsi"])
        await self._add_change_event(vessel_id, "UPDATE_PROFILE", "更新船舶主档", before, updates, operator_id)
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return await self._build_profile_response(vessel_id)

    async def get_detail(self, vessel_id: int) -> VesselDetailResponse:
        profile = await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        city_map = await _load_city_map(self.db, [profile.registry_city_code] if profile.registry_city_code else [])
        region_map = await _load_region_map(self.db, [profile.business_region_id] if profile.business_region_id else [])
        owner_rows = [row for row in await self.repo.list_by_profile(VesselOwnerPeriod, vessel_id) if _relation_is_effective(row)]
        owner_documents = await self._owner_documents_by_owner(vessel_id, label_map)
        operator_rows = [row for row in await self.repo.list_by_profile(VesselOperatorPeriod, vessel_id) if _relation_is_effective(row)]
        contact_rows = [row for row in await self.repo.list_by_profile(VesselContact, vessel_id) if _relation_is_effective(row)]
        crew_rows = [row for row in await self.repo.list_by_profile(VesselCrewAssignment, vessel_id) if _relation_is_effective(row)]
        return VesselDetailResponse(
            profile=_profile_response(profile, label_map=label_map, city_map=city_map, region_map=region_map),
            registration=self._maybe(VesselRegistrationResponse, await self.repo.get_one_by_profile(VesselRegistrationInfo, vessel_id)),
            capacity=self._maybe(VesselCapacityResponse, await self.repo.get_one_by_profile(VesselCapacityDimension, vessel_id)),
            build_info=self._maybe(VesselBuildInfoResponse, await self.repo.get_one_by_profile(VesselBuildInfo, vessel_id)),
            owners=[self._owner_response(row, label_map, documents=owner_documents.get(row.id, [])) for row in owner_rows],
            operators=[self._operator_response(row, label_map) for row in operator_rows],
            contacts=[self._contact_response(row, label_map) for row in contact_rows],
            crew=[self._crew_response(row, label_map) for row in crew_rows],
            person_certificates=await self._person_certificates_with_files(vessel_id, label_map=label_map),
            certificates=await self._certificates_with_files(vessel_id, label_map=label_map),
            name_history=[
                VesselNameHistoryResponse(
                    **_row_dict(row),
                    source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
                )
                for row in await self.repo.list_by_profile(VesselNameHistory, vessel_id, order_desc=True)
            ],
            identifier_history=[
                VesselIdentifierHistoryResponse(
                    **_row_dict(row),
                    source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
                )
                for row in await self.repo.list_by_profile(VesselIdentifierHistory, vessel_id, order_desc=True)
            ],
            change_events=[
                VesselChangeEventResponse(
                    **_row_dict(row),
                    event_type_name=label_map.get("VESSEL_CHANGE_EVENT_TYPE", {}).get(row.event_type_code),
                )
                for row in await self.repo.list_by_profile(VesselChangeEvent, vessel_id, order_desc=True)
            ],
        )

    async def upsert_registration(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselRegistrationResponse:
        await self._require_profile(vessel_id)
        before = await self.repo.get_one_by_profile(VesselRegistrationInfo, vessel_id)
        row = await self.repo.upsert_one_by_profile(VesselRegistrationInfo, vessel_id, payload.model_dump(exclude_none=True))
        profile_updates: dict[str, Any] = {}
        if row.registry_city_code:
            profile_updates["registry_city_code"] = row.registry_city_code
        if row.home_port_code:
            profile_updates["home_port_code"] = row.home_port_code
        if row.home_port_name:
            profile_updates["home_port_name"] = row.home_port_name
        if profile_updates:
            await self.repo.update_profile(vessel_id, profile_updates)
        await self._add_change_event(vessel_id, "UPSERT_REGISTRATION", "维护船籍信息", _row_dict(before) if before else None, _row_dict(row), operator_id)
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return VesselRegistrationResponse(**_row_dict(row))

    async def upsert_capacity(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselCapacityResponse:
        await self._require_profile(vessel_id)
        row = await self.repo.upsert_one_by_profile(VesselCapacityDimension, vessel_id, payload.model_dump(exclude_none=True))
        await self._add_change_event(vessel_id, "UPSERT_CAPACITY", "维护船舶尺寸信息", None, _row_dict(row), operator_id)
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return VesselCapacityResponse(**_row_dict(row))

    async def upsert_build_info(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselBuildInfoResponse:
        await self._require_profile(vessel_id)
        row = await self.repo.upsert_one_by_profile(VesselBuildInfo, vessel_id, payload.model_dump(exclude_none=True))
        await self._add_change_event(vessel_id, "UPSERT_BUILD_INFO", "维护建造信息", None, _row_dict(row), operator_id)
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return VesselBuildInfoResponse(**_row_dict(row))

    async def _build_profile_response(self, vessel_id: int) -> VesselProfileResponse:
        profile = await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        city_map = await _load_city_map(self.db, [profile.registry_city_code] if profile.registry_city_code else [])
        region_map = await _load_region_map(self.db, [profile.business_region_id] if profile.business_region_id else [])
        return _profile_response(profile, label_map=label_map, city_map=city_map, region_map=region_map)

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
