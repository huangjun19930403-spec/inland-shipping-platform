"""Formal freight profile, contact, attachment, and tag services."""

from __future__ import annotations

from app.modules.freight.support import *

class FreightService(FreightNormalizationMixin):
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = FreightRepository(db)
        self.contact_repo = FreightContactRepository(db)
        self.attachment_repo = FreightAttachmentRepository(db)
        self.tag_repo = FreightTagRelationRepository(db)
        self.batch_repo = FreightBatchTaskRepository(db)
        self.tms_repo = FreightTmsInboundRepository(db)
        self.clue_repo = FreightClueRepository(db)
        self.candidate_repo = FreightCandidateRepository(db)
        self.feedback_repo = FreightCandidateManualFeedbackRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def create_manual_freight(self, payload) -> FreightResponse:
        data = payload.model_dump(exclude_none=True)
        freight_no = (payload.freight_no or "").strip() or await self.sequence_service.next_code("FREIGHT_NO")
        if await self.repo.exists_freight_no(freight_no):
            raise ConflictError(f"freight_no already exists: {freight_no}")
        await self._enrich_location_updates(data, "origin")
        await self._enrich_location_updates(data, "destination")
        await self._enrich_commodity_updates(data)
        self._fill_default_raw_levels(data)
        self._validate_freight_minimum(data)
        data.update(
            {
                "freight_no": freight_no,
                "source_type_code": "MANUAL",
                "source_channel_code": "MANUAL_FORM",
                "cargo_title": payload.cargo_title.strip(),
                "confirmed_at": datetime.utcnow(),
            }
        )
        if data.get("status_code") == "PUBLISHED" and data.get("published_at") is None:
            data["published_at"] = datetime.utcnow()
        if data.get("hall_status_code") == "PUBLISHED" and data.get("hall_published_at") is None:
            data["hall_published_at"] = datetime.utcnow()
        row = await self.repo.create_freight(data)
        await self.db.commit()
        ctx = await _load_display_context(self.db, freights=[row])
        return _to_freight_response(row, ctx)

    async def update_freight(self, freight_id: int, payload) -> FreightResponse:
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            raise ValidationError("no update fields provided")
        await self._enrich_location_updates(updates, "origin")
        await self._enrich_location_updates(updates, "destination")
        await self._enrich_commodity_updates(updates)
        self._fill_default_raw_levels(updates)
        if updates.get("hall_status_code") == "PUBLISHED" and updates.get("hall_published_at") is None:
            updates["hall_published_at"] = datetime.utcnow()
            updates["hall_unpublished_at"] = None
        if updates.get("hall_status_code") == "UNPUBLISHED" and updates.get("hall_unpublished_at") is None:
            updates["hall_unpublished_at"] = datetime.utcnow()
        row = await self.repo.update_freight(freight_id, updates)
        if row is None:
            raise NotFoundError("Freight", freight_id)
        self._validate_freight_minimum(_entity_snapshot(row, self._freight_minimum_fields()))
        await self.db.commit()
        ctx = await _load_display_context(self.db, freights=[row])
        return _to_freight_response(row, ctx)

    async def get_freight_detail(self, freight_id: int) -> FreightDetailResponse:
        freight = await self.repo.get_freight_by_id(freight_id)
        if freight is None:
            raise NotFoundError("Freight", freight_id)
        contacts = await self.contact_repo.list_contacts(freight_id)
        attachments = await self.attachment_repo.list_attachments(freight_id)
        tags = await self.tag_repo.list_tag_relations(freight_id)
        source_batch = await self.batch_repo.get_by_id(freight.source_batch_id) if freight.source_batch_id else None
        source_tms = await self.tms_repo.get_by_id(freight.source_tms_inbound_id) if freight.source_tms_inbound_id else None
        source_clue = await self.clue_repo.get_by_id(freight.source_clue_id) if freight.source_clue_id else None
        source_candidate = await self.candidate_repo.get_by_id(freight.source_candidate_id) if freight.source_candidate_id else None
        feedback_rows = await self.feedback_repo.list_by_candidate_ids([source_candidate.id] if source_candidate else [])
        ctx = await _load_display_context(
            self.db,
            freights=[freight],
            candidates=[source_candidate] if source_candidate is not None else [],
            batches=[source_batch] if source_batch is not None else [],
            tms_inbounds=[source_tms] if source_tms is not None else [],
            clues=[source_clue] if source_clue is not None else [],
            feedback=feedback_rows,
        )
        return FreightDetailResponse(
            profile=_to_freight_response(freight, ctx),
            contacts=[_to_contact_response(item) for item in contacts],
            attachments=[_to_attachment_response(item) for item in attachments],
            tags=[_to_tag_response(item) for item in tags],
            source_batch=_to_batch_response(source_batch, ctx) if source_batch is not None else None,
            source_tms_inbound=_to_tms_response(source_tms, ctx) if source_tms is not None else None,
            source_clue=_to_clue_response(source_clue, ctx) if source_clue is not None else None,
            source_candidate=_to_candidate_response(source_candidate, ctx) if source_candidate is not None else None,
            confirmation_records=[_to_feedback_response(item, source_candidate, ctx) for item in feedback_rows],
        )

    async def change_freight_status(self, freight_id: int, status_code: str) -> None:
        target_status = str(status_code or "").strip().upper()
        if target_status not in FREIGHT_STATUS_LABELS:
            raise ValidationError(f"不支持的货源状态：{status_code}")

        freight = await self.repo.get_freight_by_id(freight_id)
        if freight is None:
            raise NotFoundError("Freight", freight_id)
        current_status = str(freight.status_code or "").strip().upper()
        if current_status == target_status:
            return

        allowed_targets = FREIGHT_STATUS_ACTIONS.get(current_status)
        if allowed_targets is not None and target_status not in allowed_targets:
            current_label = FREIGHT_STATUS_LABELS.get(current_status, current_status or "未知")
            target_label = FREIGHT_STATUS_LABELS.get(target_status, target_status)
            raise ValidationError(f"当前货源为{current_label}，不能直接变更为{target_label}")

        ok = await self.repo.update_freight_status(freight_id, target_status)
        if not ok:
            raise NotFoundError("Freight", freight_id)
        await self.db.commit()

    @staticmethod
    def _freight_minimum_fields() -> list[str]:
        return [
            "cargo_title",
            "raw_commodity_name",
            "commodity_standard_id",
            "raw_origin_text",
            "origin_node_id",
            "origin_city_code",
            "raw_destination_text",
            "destination_node_id",
            "destination_city_code",
        ]

    @staticmethod
    def _validate_freight_minimum(data: dict[str, Any]) -> None:
        missing: list[str] = []
        if str(data.get("commodity_match_level_code") or "").upper() == "STANDARD" and not data.get("commodity_standard_id"):
            missing.append("标准货品")
        if not (str(data.get("cargo_title") or "").strip() or str(data.get("raw_commodity_name") or "").strip() or data.get("commodity_standard_id")):
            missing.append("货品原文或货源标题")
        origin_level = str(data.get("origin_match_level_code") or "").upper()
        destination_level = str(data.get("destination_match_level_code") or "").upper()
        if origin_level == "NODE" and not data.get("origin_node_id"):
            missing.append("装货节点")
        if origin_level == "CITY" and not data.get("origin_city_code"):
            missing.append("装货城市")
        if destination_level == "NODE" and not data.get("destination_node_id"):
            missing.append("卸货节点")
        if destination_level == "CITY" and not data.get("destination_city_code"):
            missing.append("卸货城市")
        if not (str(data.get("raw_origin_text") or "").strip() or data.get("origin_node_id") or data.get("origin_city_code")):
            missing.append("装货地原文")
        if not (str(data.get("raw_destination_text") or "").strip() or data.get("destination_node_id") or data.get("destination_city_code")):
            missing.append("卸货地原文")
        if missing:
            raise ValidationError(f"正式货源缺少最低入库字段：{', '.join(missing)}")




class FreightContactService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.freight_repo = FreightRepository(db)
        self.repo = FreightContactRepository(db)

    async def replace_contacts(self, freight_id: int, contacts: list[dict]) -> list[FreightContactResponse]:
        freight = await self.freight_repo.get_freight_by_id(freight_id)
        if freight is None:
            raise NotFoundError("Freight", freight_id)
        rows = await self.repo.replace_contacts(freight_id, contacts)
        await self.db.commit()
        return [_to_contact_response(item) for item in rows]


class FreightAttachmentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.freight_repo = FreightRepository(db)
        self.repo = FreightAttachmentRepository(db)

    async def list_attachments(self, freight_id: int) -> list[FreightAttachmentResponse]:
        freight = await self.freight_repo.get_freight_by_id(freight_id)
        if freight is None:
            raise NotFoundError("Freight", freight_id)
        rows = await self.repo.list_attachments(freight_id)
        return [_to_attachment_response(item) for item in rows]

    async def create_attachment(self, freight_id: int, payload) -> FreightAttachmentResponse:
        freight = await self.freight_repo.get_freight_by_id(freight_id)
        if freight is None:
            raise NotFoundError("Freight", freight_id)
        row = await self.repo.create_attachment(freight_id, payload.model_dump(exclude_none=True))
        await self.db.commit()
        return _to_attachment_response(row)

    async def update_attachment(self, attachment_id: int, payload) -> FreightAttachmentResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        row = await self.repo.update_attachment(attachment_id, updates)
        if row is None:
            raise NotFoundError("FreightSourceAttachment", attachment_id)
        await self.db.commit()
        return _to_attachment_response(row)

    async def delete_attachment(self, attachment_id: int) -> None:
        ok = await self.repo.delete_attachment(attachment_id)
        if not ok:
            raise NotFoundError("FreightSourceAttachment", attachment_id)
        await self.db.commit()


class FreightTagService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.freight_repo = FreightRepository(db)
        self.repo = FreightTagRelationRepository(db)

    async def list_tag_relations(self, freight_id: int) -> list[FreightTagRelationResponse]:
        freight = await self.freight_repo.get_freight_by_id(freight_id)
        if freight is None:
            raise NotFoundError("Freight", freight_id)
        rows = await self.repo.list_tag_relations(freight_id)
        return [_to_tag_response(item) for item in rows]

    async def replace_tag_relations(self, freight_id: int, tags: list[str]) -> list[FreightTagRelationResponse]:
        freight = await self.freight_repo.get_freight_by_id(freight_id)
        if freight is None:
            raise NotFoundError("Freight", freight_id)
        rows = await self.repo.replace_tag_relations(freight_id, tags)
        await self.db.commit()
        return [_to_tag_response(item) for item in rows]
