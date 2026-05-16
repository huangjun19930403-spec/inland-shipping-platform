"""Implementation methods for the vessel compliance domain."""

from __future__ import annotations

from app.modules.vessel.shared import base as _base

globals().update({name: getattr(_base, name) for name in dir(_base) if not name.startswith("__")})


class VesselComplianceMixin:
    """Implementation methods for the vessel compliance domain."""

    async def _compliance_risk_by_profile(self, ids: list[int]) -> dict[int, dict[str, Any]]:
        if not ids:
            return {}
        profile_ids = list(dict.fromkeys(ids))

        def chunks(values: list[int], size: int = 900):
            for start in range(0, len(values), size):
                yield values[start:start + size]

        today = date.today()
        expiring_until = today + timedelta(days=30)
        cert_rows: list[VesselCertificate] = []
        for chunk in chunks(profile_ids):
            cert_rows.extend((
                await self.db.execute(
                    select(VesselCertificate).where(
                        VesselCertificate.vessel_profile_id.in_(chunk),
                        VesselCertificate.voided_at.is_(None),
                    )
                )
            ).scalars().all())
        certs_by_profile: dict[int, list[VesselCertificate]] = defaultdict(list)
        for cert in cert_rows:
            certs_by_profile[cert.vessel_profile_id].append(cert)

        owner_rows: list[VesselOwnerPeriod] = []
        for chunk in chunks(profile_ids):
            owner_rows.extend((
                await self.db.execute(
                    select(VesselOwnerPeriod).where(
                        VesselOwnerPeriod.vessel_profile_id.in_(chunk),
                        VesselOwnerPeriod.is_current.is_(True),
                    )
                )
            ).scalars().all())
        owner_by_profile = {owner.vessel_profile_id: owner for owner in owner_rows}
        owner_ids = [owner.id for owner in owner_rows]
        owner_docs: list[VesselOwnerDocument] = []
        for chunk in chunks(owner_ids):
            owner_docs.extend((
                await self.db.execute(
                    select(VesselOwnerDocument).where(
                        VesselOwnerDocument.vessel_owner_period_id.in_(chunk),
                        VesselOwnerDocument.voided_at.is_(None),
                    )
                )
            ).scalars().all())
        owner_doc_types: dict[int, set[str]] = defaultdict(set)
        for document in owner_docs:
            owner_doc_types[document.vessel_owner_period_id].add(document.document_type_code)

        result: dict[int, dict[str, Any]] = {}
        for profile_id in profile_ids:
            certs = certs_by_profile.get(profile_id, [])
            cert_types = {cert.certificate_type_code for cert in certs}
            missing_cert_types = [code for code in REQUIRED_VESSEL_CERTIFICATE_TYPES if code not in cert_types]
            expiring_certs = [
                cert.certificate_type_code for cert in certs
                if cert.valid_to is not None and cert.valid_to <= expiring_until and not cert.is_long_term_valid
            ]
            owner = owner_by_profile.get(profile_id)
            missing_owner_docs: list[str] = []
            owner_completeness_status = "UNKNOWN_OWNER_TYPE"
            if owner is not None:
                required_owner_docs = self._owner_required_document_types(owner)
                if required_owner_docs:
                    missing_owner_docs = sorted(required_owner_docs - owner_doc_types.get(owner.id, set()))
                    owner_completeness_status = "COMPLETE" if not missing_owner_docs else "INCOMPLETE"
            has_risk = bool(missing_cert_types or expiring_certs or missing_owner_docs)
            result[profile_id] = {
                "has_certificate_risk": has_risk,
                "missing_certificate_type_codes": missing_cert_types,
                "expiring_certificate_type_codes": expiring_certs,
                "owner_document_completeness_status": owner_completeness_status,
                "missing_owner_document_type_codes": missing_owner_docs,
                "required_certificate_count": len(REQUIRED_VESSEL_CERTIFICATE_TYPES),
                "archived_certificate_count": len(cert_types & set(REQUIRED_VESSEL_CERTIFICATE_TYPES)),
            }
        return result

    async def list_compliance_risks(self, query: Any) -> PageResponse[VesselRiskSignalResponse]:
        stmt = select(VesselRiskSignal).join(VesselProfile, VesselProfile.id == VesselRiskSignal.vessel_profile_id)
        if getattr(query, "vessel_id", None):
            stmt = stmt.where(VesselRiskSignal.vessel_profile_id == query.vessel_id)
        if getattr(query, "status_code", None):
            stmt = stmt.where(VesselRiskSignal.status_code == query.status_code)
        if getattr(query, "risk_type_code", None):
            stmt = stmt.where(VesselRiskSignal.risk_type_code == query.risk_type_code)
        if getattr(query, "risk_level", None):
            stmt = stmt.where(VesselRiskSignal.risk_level == query.risk_level)
        if getattr(query, "rule_code", None):
            stmt = stmt.where(VesselRiskSignal.rule_code == query.rule_code)
        if getattr(query, "keyword", None):
            like_value = f"%{query.keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    VesselRiskSignal.risk_type_code.ilike(like_value),
                    VesselRiskSignal.rule_code.ilike(like_value),
                    VesselRiskSignal.fingerprint.ilike(like_value),
                    VesselProfile.vessel_profile_code.ilike(like_value),
                    VesselProfile.ship_name.ilike(like_value),
                    VesselProfile.current_mmsi.ilike(like_value),
                )
            )
        total = await self.db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = (
            await self.db.scalars(
                stmt.order_by(VesselRiskSignal.last_detected_at.desc(), VesselRiskSignal.id.desc())
                .offset((query.page - 1) * query.page_size)
                .limit(query.page_size)
            )
        ).all()
        label_map = await _load_label_map(self.db)
        profiles = await self._profiles_by_ids([row.vessel_profile_id for row in rows])
        return PageResponse(
            total=int(total or 0),
            page=query.page,
            page_size=query.page_size,
            items=[self._risk_signal_response(row, label_map, profiles.get(row.vessel_profile_id)) for row in rows],
        )

    async def list_compliance_rules(self, query: Any) -> PageResponse[VesselCertificateRequirementRuleResponse]:
        stmt = select(VesselCertificateRequirementRule)
        if getattr(query, "status_code", None):
            stmt = stmt.where(VesselCertificateRequirementRule.status_code == query.status_code)
        if getattr(query, "scope_type_code", None):
            stmt = stmt.where(VesselCertificateRequirementRule.scope_type_code == query.scope_type_code)
        if getattr(query, "certificate_type_code", None):
            stmt = stmt.where(VesselCertificateRequirementRule.required_certificate_type_code == query.certificate_type_code)
        if getattr(query, "keyword", None):
            like_value = f"%{query.keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    VesselCertificateRequirementRule.rule_code.ilike(like_value),
                    VesselCertificateRequirementRule.rule_name.ilike(like_value),
                    VesselCertificateRequirementRule.required_certificate_type_code.ilike(like_value),
                )
            )
        total = await self.db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = (
            await self.db.scalars(
                stmt.order_by(VesselCertificateRequirementRule.status_code.asc(), VesselCertificateRequirementRule.id.asc())
                .offset((query.page - 1) * query.page_size)
                .limit(query.page_size)
            )
        ).all()
        label_map = await _load_label_map(self.db)
        return PageResponse(
            total=int(total or 0),
            page=query.page,
            page_size=query.page_size,
            items=[self._compliance_rule_response(row, label_map) for row in rows],
        )

    async def create_compliance_rule(self, payload: Any) -> VesselCertificateRequirementRuleResponse:
        data = payload.model_dump(exclude_none=True)
        existed = await self.db.scalar(
            select(VesselCertificateRequirementRule).where(VesselCertificateRequirementRule.rule_code == data["rule_code"])
        )
        if existed is not None:
            raise ConflictError("规则编码已存在", code="VESSEL_RULE_CODE_EXISTS")
        row = VesselCertificateRequirementRule(**data)
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return self._compliance_rule_response(row, await _load_label_map(self.db))

    async def update_compliance_rule(self, rule_id: int, payload: Any) -> VesselCertificateRequirementRuleResponse:
        row = await self.db.get(VesselCertificateRequirementRule, rule_id)
        if row is None:
            raise NotFoundError("VesselCertificateRequirementRule", rule_id)
        updates = payload.model_dump(exclude_none=True)
        revision = updates.pop("revision", None)
        self._ensure_revision(row, revision)
        if not updates:
            raise ValidationError("no update fields provided")
        for key, value in updates.items():
            setattr(row, key, value)
        row.revision = int(row.revision or 1) + 1
        row.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(row)
        return self._compliance_rule_response(row, await _load_label_map(self.db))

    async def void_compliance_rule(self, rule_id: int, payload: Any) -> VesselCertificateRequirementRuleResponse:
        row = await self.db.get(VesselCertificateRequirementRule, rule_id)
        if row is None:
            raise NotFoundError("VesselCertificateRequirementRule", rule_id)
        self._ensure_revision(row, getattr(payload, "revision", None))
        row.status_code = "VOIDED"
        row.remark = getattr(payload, "reason", None) or row.remark
        row.revision = int(row.revision or 1) + 1
        row.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(row)
        return self._compliance_rule_response(row, await _load_label_map(self.db))

    async def get_compliance_risk(self, vessel_id: int) -> VesselComplianceRiskResponse:
        await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        signals = await self._active_risk_signals(vessel_id)
        return await self._compliance_risk_response(vessel_id, signals, label_map)

    async def refresh_compliance_risk(self, vessel_id: int, *, operator_id: int | None = None) -> VesselComplianceRiskResponse:
        profile = await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        try:
            evaluated = await self._evaluate_compliance_risks(profile)
            touched = await self._sync_risk_signals(profile.id, evaluated)
            await self._add_change_event(
                profile.id,
                "REFRESH_COMPLIANCE_RISK",
                "刷新合规风险",
                None,
                {"risk_signal_count": len(touched), "version": COMPLIANCE_VERSION},
                operator_id,
                object_type="vessel_profile",
                object_id=profile.id,
            )
            await self.db.commit()
        except Exception as exc:  # noqa: BLE001
            await self.db.rollback()
            logger.warning("vessel compliance risk refresh failed for profile %s: %s", vessel_id, exc)
            signals = await self._active_risk_signals(vessel_id)
            return await self._compliance_risk_response(
                vessel_id,
                signals,
                label_map,
                engine_status_code="FAILED",
                extra_uncertainty_notes=["合规风险刷新失败，已保留既有风险信号；请修复数据或规则后重试"],
            )
        await self._refresh_summary_best_effort(vessel_id)
        signals = await self._active_risk_signals(vessel_id)
        return await self._compliance_risk_response(vessel_id, signals, label_map, engine_refreshed=True)

    async def _refresh_compliance_risk_best_effort(self, vessel_id: int, *, operator_id: int | None = None) -> None:
        try:
            await self.refresh_compliance_risk(vessel_id, operator_id=operator_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("best-effort vessel compliance risk refresh failed for profile %s: %s", vessel_id, exc)
            await self.db.rollback()

    async def update_risk_signal(self, vessel_id: int, signal_id: int, payload: Any, *, operator_id: int | None = None) -> VesselRiskSignalResponse:
        await self._require_profile(vessel_id)
        row = await self.db.get(VesselRiskSignal, signal_id)
        if row is None or row.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselRiskSignal", signal_id)
        self._ensure_revision(row, payload.revision)
        if payload.status_code in COMPLIANCE_CLOSED_STATUSES and not payload.resolution_reason:
            raise ValidationError("关闭风险必须填写处理原因")
        if payload.status_code in COMPLIANCE_CLOSED_STATUSES:
            resolution_type = (payload.evidence_json or {}).get("resolution_type")
            if resolution_type not in {"DATA_RECHECK_PASSED", "FALSE_POSITIVE", "REVIEW_CONFIRMED"}:
                raise ValidationError("关闭风险必须声明 resolution_type：DATA_RECHECK_PASSED / FALSE_POSITIVE / REVIEW_CONFIRMED")
        before = _row_dict(row)
        row.status_code = payload.status_code
        row.resolution_reason = payload.resolution_reason
        row.evidence_json = {**(row.evidence_json or {}), "resolution_evidence": payload.evidence_json or {}}
        row.resolved_by = operator_id if payload.status_code in COMPLIANCE_CLOSED_STATUSES else None
        row.resolved_at = datetime.utcnow() if payload.status_code in COMPLIANCE_CLOSED_STATUSES else None
        row.revision = int(row.revision or 1) + 1
        row.updated_at = datetime.utcnow()
        await self._add_change_event(
            vessel_id,
            "UPDATE_RISK_SIGNAL",
            "处理风险信号",
            before,
            _row_dict(row),
            operator_id,
            object_type="vessel_risk_signal",
            object_id=row.id,
            reason=payload.resolution_reason,
        )
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return self._risk_signal_response(row, await _load_label_map(self.db), await self._require_profile(vessel_id))

    def _vessel_signal_summary(self, profile: VesselProfile | None, label_map: dict[str, dict[str, str]]) -> VesselRiskSignalVesselSummary | None:
        if profile is None:
            return None
        return VesselRiskSignalVesselSummary(
            id=profile.id,
            ship_name=profile.ship_name,
            current_mmsi=profile.current_mmsi,
            vessel_profile_code=profile.vessel_profile_code,
            profile_status_code=profile.profile_status_code,
            profile_status_name=label_map.get("VESSEL_PROFILE_STATUS", {}).get(profile.profile_status_code),
        )

    def _risk_signal_response(
        self,
        row: VesselRiskSignal,
        label_map: dict[str, dict[str, str]],
        profile: VesselProfile | None = None,
    ) -> VesselRiskSignalResponse:
        return VesselRiskSignalResponse(
            **_row_dict(row),
            risk_type_name=label_map.get("VESSEL_RISK_SIGNAL_TYPE", {}).get(row.risk_type_code),
            risk_level_name=label_map.get("VESSEL_RISK_LEVEL", {}).get(row.risk_level),
            status_name=label_map.get("VESSEL_RISK_SIGNAL_STATUS", {}).get(row.status_code),
            confidence_level_name=label_map.get("VESSEL_CONFIDENCE_LEVEL", {}).get(row.confidence_level),
            vessel=self._vessel_signal_summary(profile, label_map),
            recommended_actions=self._risk_signal_actions(row),
            next_actions=self._risk_signal_actions(row),
            explain_reason=self._risk_signal_explain_reason(row),
            evidence_gaps=self._risk_signal_evidence_gaps(row),
            source_object_anchor=f"VESSEL_RISK_SIGNAL:{row.id}",
            workbench_group="RISK",
            verification_status_code="WAITING_RECHECK" if row.status_code in COMPLIANCE_ACTIVE_STATUSES else "PASSED",
            verification_message=(
                "风险仍处于命中状态，请按推荐动作补证、修复或提交复核。"
                if row.status_code in COMPLIANCE_ACTIVE_STATUSES
                else "风险已关闭或已缓释。"
            ),
            proof_chain=self._risk_signal_proof_chain(row),
            missing_evidence=self._risk_signal_evidence_gaps(row),
            review_action_path=f"/vessels/{row.vessel_profile_id}/compliance?risk_signal_id={row.id}&review=1",
            validation_entrypoint="POST /api/v1/vessels/{vessel_id}/compliance-risk/refresh",
        )

    def _risk_signal_actions(self, row: VesselRiskSignal) -> list[VesselRecommendedAction]:
        target_path = self._risk_signal_action_path(row)
        actions = [
            VesselRecommendedAction(
                action_type="FIX_OR_REVIEW_RISK",
                label=self._risk_signal_action_label(row),
                target_path=target_path,
                target_object_type="VESSEL_RISK_SIGNAL",
                target_object_id=str(row.id),
                required_fields=self._risk_signal_required_fields(row),
                source_object_anchor=f"VESSEL_RISK_SIGNAL:{row.id}",
                workbench_group="RISK",
                description="由后端规则给出风险修复入口；前端不再根据 risk_type_code 字符串猜跳转。",
            )
        ]
        if row.status_code in COMPLIANCE_ACTIVE_STATUSES:
            actions.append(
                VesselRecommendedAction(
                    action_type="SUBMIT_REVIEW",
                    label="提交风险复核",
                    target_path=f"/vessels/{row.vessel_profile_id}/compliance?risk_signal_id={row.id}&review=1",
                    target_object_type="VESSEL_RISK_SIGNAL",
                    target_object_id=str(row.id),
                    source_object_anchor=f"VESSEL_RISK_SIGNAL:{row.id}",
                    workbench_group="RISK",
                    description="当数据暂无法修复、规则误报或需人工认定时，走风险复核链路。",
                )
            )
        return actions

    @staticmethod
    def _risk_signal_action_path(row: VesselRiskSignal) -> str:
        return compliance_risk_action_path(row)

    @staticmethod
    def _risk_signal_action_label(row: VesselRiskSignal) -> str:
        return compliance_risk_action_label(row)

    @staticmethod
    def _risk_signal_required_fields(row: VesselRiskSignal) -> list[str]:
        return compliance_risk_required_fields(row)

    def _risk_signal_evidence_gaps(self, row: VesselRiskSignal) -> list[str]:
        required = self._risk_signal_required_fields(row)
        if required:
            return required
        if row.risk_level == "UNKNOWN":
            return ["风险判定证据", "人工复核意见"]
        return ["风险重算结果"]

    @staticmethod
    def _risk_signal_explain_reason(row: VesselRiskSignal) -> str:
        notes = row.uncertainty_notes_json or []
        note_text = "；".join(str(item) for item in notes[:2]) if isinstance(notes, list) else str(notes)
        rule = row.rule_code or row.risk_type_code
        if note_text:
            return f"规则 {rule} 命中：{note_text}"
        return f"规则 {rule} 命中，风险等级 {row.risk_level}，需按推荐动作补证、修复或复核。"

    def _risk_signal_proof_chain(self, row: VesselRiskSignal) -> list[dict[str, Any]]:
        evidence = row.evidence_json or {}
        gaps = self._risk_signal_evidence_gaps(row)
        return [
            {
                "step_code": "RULE_HIT",
                "step_name": "规则命中",
                "status_code": "HIT",
                "message": self._risk_signal_explain_reason(row),
                "payload": {"risk_type_code": row.risk_type_code, "rule_code": row.rule_code, "risk_level": row.risk_level},
            },
            {
                "step_code": "EVIDENCE",
                "step_name": "证据材料",
                "status_code": "MISSING" if gaps else "READY",
                "message": "仍缺少：" + "、".join(gaps) if gaps else "已有证据可支撑复核",
                "payload": evidence,
            },
            {
                "step_code": "VALIDATION",
                "step_name": "验收方式",
                "status_code": "WAITING_RECHECK" if row.status_code in COMPLIANCE_ACTIVE_STATUSES else "PASSED",
                "message": "修复后重新执行合规风险刷新；误报或人工认定关闭需走审核中心。",
                "payload": {"review_action_path": f"/vessels/{row.vessel_profile_id}/compliance?risk_signal_id={row.id}&review=1"},
            },
        ]

    def _compliance_rule_response(
        self,
        row: VesselCertificateRequirementRule,
        label_map: dict[str, dict[str, str]],
    ) -> VesselCertificateRequirementRuleResponse:
        return VesselCertificateRequirementRuleResponse(
            **_row_dict(row),
            scope_type_name=label_map.get("VESSEL_RULE_SCOPE_TYPE", {}).get(row.scope_type_code),
            ship_type_name=label_map.get("SHIP_TYPE", {}).get(row.ship_type_code or ""),
            required_certificate_type_name=label_map.get("VESSEL_CERTIFICATE_TYPE", {}).get(row.required_certificate_type_code),
            risk_type_name=label_map.get("VESSEL_RISK_SIGNAL_TYPE", {}).get(row.risk_type_code),
            risk_level_when_missing_name=label_map.get("VESSEL_RISK_LEVEL", {}).get(row.risk_level_when_missing),
            status_name=label_map.get("VESSEL_REQUIREMENT_RULE_STATUS", {}).get(row.status_code),
        )

    async def _active_risk_signals(self, vessel_id: int) -> list[VesselRiskSignal]:
        if not hasattr(self.db, "scalars"):
            return []
        return list(
            (
                await self.db.scalars(
                    select(VesselRiskSignal)
                    .where(
                        VesselRiskSignal.vessel_profile_id == vessel_id,
                        VesselRiskSignal.status_code.in_(COMPLIANCE_ACTIVE_STATUSES),
                    )
                    .order_by(VesselRiskSignal.risk_level.asc(), VesselRiskSignal.last_detected_at.desc())
                )
            ).all()
        )

    async def _compliance_risk_response(
        self,
        vessel_id: int,
        signals: list[VesselRiskSignal],
        label_map: dict[str, dict[str, str]],
        *,
        engine_refreshed: bool = False,
        engine_status_code: str | None = None,
        extra_uncertainty_notes: list[str] | None = None,
    ) -> VesselComplianceRiskResponse:
        profile = await self._require_profile(vessel_id)
        rules = await self._active_certificate_rules(profile)
        context_gap = self._compliance_context_gap(profile)
        active_levels = [row.risk_level for row in signals if row.status_code in COMPLIANCE_ACTIVE_STATUSES]
        overall = _max_risk_level(active_levels)
        if not signals and rules and engine_refreshed and not context_gap["not_computable"]:
            overall = "LOW"
        high_count = sum(1 for row in signals if row.risk_level == "HIGH")
        medium_count = sum(1 for row in signals if row.risk_level == "MEDIUM")
        gap_count = sum(1 for row in signals if row.risk_level in {"HIGH", "MEDIUM", "UNKNOWN"})
        rule_summary = await self._certificate_rule_summary(vessel_id, rules)
        notes: list[str] = []
        if not rules:
            notes.append("证书要求规则缺失，合规风险不可计算")
        if any(row.risk_level == "UNKNOWN" for row in signals):
            notes.append("存在证据不足的风险信号，UNKNOWN 不等同低风险")
        if context_gap["not_computable"]:
            notes.append(COMPLIANCE_NOT_COMPUTABLE_NOTE)
        if extra_uncertainty_notes:
            notes.extend(extra_uncertainty_notes)
        status_code = engine_status_code or ("RULE_MISSING" if not rules else ("NOT_COMPUTABLE" if context_gap["not_computable"] else "READY"))
        profiles = await self._profiles_by_ids([vessel_id])
        return VesselComplianceRiskResponse(
            vessel_id=vessel_id,
            generated_at=datetime.utcnow(),
            overall_risk_level=overall,
            overall_risk_level_name=label_map.get("VESSEL_RISK_LEVEL", {}).get(overall),
            engine_status_code=status_code,
            risk_signal_count=len(signals),
            open_signal_count=sum(1 for row in signals if row.status_code == "OPEN"),
            high_signal_count=high_count,
            medium_signal_count=medium_count,
            rule_coverage_rate=_percent(len(rules), len(REQUIRED_VESSEL_CERTIFICATE_TYPES)),
            evidence_gap_count=gap_count,
            data_sources=["CERTIFICATE_REQUIREMENT_RULE", "CERTIFICATE_LEDGER", "RELATION_LEDGER", "OCR_ADOPTION"],
            uncertainty_notes=notes,
            rule_summary=rule_summary,
            signals=[self._risk_signal_response(row, label_map, profiles.get(vessel_id)) for row in signals],
            proof_chain=[
                {
                    "step_code": "RULE_COVERAGE",
                    "step_name": "规则覆盖",
                    "status_code": status_code,
                    "message": "证书规则、主体结论、OCR 和名单信号共同形成合规判断。",
                    "payload": {"rule_count": len(rules), "context_gap": context_gap},
                },
                {
                    "step_code": "OPEN_RISK",
                    "step_name": "未闭合风险",
                    "status_code": "OPEN" if signals else "CLEAR",
                    "message": f"当前未闭合风险 {len(signals)} 条，高风险 {high_count} 条。",
                    "payload": {"risk_signal_ids": [row.id for row in signals]},
                },
            ],
            missing_evidence=list(dict.fromkeys([gap for row in signals for gap in self._risk_signal_evidence_gaps(row)])),
            review_action_path=f"/vessels/{vessel_id}/compliance?review=1",
        )

    async def _active_certificate_rules(self, profile: VesselProfile) -> list[VesselCertificateRequirementRule]:
        stmt = select(VesselCertificateRequirementRule).where(VesselCertificateRequirementRule.status_code == "ACTIVE")
        rows = list((await self.db.scalars(stmt)).all())
        matched: list[VesselCertificateRequirementRule] = []
        for row in rows:
            if self._rule_matches_profile_context(row, profile):
                matched.append(row)
        return matched

    @staticmethod
    def _rule_scope_codes(row: VesselCertificateRequirementRule, field_name: str) -> set[str]:
        values: set[str] = set()
        direct = getattr(row, field_name, None)
        if direct:
            values.add(str(direct))
        condition = row.condition_json or {}
        for key in (field_name, f"{field_name}s", field_name.replace("_code", "_codes")):
            raw = condition.get(key)
            if isinstance(raw, list):
                values.update(str(item) for item in raw if item)
            elif raw:
                values.add(str(raw))
        return values

    @staticmethod
    def _profile_context_code(profile: VesselProfile, *field_names: str) -> str | None:
        for field_name in field_names:
            raw = getattr(profile, field_name, None)
            if raw:
                return str(raw)
        return None

    def _rule_matches_profile_context(self, row: VesselCertificateRequirementRule, profile: VesselProfile) -> bool:
        if row.scope_type_code == "GLOBAL":
            return True
        if row.scope_type_code == "SHIP_TYPE":
            values = self._rule_scope_codes(row, "ship_type_code")
            return bool(values and profile.ship_type_code and str(profile.ship_type_code) in values)
        if row.scope_type_code == "CARGO_CATEGORY":
            values = self._rule_scope_codes(row, "cargo_category_code")
            profile_value = self._profile_context_code(profile, "cargo_category_code")
            return bool(values and profile_value and profile_value in values)
        if row.scope_type_code == "ROUTE_AREA":
            values = self._rule_scope_codes(row, "route_area_code")
            profile_value = self._profile_context_code(profile, "route_area_code")
            return bool(values and profile_value and profile_value in values)
        return False

    def _compliance_context_gap(self, profile: VesselProfile) -> dict[str, Any]:
        missing_context: list[str] = []
        if not getattr(profile, "ship_type_code", None):
            missing_context.append("ship_type_code")
        if not self._profile_context_code(profile, "cargo_category_code"):
            missing_context.append("cargo_category_code")
        if not self._profile_context_code(profile, "route_area_code"):
            missing_context.append("route_area_code")
        return {
            "not_computable": bool(missing_context),
            "missing_context": missing_context,
            "ship_type_code": getattr(profile, "ship_type_code", None),
            "cargo_category_code": self._profile_context_code(profile, "cargo_category_code"),
            "route_area_code": self._profile_context_code(profile, "route_area_code"),
        }

    async def _certificate_rule_summary(
        self,
        vessel_id: int,
        rules: list[VesselCertificateRequirementRule],
    ) -> list[dict[str, Any]]:
        certificates = await self._summary_certificates(vessel_id)
        by_type: dict[str, list[VesselCertificate]] = defaultdict(list)
        for cert in certificates:
            by_type[cert.certificate_type_code].append(cert)
        result: list[dict[str, Any]] = []
        for rule in rules:
            rows = by_type.get(rule.required_certificate_type_code, [])
            complete = [row for row in rows if self._certificate_has_complete_evidence(row)]
            result.append(
                {
                    "rule_code": rule.rule_code,
                    "rule_name": rule.rule_name,
                    "required_certificate_type_code": rule.required_certificate_type_code,
                    "status_code": "SATISFIED" if complete else ("INSUFFICIENT" if rows else "MISSING"),
                    "evidence_count": len(complete),
                    "candidate_count": len(rows),
                }
            )
        return result

    async def _evaluate_compliance_risks(self, profile: VesselProfile) -> list[dict[str, Any]]:
        today = date.today()
        expiring_limit = today + timedelta(days=30)
        rules = await self._active_certificate_rules(profile)
        certificates = await self._summary_certificates(profile.id)
        certs_by_type: dict[str, list[VesselCertificate]] = defaultdict(list)
        for cert in certificates:
            certs_by_type[cert.certificate_type_code].append(cert)
        risks: list[dict[str, Any]] = []
        for rule in rules:
            rows = certs_by_type.get(rule.required_certificate_type_code, [])
            complete_rows = [cert for cert in rows if self._certificate_has_complete_evidence(cert)]
            if not rows:
                risks.append(self._risk_payload(profile.id, "CERTIFICATE_MISSING", rule.risk_level_when_missing, rule.rule_code, rule.required_certificate_type_code, {"missing_certificate_type_code": rule.required_certificate_type_code}, ["证书缺失"]))
                continue
            if rows and not complete_rows:
                risks.append(self._risk_payload(profile.id, "CERTIFICATE_MISSING", "UNKNOWN", rule.rule_code, f"{rule.required_certificate_type_code}|insufficient", {"insufficient_certificate_type_code": rule.required_certificate_type_code, "candidate_certificate_ids": [row.id for row in rows]}, ["证书未核验或缺少证书号/有效期证据"]))
            for cert in complete_rows:
                if cert.is_long_term_valid or cert.valid_to is None:
                    continue
                if cert.valid_to < today:
                    risks.append(self._risk_payload(profile.id, "CERTIFICATE_EXPIRED", "HIGH", rule.rule_code, f"{cert.id}|expired", {"certificate_id": cert.id, "certificate_type_code": cert.certificate_type_code, "valid_to": cert.valid_to}, ["证书已过期"]))
                elif cert.valid_to <= expiring_limit:
                    risks.append(self._risk_payload(profile.id, "CERTIFICATE_EXPIRING", "MEDIUM", rule.rule_code, f"{cert.id}|expiring", {"certificate_id": cert.id, "certificate_type_code": cert.certificate_type_code, "valid_to": cert.valid_to}, ["证书 30 天内到期"]))

        owner = await self._summary_primary_relation(VesselOwnerPeriod, profile.id)
        operator = await self._summary_primary_relation(VesselOperatorPeriod, profile.id)
        if operator is None or getattr(operator, "verified_status_code", None) != "VERIFIED":
            risks.append(self._risk_payload(profile.id, "OPERATOR_QUALIFICATION_UNKNOWN", "UNKNOWN", None, "operator_qualification", {"operator_id": getattr(operator, "id", None), "verified_status_code": getattr(operator, "verified_status_code", None)}, ["经营方资质证据不足"]))
        subject_evidence = self._certificate_subject_values(certificates)
        if subject_evidence and owner is not None:
            mismatches = [item for item in subject_evidence if _normalized_text(item["subject_name"]) and _normalized_text(item["subject_name"]) != _normalized_text(owner.party_name)]
            if mismatches:
                risks.append(self._risk_payload(profile.id, "SUBJECT_MISMATCH", "MEDIUM", None, "certificate_subject_owner", {"owner_name": owner.party_name, "mismatches": mismatches}, ["证书主体与主所有方不一致"]))
        elif certificates:
            risks.append(self._risk_payload(profile.id, "SUBJECT_MISMATCH", "UNKNOWN", None, "certificate_subject_missing", {"certificate_count": len(certificates)}, ["证书主体字段证据不足，不能判断主体一致性"]))

        controller_count = int(
            await self.db.scalar(
                select(func.count(VesselControllerConclusion.id)).where(
                    VesselControllerConclusion.vessel_profile_id == profile.id,
                    VesselControllerConclusion.voided_at.is_(None),
                    VesselControllerConclusion.conclusion_status_code == "CURRENT",
                    or_(VesselControllerConclusion.effective_to.is_(None), VesselControllerConclusion.effective_to >= today),
                )
            )
            or 0
        )
        if not controller_count:
            risks.append(self._risk_payload(profile.id, "CONTROLLER_UNKNOWN", "UNKNOWN", None, "controller_missing", {}, ["未确认当前实际控制人结论"]))

        owner_is_person = owner is not None and getattr(owner, "party_type_code", None) == "PERSON"
        operator_is_company = operator is not None and getattr(operator, "party_type_code", None) == "COMPANY"
        if owner_is_person and operator_is_company:
            affiliation_count = int(
                await self.db.scalar(
                    select(func.count(VesselAffiliationConclusion.id)).where(
                        VesselAffiliationConclusion.vessel_profile_id == profile.id,
                        VesselAffiliationConclusion.voided_at.is_(None),
                        VesselAffiliationConclusion.conclusion_status_code == "CURRENT",
                        or_(VesselAffiliationConclusion.effective_to.is_(None), VesselAffiliationConclusion.effective_to >= today),
                    )
                )
                or 0
            )
            if not affiliation_count:
                risks.append(self._risk_payload(profile.id, "AFFILIATION_UNCLEAR", "UNKNOWN", None, "affiliation_missing", {"owner_id": owner.id, "operator_id": operator.id}, ["个人所有方 + 公司经营方缺少当前挂靠/授权结论"]))

        low_diff_count = int(
            await self.db.scalar(
                select(func.count(VesselRecognitionFieldDiff.id)).where(
                    VesselRecognitionFieldDiff.vessel_profile_id == profile.id,
                    VesselRecognitionFieldDiff.confidence_score.is_not(None),
                    VesselRecognitionFieldDiff.confidence_score < LOW_CONFIDENCE_SCORE_THRESHOLD,
                    VesselRecognitionFieldDiff.adopt_status_code.in_(["REVIEW_REQUIRED", "ADOPTED"]),
                )
            )
            or 0
        )
        if low_diff_count:
            risks.append(self._risk_payload(profile.id, "OCR_LOW_CONFIDENCE", "MEDIUM", None, "ocr_low_confidence", {"low_confidence_diff_count": low_diff_count}, ["存在低置信 OCR 字段需要复核"]))

        context_gap = self._compliance_context_gap(profile)
        if context_gap["not_computable"]:
            risks.append(
                self._risk_payload(
                    profile.id,
                    "CARGO_ROUTE_SHIPTYPE_UNCERTAIN",
                    "UNKNOWN",
                    None,
                    "cargo_route_shiptype_not_computable",
                    context_gap,
                    [COMPLIANCE_NOT_COMPUTABLE_NOTE],
                )
            )

        return risks

    def _risk_payload(
        self,
        profile_id: int,
        risk_type_code: str,
        risk_level: str,
        rule_code: str | None,
        evidence_key: str,
        evidence: dict[str, Any],
        notes: list[str],
    ) -> dict[str, Any]:
        return {
            "vessel_profile_id": profile_id,
            "risk_type_code": risk_type_code,
            "risk_level": risk_level,
            "rule_code": rule_code,
            "confidence_level": "LOW" if risk_level == "UNKNOWN" else "MEDIUM",
            "fingerprint": _risk_fingerprint(profile_id, risk_type_code, rule_code, evidence_key),
            "evidence_json": _jsonable(evidence),
            "source_trace_json": [
                {"source_code": "CERTIFICATE_REQUIREMENT_RULE" if rule_code else "VESSEL_COMPLIANCE_ENGINE", "rule_code": rule_code},
            ],
            "uncertainty_notes_json": notes,
        }

    async def _sync_risk_signals(self, vessel_id: int, evaluated: list[dict[str, Any]]) -> list[VesselRiskSignal]:
        now = datetime.utcnow()
        active_rows = list(
            (
                await self.db.scalars(
                    select(VesselRiskSignal).where(
                        VesselRiskSignal.vessel_profile_id == vessel_id,
                        VesselRiskSignal.status_code.in_(COMPLIANCE_ACTIVE_STATUSES),
                    )
                )
            ).all()
        )
        active_by_fingerprint = {row.fingerprint: row for row in active_rows}
        seen: set[str] = set()
        touched: list[VesselRiskSignal] = []
        for payload in evaluated:
            fingerprint = payload["fingerprint"]
            seen.add(fingerprint)
            row = active_by_fingerprint.get(fingerprint)
            if row is None:
                row = VesselRiskSignal(
                    status_code="OPEN",
                    first_detected_at=now,
                    last_detected_at=now,
                    created_at=now,
                    updated_at=now,
                    **payload,
                )
                self.db.add(row)
            else:
                row.risk_level = payload["risk_level"]
                row.rule_code = payload["rule_code"]
                row.confidence_level = payload["confidence_level"]
                row.evidence_json = payload["evidence_json"]
                row.source_trace_json = payload["source_trace_json"]
                row.uncertainty_notes_json = payload["uncertainty_notes_json"]
                row.last_detected_at = now
                row.updated_at = now
                row.revision = int(row.revision or 1) + 1
            touched.append(row)
        for row in active_rows:
            if row.fingerprint not in seen:
                if row.risk_type_code == "BLACKLIST_SIGNAL":
                    continue
                row.status_code = "MITIGATED"
                row.resolved_at = now
                row.resolution_reason = "规则重算后不再命中"
                row.updated_at = now
                row.revision = int(row.revision or 1) + 1
        await self.db.flush()
        return touched

    async def _formal_risk_summary(self, vessel_id: int) -> dict[str, Any]:
        signals = await self._active_risk_signals(vessel_id)
        if not signals:
            return {"has_formal_signals": False}
        active = [row for row in signals if row.status_code in COMPLIANCE_ACTIVE_STATUSES]
        levels = [row.risk_level for row in active]
        risk_level = _max_risk_level(levels)
        return {
            "has_formal_signals": True,
            "risk_level": risk_level,
            "risk_evidence_summary": [
                {
                    "source": "VESSEL_RISK_SIGNAL",
                    "risk_signal_id": row.id,
                    "risk_type_code": row.risk_type_code,
                    "risk_level": row.risk_level,
                    "rule_code": row.rule_code,
                    "status_code": row.status_code,
                    "evidence": row.evidence_json or {},
                    "uncertainty_notes": row.uncertainty_notes_json or [],
                }
                for row in active[:20]
            ],
            "certificate_missing_count": sum(1 for row in active if row.risk_type_code == "CERTIFICATE_MISSING"),
            "certificate_expiring_count": sum(1 for row in active if row.risk_type_code == "CERTIFICATE_EXPIRING"),
            "certificate_expired_count": sum(1 for row in active if row.risk_type_code == "CERTIFICATE_EXPIRED"),
        }

    def _certificate_subject_values(self, certificates: list[VesselCertificate]) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for cert in certificates:
            payload = cert.structured_payload_json or {}
            subject = _first_value(payload, ["owner_name", "holder_name", "ship_owner", "subject_name", "company_name"])
            if subject:
                values.append({"certificate_id": cert.id, "certificate_type_code": cert.certificate_type_code, "subject_name": str(subject)})
        return values
