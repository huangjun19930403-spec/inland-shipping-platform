"""Vessel asset summary refresh and distribution methods."""

from __future__ import annotations

from app.modules.vessel.shared import base as _base

globals().update({name: getattr(_base, name) for name in dir(_base) if not name.startswith("__")})


SUMMARY_REFRESH_DIFF_FIELDS = (
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
)

SUMMARY_RELATION_FIELDS = {
    "primary_owner_name": "OWNER",
    "primary_operator_name": "OPERATOR",
    "primary_contact_name": "CONTACT",
}


class VesselAssetSummaryMixin:
    """Summary refresh, status, and risk aggregation for vessel assets."""

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
        distributions = {
            key: await self._summary_distribution(column, dict_code, label_map, missing_unknown=missing_without_row)
            for key, column, dict_code in (
                ("quality_distribution", VesselProfileSummary.data_quality_level, "VESSEL_CONFIDENCE_LEVEL"),
                ("risk_distribution", VesselProfileSummary.risk_level, "VESSEL_RISK_LEVEL"),
                ("ais_freshness_distribution", VesselProfileSummary.ais_freshness_level, "VESSEL_AIS_FRESHNESS_LEVEL"),
            )
        }
        status_distribution = await self._summary_status_distribution(label_map, missing_without_row=missing_without_row)
        status_counts = {item.code: item.count for item in status_distribution}
        missing_summary_count = status_counts.get("MISSING", 0)
        failed_summary_count = status_counts.get("FAILED", 0)
        stale_summary_count = status_counts.get("STALE", 0)
        summarized_count = max(0, total_profiles - missing_summary_count)
        coverage_rate = _percent(summarized_count, total_profiles)
        return VesselAssetSummaryResponse(
            total_profiles=total_profiles,
            summarized_count=summarized_count,
            missing_summary_count=missing_summary_count,
            failed_summary_count=failed_summary_count,
            stale_summary_count=stale_summary_count,
            coverage_rate=coverage_rate,
            confidence_level=_coverage_confidence_level(coverage_rate, failed_summary_count),
            generated_at=generated_at,
            summary_status_distribution=status_distribution,
            **distributions,
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
        results: list[VesselSummaryRefreshBatchItemResponse] = []
        for vessel_id in dict.fromkeys(int(vessel_id) for vessel_id in body.vessel_ids):
            ship_name: str | None = None
            try:
                profile = await self._require_profile(vessel_id)
                before = (await self._build_asset_items([profile]))[0]
                ship_name = before.ship_name
                after = await self.refresh_vessel_summary(vessel_id)
                failure_reason = after.refresh_error or None
                results.append(
                    VesselSummaryRefreshBatchItemResponse(
                        vessel_id=vessel_id,
                        ship_name=after.ship_name,
                        success=failure_reason is None,
                        summary_diff=self._summary_refresh_diff(before, after),
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
        diffs = [
            VesselSummaryRefreshDiffResponse(
                field_name=field_name,
                before=None if old_value is None else str(old_value),
                after=None if new_value is None else str(new_value),
                message=f"{label}从 {old_value if old_value not in (None, '') else '-'} 变为 {new_value if new_value not in (None, '') else '-'}",
            )
            for field_name, label in SUMMARY_REFRESH_DIFF_FIELDS
            if (old_value := getattr(before, field_name, None)) != (new_value := getattr(after, field_name, None))
        ]
        return diffs or [VesselSummaryRefreshDiffResponse(field_name="summary", message="摘要刷新完成，核心指标暂无变化。")]

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
            VesselAssetDistributionItemResponse(code=code, name=label_map.get(dict_code, {}).get(code), count=count)
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
        uncertainty_reasons: list[str] = []
        for count, message in (
            (not total, "当前筛选无船舶资产样本"),
            (missing_count, f"筛选结果中 {missing_count} 条摘要未生成"),
            (failed_count, f"筛选结果中 {failed_count} 条摘要生成失败"),
            (stale_count, f"筛选结果中 {stale_count} 条摘要已过期"),
            (coverage_rate < Decimal("100.00") and total, "筛选结果覆盖率不足 100%，分析结论需结合缺失样本判断"),
        ):
            if count:
                uncertainty_reasons.append(message)
        return {
            "coverage_rate": coverage_rate,
            "confidence_level": _coverage_confidence_level(coverage_rate, failed_count),
            "generated_at": generated_at,
            "summary_status_counts": status_counts,
            "summarized_count": summarized_count,
            "missing_summary_count": missing_count,
            "failed_summary_count": failed_count,
            "stale_summary_count": stale_count,
            "source_updated_at": await self.db.scalar(select(func.max(subquery.c.source_updated_at)).select_from(subquery)),
            "uncertainty_reasons": uncertainty_reasons,
        }

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
        failure_payload = {
            "summary_status_code": "FAILED",
            "refresh_error": error[:1000],
            "updated_at": now,
        }
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
                summary_version=SUMMARY_VERSION,
                data_sources_json=["VESSEL_PROFILE"],
                uncertainty_notes_json=["摘要生成失败"],
                created_at=now,
                **failure_payload,
            )
            self.db.add(row)
        else:
            for key, value in failure_payload.items():
                setattr(row, key, value)
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
            "summary_status_code": "PARTIAL" if ais_payload["ais_unavailable_reason"] else "READY",
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
            relation_type = SUMMARY_RELATION_FIELDS.get(field_name)
            issue_type = "PRIMARY_RELATION_MISSING" if relation_type else "PROFILE_FIELD_MISSING"
            normalized_key = f"profile|{vessel_id}|{relation_type or field_name}"
            if field_name in missing_set:
                impact_key = "relation_type" if relation_type else "field_name"
                await self._upsert_quality_issue(
                    issue_type_code=issue_type,
                    profile_id=vessel_id,
                    object_type="profile",
                    object_id=vessel_id,
                    field_name=field_name,
                    normalized_key=normalized_key,
                    evidence_source="VESSEL_SUMMARY_REFRESH",
                    severity_code="MEDIUM",
                    impact_scope=[{impact_key: relation_type or field_name, "vessel_profile_id": vessel_id}],
                )
            else:
                await self._resolve_summary_issue(issue_type, vessel_id, "profile", vessel_id, field_name, normalized_key)
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
        return "HIGH" if getattr(contact, "verified_status_code", None) == "VERIFIED" else "MEDIUM"

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
        for cert in certificates:
            current_by_type[cert.certificate_type_code or "UNKNOWN"].append(cert)
        missing_types = [code for code in REQUIRED_VESSEL_CERTIFICATE_TYPES if code not in current_by_type]
        insufficient_types: list[str] = []
        complete_required_certs: list[VesselCertificate] = []
        for code in REQUIRED_VESSEL_CERTIFICATE_TYPES:
            complete_rows = [cert for cert in current_by_type.get(code, []) if self._certificate_has_complete_evidence(cert)]
            if current_by_type.get(code) and not complete_rows:
                insufficient_types.append(code)
            complete_required_certs.extend(complete_rows)
        dated_certs = [cert for cert in complete_required_certs if not cert.is_long_term_valid and cert.valid_to is not None]
        expired_count = sum(1 for cert in dated_certs if cert.valid_to < today)
        expiring_count = sum(1 for cert in dated_certs if today <= cert.valid_to <= expiring_limit)
        has_high_quality_issue = any(item.severity_code == "HIGH" for item in active_issues)
        if expired_count:
            risk_level = "HIGH"
        elif expiring_count or missing_types:
            risk_level = "MEDIUM"
        elif insufficient_types or has_high_quality_issue:
            risk_level = "UNKNOWN"
        elif len(complete_required_certs) >= len(REQUIRED_VESSEL_CERTIFICATE_TYPES):
            risk_level = "LOW"
        else:
            risk_level = "UNKNOWN"
        return {
            "risk_level": risk_level,
            "risk_evidence_summary": [
                {"source": "CERTIFICATE_LEDGER_PRE_RULE"},
                {
                    "missing_certificate_type_codes": missing_types,
                    "insufficient_certificate_type_codes": insufficient_types,
                    "expired_count": expired_count,
                    "expiring_count": expiring_count,
                },
            ],
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
