"""Implementation methods for the vessel relation domain."""

from __future__ import annotations

from app.modules.vessel.shared import base as _base
from app.modules.vessel.relation.basic_relations import BasicRelationMixin
from app.modules.vessel.relation.conclusion_helpers import RelationConclusionHelperMixin

globals().update({name: getattr(_base, name) for name in dir(_base) if not name.startswith("__")})


class VesselRelationMixin(BasicRelationMixin, RelationConclusionHelperMixin):
    """Implementation methods for the vessel relation domain."""

    async def list_controller_evidence(self, vessel_id: int) -> list[VesselControllerEvidenceResponse]:
        await self._require_profile(vessel_id)
        rows = (
            await self.db.scalars(
                select(VesselControllerEvidence)
                .where(VesselControllerEvidence.vessel_profile_id == vessel_id)
                .order_by(VesselControllerEvidence.voided_at.asc().nullsfirst(), VesselControllerEvidence.updated_at.desc())
            )
        ).all()
        label_map = await _load_label_map(self.db)
        conclusion_refs = await self._controller_evidence_ref_map(vessel_id, label_map)
        attachment_map = await self._relation_evidence_attachment_map(
            "VESSEL_CONTROLLER_EVIDENCE",
            [row.id for row in rows],
        )
        return [
            self._controller_evidence_response(
                row,
                label_map,
                conclusion_refs.get(row.id, []),
                attachment_map.get(row.id, []),
            )
            for row in rows
        ]

    async def create_controller_evidence(self, vessel_id: int, payload: Any, *, operator_id: int | None = None) -> VesselControllerEvidenceResponse:
        await self._require_profile(vessel_id)
        row = VesselControllerEvidence(vessel_profile_id=vessel_id, **payload.model_dump(exclude_none=True))
        self.db.add(row)
        await self.db.flush()
        await self._submit_evidence_approval_if_needed(
            row,
            object_type_code="VESSEL_CONTROLLER_EVIDENCE",
            object_name=row.party_name,
            operator_id=operator_id,
            before=None,
            after=_row_dict(row),
        )
        await self._add_change_event(vessel_id, "CREATE_CONTROLLER_EVIDENCE", "新增实际控制人证据", None, _row_dict(row), operator_id, object_type="vessel_controller_evidence", object_id=row.id)
        await self.rebuild_relation_conclusion_candidates(vessel_id, operator_id=operator_id, commit=False)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self.db.refresh(row)
        label_map = await _load_label_map(self.db)
        conclusion_refs = await self._controller_evidence_ref_map(vessel_id, label_map)
        attachment_map = await self._relation_evidence_attachment_map("VESSEL_CONTROLLER_EVIDENCE", [row.id])
        return self._controller_evidence_response(row, label_map, conclusion_refs.get(row.id, []), attachment_map.get(row.id, []))

    async def update_controller_evidence(self, vessel_id: int, evidence_id: int, payload: Any, *, operator_id: int | None = None) -> VesselControllerEvidenceResponse:
        row = await self._require_evidence_row(VesselControllerEvidence, vessel_id, evidence_id)
        updates = payload.model_dump(exclude_none=True)
        revision = updates.pop("revision", None)
        reason = updates.pop("reason", None)
        self._ensure_revision(row, revision)
        if not updates:
            raise ValidationError("no update fields provided")
        before = _row_dict(row)
        for key, value in updates.items():
            setattr(row, key, value)
        row.revision = int(row.revision or 1) + 1
        row.updated_at = datetime.utcnow()
        await self._submit_evidence_approval_if_needed(
            row,
            object_type_code="VESSEL_CONTROLLER_EVIDENCE",
            object_name=row.party_name,
            operator_id=operator_id,
            before=before,
            after=_row_dict(row),
        )
        await self._add_change_event(vessel_id, "UPDATE_CONTROLLER_EVIDENCE", "更新实际控制人证据", before, _row_dict(row), operator_id, object_type="vessel_controller_evidence", object_id=row.id, reason=reason)
        await self.rebuild_relation_conclusion_candidates(vessel_id, operator_id=operator_id, commit=False)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self.db.refresh(row)
        label_map = await _load_label_map(self.db)
        conclusion_refs = await self._controller_evidence_ref_map(vessel_id, label_map)
        attachment_map = await self._relation_evidence_attachment_map("VESSEL_CONTROLLER_EVIDENCE", [row.id])
        return self._controller_evidence_response(row, label_map, conclusion_refs.get(row.id, []), attachment_map.get(row.id, []))

    async def void_controller_evidence(self, vessel_id: int, evidence_id: int, payload: Any, *, operator_id: int | None = None) -> VesselControllerEvidenceResponse:
        row = await self._require_evidence_row(VesselControllerEvidence, vessel_id, evidence_id)
        if row.voided_at is not None:
            raise ConflictError("证据已作废", code="EVIDENCE_VOIDED")
        self._ensure_revision(row, getattr(payload, "revision", None))
        before = _row_dict(row)
        row.voided_at = datetime.utcnow()
        row.voided_by = operator_id
        row.void_reason = getattr(payload, "reason", None) or "证据作废"
        row.status_code = "VOIDED"
        row.revision = int(row.revision or 1) + 1
        row.updated_at = datetime.utcnow()
        await self._add_change_event(vessel_id, "VOID_CONTROLLER_EVIDENCE", "作废实际控制人证据", before, _row_dict(row), operator_id, object_type="vessel_controller_evidence", object_id=row.id, reason=row.void_reason)
        await self.rebuild_relation_conclusion_candidates(vessel_id, operator_id=operator_id, commit=False)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self.db.refresh(row)
        label_map = await _load_label_map(self.db)
        conclusion_refs = await self._controller_evidence_ref_map(vessel_id, label_map)
        attachment_map = await self._relation_evidence_attachment_map("VESSEL_CONTROLLER_EVIDENCE", [row.id])
        return self._controller_evidence_response(row, label_map, conclusion_refs.get(row.id, []), attachment_map.get(row.id, []))

    async def list_affiliation_evidence(self, vessel_id: int) -> list[VesselAffiliationEvidenceResponse]:
        await self._require_profile(vessel_id)
        rows = (
            await self.db.scalars(
                select(VesselAffiliationEvidence)
                .where(VesselAffiliationEvidence.vessel_profile_id == vessel_id)
                .order_by(VesselAffiliationEvidence.voided_at.asc().nullsfirst(), VesselAffiliationEvidence.updated_at.desc())
            )
        ).all()
        label_map = await _load_label_map(self.db)
        conclusion_refs = await self._affiliation_evidence_ref_map(vessel_id, label_map)
        attachment_map = await self._relation_evidence_attachment_map(
            "VESSEL_AFFILIATION_EVIDENCE",
            [row.id for row in rows],
        )
        return [
            self._affiliation_evidence_response(
                row,
                label_map,
                conclusion_refs.get(row.id, []),
                attachment_map.get(row.id, []),
            )
            for row in rows
        ]

    async def create_affiliation_evidence(self, vessel_id: int, payload: Any, *, operator_id: int | None = None) -> VesselAffiliationEvidenceResponse:
        await self._require_profile(vessel_id)
        data = payload.model_dump(exclude_none=True)
        await self._validate_affiliation_relation_refs(vessel_id, data)
        row = VesselAffiliationEvidence(vessel_profile_id=vessel_id, **data)
        self.db.add(row)
        await self.db.flush()
        await self._submit_evidence_approval_if_needed(
            row,
            object_type_code="VESSEL_AFFILIATION_EVIDENCE",
            object_name=row.subject_name or row.counterparty_name or row.affiliation_type_code,
            operator_id=operator_id,
            before=None,
            after=_row_dict(row),
        )
        await self._add_change_event(vessel_id, "CREATE_AFFILIATION_EVIDENCE", "新增挂靠关系证据", None, _row_dict(row), operator_id, object_type="vessel_affiliation_evidence", object_id=row.id)
        await self.rebuild_relation_conclusion_candidates(vessel_id, operator_id=operator_id, commit=False)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self.db.refresh(row)
        label_map = await _load_label_map(self.db)
        conclusion_refs = await self._affiliation_evidence_ref_map(vessel_id, label_map)
        attachment_map = await self._relation_evidence_attachment_map("VESSEL_AFFILIATION_EVIDENCE", [row.id])
        return self._affiliation_evidence_response(row, label_map, conclusion_refs.get(row.id, []), attachment_map.get(row.id, []))

    async def update_affiliation_evidence(self, vessel_id: int, evidence_id: int, payload: Any, *, operator_id: int | None = None) -> VesselAffiliationEvidenceResponse:
        row = await self._require_evidence_row(VesselAffiliationEvidence, vessel_id, evidence_id)
        updates = payload.model_dump(exclude_none=True)
        revision = updates.pop("revision", None)
        reason = updates.pop("reason", None)
        self._ensure_revision(row, revision)
        await self._validate_affiliation_relation_refs(vessel_id, updates)
        if not updates:
            raise ValidationError("no update fields provided")
        before = _row_dict(row)
        for key, value in updates.items():
            setattr(row, key, value)
        row.revision = int(row.revision or 1) + 1
        row.updated_at = datetime.utcnow()
        await self._submit_evidence_approval_if_needed(
            row,
            object_type_code="VESSEL_AFFILIATION_EVIDENCE",
            object_name=row.subject_name or row.counterparty_name or row.affiliation_type_code,
            operator_id=operator_id,
            before=before,
            after=_row_dict(row),
        )
        await self._add_change_event(vessel_id, "UPDATE_AFFILIATION_EVIDENCE", "更新挂靠关系证据", before, _row_dict(row), operator_id, object_type="vessel_affiliation_evidence", object_id=row.id, reason=reason)
        await self.rebuild_relation_conclusion_candidates(vessel_id, operator_id=operator_id, commit=False)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self.db.refresh(row)
        label_map = await _load_label_map(self.db)
        conclusion_refs = await self._affiliation_evidence_ref_map(vessel_id, label_map)
        attachment_map = await self._relation_evidence_attachment_map("VESSEL_AFFILIATION_EVIDENCE", [row.id])
        return self._affiliation_evidence_response(row, label_map, conclusion_refs.get(row.id, []), attachment_map.get(row.id, []))

    async def void_affiliation_evidence(self, vessel_id: int, evidence_id: int, payload: Any, *, operator_id: int | None = None) -> VesselAffiliationEvidenceResponse:
        row = await self._require_evidence_row(VesselAffiliationEvidence, vessel_id, evidence_id)
        if row.voided_at is not None:
            raise ConflictError("证据已作废", code="EVIDENCE_VOIDED")
        self._ensure_revision(row, getattr(payload, "revision", None))
        before = _row_dict(row)
        row.voided_at = datetime.utcnow()
        row.voided_by = operator_id
        row.void_reason = getattr(payload, "reason", None) or "证据作废"
        row.status_code = "VOIDED"
        row.revision = int(row.revision or 1) + 1
        row.updated_at = datetime.utcnow()
        await self._add_change_event(vessel_id, "VOID_AFFILIATION_EVIDENCE", "作废挂靠关系证据", before, _row_dict(row), operator_id, object_type="vessel_affiliation_evidence", object_id=row.id, reason=row.void_reason)
        await self.rebuild_relation_conclusion_candidates(vessel_id, operator_id=operator_id, commit=False)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self.db.refresh(row)
        label_map = await _load_label_map(self.db)
        conclusion_refs = await self._affiliation_evidence_ref_map(vessel_id, label_map)
        attachment_map = await self._relation_evidence_attachment_map("VESSEL_AFFILIATION_EVIDENCE", [row.id])
        return self._affiliation_evidence_response(row, label_map, conclusion_refs.get(row.id, []), attachment_map.get(row.id, []))

    async def list_relation_conclusions(self, vessel_id: int) -> VesselRelationConclusionSummaryResponse:
        await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        controller_rows = (
            await self.db.scalars(
                select(VesselControllerConclusion)
                .where(VesselControllerConclusion.vessel_profile_id == vessel_id)
                .order_by(VesselControllerConclusion.conclusion_status_code.asc(), VesselControllerConclusion.updated_at.desc())
            )
        ).all()
        affiliation_rows = (
            await self.db.scalars(
                select(VesselAffiliationConclusion)
                .where(VesselAffiliationConclusion.vessel_profile_id == vessel_id)
                .order_by(VesselAffiliationConclusion.conclusion_status_code.asc(), VesselAffiliationConclusion.updated_at.desc())
            )
        ).all()
        return VesselRelationConclusionSummaryResponse(
            vessel_profile_id=vessel_id,
            controller_conclusions=[self._controller_conclusion_response(row, label_map) for row in controller_rows],
            affiliation_conclusions=[self._affiliation_conclusion_response(row, label_map) for row in affiliation_rows],
        )

    async def upload_relation_evidence_attachment(
        self,
        vessel_id: int,
        evidence_type: str,
        evidence_id: int,
        file: UploadFile,
        *,
        operator_id: int | None = None,
    ) -> VesselRelationEvidenceAttachmentResponse:
        evidence_type_code = self._normalize_relation_evidence_type(evidence_type)
        await self._require_relation_evidence(vessel_id, evidence_type_code, evidence_id)
        storage_file = await FileStorageService(self.db).upload_file(
            file=file,
            object_prefix=f"vessels/{vessel_id}/relation-evidence/{evidence_type_code.lower()}/{evidence_id}",
            uploaded_by=operator_id,
        )
        now = datetime.utcnow()
        row = VesselRelationEvidenceAttachment(
            vessel_profile_id=vessel_id,
            evidence_type_code=evidence_type_code,
            evidence_id=evidence_id,
            storage_file_id=storage_file.id,
            file_name=storage_file.original_file_name,
            content_type=storage_file.content_type,
            file_size=storage_file.file_size,
            uploaded_by=operator_id,
            uploaded_at=now,
            created_at=now,
        )
        self.db.add(row)
        await self.db.flush()
        await self._add_change_event(
            vessel_id,
            "UPLOAD_RELATION_EVIDENCE_ATTACHMENT",
            "上传主体证据附件",
            None,
            _row_dict(row),
            operator_id,
            object_type="vessel_relation_evidence_attachment",
            object_id=row.id,
        )
        await self.db.commit()
        await self.db.refresh(row)
        return self._relation_evidence_attachment_response(row)

    async def void_relation_evidence_attachment(
        self,
        vessel_id: int,
        evidence_type: str,
        evidence_id: int,
        attachment_id: int,
        *,
        reason: str | None = None,
        operator_id: int | None = None,
    ) -> VesselRelationEvidenceAttachmentResponse:
        evidence_type_code = self._normalize_relation_evidence_type(evidence_type)
        await self._require_relation_evidence(vessel_id, evidence_type_code, evidence_id)
        row = await self.db.get(VesselRelationEvidenceAttachment, attachment_id)
        if row is None or row.vessel_profile_id != vessel_id or row.evidence_type_code != evidence_type_code or row.evidence_id != evidence_id:
            raise NotFoundError("VesselRelationEvidenceAttachment", attachment_id)
        if row.voided_at is None:
            before = _row_dict(row)
            row.voided_at = datetime.utcnow()
            row.voided_by = operator_id
            row.void_reason = reason or "前端主体证据附件作废"
            await self._add_change_event(
                vessel_id,
                "VOID_RELATION_EVIDENCE_ATTACHMENT",
                "作废主体证据附件",
                before,
                _row_dict(row),
                operator_id,
                object_type="vessel_relation_evidence_attachment",
                object_id=row.id,
                reason=row.void_reason,
            )
            await self.db.commit()
            await self.db.refresh(row)
        return self._relation_evidence_attachment_response(row)

    async def resolve_relation_conclusion_conflict(
        self,
        vessel_id: int,
        conclusion_type: str,
        conclusion_id: int,
        payload: Any,
        *,
        operator_id: int | None = None,
    ) -> VesselRelationConclusionSummaryResponse:
        model = self._relation_conclusion_model(conclusion_type)
        row = await self._require_conclusion_row(model, vessel_id, conclusion_id)
        accepted_id = getattr(payload, "accepted_conclusion_id", None)
        target_status = getattr(payload, "mark_unaccepted_as", None) or "CONFLICTED"
        if target_status not in {"CONFLICTED", "STALE_NEEDS_REVIEW"}:
            raise ValidationError("未采信结论只能标记为 CONFLICTED 或 STALE_NEEDS_REVIEW")
        reason = getattr(payload, "conflict_reason", None) or "人工处理冲突结论"
        now = datetime.utcnow()
        rows = (
            await self.db.scalars(
                select(model).where(
                    model.vessel_profile_id == vessel_id,
                    model.voided_at.is_(None),
                    model.conclusion_status_code.in_(["CANDIDATE", "CONFLICTED", "STALE_NEEDS_REVIEW", "CURRENT"]),
                )
            )
        ).all()
        accepted_row = None
        if accepted_id is not None:
            accepted_row = next((item for item in rows if item.id == int(accepted_id)), None)
            if accepted_row is None:
                raise NotFoundError(model.__name__, accepted_id)
        elif row.conclusion_status_code == "CURRENT":
            accepted_row = row
        before = [_row_dict(item) for item in rows]
        for item in rows:
            if accepted_row is not None and item.id == accepted_row.id:
                item.conclusion_status_code = "CURRENT"
                item.confirmed_at = now
                item.confirmed_by = operator_id
                item.conflict_reason = reason
            elif item.id == row.id or item.conclusion_status_code in {"CANDIDATE", "CONFLICTED", "STALE_NEEDS_REVIEW"}:
                item.conclusion_status_code = target_status
                item.conflict_reason = reason
            item.revision = int(item.revision or 1) + 1
            item.updated_at = now
        await self._add_change_event(
            vessel_id,
            "RESOLVE_RELATION_CONCLUSION_CONFLICT",
            "处理主体结论冲突",
            before,
            [_row_dict(item) for item in rows],
            operator_id,
            object_type="vessel_relation_conclusion",
            object_id=conclusion_id,
            reason=reason,
        )
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        return await self.list_relation_conclusions(vessel_id)

    async def rebuild_relation_conclusion_candidates(
        self,
        vessel_id: int,
        *,
        operator_id: int | None = None,
        commit: bool = True,
    ) -> VesselRelationConclusionSummaryResponse:
        await self._require_profile(vessel_id)
        now = datetime.utcnow()
        await self._mark_stale_relation_conclusions(vessel_id, now=now, operator_id=operator_id)
        controller_rows = (
            await self.db.scalars(
                select(VesselControllerEvidence).where(
                    VesselControllerEvidence.vessel_profile_id == vessel_id,
                    VesselControllerEvidence.status_code == "ACTIVE",
                    VesselControllerEvidence.voided_at.is_(None),
                    VesselControllerEvidence.verified_status_code == "APPROVED",
                    or_(VesselControllerEvidence.effective_to.is_(None), VesselControllerEvidence.effective_to >= date.today()),
                )
            )
        ).all()
        affiliation_rows = (
            await self.db.scalars(
                select(VesselAffiliationEvidence).where(
                    VesselAffiliationEvidence.vessel_profile_id == vessel_id,
                    VesselAffiliationEvidence.status_code == "ACTIVE",
                    VesselAffiliationEvidence.voided_at.is_(None),
                    VesselAffiliationEvidence.verified_status_code == "APPROVED",
                    or_(VesselAffiliationEvidence.effective_to.is_(None), VesselAffiliationEvidence.effective_to >= date.today()),
                )
            )
        ).all()
        await self._sync_controller_conclusion_candidates(vessel_id, controller_rows, now=now)
        await self._sync_affiliation_conclusion_candidates(vessel_id, affiliation_rows, now=now)
        await self.db.flush()
        if commit:
            await self._add_change_event(
                vessel_id,
                "REBUILD_RELATION_CONCLUSIONS",
                "重建主体关系候选结论",
                None,
                {"controller_evidence_count": len(controller_rows), "affiliation_evidence_count": len(affiliation_rows)},
                operator_id,
                object_type="vessel_relation_conclusion",
                object_id=vessel_id,
            )
            await self.db.commit()
            await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        return await self.list_relation_conclusions(vessel_id)

    async def confirm_controller_conclusion(
        self,
        vessel_id: int,
        conclusion_id: int,
        *,
        operator_id: int | None = None,
    ) -> VesselControllerConclusionResponse:
        await self._require_profile(vessel_id)
        row = await self.db.get(VesselControllerConclusion, conclusion_id)
        if row is None or row.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselControllerConclusion", conclusion_id)
        if row.conclusion_status_code in {"VOIDED", "EXPIRED"}:
            raise ValidationError("已作废或已过期的控制人结论不能确认为当前结论")
        now = datetime.utcnow()
        currents = (
            await self.db.scalars(
                select(VesselControllerConclusion).where(
                    VesselControllerConclusion.vessel_profile_id == vessel_id,
                    VesselControllerConclusion.conclusion_status_code == "CURRENT",
                    VesselControllerConclusion.id != row.id,
                    VesselControllerConclusion.voided_at.is_(None),
                )
            )
        ).all()
        for current in currents:
            current.conclusion_status_code = "STALE_NEEDS_REVIEW"
            current.conflict_reason = "已由新的人工确认结论取代"
            current.revision = int(current.revision or 1) + 1
            current.updated_at = now
        row.conclusion_status_code = "CURRENT"
        row.confirmed_at = now
        row.confirmed_by = operator_id
        row.voided_at = None
        row.voided_by = None
        row.void_reason = None
        row.revision = int(row.revision or 1) + 1
        row.updated_at = now
        await self._add_change_event(vessel_id, "CONFIRM_CONTROLLER_CONCLUSION", "确认当前实际控制人", None, _row_dict(row), operator_id, object_type="vessel_controller_conclusion", object_id=row.id)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self.db.refresh(row)
        return self._controller_conclusion_response(row, await _load_label_map(self.db))

    async def confirm_affiliation_conclusion(
        self,
        vessel_id: int,
        conclusion_id: int,
        *,
        operator_id: int | None = None,
    ) -> VesselAffiliationConclusionResponse:
        await self._require_profile(vessel_id)
        row = await self.db.get(VesselAffiliationConclusion, conclusion_id)
        if row is None or row.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselAffiliationConclusion", conclusion_id)
        if row.conclusion_status_code in {"VOIDED", "EXPIRED"}:
            raise ValidationError("已作废或已过期的挂靠/授权结论不能确认为当前结论")
        now = datetime.utcnow()
        currents = (
            await self.db.scalars(
                select(VesselAffiliationConclusion).where(
                    VesselAffiliationConclusion.vessel_profile_id == vessel_id,
                    VesselAffiliationConclusion.conclusion_status_code == "CURRENT",
                    VesselAffiliationConclusion.id != row.id,
                    VesselAffiliationConclusion.voided_at.is_(None),
                )
            )
        ).all()
        for current in currents:
            current.conclusion_status_code = "STALE_NEEDS_REVIEW"
            current.conflict_reason = "已由新的人工确认结论取代"
            current.revision = int(current.revision or 1) + 1
            current.updated_at = now
        row.conclusion_status_code = "CURRENT"
        row.confirmed_at = now
        row.confirmed_by = operator_id
        row.voided_at = None
        row.voided_by = None
        row.void_reason = None
        row.revision = int(row.revision or 1) + 1
        row.updated_at = now
        await self._add_change_event(vessel_id, "CONFIRM_AFFILIATION_CONCLUSION", "确认当前挂靠/授权关系", None, _row_dict(row), operator_id, object_type="vessel_affiliation_conclusion", object_id=row.id)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self.db.refresh(row)
        return self._affiliation_conclusion_response(row, await _load_label_map(self.db))

    async def void_controller_conclusion(
        self,
        vessel_id: int,
        conclusion_id: int,
        payload: Any,
        *,
        operator_id: int | None = None,
    ) -> VesselControllerConclusionResponse:
        row = await self._require_conclusion_row(VesselControllerConclusion, vessel_id, conclusion_id)
        self._ensure_revision(row, getattr(payload, "revision", None))
        before = _row_dict(row)
        now = datetime.utcnow()
        row.conclusion_status_code = "VOIDED"
        row.voided_at = now
        row.voided_by = operator_id
        row.void_reason = getattr(payload, "reason", None) or "主体关系结论作废"
        row.revision = int(row.revision or 1) + 1
        row.updated_at = now
        await self._add_change_event(vessel_id, "VOID_CONTROLLER_CONCLUSION", "作废实际控制人结论", before, _row_dict(row), operator_id, object_type="vessel_controller_conclusion", object_id=row.id, reason=row.void_reason)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self.db.refresh(row)
        return self._controller_conclusion_response(row, await _load_label_map(self.db))

    async def void_affiliation_conclusion(
        self,
        vessel_id: int,
        conclusion_id: int,
        payload: Any,
        *,
        operator_id: int | None = None,
    ) -> VesselAffiliationConclusionResponse:
        row = await self._require_conclusion_row(VesselAffiliationConclusion, vessel_id, conclusion_id)
        self._ensure_revision(row, getattr(payload, "revision", None))
        before = _row_dict(row)
        now = datetime.utcnow()
        row.conclusion_status_code = "VOIDED"
        row.voided_at = now
        row.voided_by = operator_id
        row.void_reason = getattr(payload, "reason", None) or "主体关系结论作废"
        row.revision = int(row.revision or 1) + 1
        row.updated_at = now
        await self._add_change_event(vessel_id, "VOID_AFFILIATION_CONCLUSION", "作废挂靠/授权结论", before, _row_dict(row), operator_id, object_type="vessel_affiliation_conclusion", object_id=row.id, reason=row.void_reason)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self.db.refresh(row)
        return self._affiliation_conclusion_response(row, await _load_label_map(self.db))

    def _controller_evidence_response(
        self,
        row: VesselControllerEvidence,
        label_map: dict[str, dict[str, str]],
        conclusion_refs: list[VesselEvidenceConclusionRefResponse] | None = None,
        attachments: list[VesselRelationEvidenceAttachmentResponse] | None = None,
    ) -> VesselControllerEvidenceResponse:
        missing_fields = self._controller_evidence_missing_fields(row)
        return VesselControllerEvidenceResponse(
            **_row_dict(row),
            controller_role_name=label_map.get("VESSEL_CONTROLLER_ROLE", {}).get(row.controller_role_code),
            confidence_level_name=label_map.get("VESSEL_CONFIDENCE_LEVEL", {}).get(row.confidence_level),
            source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
            verified_status_name=label_map.get("VESSEL_EVIDENCE_VERIFIED_STATUS", {}).get(row.verified_status_code),
            conclusion_refs=conclusion_refs or [],
            evidence_completeness=self._evidence_completeness(missing_fields),
            missing_required_fields=missing_fields,
            attachments=attachments or [],
        )

    def _affiliation_evidence_response(
        self,
        row: VesselAffiliationEvidence,
        label_map: dict[str, dict[str, str]],
        conclusion_refs: list[VesselEvidenceConclusionRefResponse] | None = None,
        attachments: list[VesselRelationEvidenceAttachmentResponse] | None = None,
    ) -> VesselAffiliationEvidenceResponse:
        missing_fields = self._affiliation_evidence_missing_fields(row)
        return VesselAffiliationEvidenceResponse(
            **_row_dict(row),
            affiliation_type_name=label_map.get("VESSEL_AFFILIATION_TYPE", {}).get(row.affiliation_type_code),
            confidence_level_name=label_map.get("VESSEL_CONFIDENCE_LEVEL", {}).get(row.confidence_level),
            source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
            verified_status_name=label_map.get("VESSEL_EVIDENCE_VERIFIED_STATUS", {}).get(row.verified_status_code),
            conclusion_refs=conclusion_refs or [],
            evidence_completeness=self._evidence_completeness(missing_fields),
            missing_required_fields=missing_fields,
            attachments=attachments or [],
        )

    @staticmethod
    def _relation_evidence_attachment_response(row: VesselRelationEvidenceAttachment) -> VesselRelationEvidenceAttachmentResponse:
        return VesselRelationEvidenceAttachmentResponse(
            **_row_dict(row),
            download_url=f"/api/v1/files/{row.storage_file_id}/content",
        )

    async def _relation_evidence_attachment_map(
        self,
        evidence_type_code: str,
        evidence_ids: list[int],
        *,
        include_voided: bool = False,
    ) -> dict[int, list[VesselRelationEvidenceAttachmentResponse]]:
        if not evidence_ids:
            return {}
        stmt = select(VesselRelationEvidenceAttachment).where(
            VesselRelationEvidenceAttachment.evidence_type_code == evidence_type_code,
            VesselRelationEvidenceAttachment.evidence_id.in_(evidence_ids),
        )
        if not include_voided:
            stmt = stmt.where(VesselRelationEvidenceAttachment.voided_at.is_(None))
        rows = (await self.db.scalars(stmt.order_by(VesselRelationEvidenceAttachment.created_at.desc()))).all()
        result: dict[int, list[VesselRelationEvidenceAttachmentResponse]] = defaultdict(list)
        for row in rows:
            result[int(row.evidence_id)].append(self._relation_evidence_attachment_response(row))
        return result

    @staticmethod
    def _normalize_relation_evidence_type(value: str) -> str:
        normalized = (value or "").upper().replace("-", "_")
        aliases = {
            "CONTROLLER": "VESSEL_CONTROLLER_EVIDENCE",
            "VESSEL_CONTROLLER_EVIDENCE": "VESSEL_CONTROLLER_EVIDENCE",
            "AFFILIATION": "VESSEL_AFFILIATION_EVIDENCE",
            "VESSEL_AFFILIATION_EVIDENCE": "VESSEL_AFFILIATION_EVIDENCE",
        }
        if normalized not in aliases:
            raise ValidationError("主体证据类型必须是 controller 或 affiliation")
        return aliases[normalized]

    async def _require_relation_evidence(self, vessel_id: int, evidence_type_code: str, evidence_id: int) -> Any:
        if evidence_type_code == "VESSEL_CONTROLLER_EVIDENCE":
            return await self._require_evidence_row(VesselControllerEvidence, vessel_id, evidence_id)
        if evidence_type_code == "VESSEL_AFFILIATION_EVIDENCE":
            return await self._require_evidence_row(VesselAffiliationEvidence, vessel_id, evidence_id)
        raise ValidationError("不支持的主体证据类型")

    @staticmethod
    def _relation_conclusion_model(conclusion_type: str) -> type[Any]:
        normalized = (conclusion_type or "").upper().replace("-", "_")
        if normalized in {"CONTROLLER", "VESSEL_CONTROLLER_CONCLUSION"}:
            return VesselControllerConclusion
        if normalized in {"AFFILIATION", "VESSEL_AFFILIATION_CONCLUSION"}:
            return VesselAffiliationConclusion
        raise ValidationError("主体结论类型必须是 controller 或 affiliation")

    async def _controller_evidence_ref_map(
        self,
        vessel_id: int,
        label_map: dict[str, dict[str, str]],
    ) -> dict[int, list[VesselEvidenceConclusionRefResponse]]:
        rows = (
            await self.db.scalars(
                select(VesselControllerConclusion).where(
                    VesselControllerConclusion.vessel_profile_id == vessel_id,
                    VesselControllerConclusion.voided_at.is_(None),
                )
            )
        ).all()
        refs: dict[int, list[VesselEvidenceConclusionRefResponse]] = defaultdict(list)
        for row in rows:
            ref = VesselEvidenceConclusionRefResponse(
                conclusion_id=row.id,
                conclusion_type="CONTROLLER",
                conclusion_status_code=row.conclusion_status_code,
                conclusion_status_name=label_map.get("VESSEL_RELATION_CONCLUSION_STATUS", {}).get(row.conclusion_status_code),
                role=row.conclusion_status_code,
                display_name=row.party_name,
                effective_from=row.effective_from,
                effective_to=row.effective_to,
            )
            for evidence_id in self._conclusion_evidence_ids(row.evidence_ids_json):
                refs[evidence_id].append(ref)
        return refs

    async def _affiliation_evidence_ref_map(
        self,
        vessel_id: int,
        label_map: dict[str, dict[str, str]],
    ) -> dict[int, list[VesselEvidenceConclusionRefResponse]]:
        rows = (
            await self.db.scalars(
                select(VesselAffiliationConclusion).where(
                    VesselAffiliationConclusion.vessel_profile_id == vessel_id,
                    VesselAffiliationConclusion.voided_at.is_(None),
                )
            )
        ).all()
        refs: dict[int, list[VesselEvidenceConclusionRefResponse]] = defaultdict(list)
        for row in rows:
            display_name = " / ".join(part for part in (row.subject_name, row.counterparty_name) if part) or row.affiliation_type_code
            ref = VesselEvidenceConclusionRefResponse(
                conclusion_id=row.id,
                conclusion_type="AFFILIATION",
                conclusion_status_code=row.conclusion_status_code,
                conclusion_status_name=label_map.get("VESSEL_RELATION_CONCLUSION_STATUS", {}).get(row.conclusion_status_code),
                role=row.conclusion_status_code,
                display_name=display_name,
                effective_from=row.effective_from,
                effective_to=row.effective_to,
            )
            for evidence_id in self._conclusion_evidence_ids(row.evidence_ids_json):
                refs[evidence_id].append(ref)
        return refs

    @staticmethod
    def _conclusion_evidence_ids(value: Any) -> list[int]:
        if not isinstance(value, list):
            return []
        ids: list[int] = []
        for item in value:
            try:
                ids.append(int(item))
            except (TypeError, ValueError):
                continue
        return ids

    @staticmethod
    def _json_path_value(payload: dict[str, Any] | None, path: str) -> Any:
        current: Any = payload
        for part in path.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    @classmethod
    def _missing_json_paths(cls, payload: dict[str, Any] | None, specs: list[tuple[str, str]]) -> list[str]:
        missing: list[str] = []
        for path, label in specs:
            value = cls._json_path_value(payload, path)
            if value is None or value == "" or value == []:
                missing.append(label)
        return missing

    @staticmethod
    def _evidence_completeness(missing_fields: list[str]) -> str:
        if not missing_fields:
            return "COMPLETE"
        if any(item.startswith("必填：") for item in missing_fields):
            return "MISSING_REQUIRED"
        return "PARTIAL"

    def _controller_evidence_missing_fields(self, row: VesselControllerEvidence) -> list[str]:
        missing: list[str] = []
        if not row.party_name:
            missing.append("必填：实际控制人姓名/公司")
        if not row.evidence_summary:
            missing.append("必填：证据摘要")
        payload = row.evidence_json if isinstance(row.evidence_json, dict) else {}
        missing.extend(
            self._missing_json_paths(
                payload,
                [
                    ("confirmation.source", "必填：确认来源"),
                    ("confirmation.method", "必填：确认方式"),
                    ("controller_identity.certificate_type", "证件类型"),
                    ("controller_identity.certificate_no", "证件号"),
                    ("contact.phone", "联系方式"),
                    ("relationship.owner_relationship", "与所有人关系"),
                    ("relationship.operator_relationship", "与经营人关系"),
                    ("confirmation.confirmed_at", "确认时间"),
                    ("confirmation.confirmed_by", "确认人"),
                ],
            )
        )
        if row.effective_from is None:
            missing.append("证据有效期开始")
        return list(dict.fromkeys(missing))

    def _affiliation_evidence_missing_fields(self, row: VesselAffiliationEvidence) -> list[str]:
        missing: list[str] = []
        if not row.subject_name:
            missing.append("必填：主体")
        if not row.counterparty_name:
            missing.append("必填：相对方")
        if not row.evidence_summary:
            missing.append("必填：证据摘要")
        payload = row.evidence_json if isinstance(row.evidence_json, dict) else {}
        missing.extend(
            self._missing_json_paths(
                payload,
                [
                    ("affiliation_contract.affiliation_company", "必填：挂靠公司"),
                    ("affiliation_contract.actual_shipowner", "必填：实际船东"),
                    ("affiliation_contract.agreement_start", "协议开始时间"),
                    ("affiliation_contract.agreement_end", "协议结束时间"),
                    ("operation_qualification.certificate_operator", "证书经营主体"),
                    ("operation_qualification.transport_permit_relation", "营运证关系"),
                    ("contact.business_contact", "业务联系人"),
                    ("confirmation.source", "确认来源"),
                    ("confirmation.method", "确认方式"),
                    ("confirmation.confirmed_at", "确认时间"),
                ],
            )
        )
        if row.effective_from is None:
            missing.append("证据有效期开始")
        return list(dict.fromkeys(missing))
