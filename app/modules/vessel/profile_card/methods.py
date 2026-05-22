"""Implementation methods for the vessel profile-card domain."""

from __future__ import annotations

from app.modules.vessel.shared import base as _base

globals().update({name: getattr(_base, name) for name in dir(_base) if not name.startswith("__")})


class VesselProfileCardMixin:
    """Implementation methods for the vessel profile-card domain."""

    def _profile_card_source_trace(
        self,
        source_code: str,
        *,
        updated_at: datetime | None = None,
        confidence_level: str = "UNKNOWN",
        coverage_rate: Decimal | None = None,
        status_code: str | None = None,
        note: str | None = None,
    ) -> VesselProfileCardSourceTrace:
        return VesselProfileCardSourceTrace(
            source_code=source_code,
            source_name={
                "VESSEL_PROFILE": "船舶主档",
                "VESSEL_SUMMARY": "船舶资产摘要",
                "RELATION_LEDGER": "主体关系账本",
                "QUALITY_ISSUE": "质量问题",
                "CERTIFICATE_LEDGER_PRE_RULE": "证书账本预规则",
                "CERTIFICATE_REQUIREMENT_RULE": "证书要求规则",
                "VESSEL_RISK_SIGNAL": "合规风险信号",
                "VESSEL_COMPLIANCE_ENGINE": "合规风险引擎",
                "AIS_SUMMARY": "AIS 摘要",
                "OCR_ADOPTION": "OCR 可信采纳",
                "CANDIDATE_ANALYSIS": "候选适配分析",
            }.get(source_code, source_code),
            updated_at=updated_at,
            confidence_level=confidence_level,
            coverage_rate=coverage_rate,
            status_code=status_code,
            note=note,
        )

    def _issue_summary(self, row: VesselDataQualityIssue) -> VesselProfileCardIssueSummary:
        return VesselProfileCardIssueSummary(
            id=row.id,
            issue_type_code=row.issue_type_code,
            severity_code=row.severity_code,
            status_code=row.status_code,
            field_name=row.field_name,
            affected_object_type=row.affected_object_type,
            affected_object_id=row.affected_object_id,
            updated_at=row.updated_at,
        )

    async def _recognition_card_metrics(self, vessel_id: int) -> dict[str, Any]:
        pending_diff_count = await self.db.scalar(
            select(func.count(VesselRecognitionFieldDiff.id)).where(
                VesselRecognitionFieldDiff.vessel_profile_id == vessel_id,
                VesselRecognitionFieldDiff.adopt_status_code == "REVIEW_REQUIRED",
            )
        )
        low_confidence_diff_count = await self.db.scalar(
            select(func.count(VesselRecognitionFieldDiff.id)).where(
                VesselRecognitionFieldDiff.vessel_profile_id == vessel_id,
                VesselRecognitionFieldDiff.adopt_status_code == "REVIEW_REQUIRED",
                VesselRecognitionFieldDiff.confidence_score.is_not(None),
                VesselRecognitionFieldDiff.confidence_score < LOW_CONFIDENCE_SCORE_THRESHOLD,
            )
        )
        adoption_count = await self.db.scalar(
            select(func.count(VesselRecognitionAdoptionRecord.id)).where(
                VesselRecognitionAdoptionRecord.vessel_profile_id == vessel_id
            )
        )
        latest_adoption = await self.db.scalar(
            select(VesselRecognitionAdoptionRecord)
            .where(VesselRecognitionAdoptionRecord.vessel_profile_id == vessel_id)
            .order_by(VesselRecognitionAdoptionRecord.confirmed_at.desc(), VesselRecognitionAdoptionRecord.id.desc())
            .limit(1)
        )
        active_task_count = 0
        for model in [
            VesselCertificateImageRecognition,
            VesselPersonCertificateImageRecognition,
            VesselOwnerDocumentImageRecognition,
        ]:
            active_task_count += int(
                await self.db.scalar(
                    select(func.count(model.id)).where(
                        model.vessel_profile_id == vessel_id,
                        model.status_code.in_(ACTIVE_RECOGNITION_STATUSES | {"NEED_CONFIRM"}),
                    )
                )
                or 0
            )
        return {
            "pending_diff_count": int(pending_diff_count or 0),
            "low_confidence_diff_count": int(low_confidence_diff_count or 0),
            "active_task_count": active_task_count,
            "adoption_count": int(adoption_count or 0),
            "latest_adoption": (
                {
                    "id": latest_adoption.id,
                    "recognition_object_type": latest_adoption.recognition_object_type,
                    "recognition_id": latest_adoption.recognition_id,
                    "target_object_type": latest_adoption.target_object_type,
                    "target_object_id": latest_adoption.target_object_id,
                    "adopted_fields": latest_adoption.adopted_fields_json or [],
                    "skipped_fields": latest_adoption.skipped_fields_json or [],
                    "confirmed_at": latest_adoption.confirmed_at,
                    "change_event_id": latest_adoption.change_event_id,
                }
                if latest_adoption is not None
                else None
            ),
            "updated_at": latest_adoption.confirmed_at if latest_adoption is not None else None,
        }

    async def get_profile_card(self, vessel_id: int) -> VesselProfileCardResponse:
        profile = await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        city_map = await _load_city_map(self.db, [profile.registry_city_code] if profile.registry_city_code else [])
        region_map = await _load_region_map(self.db, [profile.business_region_id] if profile.business_region_id else [])
        profile_response = _profile_response(profile, label_map=label_map, city_map=city_map, region_map=region_map)
        summary = await self.db.scalar(select(VesselProfileSummary).where(VesselProfileSummary.vessel_profile_id == vessel_id))
        summary_status = self._effective_summary_status(summary) if summary is not None else "MISSING"
        summary_notes = self._summary_json_list(summary.uncertainty_notes_json if summary is not None else None)
        if summary is None:
            summary_notes.append("资产摘要未生成，画像可信字段以 UNKNOWN 展示")
        elif summary_status == "STALE":
            summary_notes.append("源数据晚于摘要刷新时间，画像可能已过期")
        elif summary.summary_status_code == "FAILED":
            summary_notes.append(summary.refresh_error or "摘要刷新失败")

        capacity = await self.repo.get_one_by_profile(VesselCapacityDimension, vessel_id)
        owner_rows = await self.repo.list_by_profile(VesselOwnerPeriod, vessel_id)
        operator_rows = await self.repo.list_by_profile(VesselOperatorPeriod, vessel_id)
        contact_rows = await self.repo.list_by_profile(VesselContact, vessel_id)
        crew_rows = await self.repo.list_by_profile(VesselCrewAssignment, vessel_id)
        current_owners = [row for row in owner_rows if _relation_is_effective(row)]
        current_operators = [row for row in operator_rows if _relation_is_effective(row)]
        current_contacts = [row for row in contact_rows if _relation_is_effective(row)]
        current_crew = [row for row in crew_rows if _relation_is_effective(row)]
        all_relation_rows = [*owner_rows, *operator_rows, *contact_rows, *crew_rows]
        primary_owner = next((row for row in current_owners if row.is_primary), current_owners[0] if current_owners else None)
        primary_operator = next((row for row in current_operators if row.is_primary), current_operators[0] if current_operators else None)
        primary_contact = next((row for row in current_contacts if row.is_primary), current_contacts[0] if current_contacts else None)
        if hasattr(self.db, "scalars"):
            controller_rows = (
                await self.db.scalars(
                    select(VesselControllerEvidence).where(
                        VesselControllerEvidence.vessel_profile_id == vessel_id,
                        VesselControllerEvidence.status_code == "ACTIVE",
                        VesselControllerEvidence.voided_at.is_(None),
                    )
                )
            ).all()
            affiliation_rows = (
                await self.db.scalars(
                    select(VesselAffiliationEvidence).where(
                        VesselAffiliationEvidence.vessel_profile_id == vessel_id,
                        VesselAffiliationEvidence.status_code == "ACTIVE",
                        VesselAffiliationEvidence.voided_at.is_(None),
                    )
                )
            ).all()
        else:
            controller_rows = []
            affiliation_rows = []
        approved_controller_count = sum(
            1 for row in controller_rows if row.verified_status_code == "APPROVED" and row.confidence_level in {"HIGH", "MEDIUM"}
        )
        approved_affiliation_count = sum(
            1 for row in affiliation_rows if row.verified_status_code == "APPROVED" and row.confidence_level in {"HIGH", "MEDIUM"}
        )
        pending_controller_count = sum(1 for row in controller_rows if row.verified_status_code in {"DRAFT", "PENDING", "CHANGE_REQUESTED"})
        pending_affiliation_count = sum(1 for row in affiliation_rows if row.verified_status_code in {"DRAFT", "PENDING", "CHANGE_REQUESTED"})

        name_history = (await self.repo.list_by_profile(VesselNameHistory, vessel_id, order_desc=True))[:5]
        identifier_history = (await self.repo.list_by_profile(VesselIdentifierHistory, vessel_id, order_desc=True))[:5]
        active_issues = await self._summary_active_issues(vessel_id)
        certificate_evidence_count = int(
            await self.db.scalar(
                select(func.count(VesselCertificate.id)).where(
                    VesselCertificate.vessel_profile_id == vessel_id,
                    VesselCertificate.voided_at.is_(None),
                )
            )
            or 0
        )
        formal_risk_payload = await self._formal_risk_summary(vessel_id)
        formal_risk_signals = await self._active_risk_signals(vessel_id) if formal_risk_payload.get("has_formal_signals") else []
        compliance_risk_level = (
            formal_risk_payload["risk_level"]
            if formal_risk_payload.get("has_formal_signals")
            else (summary.risk_level if summary is not None else "UNKNOWN")
        )
        compliance_source_code = "VESSEL_RISK_SIGNAL" if formal_risk_payload.get("has_formal_signals") else "CERTIFICATE_LEDGER_PRE_RULE"
        compliance_source_status = "FORMAL_RISK" if formal_risk_payload.get("has_formal_signals") else "PRE_RULE"
        compliance_message = (
            "Round 5 风险信号，包含规则来源、证据和处理状态"
            if formal_risk_payload.get("has_formal_signals")
            else "证书账本预规则回退，不代表正式合规判断"
        )
        severity_counts: dict[str, int] = defaultdict(int)
        for issue in active_issues:
            severity_counts[issue.severity_code] += 1
        recognition_metrics = await self._recognition_card_metrics(vessel_id)
        relation_updated_at = self._latest_datetime(*(getattr(row, "updated_at", None) for row in all_relation_rows))
        quality_updated_at = self._latest_datetime(*(row.updated_at for row in active_issues))
        recognition_updated_at = recognition_metrics["updated_at"]

        summary_confidence = summary.data_quality_level if summary is not None else "UNKNOWN"
        summary_coverage = _decimal(summary.coverage_rate) if summary is not None else None
        profile_source = self._profile_card_source_trace(
            "VESSEL_PROFILE",
            updated_at=profile.updated_at,
            confidence_level=summary.identity_confidence_level if summary is not None else "UNKNOWN",
        )
        summary_source = self._profile_card_source_trace(
            "VESSEL_SUMMARY",
            updated_at=summary.refreshed_at if summary is not None else None,
            confidence_level=summary_confidence,
            coverage_rate=summary_coverage,
            status_code=summary_status,
            note=summary.refresh_error if summary is not None and summary.summary_status_code == "FAILED" else None,
        )
        relation_source = self._profile_card_source_trace(
            "RELATION_LEDGER",
            updated_at=relation_updated_at,
            confidence_level=summary.subject_consistency_level if summary is not None else "UNKNOWN",
        )
        quality_source = self._profile_card_source_trace(
            "QUALITY_ISSUE",
            updated_at=quality_updated_at,
            confidence_level=summary.data_quality_level if summary is not None else "UNKNOWN",
            status_code="ACTIVE" if active_issues else "EMPTY",
        )
        compliance_source = self._profile_card_source_trace(
            compliance_source_code,
            updated_at=(max((row.updated_at for row in formal_risk_signals), default=None) if formal_risk_signals else (summary.refreshed_at if summary is not None else None)),
            confidence_level=compliance_risk_level,
            status_code=compliance_source_status,
            note=compliance_message,
        )
        trajectory_source = self._profile_card_source_trace(
            "AIS_SUMMARY",
            updated_at=summary.latest_position_time if summary is not None else None,
            confidence_level=summary.ais_freshness_level if summary is not None else "UNKNOWN",
            status_code="AVAILABLE" if summary is not None and summary.latest_position_time else "UNKNOWN",
            note=summary.ais_unavailable_reason if summary is not None else None,
        )
        recognition_source = self._profile_card_source_trace(
            "OCR_ADOPTION",
            updated_at=recognition_updated_at,
            confidence_level="LOW" if recognition_metrics["low_confidence_diff_count"] else ("MEDIUM" if recognition_metrics["pending_diff_count"] else "UNKNOWN"),
            status_code="REVIEW_REQUIRED" if recognition_metrics["pending_diff_count"] else ("ADOPTED" if recognition_metrics["adoption_count"] else "EMPTY"),
        )
        candidate_source = self._profile_card_source_trace(
            "CANDIDATE_ANALYSIS",
            confidence_level="UNKNOWN",
            status_code="UNAVAILABLE",
            note="候选船舶分析将在 Round 8 接入",
        )
        source_trace = [
            profile_source,
            summary_source,
            relation_source,
            quality_source,
            compliance_source,
            trajectory_source,
            recognition_source,
            candidate_source,
        ]
        identity_updated_at = self._latest_datetime(profile.updated_at, summary.refreshed_at if summary else None)
        relation_voided_count = sum(1 for row in all_relation_rows if getattr(row, "voided_at", None) is not None)
        relation_history_count = sum(1 for row in all_relation_rows if self._relation_status_code(row) == "HISTORY")
        current_relation_count = len(current_owners) + len(current_operators) + len(current_contacts) + len(current_crew)
        top_issues = [self._issue_summary(row) for row in active_issues[:5]]
        conflict_warnings = [
            f"{item.issue_type_code}:{item.field_name or item.affected_object_type}"
            for item in active_issues
            if item.issue_type_code in {"MMSI_CONFLICT", "PROFILE_FIELD_MISSING", "PRIMARY_RELATION_MISSING"}
        ][:5]
        trajectory_card = VesselProfileTrajectoryCard(
            status_code="AVAILABLE" if summary is not None and summary.latest_position_time else "UNKNOWN",
            confidence_level=summary.ais_freshness_level if summary is not None else "UNKNOWN",
            evidence_count=1 if summary is not None and summary.latest_position_time else 0,
            updated_at=summary.latest_position_time if summary is not None else None,
            source_codes=["AIS_SUMMARY", "VESSEL_SUMMARY"],
            uncertainty_notes=[summary.ais_unavailable_reason] if summary is not None and summary.ais_unavailable_reason else ([] if summary is not None and summary.latest_position_time else ["暂无 AIS 摘要位置证据"]),
            ais_freshness_level=summary.ais_freshness_level if summary is not None else "UNKNOWN",
            latest_position_time=summary.latest_position_time if summary is not None else None,
            latest_city_code=summary.latest_city_code if summary is not None else None,
            latest_city_name=summary.latest_city_name if summary is not None else None,
            ais_unavailable_reason=summary.ais_unavailable_reason if summary is not None else None,
            data_availability_status="AVAILABLE" if summary is not None and summary.latest_position_time else "UNKNOWN",
        )
        ais_card = trajectory_card.model_copy(update={"deprecated_alias": True})
        pending_work_items = self._profile_pending_work_items(
            vessel_id=vessel_id,
            active_issue_count=len(active_issues),
            high_issue_count=severity_counts.get("HIGH", 0),
            active_risk_count=len(formal_risk_signals),
            pending_controller_count=pending_controller_count,
            pending_affiliation_count=pending_affiliation_count,
            ocr_pending_count=recognition_metrics["pending_diff_count"],
            ais_freshness_level=summary.ais_freshness_level if summary is not None else "UNKNOWN",
            summary_status_code=summary_status,
        )

        return VesselProfileCardResponse(
            vessel_id=vessel_id,
            generated_at=datetime.utcnow(),
            summary_status_code=summary_status,
            refreshed_at=summary.refreshed_at if summary is not None else None,
            source_updated_at=summary.source_updated_at if summary is not None else profile.updated_at,
            refresh_available=summary_status in {"MISSING", "STALE", "FAILED", "PARTIAL"},
            stale=summary_status == "STALE",
            data_sources=[item.source_code for item in source_trace],
            confidence_level=summary_confidence,
            coverage_rate=summary_coverage,
            source_trace=source_trace,
            uncertainty_notes=summary_notes,
            quality_warnings=[] if not active_issues else [f"当前存在 {len(active_issues)} 条未关闭质量问题"],
            identity_card=VesselProfileIdentityCard(
                status_code="AVAILABLE",
                confidence_level=summary.identity_confidence_level if summary is not None else "UNKNOWN",
                evidence_count=1 + len(name_history) + len(identifier_history),
                updated_at=identity_updated_at,
                source_codes=["VESSEL_PROFILE", "VESSEL_SUMMARY"],
                uncertainty_notes=conflict_warnings,
                ship_name=summary.ship_name if summary is not None and summary.ship_name else profile_response.ship_name,
                current_mmsi=summary.current_mmsi if summary is not None and summary.current_mmsi else profile_response.current_mmsi,
                vessel_profile_code=profile_response.vessel_profile_code,
                ship_type_code=summary.ship_type_code if summary is not None and summary.ship_type_code else profile_response.ship_type_code,
                ship_type_name=summary.ship_type_name if summary is not None and summary.ship_type_name else profile_response.ship_type_name,
                profile_status_code=profile_response.profile_status_code,
                profile_status_name=profile_response.profile_status_name,
                identity_status_code=profile_response.identity_status_code,
                identity_status_name=profile_response.identity_status_name,
                registry_city_code=profile_response.registry_city_code,
                registry_city_name=profile_response.registry_city_name,
                deadweight_ton=_decimal(summary.deadweight_ton if summary is not None else getattr(capacity, "deadweight_ton", None)),
                length_m=_decimal(summary.length_m if summary is not None else getattr(capacity, "length_m", None)),
                width_m=_decimal(summary.width_m if summary is not None else getattr(capacity, "width_m", None)),
                design_draft_m=_decimal(summary.design_draft_m if summary is not None else getattr(capacity, "design_draft_m", None)),
                name_history_summary=[
                    {"id": row.id, "ship_name": row.ship_name, "source_type_code": row.source_type_code, "created_at": row.created_at}
                    for row in name_history[:3]
                ],
                identifier_history_summary=[
                    {
                        "id": row.id,
                        "identifier_type_code": row.identifier_type_code,
                        "identifier_value": row.identifier_value,
                        "status_code": row.status_code,
                        "created_at": row.created_at,
                    }
                    for row in identifier_history[:3]
                ],
                conflict_warnings=conflict_warnings,
            ),
            relation_card=VesselProfileRelationCard(
                status_code="AVAILABLE" if current_relation_count else "UNKNOWN",
                confidence_level=summary.subject_consistency_level if summary is not None else "UNKNOWN",
                evidence_count=len(all_relation_rows),
                updated_at=relation_updated_at,
                source_codes=["RELATION_LEDGER"],
                uncertainty_notes=(
                    ([] if current_relation_count else ["当前有效主体关系缺失"])
                    + ([] if approved_controller_count else ["实际控制人缺少已审核可信证据"])
                    + ([] if approved_affiliation_count or not (primary_owner and primary_operator) else ["挂靠/授权关系缺少已审核可信证据"])
                ),
                primary_owner_name=summary.primary_owner_name if summary is not None and summary.primary_owner_name else (primary_owner.party_name if primary_owner else None),
                primary_operator_name=summary.primary_operator_name if summary is not None and summary.primary_operator_name else (primary_operator.operator_name if primary_operator else None),
                primary_contact_name=summary.primary_contact_name if summary is not None and summary.primary_contact_name else (primary_contact.contact_name if primary_contact else None),
                primary_contact_phone_masked=summary.primary_contact_phone_masked if summary is not None and summary.primary_contact_phone_masked else _mask_phone(primary_contact.mobile_phone if primary_contact else None),
                owner_count=len(current_owners),
                operator_count=len(current_operators),
                contact_count=len(current_contacts),
                crew_count=len(current_crew),
                current_relation_count=current_relation_count,
                history_relation_count=relation_history_count,
                voided_relation_count=relation_voided_count,
                controller_status_code="APPROVED" if approved_controller_count else ("PENDING" if pending_controller_count else "UNKNOWN"),
                affiliation_status_code="APPROVED" if approved_affiliation_count else ("PENDING" if pending_affiliation_count else "UNKNOWN"),
                controller_message=f"已审核可信证据 {approved_controller_count} 条；待治理 {pending_controller_count} 条",
                affiliation_message=f"已审核可信证据 {approved_affiliation_count} 条；待治理 {pending_affiliation_count} 条",
            ),
            quality_card=VesselProfileQualityCard(
                status_code="AVAILABLE" if summary is not None else "UNKNOWN",
                confidence_level=summary.data_quality_level if summary is not None else "UNKNOWN",
                evidence_count=len(active_issues),
                updated_at=quality_updated_at or (summary.refreshed_at if summary is not None else None),
                source_codes=["VESSEL_SUMMARY", "QUALITY_ISSUE"],
                uncertainty_notes=[] if summary is not None else ["摘要缺失，质量评分不可计算"],
                profile_completeness_rate=_decimal(summary.profile_completeness_rate if summary is not None else None),
                data_quality_score=_decimal(summary.data_quality_score if summary is not None else None),
                quality_level=summary.data_quality_level if summary is not None else "UNKNOWN",
                open_issue_count=len(active_issues),
                high_issue_count=severity_counts.get("HIGH", 0),
                medium_issue_count=severity_counts.get("MEDIUM", 0),
                missing_field_count=summary.missing_field_count if summary is not None else 0,
                conflict_count=summary.conflict_count if summary is not None else 0,
                top_active_issues=top_issues,
            ),
            compliance_card=VesselProfileComplianceCard(
                status_code=compliance_source_status if summary is not None or formal_risk_signals else "UNKNOWN",
                confidence_level=compliance_risk_level,
                evidence_count=len(formal_risk_signals) if formal_risk_signals else certificate_evidence_count,
                updated_at=max((row.updated_at for row in formal_risk_signals), default=None) if formal_risk_signals else (summary.refreshed_at if summary is not None else None),
                source_codes=[compliance_source_code, "VESSEL_SUMMARY"],
                uncertainty_notes=[] if compliance_risk_level != "UNKNOWN" else ["证书或主体证据不足，不能输出确定低风险"],
                risk_level=compliance_risk_level,
                certificate_missing_count=formal_risk_payload.get("certificate_missing_count", summary.certificate_missing_count if summary is not None else 0),
                certificate_expiring_count=formal_risk_payload.get("certificate_expiring_count", summary.certificate_expiring_count if summary is not None else 0),
                certificate_expired_count=formal_risk_payload.get("certificate_expired_count", summary.certificate_expired_count if summary is not None else 0),
                risk_evidence_summary=(
                    formal_risk_payload.get("risk_evidence_summary", [])
                    if formal_risk_payload.get("has_formal_signals")
                    else self._summary_json_list(summary.risk_evidence_summary_json if summary is not None else None)
                ),
                evidence_gap_count=(
                    formal_risk_payload.get("certificate_missing_count", 0)
                    + formal_risk_payload.get("certificate_expiring_count", 0)
                    + formal_risk_payload.get("certificate_expired_count", 0)
                    if formal_risk_payload.get("has_formal_signals")
                    else ((summary.certificate_missing_count + summary.certificate_expiring_count + summary.certificate_expired_count) if summary is not None else 0)
                ),
                message=compliance_message,
            ),
            trajectory_card=trajectory_card,
            ais_card=ais_card,
            recognition_card=VesselProfileRecognitionCard(
                status_code="REVIEW_REQUIRED" if recognition_metrics["pending_diff_count"] else ("ADOPTED" if recognition_metrics["adoption_count"] else "EMPTY"),
                confidence_level="LOW" if recognition_metrics["low_confidence_diff_count"] else ("MEDIUM" if recognition_metrics["pending_diff_count"] else "UNKNOWN"),
                evidence_count=recognition_metrics["pending_diff_count"] + recognition_metrics["adoption_count"],
                updated_at=recognition_updated_at,
                source_codes=["OCR_ADOPTION"],
                uncertainty_notes=["存在低置信 OCR 字段待复核"] if recognition_metrics["low_confidence_diff_count"] else [],
                pending_diff_count=recognition_metrics["pending_diff_count"],
                low_confidence_diff_count=recognition_metrics["low_confidence_diff_count"],
                active_task_count=recognition_metrics["active_task_count"],
                adoption_count=recognition_metrics["adoption_count"],
                latest_adoption=recognition_metrics["latest_adoption"],
                message="暂无 OCR 证据" if not recognition_metrics["pending_diff_count"] and not recognition_metrics["adoption_count"] else None,
            ),
            candidate_card=VesselProfileCandidateCard(
                status_code="UNAVAILABLE",
                confidence_level="UNKNOWN",
                evidence_count=0,
                source_codes=["CANDIDATE_ANALYSIS"],
                uncertainty_notes=["候选船舶分析将在 Round 8 接入"],
            ),
            pending_work_items=pending_work_items,
        )

    def _profile_pending_work_items(
        self,
        *,
        vessel_id: int,
        active_issue_count: int,
        high_issue_count: int,
        active_risk_count: int,
        pending_controller_count: int,
        pending_affiliation_count: int,
        ocr_pending_count: int,
        ais_freshness_level: str,
        summary_status_code: str,
    ) -> list[VesselWorkbenchItemResponse]:
        specs: list[tuple[str, str, int, str, str, dict[str, Any], str, str, list[str]]] = []
        if active_issue_count:
            specs.append((
                "profile_quality_issues",
                "质量问题待处理",
                active_issue_count,
                "HIGH" if high_issue_count else "MEDIUM",
                "/vessels/quality",
                {"vessel_id": vessel_id, "status_code": "OPEN"},
                "该船存在未关闭质量问题，需修复源字段后重新校验。",
                "QUALITY",
                ["源字段", "重新校验记录"],
            ))
        if active_risk_count:
            specs.append((
                "profile_risk_signals",
                "合规风险待处理",
                active_risk_count,
                "HIGH",
                f"/vessels/{vessel_id}/compliance",
                {},
                "该船存在正式风险信号，需要按推荐动作补证、修复或复核。",
                "RISK",
                ["风险证据", "证明链缺口", "复核意见"],
            ))
        relation_pending = pending_controller_count + pending_affiliation_count
        if relation_pending:
            specs.append((
                "profile_relation_evidence",
                "主体证据待审核",
                relation_pending,
                "MEDIUM",
                f"/vessels/{vessel_id}/relations",
                {"tab": "controller" if pending_controller_count else "affiliation"},
                "控制人/挂靠证据审核后会进入候选结论，人工确认后才成为当前结论。",
                "EVIDENCE",
                ["证据审核意见", "候选结论确认"],
            ))
        if ocr_pending_count:
            specs.append((
                "profile_ocr_pending",
                "OCR 字段待确认",
                ocr_pending_count,
                "MEDIUM",
                "/vessels/recognitions",
                {"vessel_id": vessel_id},
                "OCR 字段差异需要人工采纳或跳过，才会沉淀为可信档案字段。",
                "OCR",
                ["识别字段", "采纳/跳过原因"],
            ))
        if ais_freshness_level in {"STALE", "EXPIRED", "UNKNOWN"}:
            specs.append((
                "profile_ais_gap",
                "AIS 观测需核对",
                1,
                "MEDIUM",
                "/vessels/ais-situation",
                {"vessel_id": vessel_id},
                "AIS 新鲜度不足会影响轨迹态势、空间分析和候选分析可信度。",
                "AIS",
                ["MMSI 映射", "最新 AIS 点位"],
            ))
        if summary_status_code in {"MISSING", "STALE", "FAILED", "PARTIAL"}:
            specs.append((
                "profile_summary_refresh",
                "资产摘要需刷新",
                1,
                "LOW",
                f"/vessels/{vessel_id}/profile-card",
                {},
                "资产摘要需要重算后才能反映最新质量、主体、合规和 AIS 可信状态。",
                "ASSET",
                ["摘要刷新结果"],
            ))
        return [
            VesselWorkbenchItemResponse(
                code=code,
                title=title,
                count=count,
                priority_code=priority,
                target_path=target_path,
                target_query=query,
                explain_reason=reason,
                evidence_gaps=gaps,
                source_object_anchor=f"VESSEL_PROFILE:{vessel_id}",
                workbench_group=group,
                recommended_actions=[
                    VesselRecommendedAction(
                        action_type="DRILLDOWN",
                        label="进入处理",
                        target_path=target_path,
                        target_object_type="VESSEL_PROFILE",
                        target_object_id=str(vessel_id),
                        source_object_anchor=f"VESSEL_PROFILE:{vessel_id}",
                        workbench_group=group,
                        payload=query,
                        description=reason,
                    )
                ],
            )
            for code, title, count, priority, target_path, query, reason, group, gaps in specs
        ]

    def _paginate_evidence_items(
        self,
        items: list[VesselProfileCardEvidenceItem],
        *,
        page: int,
        page_size: int,
    ) -> list[VesselProfileCardEvidenceItem]:
        start = (page - 1) * page_size
        return items[start : start + page_size]

    def _relation_evidence_item(
        self,
        section: str,
        object_type: str,
        row: Any,
        title: str,
        *,
        conclusion_refs: list[Any] | None = None,
    ) -> VesselProfileCardEvidenceItem:
        status_code = self._relation_status_code(row)
        evidence_json = getattr(row, "evidence_json", None)
        evidence_payload = evidence_json if isinstance(evidence_json, dict) else {}
        missing_fields: list[str] = []
        if isinstance(row, VesselControllerEvidence):
            missing_fields = self._controller_evidence_missing_fields(row)
        elif isinstance(row, VesselAffiliationEvidence):
            missing_fields = self._affiliation_evidence_missing_fields(row)
        attachment_refs = evidence_payload.get("attachment_refs")
        if not isinstance(attachment_refs, list):
            attachment_refs = []
        relation_payload: dict[str, Any] = {}
        if isinstance(row, VesselControllerEvidence):
            relation_payload = {
                "party_name": row.party_name,
                "controller_role_code": row.controller_role_code,
                "confidence_level": row.confidence_level,
                "controller_certificate_type": self._json_path_value(evidence_payload, "controller_identity.certificate_type"),
                "controller_certificate_no": self._json_path_value(evidence_payload, "controller_identity.certificate_no"),
                "contact_phone": self._json_path_value(evidence_payload, "contact.phone"),
                "owner_relationship": self._json_path_value(evidence_payload, "relationship.owner_relationship"),
                "operator_relationship": self._json_path_value(evidence_payload, "relationship.operator_relationship"),
                "confirmation_source": self._json_path_value(evidence_payload, "confirmation.source"),
                "confirmation_method": self._json_path_value(evidence_payload, "confirmation.method"),
            }
        elif isinstance(row, VesselAffiliationEvidence):
            relation_payload = {
                "affiliation_type_code": row.affiliation_type_code,
                "subject_name": row.subject_name,
                "counterparty_name": row.counterparty_name,
                "confidence_level": row.confidence_level,
                "affiliation_company": self._json_path_value(evidence_payload, "affiliation_contract.affiliation_company"),
                "actual_shipowner": self._json_path_value(evidence_payload, "affiliation_contract.actual_shipowner"),
                "agreement_start": self._json_path_value(evidence_payload, "affiliation_contract.agreement_start"),
                "agreement_end": self._json_path_value(evidence_payload, "affiliation_contract.agreement_end"),
                "certificate_operator": self._json_path_value(evidence_payload, "operation_qualification.certificate_operator"),
                "transport_permit_relation": self._json_path_value(evidence_payload, "operation_qualification.transport_permit_relation"),
                "business_contact": self._json_path_value(evidence_payload, "contact.business_contact"),
            }
        return VesselProfileCardEvidenceItem(
            id=f"{object_type}:{row.id}",
            section=section,
            object_type=object_type,
            object_id=str(row.id),
            title=title,
            status_code=status_code,
            source_code=getattr(row, "source_type_code", None),
            created_at=getattr(row, "created_at", None),
            updated_at=getattr(row, "updated_at", None),
            payload={
                **relation_payload,
                "start_date": getattr(row, "start_date", None),
                "end_date": getattr(row, "end_date", None),
                "effective_from": getattr(row, "effective_from", None),
                "effective_to": getattr(row, "effective_to", None),
                "is_current": getattr(row, "is_current", None),
                "is_primary": getattr(row, "is_primary", None),
                "revision": getattr(row, "revision", None),
                "verified_status_code": getattr(row, "verified_status_code", None),
                "verified_at": getattr(row, "verified_at", None),
                "verified_by": getattr(row, "verified_by", None),
                "evidence_summary": getattr(row, "evidence_summary", None),
                "evidence_json": evidence_payload,
                "voided_at": getattr(row, "voided_at", None),
                "void_reason": getattr(row, "void_reason", None),
            },
            evidence_completeness=self._evidence_completeness(missing_fields) if missing_fields or object_type in {"VESSEL_CONTROLLER_EVIDENCE", "VESSEL_AFFILIATION_EVIDENCE"} else None,
            missing_required_fields=missing_fields,
            attachment_refs=attachment_refs,
            approval_history=self._profile_evidence_approval_history(row),
            conclusion_refs=[ref.model_dump(mode="json") if hasattr(ref, "model_dump") else _jsonable(ref) for ref in (conclusion_refs or [])],
        )

    @staticmethod
    def _profile_evidence_approval_history(row: Any) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        verified_status_code = getattr(row, "verified_status_code", None)
        if verified_status_code:
            history.append({"label": "审批状态", "value": verified_status_code})
        verified_at = getattr(row, "verified_at", None)
        if verified_at:
            history.append({"label": "审批时间", "value": _jsonable(verified_at)})
        verified_by = getattr(row, "verified_by", None)
        if verified_by:
            history.append({"label": "审批人", "value": verified_by})
        revision = getattr(row, "revision", None)
        if revision is not None:
            history.append({"label": "版本", "value": revision})
        return history

    async def get_profile_card_evidence(self, vessel_id: int, query: Any) -> VesselProfileCardEvidenceResponse:
        profile = await self._require_profile(vessel_id)
        section = query.section
        page = query.page
        page_size = query.page_size
        items: list[VesselProfileCardEvidenceItem] = []
        notes: list[str] = []

        if section == "identity":
            capacity = await self.repo.get_one_by_profile(VesselCapacityDimension, vessel_id)
            items.append(
                VesselProfileCardEvidenceItem(
                    id=f"vessel_profile:{profile.id}",
                    section=section,
                    object_type="VESSEL_PROFILE",
                    object_id=str(profile.id),
                    title=f"当前船舶主档：{profile.ship_name}",
                    status_code=profile.identity_status_code,
                    source_code=profile.source_type_code,
                    created_at=profile.created_at,
                    updated_at=profile.updated_at,
                    payload={
                        "ship_name": profile.ship_name,
                        "current_mmsi": profile.current_mmsi,
                        "vessel_profile_code": profile.vessel_profile_code,
                        "ship_type_code": profile.ship_type_code,
                        "profile_status_code": profile.profile_status_code,
                        "registry_city_code": profile.registry_city_code,
                        "deadweight_ton": getattr(capacity, "deadweight_ton", None),
                        "length_m": getattr(capacity, "length_m", None),
                        "width_m": getattr(capacity, "width_m", None),
                        "design_draft_m": getattr(capacity, "design_draft_m", None),
                    },
                )
            )
            name_rows = await self.repo.list_by_profile(VesselNameHistory, vessel_id, order_desc=True)
            identifier_rows = await self.repo.list_by_profile(VesselIdentifierHistory, vessel_id, order_desc=True)
            for row in name_rows:
                items.append(
                    VesselProfileCardEvidenceItem(
                        id=f"name_history:{row.id}",
                        section=section,
                        object_type="NAME_HISTORY",
                        object_id=str(row.id),
                        title=f"船名历史：{row.ship_name}",
                        source_code=row.source_type_code,
                        created_at=row.created_at,
                        updated_at=row.created_at,
                        payload={
                            "ship_name": row.ship_name,
                            "start_date": row.start_date,
                            "end_date": row.end_date,
                        },
                    )
                )
            for row in identifier_rows:
                items.append(
                    VesselProfileCardEvidenceItem(
                        id=f"identifier_history:{row.id}",
                        section=section,
                        object_type="IDENTIFIER_HISTORY",
                        object_id=str(row.id),
                        title=f"{row.identifier_type_code} 历史：{row.identifier_value}",
                        status_code=row.status_code,
                        source_code=row.source_type_code,
                        confidence_score=row.confidence_score,
                        created_at=row.created_at,
                        updated_at=row.created_at,
                        payload={
                            "identifier_type_code": row.identifier_type_code,
                            "identifier_value": row.identifier_value,
                            "start_date": row.start_date,
                            "end_date": row.end_date,
                            "source_trace_id": row.source_trace_id,
                        },
                    )
                )
        elif section == "relation":
            for row in await self.repo.list_by_profile(VesselOwnerPeriod, vessel_id):
                items.append(self._relation_evidence_item(section, "OWNER_PERIOD", row, f"所有方：{row.party_name}"))
            for row in await self.repo.list_by_profile(VesselOperatorPeriod, vessel_id):
                items.append(self._relation_evidence_item(section, "OPERATOR_PERIOD", row, f"经营方：{row.operator_name}"))
            for row in await self.repo.list_by_profile(VesselContact, vessel_id):
                items.append(self._relation_evidence_item(section, "CONTACT", row, f"联系人：{row.contact_name}"))
            for row in await self.repo.list_by_profile(VesselCrewAssignment, vessel_id):
                items.append(self._relation_evidence_item(section, "CREW_ASSIGNMENT", row, f"船员：{row.crew_name}"))
            controller_rows = (
                await self.db.scalars(
                    select(VesselControllerEvidence)
                    .where(VesselControllerEvidence.vessel_profile_id == vessel_id)
                    .order_by(VesselControllerEvidence.voided_at.asc().nullsfirst(), VesselControllerEvidence.updated_at.desc())
                )
            ).all()
            affiliation_rows = (
                await self.db.scalars(
                    select(VesselAffiliationEvidence)
                    .where(VesselAffiliationEvidence.vessel_profile_id == vessel_id)
                    .order_by(VesselAffiliationEvidence.voided_at.asc().nullsfirst(), VesselAffiliationEvidence.updated_at.desc())
                )
            ).all()
            label_map = await _load_label_map(self.db)
            controller_refs = await self._controller_evidence_ref_map(vessel_id, label_map)
            affiliation_refs = await self._affiliation_evidence_ref_map(vessel_id, label_map)
            for row in controller_rows:
                items.append(
                    self._relation_evidence_item(
                        section,
                        "VESSEL_CONTROLLER_EVIDENCE",
                        row,
                        f"实际控制人证据：{row.party_name}",
                        conclusion_refs=controller_refs.get(row.id, []),
                    )
                )
            for row in affiliation_rows:
                items.append(
                    self._relation_evidence_item(
                        section,
                        "VESSEL_AFFILIATION_EVIDENCE",
                        row,
                        f"挂靠关系证据：{row.affiliation_type_code}",
                        conclusion_refs=affiliation_refs.get(row.id, []),
                    )
                )
            if not controller_rows:
                notes.append("暂无实际控制人证据，相关风险保持不可计算或待补证")
            if not affiliation_rows:
                notes.append("暂无挂靠关系证据，相关风险保持不可计算或待补证")
        elif section == "quality":
            rows = (
                await self.db.scalars(
                    select(VesselDataQualityIssue)
                    .where(VesselDataQualityIssue.vessel_profile_id == vessel_id)
                    .order_by(VesselDataQualityIssue.updated_at.desc(), VesselDataQualityIssue.id.desc())
                )
            ).all()
            for row in rows:
                items.append(
                    VesselProfileCardEvidenceItem(
                        id=f"quality_issue:{row.id}",
                        section=section,
                        object_type="QUALITY_ISSUE",
                        object_id=str(row.id),
                        title=f"{row.issue_type_code} / {row.field_name or row.affected_object_type}",
                        status_code=row.status_code,
                        severity_code=row.severity_code,
                        source_code=row.evidence_source,
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                        payload={
                            "affected_object_type": row.affected_object_type,
                            "affected_object_id": row.affected_object_id,
                            "fingerprint": row.fingerprint,
                            "impact_scope": row.impact_scope_json or [],
                            "resolved_at": row.resolved_at,
                            "resolved_evidence": row.resolved_evidence,
                        },
                    )
                )
        elif section == "compliance":
            signal_rows = (
                await self.db.scalars(
                    select(VesselRiskSignal)
                    .where(VesselRiskSignal.vessel_profile_id == vessel_id)
                    .order_by(VesselRiskSignal.updated_at.desc(), VesselRiskSignal.id.desc())
                )
            ).all()
            for row in signal_rows:
                items.append(
                    VesselProfileCardEvidenceItem(
                        id=f"risk_signal:{row.id}",
                        section=section,
                        object_type="VESSEL_RISK_SIGNAL",
                        object_id=str(row.id),
                        title=f"风险信号：{row.risk_type_code}",
                        status_code=row.status_code,
                        severity_code=row.risk_level,
                        source_code="VESSEL_RISK_SIGNAL",
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                        payload={
                            "risk_type_code": row.risk_type_code,
                            "risk_level": row.risk_level,
                            "rule_code": row.rule_code,
                            "confidence_level": row.confidence_level,
                            "evidence": row.evidence_json or {},
                            "uncertainty_notes": row.uncertainty_notes_json or [],
                            "revision": row.revision,
                        },
                    )
                )
            for row in await self.db.scalars(
                select(VesselControllerEvidence).where(VesselControllerEvidence.vessel_profile_id == vessel_id)
            ):
                items.append(self._relation_evidence_item(section, "VESSEL_CONTROLLER_EVIDENCE", row, f"实际控制人证据：{row.party_name}"))
            for row in await self.db.scalars(
                select(VesselAffiliationEvidence).where(VesselAffiliationEvidence.vessel_profile_id == vessel_id)
            ):
                items.append(self._relation_evidence_item(section, "VESSEL_AFFILIATION_EVIDENCE", row, f"挂靠关系证据：{row.affiliation_type_code}"))
            if signal_rows:
                notes.append("合规风险证据来自 Round 5 风险信号和补充证据")
            rows = (
                await self.db.scalars(
                    select(VesselCertificate)
                    .where(VesselCertificate.vessel_profile_id == vessel_id, VesselCertificate.voided_at.is_(None))
                    .order_by(VesselCertificate.updated_at.desc(), VesselCertificate.id.desc())
                )
            ).all()
            for row in rows:
                items.append(
                    VesselProfileCardEvidenceItem(
                        id=f"certificate:{row.id}",
                        section=section,
                        object_type="VESSEL_CERTIFICATE",
                        object_id=str(row.id),
                        title=f"船舶证书：{row.certificate_type_code}",
                        status_code=row.verify_status_code,
                        source_code="CERTIFICATE_LEDGER_PRE_RULE",
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                        payload={
                            "certificate_type_code": row.certificate_type_code,
                            "certificate_no": row.certificate_no,
                            "issuing_authority": row.issuing_authority,
                            "valid_from": row.valid_from,
                            "valid_to": row.valid_to,
                            "is_long_term_valid": row.is_long_term_valid,
                            "validity_text_raw": row.validity_text_raw,
                        },
                    )
                )
            if not signal_rows:
                notes.append("尚未刷新正式风险信号，当前仅展示证书账本证据")
        elif section == "recognition":
            diff_rows = (
                await self.db.scalars(
                    select(VesselRecognitionFieldDiff)
                    .where(VesselRecognitionFieldDiff.vessel_profile_id == vessel_id)
                    .order_by(VesselRecognitionFieldDiff.updated_at.desc(), VesselRecognitionFieldDiff.id.desc())
                )
            ).all()
            adoption_rows = (
                await self.db.scalars(
                    select(VesselRecognitionAdoptionRecord)
                    .where(VesselRecognitionAdoptionRecord.vessel_profile_id == vessel_id)
                    .order_by(VesselRecognitionAdoptionRecord.confirmed_at.desc(), VesselRecognitionAdoptionRecord.id.desc())
                )
            ).all()
            for row in diff_rows:
                items.append(
                    VesselProfileCardEvidenceItem(
                        id=f"recognition_diff:{row.id}",
                        section=section,
                        object_type="RECOGNITION_FIELD_DIFF",
                        object_id=str(row.id),
                        title=f"字段差异：{row.field_name}",
                        status_code=row.adopt_status_code,
                        source_code=row.recognition_object_type,
                        confidence_score=row.confidence_score,
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                        payload={
                            "recognition_id": row.recognition_id,
                            "target_object_type": row.target_object_type,
                            "target_object_id": row.target_object_id,
                            "current_value_text": row.current_value_text,
                            "recognized_value_text": row.recognized_value_text,
                            "evidence_text": row.evidence_text,
                        },
                    )
                )
            for row in adoption_rows:
                items.append(
                    VesselProfileCardEvidenceItem(
                        id=f"recognition_adoption:{row.id}",
                        section=section,
                        object_type="RECOGNITION_ADOPTION",
                        object_id=str(row.id),
                        title=f"OCR 采纳：{row.target_object_type}",
                        status_code="ADOPTED",
                        source_code=row.recognition_object_type,
                        created_at=row.created_at,
                        updated_at=row.confirmed_at,
                        payload={
                            "recognition_id": row.recognition_id,
                            "target_object_id": row.target_object_id,
                            "adopted_fields": row.adopted_fields_json or [],
                            "skipped_fields": row.skipped_fields_json or [],
                            "reason": row.reason,
                            "change_event_id": row.change_event_id,
                        },
                    )
                )
            if not items:
                notes.append("暂无 OCR 证据")
        elif section == "trajectory":
            summary = await self.db.scalar(select(VesselProfileSummary).where(VesselProfileSummary.vessel_profile_id == vessel_id))
            if summary is None:
                notes.append("资产摘要未生成，暂无轨迹摘要证据")
            else:
                items.append(
                    VesselProfileCardEvidenceItem(
                        id=f"trajectory_summary:{summary.id}",
                        section=section,
                        object_type="AIS_SUMMARY",
                        object_id=str(summary.id),
                        title=f"AIS 摘要：{summary.ais_freshness_level}",
                        status_code=summary.ais_freshness_level,
                        source_code="AIS_SUMMARY",
                        created_at=summary.created_at,
                        updated_at=summary.refreshed_at,
                        payload={
                            "latest_position_time": summary.latest_position_time,
                            "latest_city_code": summary.latest_city_code,
                            "latest_city_name": summary.latest_city_name,
                            "ais_unavailable_reason": summary.ais_unavailable_reason,
                            "summary_status_code": self._effective_summary_status(summary),
                        },
                    )
                )

        for item in items:
            if not item.display_fields:
                item.display_fields = self._profile_evidence_display_fields(item)
            if not item.recommended_actions:
                item.recommended_actions = self._profile_evidence_actions(vessel_id, item)
        await self._attach_profile_relation_files(items)
        items.sort(key=lambda item: item.updated_at or item.created_at or datetime.min, reverse=True)
        source_code = {
            "identity": "VESSEL_PROFILE",
            "relation": "RELATION_LEDGER",
            "quality": "QUALITY_ISSUE",
            "compliance": "VESSEL_RISK_SIGNAL",
            "recognition": "OCR_ADOPTION",
            "trajectory": "AIS_SUMMARY",
        }.get(section, "VESSEL_PROFILE")
        return VesselProfileCardEvidenceResponse(
            total=len(items),
            page=page,
            page_size=page_size,
            items=self._paginate_evidence_items(items, page=page, page_size=page_size),
            section=section,
            source_trace=[self._profile_card_source_trace(source_code, status_code="AVAILABLE" if items else "EMPTY")],
            uncertainty_notes=notes,
        )

    @staticmethod
    def _profile_evidence_display_fields(item: VesselProfileCardEvidenceItem) -> list[dict[str, Any]]:
        payload = item.payload or {}
        templates: dict[str, list[tuple[str, str]]] = {
            "VESSEL_PROFILE": [
                ("船名", "ship_name"),
                ("MMSI", "current_mmsi"),
                ("船型", "ship_type_code"),
                ("档案状态", "profile_status_code"),
            ],
            "QUALITY_ISSUE": [
                ("对象", "affected_object_type"),
                ("对象 ID", "affected_object_id"),
                ("影响范围", "impact_scope"),
                ("关闭证据", "resolved_evidence"),
            ],
            "VESSEL_RISK_SIGNAL": [
                ("风险类型", "risk_type_code"),
                ("风险等级", "risk_level"),
                ("规则", "rule_code"),
                ("不确定性", "uncertainty_notes"),
            ],
            "VESSEL_CERTIFICATE": [
                ("证书类型", "certificate_type_code"),
                ("证书号", "certificate_no"),
                ("签发机构", "issuing_authority"),
                ("有效期至", "valid_to"),
            ],
            "VESSEL_CONTROLLER_EVIDENCE": [
                ("控制人", "party_name"),
                ("控制人角色", "controller_role_code"),
                ("可信度", "confidence_level"),
                ("审核状态", "verified_status_code"),
                ("证件类型", "controller_certificate_type"),
                ("证件号", "controller_certificate_no"),
                ("联系方式", "contact_phone"),
                ("与所有人关系", "owner_relationship"),
                ("与经营人关系", "operator_relationship"),
                ("确认来源", "confirmation_source"),
                ("确认方式", "confirmation_method"),
                ("有效期开始", "effective_from"),
                ("有效期结束", "effective_to"),
                ("证据摘要", "evidence_summary"),
            ],
            "VESSEL_AFFILIATION_EVIDENCE": [
                ("挂靠类型", "affiliation_type_code"),
                ("主体", "subject_name"),
                ("相对方", "counterparty_name"),
                ("挂靠公司", "affiliation_company"),
                ("实际船东", "actual_shipowner"),
                ("协议开始", "agreement_start"),
                ("协议结束", "agreement_end"),
                ("证书经营主体", "certificate_operator"),
                ("营运证关系", "transport_permit_relation"),
                ("业务联系人", "business_contact"),
                ("可信度", "confidence_level"),
                ("证据摘要", "evidence_summary"),
            ],
            "RECOGNITION_FIELD_DIFF": [
                ("字段", "field_name"),
                ("当前值", "current_value_text"),
                ("识别值", "recognized_value_text"),
                ("置信度", "confidence_score"),
            ],
            "RECOGNITION_ADOPTION": [
                ("识别记录", "recognition_id"),
                ("采纳字段", "adopted_fields"),
                ("跳过字段", "skipped_fields"),
                ("原因", "reason"),
            ],
            "AIS_SUMMARY": [
                ("最新时间", "latest_position_time"),
                ("城市", "latest_city_name"),
                ("新鲜度", "summary_status_code"),
                ("不可用原因", "ais_unavailable_reason"),
            ],
        }
        keys = templates.get(item.object_type)
        if keys is None:
            keys = [(key, key) for key in list(payload)[:5]]
        fields: list[dict[str, Any]] = []
        for label, key in keys:
            value = payload.get(key)
            if value is not None and value != "":
                fields.append({"label": label, "value": value})
        return fields

    @staticmethod
    def _profile_evidence_actions(vessel_id: int, item: VesselProfileCardEvidenceItem) -> list[VesselRecommendedAction]:
        if item.object_type == "QUALITY_ISSUE":
            return [
                VesselRecommendedAction(
                    action_type="OPEN_QUALITY",
                    label="处理质量问题",
                    target_path=f"/vessels/quality?quality_issue_id={item.object_id}&vessel_id={vessel_id}",
                    target_object_type=item.object_type,
                    target_object_id=item.object_id,
                    source_object_anchor=f"{item.object_type}:{item.object_id}",
                    workbench_group="QUALITY",
                )
            ]
        if item.object_type == "VESSEL_RISK_SIGNAL":
            return [
                VesselRecommendedAction(
                    action_type="OPEN_RISK",
                    label="处理风险",
                    target_path=f"/vessels/{vessel_id}/compliance?risk_signal_id={item.object_id}",
                    target_object_type=item.object_type,
                    target_object_id=item.object_id,
                    source_object_anchor=f"{item.object_type}:{item.object_id}",
                    workbench_group="RISK",
                )
            ]
        if item.object_type in {"VESSEL_CONTROLLER_EVIDENCE", "VESSEL_AFFILIATION_EVIDENCE"}:
            tab = "controller" if item.object_type == "VESSEL_CONTROLLER_EVIDENCE" else "affiliation"
            return [
                VesselRecommendedAction(
                    action_type="OPEN_RELATION_EVIDENCE",
                    label="查看主体证据",
                    target_path=f"/vessels/{vessel_id}/relations?tab={tab}&evidence_id={item.object_id}",
                    target_object_type=item.object_type,
                    target_object_id=item.object_id,
                    source_object_anchor=f"{item.object_type}:{item.object_id}",
                    workbench_group="EVIDENCE",
                )
            ]
        if item.object_type == "VESSEL_CERTIFICATE":
            return [
                VesselRecommendedAction(
                    action_type="OPEN_CERTIFICATE",
                    label="维护证书",
                    target_path=f"/vessels/{vessel_id}/edit?tab=certificates&certificate_id={item.object_id}",
                    target_object_type=item.object_type,
                    target_object_id=item.object_id,
                    source_object_anchor=f"{item.object_type}:{item.object_id}",
                    workbench_group="RISK",
                )
            ]
        if item.object_type == "RECOGNITION_FIELD_DIFF":
            return [
                VesselRecommendedAction(
                    action_type="OPEN_OCR",
                    label="确认 OCR 字段",
                    target_path=f"/vessels/recognitions?vessel_id={vessel_id}&field_diff_id={item.object_id}",
                    target_object_type=item.object_type,
                    target_object_id=item.object_id,
                    source_object_anchor=f"{item.object_type}:{item.object_id}",
                    workbench_group="OCR",
                )
            ]
        return []
