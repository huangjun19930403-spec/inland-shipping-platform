"""Basic owner, operator, contact, and crew relation workflows."""

from __future__ import annotations

from app.modules.vessel.shared import base as _base

globals().update({name: getattr(_base, name) for name in dir(_base) if not name.startswith("__")})


class BasicRelationMixin:
    """Basic relation CRUD and owner document helpers."""

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

    async def _relation_response_for_model(
        self,
        model: type[Any],
        vessel_id: int,
        row: Any,
        label_map: dict[str, dict[str, str]],
    ) -> Any:
        if model is VesselOwnerPeriod:
            docs = await self._owner_documents_by_owner(vessel_id, label_map)
            return self._owner_response(row, label_map, documents=docs.get(row.id, []))
        if model is VesselOperatorPeriod:
            return self._operator_response(row, label_map)
        if model is VesselContact:
            return self._contact_response(row, label_map)
        if model is VesselCrewAssignment:
            return self._crew_response(row, label_map)
        raise ValidationError(f"unsupported relation model: {model!r}")

    async def _create_relation_and_respond(
        self,
        model: type[Any],
        vessel_id: int,
        payload: Any,
        *,
        event_type_code: str,
        event_title: str,
        operator_id: int | None,
        strip_payload_id: bool = False,
        after_create: Any | None = None,
    ) -> Any:
        await self._require_profile(vessel_id)
        data = payload.model_dump(exclude_none=True)
        if strip_payload_id:
            data.pop("id", None)
        row, cancelled_ids, event_id = await self._create_relation(
            model,
            vessel_id,
            data,
            event_type_code=event_type_code,
            event_title=event_title,
            operator_id=operator_id,
        )
        if after_create is not None:
            await after_create(row)
        label_map = await _load_label_map(self.db)
        response = await self._relation_response_for_model(model, vessel_id, row, label_map)
        response.cancelled_primary_ids = cancelled_ids
        response.change_event_id = event_id
        return response

    async def _mutate_relation_and_respond(
        self,
        action: str,
        model: type[Any],
        vessel_id: int,
        row_id: int,
        payload: Any,
        *,
        event_type_code: str,
        event_title: str,
        operator_id: int | None,
    ) -> Any:
        operations = {
            "update": self._update_relation,
            "end": self._end_relation,
            "void": self._void_relation,
        }
        row, event_id = await operations[action](
            model,
            vessel_id,
            row_id,
            payload,
            event_type_code=event_type_code,
            event_title=event_title,
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = await self._relation_response_for_model(model, vessel_id, row, label_map)
        response.change_event_id = event_id
        return response

    async def _set_primary_relation_and_respond(
        self,
        model: type[Any],
        vessel_id: int,
        row_id: int,
        payload: Any,
        *,
        event_type_code: str,
        event_title: str,
        operator_id: int | None,
    ) -> Any:
        row, cancelled_ids, event_id = await self._set_primary_relation(
            model,
            vessel_id,
            row_id,
            payload,
            event_type_code=event_type_code,
            event_title=event_title,
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = await self._relation_response_for_model(model, vessel_id, row, label_map)
        response.cancelled_primary_ids = cancelled_ids
        response.change_event_id = event_id
        return response

    async def create_owner(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselOwnerResponse:
        return await self._create_relation_and_respond(
            VesselOwnerPeriod,
            vessel_id,
            payload,
            event_type_code="CREATE_OWNER",
            event_title="新增所有方关系",
            operator_id=operator_id,
        )

    async def update_owner(self, vessel_id: int, owner_id: int, payload, *, operator_id: int | None = None) -> VesselOwnerResponse:
        return await self._mutate_relation_and_respond("update", VesselOwnerPeriod, vessel_id, owner_id, payload, event_type_code="UPDATE_OWNER", event_title="更新所有方关系", operator_id=operator_id)

    async def end_owner(self, vessel_id: int, owner_id: int, payload, *, operator_id: int | None = None) -> VesselOwnerResponse:
        return await self._mutate_relation_and_respond("end", VesselOwnerPeriod, vessel_id, owner_id, payload, event_type_code="END_OWNER", event_title="结束所有方关系", operator_id=operator_id)

    async def void_owner(self, vessel_id: int, owner_id: int, payload, *, operator_id: int | None = None) -> VesselOwnerResponse:
        return await self._mutate_relation_and_respond("void", VesselOwnerPeriod, vessel_id, owner_id, payload, event_type_code="VOID_OWNER", event_title="作废所有方关系", operator_id=operator_id)

    async def set_primary_owner(self, vessel_id: int, owner_id: int, payload, *, operator_id: int | None = None) -> VesselOwnerResponse:
        return await self._set_primary_relation_and_respond(VesselOwnerPeriod, vessel_id, owner_id, payload, event_type_code="SET_PRIMARY_OWNER", event_title="设置主所有方", operator_id=operator_id)

    async def create_operator(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselOperatorResponse:
        async def mark_operating(_: Any) -> None:
            await self.repo.update_profile(vessel_id, {"operation_status_code": "OPERATING"})
            await self.db.commit()

        return await self._create_relation_and_respond(
            VesselOperatorPeriod,
            vessel_id,
            payload,
            event_type_code="CREATE_OPERATOR",
            event_title="新增运营方关系",
            operator_id=operator_id,
            after_create=mark_operating,
        )

    async def update_operator(self, vessel_id: int, operator_period_id: int, payload, *, operator_id: int | None = None) -> VesselOperatorResponse:
        return await self._mutate_relation_and_respond("update", VesselOperatorPeriod, vessel_id, operator_period_id, payload, event_type_code="UPDATE_OPERATOR", event_title="更新运营方关系", operator_id=operator_id)

    async def end_operator(self, vessel_id: int, operator_period_id: int, payload, *, operator_id: int | None = None) -> VesselOperatorResponse:
        return await self._mutate_relation_and_respond("end", VesselOperatorPeriod, vessel_id, operator_period_id, payload, event_type_code="END_OPERATOR", event_title="结束运营方关系", operator_id=operator_id)

    async def void_operator(self, vessel_id: int, operator_period_id: int, payload, *, operator_id: int | None = None) -> VesselOperatorResponse:
        return await self._mutate_relation_and_respond("void", VesselOperatorPeriod, vessel_id, operator_period_id, payload, event_type_code="VOID_OPERATOR", event_title="作废运营方关系", operator_id=operator_id)

    async def set_primary_operator(self, vessel_id: int, operator_period_id: int, payload, *, operator_id: int | None = None) -> VesselOperatorResponse:
        return await self._set_primary_relation_and_respond(VesselOperatorPeriod, vessel_id, operator_period_id, payload, event_type_code="SET_PRIMARY_OPERATOR", event_title="设置主运营方", operator_id=operator_id)

    async def create_contact(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselContactResponse:
        return await self._create_relation_and_respond(VesselContact, vessel_id, payload, event_type_code="CREATE_CONTACT", event_title="新增联系人", operator_id=operator_id)

    async def update_contact(self, vessel_id: int, contact_id: int, payload, *, operator_id: int | None = None) -> VesselContactResponse:
        return await self._mutate_relation_and_respond("update", VesselContact, vessel_id, contact_id, payload, event_type_code="UPDATE_CONTACT", event_title="更新联系人", operator_id=operator_id)

    async def end_contact(self, vessel_id: int, contact_id: int, payload, *, operator_id: int | None = None) -> VesselContactResponse:
        return await self._mutate_relation_and_respond("end", VesselContact, vessel_id, contact_id, payload, event_type_code="END_CONTACT", event_title="结束联系人", operator_id=operator_id)

    async def void_contact(self, vessel_id: int, contact_id: int, payload, *, operator_id: int | None = None) -> VesselContactResponse:
        return await self._mutate_relation_and_respond("void", VesselContact, vessel_id, contact_id, payload, event_type_code="VOID_CONTACT", event_title="作废联系人", operator_id=operator_id)

    async def set_primary_contact(self, vessel_id: int, contact_id: int, payload, *, operator_id: int | None = None) -> VesselContactResponse:
        return await self._set_primary_relation_and_respond(VesselContact, vessel_id, contact_id, payload, event_type_code="SET_PRIMARY_CONTACT", event_title="设置主联系人", operator_id=operator_id)

    async def create_crew(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselCrewResponse:
        return await self._create_relation_and_respond(VesselCrewAssignment, vessel_id, payload, event_type_code="CREATE_CREW", event_title="新增船员任职", operator_id=operator_id, strip_payload_id=True)

    async def update_crew(self, vessel_id: int, crew_id: int, payload, *, operator_id: int | None = None) -> VesselCrewResponse:
        return await self._mutate_relation_and_respond("update", VesselCrewAssignment, vessel_id, crew_id, payload, event_type_code="UPDATE_CREW", event_title="更新船员任职", operator_id=operator_id)

    async def end_crew(self, vessel_id: int, crew_id: int, payload, *, operator_id: int | None = None) -> VesselCrewResponse:
        return await self._mutate_relation_and_respond("end", VesselCrewAssignment, vessel_id, crew_id, payload, event_type_code="END_CREW", event_title="结束船员任职", operator_id=operator_id)

    async def void_crew(self, vessel_id: int, crew_id: int, payload, *, operator_id: int | None = None) -> VesselCrewResponse:
        return await self._mutate_relation_and_respond("void", VesselCrewAssignment, vessel_id, crew_id, payload, event_type_code="VOID_CREW", event_title="作废船员任职", operator_id=operator_id)

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
