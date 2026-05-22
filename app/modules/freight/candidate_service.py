"""Freight candidate pool review and confirmation service."""

from __future__ import annotations

from app.modules.freight.support import *

class FreightCandidateService(FreightNormalizationMixin):
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = FreightCandidateRepository(db)
        self.feedback_repo = FreightCandidateManualFeedbackRepository(db)
        self.freight_repo = FreightRepository(db)
        self.contact_repo = FreightContactRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_items(
        self,
        *,
        keyword: str | None,
        status_code: str | None,
        source_type_code: str | None,
        source_batch_id: int | None,
        page: int,
        page_size: int,
    ) -> PageResponse[FreightCandidateResponse]:
        rows, total = await self.repo.list_items(
            keyword=keyword,
            status_code=status_code,
            source_type_code=source_type_code,
            source_batch_id=source_batch_id,
            page=page,
            page_size=page_size,
        )
        ctx = await _load_display_context(self.db, candidates=rows)
        return PageResponse[FreightCandidateResponse](total=total, page=page, page_size=page_size, items=[_to_candidate_response(item, ctx) for item in rows])

    async def get(self, candidate_id: int) -> FreightCandidateResponse:
        row = await self.repo.get_by_id(candidate_id)
        if row is None:
            raise NotFoundError("FreightCandidate", candidate_id)
        ctx = await _load_display_context(self.db, candidates=[row])
        return _to_candidate_response(row, ctx)

    async def update(self, candidate_id: int, payload) -> FreightCandidateResponse:
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            raise ValidationError("no update fields provided")
        await self._enrich_location_updates(updates, "origin")
        await self._enrich_location_updates(updates, "destination")
        await self._enrich_commodity_updates(updates)
        self._fill_default_raw_levels(updates)
        row = await self.repo.get_by_id(candidate_id)
        if row is None:
            raise NotFoundError("FreightCandidate", candidate_id)
        manual = dict(row.manual_overrides_json or {})
        manual.update(_compact_json_value(updates))
        updates["manual_overrides_json"] = manual
        row = await self.repo.update(candidate_id, updates)
        await self.db.commit()
        ctx = await _load_display_context(self.db, candidates=[row])
        return _to_candidate_response(row, ctx)

    async def confirm(self, candidate_id: int, payload, operator_id: int | None) -> FreightResponse:
        candidate = await self.repo.get_by_id(candidate_id)
        if candidate is None:
            raise NotFoundError("FreightCandidate", candidate_id)
        if candidate.status_code != "PENDING":
            raise ValidationError("只有待确认候选货源可以确认入库")
        before = _entity_snapshot(candidate, self._candidate_snapshot_fields())
        action_code = "CONFIRM"
        has_overrides = payload.overrides is not None and bool(payload.overrides.model_dump(exclude_unset=True))
        if payload.overrides is not None:
            updates = payload.overrides.model_dump(exclude_unset=True)
            if updates:
                await self._enrich_location_updates(updates, "origin")
                await self._enrich_location_updates(updates, "destination")
                await self._enrich_commodity_updates(updates)
                self._fill_default_raw_levels(updates)
                manual = dict(candidate.manual_overrides_json or {})
                manual.update(_compact_json_value(updates))
                updates["manual_overrides_json"] = manual
                candidate = await self.repo.update(candidate_id, updates) or candidate
                action_code = "EDIT_CONFIRM"
        self._validate_candidate_ready(candidate, allow_review_override=has_overrides)
        if has_overrides:
            candidate = await self.repo.update(
                candidate_id,
                {
                    "ai_review_status_code": AI_REVIEW_MANUAL_ACCEPTED,
                    "ai_review_json": {
                        **(candidate.ai_review_json or {}),
                        "status_code": AI_REVIEW_MANUAL_ACCEPTED,
                        "reason": "人工编辑确认后接受",
                        "accepted_by": operator_id,
                    },
                },
            ) or candidate
        now = datetime.utcnow()
        freight_payload = {
                "freight_no": await self.sequence_service.next_code("FREIGHT_NO"),
                "source_type_code": candidate.source_type_code,
                "source_channel_code": candidate.source_channel_code,
                "source_ref_no": candidate.source_ref_no or candidate.candidate_no,
                "source_batch_id": candidate.source_batch_id,
                "source_tms_inbound_id": candidate.source_tms_inbound_id,
                "source_clue_id": candidate.clue_id,
                "source_candidate_id": candidate.id,
                "raw_commodity_name": candidate.raw_commodity_name,
                "raw_tonnage_text": candidate.raw_tonnage_text,
                "raw_origin_text": candidate.raw_origin_text,
                "raw_destination_text": candidate.raw_destination_text,
                "cargo_title": candidate.cargo_title,
                "cargo_description": candidate.cargo_description,
                "commodity_standard_id": candidate.commodity_standard_id,
                "commodity_match_level_code": candidate.commodity_match_level_code,
                "packaging_form_code": candidate.packaging_form_code,
                "estimated_tonnage": candidate.estimated_tonnage,
                "min_tonnage": candidate.min_tonnage,
                "max_tonnage": candidate.max_tonnage,
                "unit_price": candidate.unit_price,
                "total_price": candidate.total_price,
                "price_unit": candidate.price_unit,
                "settlement_method_code": candidate.settlement_method_code,
                "origin_node_id": candidate.origin_node_id,
                "destination_node_id": candidate.destination_node_id,
                "origin_match_level_code": candidate.origin_match_level_code,
                "destination_match_level_code": candidate.destination_match_level_code,
                "origin_province_code": candidate.origin_province_code,
                "origin_city_code": candidate.origin_city_code,
                "origin_district_code": candidate.origin_district_code,
                "destination_province_code": candidate.destination_province_code,
                "destination_city_code": candidate.destination_city_code,
                "destination_district_code": candidate.destination_district_code,
                "origin_region_id_cache": candidate.origin_region_id_cache,
                "destination_region_id_cache": candidate.destination_region_id_cache,
                "loading_time_from": candidate.loading_time_from,
                "loading_time_to": candidate.loading_time_to,
                "unloading_time_from": candidate.unloading_time_from,
                "unloading_time_to": candidate.unloading_time_to,
                "publisher_org_name": candidate.publisher_org_name,
                "status_code": "PUBLISHED",
                "published_at": now,
                "expired_at": candidate.loading_time_to,
                "confirmed_at": now,
                "confirmed_by": operator_id,
                "hall_status_code": "NOT_LISTED",
            }
        self._fill_default_raw_levels(freight_payload)
        freight = await self.freight_repo.create_freight(freight_payload)
        candidate = await self.repo.update(
            candidate.id,
            {"status_code": "CONFIRMED", "confirmed_freight_id": freight.id, "confirmed_at": now},
        ) or candidate
        if candidate.contact_name or candidate.contact_phone or candidate.contact_wechat:
            await self.contact_repo.create_contact(
                freight.id,
                {
                    "contact_name": candidate.contact_name or "货源联系人",
                    "contact_role_code": "FREIGHT_CONTACT",
                    "mobile_phone": candidate.contact_phone,
                    "landline_phone": None,
                    "wechat": candidate.contact_wechat,
                    "is_primary": True,
                },
            )
        await self.feedback_repo.create(
            {
                "candidate_id": candidate.id,
                "action_code": action_code,
                "before_json": before,
                "after_json": _entity_snapshot(candidate, self._candidate_snapshot_fields()),
                "feedback_remark": payload.remark,
                "operator_id": operator_id,
                "operated_at": now,
                "created_at": now,
            }
        )
        await self.db.commit()
        ctx = await _load_display_context(self.db, freights=[freight])
        return _to_freight_response(freight, ctx)

    async def reject(self, candidate_id: int, payload, operator_id: int | None) -> FreightCandidateResponse:
        candidate = await self.repo.get_by_id(candidate_id)
        if candidate is None:
            raise NotFoundError("FreightCandidate", candidate_id)
        if candidate.status_code == "CONFIRMED":
            raise ValidationError("已确认候选货源不能驳回")
        before = _entity_snapshot(candidate, self._candidate_snapshot_fields())
        row = await self.repo.update(candidate_id, {"status_code": "REJECTED"})
        now = datetime.utcnow()
        await self.feedback_repo.create(
            {
                "candidate_id": candidate_id,
                "action_code": "REJECT",
                "before_json": before,
                "after_json": _entity_snapshot(row, self._candidate_snapshot_fields()) if row is not None else None,
                "feedback_remark": payload.remark,
                "operator_id": operator_id,
                "operated_at": now,
                "created_at": now,
            }
        )
        await self.db.commit()
        ctx = await _load_display_context(self.db, candidates=[row])
        return _to_candidate_response(row, ctx)

    async def bulk_confirm_batch(self, batch_id: int, operator_id: int | None) -> FreightCandidateBulkConfirmResponse:
        rows = await self.repo.list_by_batch(batch_id)
        confirmed_ids: list[int] = []
        skipped: list[dict[str, Any]] = []
        for row in rows:
            if row.status_code != "PENDING":
                skipped.append({"candidate_id": row.id, "candidate_no": row.candidate_no, "reason": "不是待确认状态"})
                continue
            if row.availability_status_code != "READY":
                skipped.append({"candidate_id": row.id, "candidate_no": row.candidate_no, "reason": row.manual_review_reason or "需要人工编辑确认"})
                continue
            if not _candidate_ai_review_pass(row):
                skipped.append({"candidate_id": row.id, "candidate_no": row.candidate_no, "reason": _candidate_ai_review_reason(row) or "AI 复核状态需人工判断"})
                continue
            try:
                freight = await self.confirm(row.id, type("Payload", (), {"remark": "批次一键确认入库", "overrides": None})(), operator_id)
                confirmed_ids.append(freight.id)
            except Exception as exc:  # noqa: BLE001
                skipped.append({"candidate_id": row.id, "candidate_no": row.candidate_no, "reason": str(exc)})
        return FreightCandidateBulkConfirmResponse(
            batch_id=batch_id,
            confirmed_count=len(confirmed_ids),
            skipped_count=len(skipped),
            freight_ids=confirmed_ids,
            skipped=skipped,
        )

    @staticmethod
    def _candidate_snapshot_fields() -> list[str]:
        return [
            "candidate_no",
            "cargo_title",
            "commodity_standard_id",
            "commodity_match_level_code",
            "raw_commodity_name",
            "origin_node_id",
            "origin_city_code",
            "origin_match_level_code",
            "raw_origin_text",
            "destination_node_id",
            "destination_city_code",
            "destination_match_level_code",
            "raw_destination_text",
            "raw_tonnage_text",
            "estimated_tonnage",
            "unit_price",
            "availability_status_code",
            "manual_review_reason",
            "ai_review_status_code",
            "status_code",
        ]

    @staticmethod
    def _validate_candidate_ready(candidate, *, allow_review_override: bool = False) -> None:
        if candidate.availability_status_code != "READY" and not allow_review_override:
            reason = candidate.manual_review_reason or "AI 未判断为可直接发布"
            raise ValidationError(f"候选货源需要编辑确认后才能入库：{reason}")
        if not _candidate_ai_review_pass(candidate) and not allow_review_override:
            reason = _candidate_ai_review_reason(candidate) or "AI 复核状态需人工判断"
            raise ValidationError(f"候选货源需要编辑确认后才能入库：{reason}")
        missing: list[str] = []
        if str(candidate.commodity_match_level_code or "").upper() == "STANDARD" and candidate.commodity_standard_id is None:
            missing.append("标准货品")
        if not (
            str(candidate.cargo_title or "").strip()
            or str(candidate.raw_commodity_name or "").strip()
            or candidate.commodity_standard_id is not None
        ):
            missing.append("货品原文或货源标题")
        origin_level = str(candidate.origin_match_level_code or "").upper()
        destination_level = str(candidate.destination_match_level_code or "").upper()
        if origin_level == "NODE" and candidate.origin_node_id is None:
            missing.append("装货节点")
        if origin_level == "CITY" and not candidate.origin_city_code:
            missing.append("装货城市")
        if destination_level == "NODE" and candidate.destination_node_id is None:
            missing.append("卸货节点")
        if destination_level == "CITY" and not candidate.destination_city_code:
            missing.append("卸货城市")
        if not (
            str(candidate.raw_origin_text or "").strip()
            or candidate.origin_node_id is not None
            or bool(candidate.origin_city_code)
        ):
            missing.append("装货地原文")
        if not (
            str(candidate.raw_destination_text or "").strip()
            or candidate.destination_node_id is not None
            or bool(candidate.destination_city_code)
        ):
            missing.append("卸货地原文")
        if missing:
            raise ValidationError(f"候选货源缺少确认入库字段：{', '.join(missing)}")

