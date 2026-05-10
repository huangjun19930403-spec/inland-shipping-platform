"""Implementation methods for the vessel relation domain."""

from __future__ import annotations

from app.modules.vessel.shared import base as _base

globals().update({name: getattr(_base, name) for name in dir(_base) if not name.startswith("__")})


class VesselRelationMixin:
    """Implementation methods for the vessel relation domain."""

    def _relation_status_code(self, row: Any) -> str:
        if getattr(row, "voided_at", None) is not None:
            return "VOIDED"
        if getattr(row, "end_date", None) is not None or bool(getattr(row, "is_current", True)) is False:
            return "HISTORY"
        return "CURRENT"

    async def _attach_profile_relation_files(self, items: list[VesselProfileCardEvidenceItem]) -> None:
        grouped: dict[str, list[int]] = defaultdict(list)
        for item in items:
            if item.object_type not in {"VESSEL_CONTROLLER_EVIDENCE", "VESSEL_AFFILIATION_EVIDENCE"}:
                continue
            try:
                grouped[item.object_type].append(int(item.object_id or 0))
            except (TypeError, ValueError):
                continue
        attachment_maps: dict[str, dict[int, list[VesselRelationEvidenceAttachmentResponse]]] = {}
        for evidence_type, ids in grouped.items():
            attachment_maps[evidence_type] = await self._relation_evidence_attachment_map(evidence_type, ids)
        for item in items:
            if item.object_type not in attachment_maps:
                continue
            try:
                evidence_id = int(item.object_id or 0)
            except (TypeError, ValueError):
                continue
            attachments = attachment_maps[item.object_type].get(evidence_id, [])
            if attachments:
                item.attachment_refs = [attachment.model_dump(mode="json") for attachment in attachments]

    async def list_owners(self, vessel_id: int, *, current_only: bool = True) -> list[VesselOwnerResponse]:
        await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        rows = await self.repo.list_by_profile(VesselOwnerPeriod, vessel_id)
        if current_only:
            rows = [row for row in rows if _relation_is_effective(row)]
        docs = await self._owner_documents_by_owner(vessel_id, label_map)
        return [self._owner_response(row, label_map, documents=docs.get(row.id, [])) for row in rows]

    async def list_operators(self, vessel_id: int, *, current_only: bool = True) -> list[VesselOperatorResponse]:
        await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        rows = await self.repo.list_by_profile(VesselOperatorPeriod, vessel_id)
        if current_only:
            rows = [row for row in rows if _relation_is_effective(row)]
        return [self._operator_response(row, label_map) for row in rows]

    async def list_contacts(self, vessel_id: int, *, current_only: bool = True) -> list[VesselContactResponse]:
        await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        rows = await self.repo.list_by_profile(VesselContact, vessel_id)
        if current_only:
            rows = [row for row in rows if _relation_is_effective(row)]
        return [self._contact_response(row, label_map) for row in rows]

    async def list_crew(self, vessel_id: int, *, current_only: bool = True) -> list[VesselCrewResponse]:
        await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        rows = await self.repo.list_by_profile(VesselCrewAssignment, vessel_id)
        if current_only:
            rows = [row for row in rows if _relation_is_effective(row)]
        return [self._crew_response(row, label_map) for row in rows]

    async def replace_owners(self, vessel_id: int, payload, *, operator_id: int | None = None) -> list[VesselOwnerResponse]:
        await self._require_profile(vessel_id)
        _ = payload, operator_id
        self._raise_replace_gone("owners")

    async def upload_owner_document(
        self,
        vessel_id: int,
        owner_id: int,
        file: UploadFile,
        *,
        document_type_code: str,
        operator_id: int | None = None,
    ) -> VesselOwnerDocumentResponse:
        await self._require_profile(vessel_id)
        owner = await self.db.get(VesselOwnerPeriod, owner_id)
        if owner is None or owner.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselOwnerPeriod", owner_id)
        row = await self._store_owner_document(
            vessel_id,
            owner_id,
            file,
            document_type_code=document_type_code,
            operator_id=operator_id,
        )
        recognition = None
        if row.content_type.lower().startswith("image/") and document_type_code in IMAGE_RECOGNIZABLE_OWNER_DOCUMENT_TYPES:
            recognition = await self._create_owner_document_image_recognition_record(
                vessel_id,
                owner_id,
                row.id,
                row.storage_file_id,
                operator_id=operator_id,
            )
        await self.db.commit()
        if recognition is not None:
            await self._dispatch_owner_document_recognition_or_fail(recognition)
        label_map = await _load_label_map(self.db)
        latest = await self._latest_owner_document_recognition(row.id)
        return self._owner_document_response(
            row,
            label_map,
            latest_recognition=latest,
            current_recognition=latest if latest is not None and latest.status_code in CURRENT_RECOGNITION_STATUSES else None,
            latest_confirmed_recognition=latest if latest is not None and latest.status_code == "CONFIRMED" else None,
            has_recognition_history=latest is not None,
        )

    async def void_owner_document(
        self,
        vessel_id: int,
        owner_id: int,
        owner_document_id: int,
        *,
        reason: str | None = None,
        operator_id: int | None = None,
    ) -> None:
        owner = await self.db.get(VesselOwnerPeriod, owner_id)
        if owner is None or owner.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselOwnerPeriod", owner_id)
        document = await self.repo.get_owner_document(owner_document_id)
        if document is None or document.vessel_owner_period_id != owner_id or document.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselOwnerDocument", owner_document_id)
        before = _row_dict(document)
        document.voided_at = datetime.utcnow()
        document.voided_by = operator_id
        document.void_reason = reason or "所有方证照作废"
        await self._add_change_event(vessel_id, "VOID_OWNER_DOCUMENT", "作废所有方证照", before, _row_dict(document), operator_id)
        await self.db.commit()

    async def replace_operators(self, vessel_id: int, payload, *, operator_id: int | None = None) -> list[VesselOperatorResponse]:
        await self._require_profile(vessel_id)
        _ = payload, operator_id
        self._raise_replace_gone("operators")

    async def replace_contacts(self, vessel_id: int, payload, *, operator_id: int | None = None) -> list[VesselContactResponse]:
        await self._require_profile(vessel_id)
        _ = payload, operator_id
        self._raise_replace_gone("contacts")

    async def replace_crew(self, vessel_id: int, payload, *, operator_id: int | None = None) -> list[VesselCrewResponse]:
        await self._require_profile(vessel_id)
        _ = payload, operator_id
        self._raise_replace_gone("crew")

    async def create_owner(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselOwnerResponse:
        await self._require_profile(vessel_id)
        row, cancelled_ids, event_id = await self._create_relation(
            VesselOwnerPeriod,
            vessel_id,
            payload.model_dump(exclude_none=True),
            event_type_code="CREATE_OWNER",
            event_title="新增所有方关系",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        docs = await self._owner_documents_by_owner(vessel_id, label_map)
        response = self._owner_response(row, label_map, documents=docs.get(row.id, []))
        response.cancelled_primary_ids = cancelled_ids
        response.change_event_id = event_id
        return response

    async def update_owner(self, vessel_id: int, owner_id: int, payload, *, operator_id: int | None = None) -> VesselOwnerResponse:
        row, event_id = await self._update_relation(
            VesselOwnerPeriod,
            vessel_id,
            owner_id,
            payload,
            event_type_code="UPDATE_OWNER",
            event_title="更新所有方关系",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        docs = await self._owner_documents_by_owner(vessel_id, label_map)
        response = self._owner_response(row, label_map, documents=docs.get(row.id, []))
        response.change_event_id = event_id
        return response

    async def end_owner(self, vessel_id: int, owner_id: int, payload, *, operator_id: int | None = None) -> VesselOwnerResponse:
        row, event_id = await self._end_relation(
            VesselOwnerPeriod,
            vessel_id,
            owner_id,
            payload,
            event_type_code="END_OWNER",
            event_title="结束所有方关系",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._owner_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def void_owner(self, vessel_id: int, owner_id: int, payload, *, operator_id: int | None = None) -> VesselOwnerResponse:
        row, event_id = await self._void_relation(
            VesselOwnerPeriod,
            vessel_id,
            owner_id,
            payload,
            event_type_code="VOID_OWNER",
            event_title="作废所有方关系",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._owner_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def set_primary_owner(self, vessel_id: int, owner_id: int, payload, *, operator_id: int | None = None) -> VesselOwnerResponse:
        row, cancelled_ids, event_id = await self._set_primary_relation(
            VesselOwnerPeriod,
            vessel_id,
            owner_id,
            payload,
            event_type_code="SET_PRIMARY_OWNER",
            event_title="设置主所有方",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        docs = await self._owner_documents_by_owner(vessel_id, label_map)
        response = self._owner_response(row, label_map, documents=docs.get(row.id, []))
        response.cancelled_primary_ids = cancelled_ids
        response.change_event_id = event_id
        return response

    async def create_operator(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselOperatorResponse:
        await self._require_profile(vessel_id)
        row, cancelled_ids, event_id = await self._create_relation(
            VesselOperatorPeriod,
            vessel_id,
            payload.model_dump(exclude_none=True),
            event_type_code="CREATE_OPERATOR",
            event_title="新增运营方关系",
            operator_id=operator_id,
        )
        await self.repo.update_profile(vessel_id, {"operation_status_code": "OPERATING"})
        await self.db.commit()
        label_map = await _load_label_map(self.db)
        response = self._operator_response(row, label_map)
        response.cancelled_primary_ids = cancelled_ids
        response.change_event_id = event_id
        return response

    async def update_operator(self, vessel_id: int, operator_period_id: int, payload, *, operator_id: int | None = None) -> VesselOperatorResponse:
        row, event_id = await self._update_relation(
            VesselOperatorPeriod,
            vessel_id,
            operator_period_id,
            payload,
            event_type_code="UPDATE_OPERATOR",
            event_title="更新运营方关系",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._operator_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def end_operator(self, vessel_id: int, operator_period_id: int, payload, *, operator_id: int | None = None) -> VesselOperatorResponse:
        row, event_id = await self._end_relation(
            VesselOperatorPeriod,
            vessel_id,
            operator_period_id,
            payload,
            event_type_code="END_OPERATOR",
            event_title="结束运营方关系",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._operator_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def void_operator(self, vessel_id: int, operator_period_id: int, payload, *, operator_id: int | None = None) -> VesselOperatorResponse:
        row, event_id = await self._void_relation(
            VesselOperatorPeriod,
            vessel_id,
            operator_period_id,
            payload,
            event_type_code="VOID_OPERATOR",
            event_title="作废运营方关系",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._operator_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def set_primary_operator(self, vessel_id: int, operator_period_id: int, payload, *, operator_id: int | None = None) -> VesselOperatorResponse:
        row, cancelled_ids, event_id = await self._set_primary_relation(
            VesselOperatorPeriod,
            vessel_id,
            operator_period_id,
            payload,
            event_type_code="SET_PRIMARY_OPERATOR",
            event_title="设置主运营方",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._operator_response(row, label_map)
        response.cancelled_primary_ids = cancelled_ids
        response.change_event_id = event_id
        return response

    async def create_contact(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselContactResponse:
        await self._require_profile(vessel_id)
        row, cancelled_ids, event_id = await self._create_relation(
            VesselContact,
            vessel_id,
            payload.model_dump(exclude_none=True),
            event_type_code="CREATE_CONTACT",
            event_title="新增联系人",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._contact_response(row, label_map)
        response.cancelled_primary_ids = cancelled_ids
        response.change_event_id = event_id
        return response

    async def update_contact(self, vessel_id: int, contact_id: int, payload, *, operator_id: int | None = None) -> VesselContactResponse:
        row, event_id = await self._update_relation(
            VesselContact,
            vessel_id,
            contact_id,
            payload,
            event_type_code="UPDATE_CONTACT",
            event_title="更新联系人",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._contact_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def end_contact(self, vessel_id: int, contact_id: int, payload, *, operator_id: int | None = None) -> VesselContactResponse:
        row, event_id = await self._end_relation(
            VesselContact,
            vessel_id,
            contact_id,
            payload,
            event_type_code="END_CONTACT",
            event_title="结束联系人",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._contact_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def void_contact(self, vessel_id: int, contact_id: int, payload, *, operator_id: int | None = None) -> VesselContactResponse:
        row, event_id = await self._void_relation(
            VesselContact,
            vessel_id,
            contact_id,
            payload,
            event_type_code="VOID_CONTACT",
            event_title="作废联系人",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._contact_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def set_primary_contact(self, vessel_id: int, contact_id: int, payload, *, operator_id: int | None = None) -> VesselContactResponse:
        row, cancelled_ids, event_id = await self._set_primary_relation(
            VesselContact,
            vessel_id,
            contact_id,
            payload,
            event_type_code="SET_PRIMARY_CONTACT",
            event_title="设置主联系人",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._contact_response(row, label_map)
        response.cancelled_primary_ids = cancelled_ids
        response.change_event_id = event_id
        return response

    async def create_crew(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselCrewResponse:
        await self._require_profile(vessel_id)
        data = payload.model_dump(exclude_none=True)
        data.pop("id", None)
        row, _, event_id = await self._create_relation(
            VesselCrewAssignment,
            vessel_id,
            data,
            event_type_code="CREATE_CREW",
            event_title="新增船员任职",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._crew_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def update_crew(self, vessel_id: int, crew_id: int, payload, *, operator_id: int | None = None) -> VesselCrewResponse:
        row, event_id = await self._update_relation(
            VesselCrewAssignment,
            vessel_id,
            crew_id,
            payload,
            event_type_code="UPDATE_CREW",
            event_title="更新船员任职",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._crew_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def end_crew(self, vessel_id: int, crew_id: int, payload, *, operator_id: int | None = None) -> VesselCrewResponse:
        row, event_id = await self._end_relation(
            VesselCrewAssignment,
            vessel_id,
            crew_id,
            payload,
            event_type_code="END_CREW",
            event_title="结束船员任职",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._crew_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def void_crew(self, vessel_id: int, crew_id: int, payload, *, operator_id: int | None = None) -> VesselCrewResponse:
        row, event_id = await self._void_relation(
            VesselCrewAssignment,
            vessel_id,
            crew_id,
            payload,
            event_type_code="VOID_CREW",
            event_title="作废船员任职",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._crew_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def owner_transfer(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselProfileResponse:
        profile = await self._require_profile(vessel_id)
        transfer_date = payload.transfer_date or date.today()
        transfer_time = datetime.utcnow()
        code = await CodeSequenceService(self.db).next_code("VESSEL_PROFILE_CODE")
        old_snapshot = _row_dict(profile)
        await self._assert_active_mmsi_available(
            profile.current_mmsi,
            exclude_vessel_id=vessel_id,
            attempted_profile_id=vessel_id,
            evidence_source="OWNER_TRANSFER",
        )
        profile.profile_status_code = "TRANSFERRED"
        existing_owners = await self.repo.list_by_profile(VesselOwnerPeriod, vessel_id)
        for owner in existing_owners:
            if owner.is_current:
                owner.is_current = False
                owner.end_date = transfer_date
                owner.is_primary = False
                owner.revision = int(owner.revision or 1) + 1
        new_profile = await self.repo.create_profile(
            {
                "vessel_identity_id": profile.vessel_identity_id,
                "ship_name": profile.ship_name,
                "ship_name_en": profile.ship_name_en,
                "current_mmsi": profile.current_mmsi,
                "ship_type_code": profile.ship_type_code,
                "operation_status_code": profile.operation_status_code,
                "home_port_code": profile.home_port_code,
                "home_port_name": profile.home_port_name,
                "registry_city_code": profile.registry_city_code,
                "business_region_id": profile.business_region_id,
                "source_type_code": profile.source_type_code,
                "vessel_profile_code": code,
                "profile_status_code": "ACTIVE",
                "identity_status_code": profile.identity_status_code,
                "audit_status": "PENDING",
                "remark": payload.remark,
            }
        )
        await self._copy_singletons(vessel_id, new_profile.id)
        await self._copy_history(vessel_id, new_profile.id)
        await self.repo.create_many_by_profile(
            VesselOwnerPeriod,
            new_profile.id,
            [
                {
                    "party_name": payload.new_owner_name,
                    "party_type_code": payload.party_type_code,
                    "certificate_no": payload.certificate_no,
                    "address": payload.address,
                    "start_date": transfer_date,
                    "is_current": True,
                    "is_primary": True,
                }
            ],
        )
        if profile.vessel_identity_id:
            existing_links = (
                await self.db.execute(
                    select(VesselIdentityLink).where(
                        VesselIdentityLink.vessel_identity_id == profile.vessel_identity_id,
                        VesselIdentityLink.vessel_profile_id == vessel_id,
                        VesselIdentityLink.end_at.is_(None),
                    )
                )
            ).scalars().all()
            for link in existing_links:
                link.end_at = transfer_time
                link.is_primary = False
            self.db.add(
                VesselIdentityLink(
                    vessel_identity_id=profile.vessel_identity_id,
                    vessel_profile_id=new_profile.id,
                    link_type_code="OWNER_TRANSFER",
                    confidence_score=90,
                    is_primary=True,
                    start_at=transfer_time,
                )
            )
        await self._add_change_event(vessel_id, "OWNER_TRANSFER_OUT", "所有方转移出", old_snapshot, {"new_profile_id": new_profile.id}, operator_id)
        await self._add_change_event(new_profile.id, "OWNER_TRANSFER_IN", "所有方转移入", None, {"from_profile_id": vessel_id}, operator_id)
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        await self._refresh_summary_best_effort(new_profile.id)
        return await self._build_profile_response(new_profile.id)

    async def get_change_events(self, vessel_id: int) -> list[VesselChangeEventResponse]:
        await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        return [
            VesselChangeEventResponse(
                **_row_dict(row),
                event_type_name=label_map.get("VESSEL_CHANGE_EVENT_TYPE", {}).get(row.event_type_code),
            )
            for row in await self.repo.list_by_profile(VesselChangeEvent, vessel_id, order_desc=True)
        ]

    async def _owner_documents_by_owner(
        self,
        vessel_id: int,
        label_map: dict[str, dict[str, str]],
    ) -> dict[int, list[VesselOwnerDocumentResponse]]:
        docs = [row for row in await self.repo.list_owner_documents(vessel_id) if row.voided_at is None]
        if not docs:
            return {}
        recognition_rows = (
            await self.db.execute(
                select(VesselOwnerDocumentImageRecognition)
                .where(VesselOwnerDocumentImageRecognition.owner_document_id.in_([row.id for row in docs]))
                .order_by(VesselOwnerDocumentImageRecognition.created_at.desc(), VesselOwnerDocumentImageRecognition.id.desc())
            )
        ).scalars().all()
        latest_recognition_map: dict[int, VesselOwnerDocumentImageRecognition] = {}
        current_recognition_map: dict[int, VesselOwnerDocumentImageRecognition] = {}
        latest_confirmed_recognition_map: dict[int, VesselOwnerDocumentImageRecognition] = {}
        has_recognition_history: set[int] = set()
        for row in recognition_rows:
            has_recognition_history.add(row.owner_document_id)
            if row.owner_document_id not in latest_recognition_map:
                latest_recognition_map[row.owner_document_id] = row
                if row.status_code in CURRENT_RECOGNITION_STATUSES:
                    current_recognition_map[row.owner_document_id] = row
            if row.status_code == "CONFIRMED":
                latest_confirmed_recognition_map.setdefault(row.owner_document_id, row)
        result: dict[int, list[VesselOwnerDocumentResponse]] = defaultdict(list)
        for row in docs:
            result[row.vessel_owner_period_id].append(
                self._owner_document_response(
                    row,
                    label_map,
                    latest_recognition=latest_recognition_map.get(row.id),
                    current_recognition=current_recognition_map.get(row.id),
                    latest_confirmed_recognition=latest_confirmed_recognition_map.get(row.id),
                    has_recognition_history=row.id in has_recognition_history,
                )
            )
        return result

    def _owner_document_response(
        self,
        row: VesselOwnerDocument,
        label_map: dict[str, dict[str, str]],
        *,
        latest_recognition: VesselOwnerDocumentImageRecognition | None = None,
        current_recognition: VesselOwnerDocumentImageRecognition | None = None,
        latest_confirmed_recognition: VesselOwnerDocumentImageRecognition | None = None,
        has_recognition_history: bool = False,
    ) -> VesselOwnerDocumentResponse:
        return VesselOwnerDocumentResponse(
            **_row_dict(row),
            document_type_name=label_map.get("OWNER_DOCUMENT_TYPE", {}).get(row.document_type_code),
            download_url=f"/api/v1/files/{row.storage_file_id}/content",
            latest_image_recognition=(
                self._owner_document_image_recognition_response(latest_recognition, label_map)
                if latest_recognition is not None
                else None
            ),
            current_image_recognition=(
                self._owner_document_image_recognition_response(current_recognition, label_map)
                if current_recognition is not None
                else None
            ),
            latest_confirmed_image_recognition=(
                self._owner_document_image_recognition_response(latest_confirmed_recognition, label_map)
                if latest_confirmed_recognition is not None
                else None
            ),
            has_recognition_history=has_recognition_history,
        )

    def _owner_response(
        self,
        row: VesselOwnerPeriod,
        label_map: dict[str, dict[str, str]],
        *,
        documents: list[VesselOwnerDocumentResponse] | None = None,
    ) -> VesselOwnerResponse:
        document_list = documents or []
        return VesselOwnerResponse(
            **_row_dict(row),
            party_type_name=label_map.get("PARTY_SUBJECT_TYPE", {}).get(row.party_type_code),
            verified_status_name=label_map.get("VESSEL_RELATION_VERIFIED_STATUS", {}).get(row.verified_status_code),
            source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
            documents=document_list,
            document_ledger=self._owner_document_ledger(row, document_list, label_map),
            document_completeness=self._owner_document_completeness(row, document_list),
        )

    def _owner_required_document_types(self, row: VesselOwnerPeriod) -> set[str]:
        return OWNER_REQUIRED_DOCUMENT_TYPES_BY_PARTY.get(row.party_type_code or "UNKNOWN", set())

    def _owner_document_ledger(
        self,
        owner: VesselOwnerPeriod,
        documents: list[VesselOwnerDocumentResponse],
        label_map: dict[str, dict[str, str]],
    ) -> list[VesselOwnerDocumentLedgerItemResponse]:
        required_types = self._owner_required_document_types(owner)
        doc_by_type: dict[str, VesselOwnerDocumentResponse] = {}
        for document in documents:
            doc_by_type.setdefault(document.document_type_code, document)
        types = [code for code in OWNER_DOCUMENT_LEDGER_TYPES if code in required_types or code in doc_by_type or code not in {"OTHER"}]
        if "OTHER" in doc_by_type:
            types.append("OTHER")
        result: list[VesselOwnerDocumentLedgerItemResponse] = []
        for code in dict.fromkeys(types):
            document = doc_by_type.get(code)
            status = self._owner_document_ledger_status(owner, document)
            result.append(
                VesselOwnerDocumentLedgerItemResponse(
                    document_type_code=code,
                    document_type_name=label_map.get("OWNER_DOCUMENT_TYPE", {}).get(code),
                    required=code in required_types,
                    status_code=status,
                    status_name=self._owner_document_ledger_status_name(status),
                    document=document,
                )
            )
        return result

    def _owner_document_ledger_status(
        self,
        owner: VesselOwnerPeriod,
        document: VesselOwnerDocumentResponse | None,
    ) -> str:
        if owner.party_type_code not in OWNER_REQUIRED_DOCUMENT_TYPES_BY_PARTY:
            return "UNKNOWN_OWNER_TYPE"
        if document is None:
            return "MISSING"
        current = document.current_image_recognition
        if current is not None and current.status_code == "NEED_CONFIRM":
            return "NEED_CONFIRM"
        if current is not None and current.status_code in ACTIVE_RECOGNITION_STATUSES:
            return current.status_code
        if current is not None and current.status_code == "FAILED":
            return "RECOGNITION_FAILED"
        if document.latest_confirmed_image_recognition is not None:
            return "CONFIRMED"
        return "ARCHIVED"

    def _owner_document_ledger_status_name(self, status: str) -> str:
        return {
            "UNKNOWN_OWNER_TYPE": "主体类型未确认",
            "MISSING": "缺失",
            "ARCHIVED": "已归档",
            "QUEUED": "排队识别",
            "PROCESSING": "识别中",
            "NEED_CONFIRM": "待确认",
            "RECOGNITION_FAILED": "识别失败",
            "CONFIRMED": "已确认",
        }.get(status, status)

    def _owner_document_completeness(
        self,
        owner: VesselOwnerPeriod,
        documents: list[VesselOwnerDocumentResponse],
    ) -> VesselOwnerDocumentCompletenessResponse:
        required_types = self._owner_required_document_types(owner)
        if not required_types:
            return VesselOwnerDocumentCompletenessResponse(
                status_code="UNKNOWN_OWNER_TYPE",
                status_name="主体类型未确认",
                required_count=0,
                completed_count=0,
                missing_document_type_codes=[],
                message="主体类型未确认，无法计算资料完整度",
            )
        existing_types = {document.document_type_code for document in documents}
        missing = sorted(required_types - existing_types)
        return VesselOwnerDocumentCompletenessResponse(
            status_code="COMPLETE" if not missing else "INCOMPLETE",
            status_name="资料完整" if not missing else "资料缺失",
            required_count=len(required_types),
            completed_count=len(required_types) - len(missing),
            missing_document_type_codes=missing,
            message=None if not missing else "缺少必备所有方证照",
        )

    def _operator_response(self, row: VesselOperatorPeriod, label_map: dict[str, dict[str, str]]) -> VesselOperatorResponse:
        return VesselOperatorResponse(
            **_row_dict(row),
            party_type_name=label_map.get("PARTY_SUBJECT_TYPE", {}).get(row.party_type_code),
            verified_status_name=label_map.get("VESSEL_RELATION_VERIFIED_STATUS", {}).get(row.verified_status_code),
            source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
        )

    def _contact_response(self, row: VesselContact, label_map: dict[str, dict[str, str]]) -> VesselContactResponse:
        return VesselContactResponse(
            **_row_dict(row),
            contact_scope_name=label_map.get("CONTACT_SCOPE", {}).get(row.contact_scope_code),
            contact_role_name=label_map.get("CONTACT_ROLE", {}).get(row.contact_role_code),
            verified_status_name=label_map.get("VESSEL_RELATION_VERIFIED_STATUS", {}).get(row.verified_status_code),
            source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
        )

    def _crew_response(self, row: VesselCrewAssignment, label_map: dict[str, dict[str, str]]) -> VesselCrewResponse:
        return VesselCrewResponse(
            **_row_dict(row),
            crew_role_name=label_map.get("VESSEL_CREW_ROLE", {}).get(row.crew_role_code),
            verified_status_name=label_map.get("VESSEL_RELATION_VERIFIED_STATUS", {}).get(row.verified_status_code),
            source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
        )

    async def _require_relation_row(self, model: type[Any], vessel_id: int, row_id: int) -> Any:
        row = await self.db.get(model, row_id)
        if row is None or getattr(row, "vessel_profile_id", None) != vessel_id:
            raise NotFoundError(model.__name__, row_id)
        return row

    async def _create_relation(
        self,
        model: type[Any],
        vessel_id: int,
        data: dict[str, Any],
        *,
        event_type_code: str,
        event_title: str,
        operator_id: int | None,
    ) -> tuple[Any, list[int], int]:
        wants_primary = bool(data.get("is_primary", False)) and hasattr(model, "is_primary")
        data.setdefault("revision", 1)
        data.setdefault("verified_status_code", "UNVERIFIED")
        data.setdefault("source_type_code", "MANUAL")
        row = model(vessel_profile_id=vessel_id, **data)
        self.db.add(row)
        await self.db.flush()
        cancelled_ids: list[int] = []
        if wants_primary:
            cancelled_ids = await self._cancel_other_primaries(model, vessel_id, int(row.id))
        after = _row_dict(row)
        event_id = await self._add_change_event(
            vessel_id,
            event_type_code,
            event_title,
            None,
            {"row": after, "cancelled_primary_ids": cancelled_ids},
            operator_id,
            object_type=model.__tablename__,
            object_id=row.id,
        )
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return row, cancelled_ids, event_id

    async def _update_relation(
        self,
        model: type[Any],
        vessel_id: int,
        row_id: int,
        payload: Any,
        *,
        event_type_code: str,
        event_title: str,
        operator_id: int | None,
    ) -> tuple[Any, int]:
        await self._require_profile(vessel_id)
        row = await self._require_relation_row(model, vessel_id, row_id)
        _ensure_relation_writable(row)
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
        event_id = await self._add_change_event(
            vessel_id,
            event_type_code,
            event_title,
            before,
            _row_dict(row),
            operator_id,
            object_type=model.__tablename__,
            object_id=row.id,
            reason=reason,
        )
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return row, event_id

    async def _end_relation(
        self,
        model: type[Any],
        vessel_id: int,
        row_id: int,
        payload: Any,
        *,
        event_type_code: str,
        event_title: str,
        operator_id: int | None,
    ) -> tuple[Any, int]:
        await self._require_profile(vessel_id)
        row = await self._require_relation_row(model, vessel_id, row_id)
        self._ensure_revision(row, payload.revision)
        _ensure_relation_writable(row)
        before = _row_dict(row)
        row.end_date = payload.end_date or date.today()
        row.is_current = False
        if hasattr(row, "is_primary"):
            row.is_primary = False
        row.revision = int(row.revision or 1) + 1
        event_id = await self._add_change_event(
            vessel_id,
            event_type_code,
            event_title,
            before,
            _row_dict(row),
            operator_id,
            object_type=model.__tablename__,
            object_id=row.id,
            reason=payload.reason,
        )
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return row, event_id

    async def _void_relation(
        self,
        model: type[Any],
        vessel_id: int,
        row_id: int,
        payload: Any,
        *,
        event_type_code: str,
        event_title: str,
        operator_id: int | None,
    ) -> tuple[Any, int]:
        await self._require_profile(vessel_id)
        row = await self._require_relation_row(model, vessel_id, row_id)
        self._ensure_revision(row, payload.revision)
        _ensure_relation_writable(row, require_current=False)
        before = _row_dict(row)
        row.voided_at = datetime.utcnow()
        row.voided_by = operator_id
        row.void_reason = payload.reason or "关系作废"
        row.is_current = False
        if hasattr(row, "is_primary"):
            row.is_primary = False
        row.revision = int(row.revision or 1) + 1
        event_id = await self._add_change_event(
            vessel_id,
            event_type_code,
            event_title,
            before,
            _row_dict(row),
            operator_id,
            object_type=model.__tablename__,
            object_id=row.id,
            reason=payload.reason,
        )
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return row, event_id

    async def _cancel_other_primaries(self, model: type[Any], vessel_id: int, target_id: int) -> list[int]:
        rows = (
            await self.db.execute(
                select(model).where(
                    model.vessel_profile_id == vessel_id,
                    model.id != target_id,
                    model.is_primary.is_(True),
                    model.is_current.is_(True),
                    model.voided_at.is_(None),
                )
            )
        ).scalars().all()
        cancelled_ids: list[int] = []
        for row in rows:
            row.is_primary = False
            row.revision = int(row.revision or 1) + 1
            cancelled_ids.append(int(row.id))
        return cancelled_ids

    async def _set_primary_relation(
        self,
        model: type[Any],
        vessel_id: int,
        row_id: int,
        payload: Any,
        *,
        event_type_code: str,
        event_title: str,
        operator_id: int | None,
    ) -> tuple[Any, list[int], int | None]:
        await self._require_profile(vessel_id)
        row = await self._require_relation_row(model, vessel_id, row_id)
        self._ensure_revision(row, payload.revision)
        if not _relation_is_effective(row):
            _ensure_relation_writable(row)
            raise ConflictError(
                "只能将当前有效关系设置为主关系",
                code="RELATION_NOT_CURRENT",
                detail={"id": getattr(row, "id", None)},
            )
        primary_rows = (
            await self.db.execute(
                select(model).where(
                    model.vessel_profile_id == vessel_id,
                    model.is_primary.is_(True),
                    model.is_current.is_(True),
                    model.voided_at.is_(None),
                    model.end_date.is_(None),
                )
            )
        ).scalars().all()
        if row.is_primary and len(primary_rows) == 1 and int(primary_rows[0].id) == int(row.id):
            await self.db.commit()
            return row, [], None
        before = {"target": _row_dict(row), "primaries": [_row_dict(item) for item in primary_rows]}
        cancelled_ids = await self._cancel_other_primaries(model, vessel_id, int(row.id))
        if not row.is_primary:
            row.is_primary = True
        row.revision = int(row.revision or 1) + 1
        event_id = await self._add_change_event(
            vessel_id,
            event_type_code,
            event_title,
            before,
            {"target": _row_dict(row), "cancelled_primary_ids": cancelled_ids},
            operator_id,
            object_type=model.__tablename__,
            object_id=row.id,
            reason=payload.reason,
        )
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return row, cancelled_ids, event_id

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
        await self._create_evidence_audit_task_if_needed(
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
        await self._create_evidence_audit_task_if_needed(
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
        await self._create_evidence_audit_task_if_needed(
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
        await self._create_evidence_audit_task_if_needed(
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

    async def _create_evidence_audit_task_if_needed(
        self,
        row: Any,
        *,
        object_type_code: str,
        object_name: str | None,
        operator_id: int | None,
        before: dict[str, Any] | None,
        after: dict[str, Any],
    ) -> None:
        if getattr(row, "verified_status_code", None) != "PENDING" or getattr(row, "audit_task_id", None):
            return
        now = datetime.utcnow()
        task = AuditTask(
            task_no=f"VA{now:%Y%m%d%H%M%S}{uuid.uuid4().hex[:6].upper()}",
            biz_type_code="VESSEL",
            biz_id=row.id,
            biz_code=object_type_code,
            object_type_code=object_type_code,
            object_code=str(row.id),
            object_name=object_name,
            change_type_code="UPDATE" if before else "CREATE",
            source_module_code="VESSEL",
            submitter_id=operator_id,
            current_handler_id=None,
            audit_status="PENDING",
            audit_remark="Round 10 船舶证据审核",
            submitted_at=now,
        )
        self.db.add(task)
        await self.db.flush()
        row.audit_task_id = task.id
        self.db.add_all(
            [
                AuditTaskSnapshot(
                    task_id=task.id,
                    before_snapshot_json=_jsonable(before) if before else None,
                    after_snapshot_json=_jsonable(after),
                    diff_json=None,
                    summary_json={
                        "round": "ROUND_10",
                        "object_type_code": object_type_code,
                        "vessel_profile_id": row.vessel_profile_id,
                    },
                    created_at=now,
                    updated_at=now,
                ),
                AuditRecord(
                    task_id=task.id,
                    action_code="SUBMIT",
                    operator_id=operator_id,
                    from_status_code=None,
                    to_status_code="PENDING",
                    remark="提交船舶证据审核",
                    created_at=now,
                ),
            ]
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
