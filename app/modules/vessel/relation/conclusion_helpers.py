"""Relation conclusion helper methods."""

from __future__ import annotations

from app.modules.approval.client import ApprovalClient

from app.modules.vessel.shared import base as _base

globals().update({name: getattr(_base, name) for name in dir(_base) if not name.startswith("__")})


class RelationConclusionHelperMixin:
    """Shared response, completeness, and conclusion candidate helpers."""

    def _controller_conclusion_response(
        self,
        row: VesselControllerConclusion,
        label_map: dict[str, dict[str, str]],
    ) -> VesselControllerConclusionResponse:
        return VesselControllerConclusionResponse(
            **_row_dict(row),
            conclusion_status_name=label_map.get("VESSEL_RELATION_CONCLUSION_STATUS", {}).get(row.conclusion_status_code),
            controller_role_name=label_map.get("VESSEL_CONTROLLER_ROLE", {}).get(row.controller_role_code),
            confidence_level_name=label_map.get("VESSEL_CONFIDENCE_LEVEL", {}).get(row.confidence_level),
        )

    def _affiliation_conclusion_response(
        self,
        row: VesselAffiliationConclusion,
        label_map: dict[str, dict[str, str]],
    ) -> VesselAffiliationConclusionResponse:
        return VesselAffiliationConclusionResponse(
            **_row_dict(row),
            conclusion_status_name=label_map.get("VESSEL_RELATION_CONCLUSION_STATUS", {}).get(row.conclusion_status_code),
            affiliation_type_name=label_map.get("VESSEL_AFFILIATION_TYPE", {}).get(row.affiliation_type_code),
            confidence_level_name=label_map.get("VESSEL_CONFIDENCE_LEVEL", {}).get(row.confidence_level),
        )

    async def _require_conclusion_row(
        self,
        model: type[Any],
        vessel_id: int,
        conclusion_id: int,
    ) -> Any:
        await self._require_profile(vessel_id)
        row = await self.db.get(model, conclusion_id)
        if row is None or row.vessel_profile_id != vessel_id:
            raise NotFoundError(model.__name__, conclusion_id)
        return row

    async def _mark_stale_relation_conclusions(
        self,
        vessel_id: int,
        *,
        now: datetime,
        operator_id: int | None = None,
    ) -> None:
        today = date.today()
        controller_rows = (
            await self.db.scalars(
                select(VesselControllerConclusion).where(
                    VesselControllerConclusion.vessel_profile_id == vessel_id,
                    VesselControllerConclusion.conclusion_status_code == "CURRENT",
                    VesselControllerConclusion.voided_at.is_(None),
                )
            )
        ).all()
        affiliation_rows = (
            await self.db.scalars(
                select(VesselAffiliationConclusion).where(
                    VesselAffiliationConclusion.vessel_profile_id == vessel_id,
                    VesselAffiliationConclusion.conclusion_status_code == "CURRENT",
                    VesselAffiliationConclusion.voided_at.is_(None),
                )
            )
        ).all()
        for row in controller_rows:
            if row.effective_to and row.effective_to < today:
                row.conclusion_status_code = "EXPIRED"
                row.conflict_reason = "结论有效期已过"
            elif not await self._controller_conclusion_evidence_current(row):
                row.conclusion_status_code = "STALE_NEEDS_REVIEW"
                row.conflict_reason = "引用证据已作废、过期或不再通过审核"
            else:
                continue
            row.revision = int(row.revision or 1) + 1
            row.updated_at = now
        for row in affiliation_rows:
            if row.effective_to and row.effective_to < today:
                row.conclusion_status_code = "EXPIRED"
                row.conflict_reason = "结论有效期已过"
            elif not await self._affiliation_conclusion_evidence_current(row):
                row.conclusion_status_code = "STALE_NEEDS_REVIEW"
                row.conflict_reason = "引用证据已作废、过期或不再通过审核"
            else:
                continue
            row.revision = int(row.revision or 1) + 1
            row.updated_at = now

    async def _controller_conclusion_evidence_current(self, row: VesselControllerConclusion) -> bool:
        ids = [int(value) for value in (row.evidence_ids_json or []) if str(value).isdigit()]
        if not ids:
            return False
        today = date.today()
        count = int(
            await self.db.scalar(
                select(func.count(VesselControllerEvidence.id)).where(
                    VesselControllerEvidence.id.in_(ids),
                    VesselControllerEvidence.vessel_profile_id == row.vessel_profile_id,
                    VesselControllerEvidence.status_code == "ACTIVE",
                    VesselControllerEvidence.voided_at.is_(None),
                    VesselControllerEvidence.verified_status_code == "APPROVED",
                    or_(VesselControllerEvidence.effective_to.is_(None), VesselControllerEvidence.effective_to >= today),
                )
            )
            or 0
        )
        return count == len(ids)

    async def _affiliation_conclusion_evidence_current(self, row: VesselAffiliationConclusion) -> bool:
        ids = [int(value) for value in (row.evidence_ids_json or []) if str(value).isdigit()]
        if not ids:
            return False
        today = date.today()
        count = int(
            await self.db.scalar(
                select(func.count(VesselAffiliationEvidence.id)).where(
                    VesselAffiliationEvidence.id.in_(ids),
                    VesselAffiliationEvidence.vessel_profile_id == row.vessel_profile_id,
                    VesselAffiliationEvidence.status_code == "ACTIVE",
                    VesselAffiliationEvidence.voided_at.is_(None),
                    VesselAffiliationEvidence.verified_status_code == "APPROVED",
                    or_(VesselAffiliationEvidence.effective_to.is_(None), VesselAffiliationEvidence.effective_to >= today),
                )
            )
            or 0
        )
        return count == len(ids)

    async def _sync_controller_conclusion_candidates(
        self,
        vessel_id: int,
        evidence_rows: list[VesselControllerEvidence],
        *,
        now: datetime,
    ) -> None:
        groups: dict[str, list[VesselControllerEvidence]] = defaultdict(list)
        for row in evidence_rows:
            key = _normalized_text(row.party_name)
            if key:
                groups[key].append(row)
        conflict = len(groups) > 1
        for rows in groups.values():
            sample = rows[0]
            status = "CONFLICTED" if conflict else "CANDIDATE"
            current = await self.db.scalar(
                select(VesselControllerConclusion).where(
                    VesselControllerConclusion.vessel_profile_id == vessel_id,
                    VesselControllerConclusion.party_name == sample.party_name,
                    VesselControllerConclusion.conclusion_status_code == "CURRENT",
                    VesselControllerConclusion.voided_at.is_(None),
                )
            )
            target = current or await self.db.scalar(
                select(VesselControllerConclusion)
                .where(
                    VesselControllerConclusion.vessel_profile_id == vessel_id,
                    VesselControllerConclusion.party_name == sample.party_name,
                    VesselControllerConclusion.conclusion_status_code.in_(("CANDIDATE", "CONFLICTED", "STALE_NEEDS_REVIEW")),
                    VesselControllerConclusion.voided_at.is_(None),
                )
                .order_by(VesselControllerConclusion.updated_at.desc(), VesselControllerConclusion.id.desc())
                .limit(1)
            )
            payload = {
                "controller_role_code": sample.controller_role_code or "ACTUAL_CONTROLLER",
                "confidence_level": self._max_confidence(row.confidence_level for row in rows),
                "evidence_ids_json": [row.id for row in rows],
                "evidence_count": len(rows),
                "conflict_reason": "存在多组已审核控制人证据，请人工确认当前实际控制人" if conflict else None,
                "effective_from": self._min_date(row.effective_from for row in rows),
                "effective_to": self._max_date(row.effective_to for row in rows),
            }
            if target is None:
                self.db.add(
                    VesselControllerConclusion(
                        vessel_profile_id=vessel_id,
                        conclusion_status_code=status,
                        party_name=sample.party_name,
                        created_at=now,
                        updated_at=now,
                        **payload,
                    )
                )
            elif target.conclusion_status_code != "CURRENT":
                for key, value in payload.items():
                    setattr(target, key, value)
                target.conclusion_status_code = status
                target.updated_at = now
                target.revision = int(target.revision or 1) + 1
            else:
                for key, value in payload.items():
                    setattr(target, key, value)
                target.updated_at = now
                target.revision = int(target.revision or 1) + 1

    async def _sync_affiliation_conclusion_candidates(
        self,
        vessel_id: int,
        evidence_rows: list[VesselAffiliationEvidence],
        *,
        now: datetime,
    ) -> None:
        groups: dict[tuple[str, str, str], list[VesselAffiliationEvidence]] = defaultdict(list)
        for row in evidence_rows:
            key = (row.affiliation_type_code or "UNKNOWN", _normalized_text(row.subject_name), _normalized_text(row.counterparty_name))
            groups[key].append(row)
        conflict = len(groups) > 1
        for rows in groups.values():
            sample = rows[0]
            status = "CONFLICTED" if conflict else "CANDIDATE"
            target = await self.db.scalar(
                select(VesselAffiliationConclusion)
                .where(
                    VesselAffiliationConclusion.vessel_profile_id == vessel_id,
                    VesselAffiliationConclusion.affiliation_type_code == sample.affiliation_type_code,
                    VesselAffiliationConclusion.subject_name.is_(None)
                    if sample.subject_name is None
                    else VesselAffiliationConclusion.subject_name == sample.subject_name,
                    VesselAffiliationConclusion.counterparty_name.is_(None)
                    if sample.counterparty_name is None
                    else VesselAffiliationConclusion.counterparty_name == sample.counterparty_name,
                    VesselAffiliationConclusion.conclusion_status_code.in_(("CURRENT", "CANDIDATE", "CONFLICTED", "STALE_NEEDS_REVIEW")),
                    VesselAffiliationConclusion.voided_at.is_(None),
                )
                .order_by(VesselAffiliationConclusion.conclusion_status_code.desc(), VesselAffiliationConclusion.updated_at.desc())
                .limit(1)
            )
            payload = {
                "confidence_level": self._max_confidence(row.confidence_level for row in rows),
                "evidence_ids_json": [row.id for row in rows],
                "evidence_count": len(rows),
                "conflict_reason": "存在多组已审核挂靠/授权证据，请人工确认当前关系" if conflict else None,
                "effective_from": self._min_date(row.effective_from for row in rows),
                "effective_to": self._max_date(row.effective_to for row in rows),
            }
            if target is None:
                self.db.add(
                    VesselAffiliationConclusion(
                        vessel_profile_id=vessel_id,
                        conclusion_status_code=status,
                        affiliation_type_code=sample.affiliation_type_code,
                        subject_name=sample.subject_name,
                        counterparty_name=sample.counterparty_name,
                        created_at=now,
                        updated_at=now,
                        **payload,
                    )
                )
            elif target.conclusion_status_code != "CURRENT":
                for key, value in payload.items():
                    setattr(target, key, value)
                target.conclusion_status_code = status
                target.updated_at = now
                target.revision = int(target.revision or 1) + 1
            else:
                for key, value in payload.items():
                    setattr(target, key, value)
                target.updated_at = now
                target.revision = int(target.revision or 1) + 1

    @staticmethod
    def _max_confidence(values: Any) -> str:
        levels = [value for value in values if value]
        if not levels:
            return "UNKNOWN"
        return max(levels, key=lambda value: {"UNKNOWN": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}.get(value, 0))

    @staticmethod
    def _min_date(values: Any) -> date | None:
        items = [value for value in values if value is not None]
        return min(items) if items else None

    @staticmethod
    def _max_date(values: Any) -> date | None:
        items = [value for value in values if value is not None]
        return max(items) if items else None

    async def _submit_evidence_approval_if_needed(
        self,
        row: Any,
        *,
        object_type_code: str,
        object_name: str | None,
        operator_id: int | None,
        before: dict[str, Any] | None,
        after: dict[str, Any],
    ) -> None:
        if getattr(row, "verified_status_code", None) != "PENDING":
            return
        await ApprovalClient(self.db).submit(
            {
                "subject_type": object_type_code,
                "trigger_action_code": "VERIFY",
                "subject_id": row.id,
                "subject_ref": f"{object_type_code}:{row.id}",
                "subject_code": str(row.id),
                "subject_name": object_name or f"{object_type_code} #{row.id}",
                "subject_path": f"/vessels/{row.vessel_profile_id}/relations",
                "before_snapshot_json": _jsonable(before) if before else None,
                "after_snapshot_json": _jsonable(after),
                "diff_json": None,
                "summary_json": {
                    "object_type_code": object_type_code,
                    "vessel_profile_id": row.vessel_profile_id,
                },
                "submit_payload_json": {
                    "vessel_profile_id": row.vessel_profile_id,
                    "evidence_id": row.id,
                    "object_type_code": object_type_code,
                },
                "idempotency_key": f"VESSEL_EVIDENCE:{object_type_code}:{row.id}:{row.revision}",
            },
            submitter_id=operator_id,
        )

    async def _require_evidence_row(self, model: type[Any], vessel_id: int, row_id: int) -> Any:
        row = await self.db.get(model, row_id)
        if row is None or getattr(row, "vessel_profile_id", None) != vessel_id:
            raise NotFoundError(model.__name__, row_id)
        return row

    async def _validate_affiliation_relation_refs(self, vessel_id: int, data: dict[str, Any]) -> None:
        owner_id = data.get("owner_period_id")
        operator_id = data.get("operator_period_id")
        if owner_id is not None:
            owner = await self.db.get(VesselOwnerPeriod, owner_id)
            if owner is None or owner.vessel_profile_id != vessel_id:
                raise NotFoundError("VesselOwnerPeriod", owner_id)
        if operator_id is not None:
            operator = await self.db.get(VesselOperatorPeriod, operator_id)
            if operator is None or operator.vessel_profile_id != vessel_id:
                raise NotFoundError("VesselOperatorPeriod", operator_id)
