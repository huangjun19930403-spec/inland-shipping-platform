"""Implementation methods for the vessel recognition domain."""

from __future__ import annotations

from app.modules.vessel.shared import base as _base

globals().update({name: getattr(_base, name) for name in dir(_base) if not name.startswith("__")})


class VesselRecognitionMixin:
    """Implementation methods for the vessel recognition domain."""

    async def confirm_owner_document_image_recognition(
        self,
        vessel_id: int,
        owner_id: int,
        owner_document_id: int,
        recognition_id: int,
        payload,
        *,
        operator_id: int | None = None,
    ) -> VesselOwnerResponse:
        return await self.adopt_owner_document_recognition(
            vessel_id,
            owner_id,
            owner_document_id,
            recognition_id,
            payload,
            operator_id=operator_id,
        )
        owner = await self.db.get(VesselOwnerPeriod, owner_id)
        if owner is None or owner.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselOwnerPeriod", owner_id)
        document = await self.repo.get_owner_document(owner_document_id)
        if document is None or document.vessel_owner_period_id != owner_id or document.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselOwnerDocument", owner_document_id)
        recognition = await self.repo.get_owner_document_image_recognition(recognition_id)
        if (
            recognition is None
            or recognition.vessel_profile_id != vessel_id
            or recognition.vessel_owner_period_id != owner_id
            or recognition.owner_document_id != owner_document_id
        ):
            raise NotFoundError("VesselOwnerDocumentImageRecognition", recognition_id)
        accepted = self._normalize_recognition_payload(payload.accepted_payload_json or recognition.candidate_payload_json or {})
        updates: dict[str, Any] = {}
        owner_name_conflict: dict[str, Any] | None = None
        if payload.apply_to_owner:
            party_name = accepted.get("holder_name") or accepted.get("company_name") or accepted.get("party_name")
            certificate_no = accepted.get("certificate_no") or accepted.get("document_no") or accepted.get("license_no")
            address = accepted.get("address")
            if party_name:
                recognized_name = str(party_name).strip()
                if recognized_name and recognized_name != owner.party_name:
                    owner_name_conflict = {
                        "current_party_name": owner.party_name,
                        "recognized_party_name": recognized_name,
                        "message": "识别名称与当前所有方不一致，请通过所有方变更流程处理",
                    }
                    accepted["owner_name_conflict"] = owner_name_conflict
            if certificate_no:
                updates["certificate_no"] = str(certificate_no).strip()
            if address:
                updates["address"] = str(address).strip()
            for key, value in updates.items():
                setattr(owner, key, value)
        recognition.status_code = "CONFIRMED"
        recognition.confirmed_payload_json = accepted
        recognition.confirmed_by = operator_id
        recognition.confirmed_at = datetime.utcnow()
        await self._add_change_event(
            vessel_id,
            "CONFIRM_OWNER_DOCUMENT_IMAGE_RECOGNITION",
            "确认所有方证照识别",
            None,
            {"recognition_id": recognition.id, "owner_updates": updates, "owner_name_conflict": owner_name_conflict},
            operator_id,
        )
        await self.db.commit()
        label_map = await _load_label_map(self.db)
        docs = await self._owner_documents_by_owner(vessel_id, label_map)
        return self._owner_response(owner, label_map, documents=docs.get(owner.id, []))

    async def create_person_certificate_image_recognition(
        self,
        vessel_id: int,
        person_certificate_id: int,
        payload,
        *,
        operator_id: int | None = None,
    ) -> VesselPersonCertificateImageRecognitionResponse:
        await self._require_profile(vessel_id)
        cert = await self.repo.get_person_certificate(person_certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselPersonCertificate", person_certificate_id)
        cert_file = await self.repo.get_person_certificate_file_by_storage_file(person_certificate_id, payload.file_id)
        if cert_file is None:
            raise NotFoundError("VesselPersonCertificateFile", payload.file_id)
        if not (cert_file.content_type or "").lower().startswith("image/"):
            raise ValidationError("图片识别助手仅支持图片附件，PDF 可归档预览但不能识别")

        await self.db.commit()
        recognition = await self._create_person_image_recognition_record(
            vessel_id,
            person_certificate_id,
            cert_file.id,
            payload.file_id,
            operator_id=operator_id,
        )
        await self.db.commit()
        await self._dispatch_person_recognition_or_fail(recognition)
        await self.db.refresh(recognition)
        label_map = await _load_label_map(self.db)
        return self._person_image_recognition_response(recognition, label_map)

    async def confirm_person_certificate_image_recognition(
        self,
        vessel_id: int,
        person_certificate_id: int,
        recognition_id: int,
        payload,
        *,
        operator_id: int | None = None,
    ) -> VesselPersonCertificateResponse:
        return await self.adopt_person_certificate_recognition(
            vessel_id,
            person_certificate_id,
            recognition_id,
            payload,
            operator_id=operator_id,
        )
        await self._require_profile(vessel_id)
        cert = await self.repo.get_person_certificate(person_certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselPersonCertificate", person_certificate_id)
        recognition = await self.repo.get_person_image_recognition(recognition_id)
        if (
            recognition is None
            or recognition.vessel_profile_id != vessel_id
            or recognition.vessel_person_certificate_id != person_certificate_id
        ):
            raise NotFoundError("VesselPersonCertificateImageRecognition", recognition_id)
        accepted = self._normalize_recognition_payload(
            payload.accepted_payload_json or recognition.candidate_payload_json or {}
        )
        if not accepted:
            raise ValidationError("没有可确认的识别结果")

        before = _row_dict(cert)
        updates = self._person_certificate_updates_from_recognition(accepted)
        if updates:
            updates["structured_payload_json"] = accepted
            updates["verify_status_code"] = "VERIFIED"
            await self.repo.update_person_certificate(person_certificate_id, updates)
        recognition.status_code = "CONFIRMED"
        recognition.confirmed_payload_json = accepted
        recognition.confirmed_by = operator_id
        recognition.confirmed_at = datetime.utcnow()
        await self._add_change_event(
            vessel_id,
            "CONFIRM_PERSON_CERTIFICATE_IMAGE_RECOGNITION",
            "确认人员证件图片识别结果",
            before,
            {"recognition_id": recognition.id, "certificate_updates": updates},
            operator_id,
        )
        await self.db.flush()
        await self.db.commit()
        return (await self._person_certificates_with_files(vessel_id, person_certificate_id=person_certificate_id))[0]

    async def list_certificate_image_recognitions(
        self,
        vessel_id: int,
        certificate_id: int,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> PageResponse[VesselCertificateImageRecognitionResponse]:
        cert = await self.repo.get_certificate(certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselCertificate", certificate_id)
        page_size = min(max(page_size, 1), 100)
        page = max(page, 1)
        filters = (
            VesselCertificateImageRecognition.vessel_profile_id == vessel_id,
            VesselCertificateImageRecognition.vessel_certificate_id == certificate_id,
        )
        total = int(await self.db.scalar(select(func.count()).select_from(VesselCertificateImageRecognition).where(*filters)) or 0)
        rows = (
            await self.db.execute(
                select(VesselCertificateImageRecognition)
                .where(*filters)
                .order_by(VesselCertificateImageRecognition.created_at.desc(), VesselCertificateImageRecognition.id.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        ).scalars().all()
        label_map = await _load_label_map(self.db)
        return PageResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[self._image_recognition_response(row, label_map) for row in rows],
        )

    async def list_person_certificate_image_recognitions(
        self,
        vessel_id: int,
        person_certificate_id: int,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> PageResponse[VesselPersonCertificateImageRecognitionResponse]:
        cert = await self.repo.get_person_certificate(person_certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselPersonCertificate", person_certificate_id)
        page_size = min(max(page_size, 1), 100)
        page = max(page, 1)
        filters = (
            VesselPersonCertificateImageRecognition.vessel_profile_id == vessel_id,
            VesselPersonCertificateImageRecognition.vessel_person_certificate_id == person_certificate_id,
        )
        total = int(await self.db.scalar(select(func.count()).select_from(VesselPersonCertificateImageRecognition).where(*filters)) or 0)
        rows = (
            await self.db.execute(
                select(VesselPersonCertificateImageRecognition)
                .where(*filters)
                .order_by(VesselPersonCertificateImageRecognition.created_at.desc(), VesselPersonCertificateImageRecognition.id.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        ).scalars().all()
        label_map = await _load_label_map(self.db)
        return PageResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[self._person_image_recognition_response(row, label_map) for row in rows],
        )

    async def list_owner_document_image_recognitions(
        self,
        vessel_id: int,
        owner_id: int,
        owner_document_id: int,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> PageResponse[VesselOwnerDocumentImageRecognitionResponse]:
        owner = await self.db.scalar(
            select(VesselOwnerPeriod).where(VesselOwnerPeriod.id == owner_id)
        )
        if owner is None or owner.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselOwnerPeriod", owner_id)
        document = await self.repo.get_owner_document(owner_document_id)
        if document is None or document.vessel_profile_id != vessel_id or document.vessel_owner_period_id != owner_id:
            raise NotFoundError("VesselOwnerDocument", owner_document_id)
        page_size = min(max(page_size, 1), 100)
        page = max(page, 1)
        filters = (
            VesselOwnerDocumentImageRecognition.vessel_profile_id == vessel_id,
            VesselOwnerDocumentImageRecognition.vessel_owner_period_id == owner_id,
            VesselOwnerDocumentImageRecognition.owner_document_id == owner_document_id,
        )
        total = int(await self.db.scalar(select(func.count()).select_from(VesselOwnerDocumentImageRecognition).where(*filters)) or 0)
        rows = (
            await self.db.execute(
                select(VesselOwnerDocumentImageRecognition)
                .where(*filters)
                .order_by(VesselOwnerDocumentImageRecognition.created_at.desc(), VesselOwnerDocumentImageRecognition.id.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        ).scalars().all()
        label_map = await _load_label_map(self.db)
        return PageResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[self._owner_document_image_recognition_response(row, label_map) for row in rows],
        )

    async def create_certificate_image_recognition(
        self,
        vessel_id: int,
        certificate_id: int,
        payload,
        *,
        operator_id: int | None = None,
    ) -> VesselCertificateImageRecognitionResponse:
        await self._require_profile(vessel_id)
        cert = await self.repo.get_certificate(certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselCertificate", certificate_id)
        cert_file = await self.repo.get_certificate_file_by_storage_file(certificate_id, payload.file_id)
        if cert_file is None:
            raise NotFoundError("VesselCertificateFile", payload.file_id)
        if not (cert_file.content_type or "").lower().startswith("image/"):
            raise ValidationError("图片识别助手仅支持图片附件，PDF 可归档预览但不能识别")

        await self.db.commit()
        recognition = await self._create_certificate_image_recognition_record(
            vessel_id,
            certificate_id,
            cert_file.id,
            payload.file_id,
            operator_id=operator_id,
        )
        await self.db.commit()
        await self._dispatch_certificate_recognition_or_fail(recognition)
        await self.db.refresh(recognition)
        label_map = await _load_label_map(self.db)
        return self._image_recognition_response(recognition, label_map)

    async def confirm_certificate_image_recognition(
        self,
        vessel_id: int,
        certificate_id: int,
        recognition_id: int,
        payload,
        *,
        operator_id: int | None = None,
    ) -> VesselCertificateResponse:
        return await self.adopt_certificate_recognition(
            vessel_id,
            certificate_id,
            recognition_id,
            payload,
            operator_id=operator_id,
        )
        await self._require_profile(vessel_id)
        cert = await self.repo.get_certificate(certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselCertificate", certificate_id)
        recognition = await self.repo.get_image_recognition(recognition_id)
        if (
            recognition is None
            or recognition.vessel_profile_id != vessel_id
            or recognition.vessel_certificate_id != certificate_id
        ):
            raise NotFoundError("VesselCertificateImageRecognition", recognition_id)
        accepted = self._normalize_recognition_payload(payload.accepted_payload_json or recognition.candidate_payload_json or {})
        if not isinstance(accepted, dict) or not accepted:
            raise ValidationError("没有可确认的识别结果")

        before_cert = _row_dict(cert)
        updates = self._certificate_updates_from_recognition(accepted)
        if updates:
            updates["structured_payload_json"] = accepted
            updates["verify_status_code"] = "VERIFIED"
            await self.repo.update_certificate(certificate_id, updates)
        recognition.status_code = "CONFIRMED"
        recognition.confirmed_payload_json = accepted
        recognition.confirmed_by = operator_id
        recognition.confirmed_at = datetime.utcnow()

        profile_updates, capacity_updates = self._adoption_updates_from_recognition(
            accepted,
            payload.adopt_to_profile_fields,
        )
        if profile_updates:
            await self.repo.update_profile(vessel_id, profile_updates)
            if "ship_name" in profile_updates:
                await self.repo.add_name_history(vessel_id, profile_updates["ship_name"], source_type_code="AI_RECOGNITION")
            if "current_mmsi" in profile_updates:
                await self.repo.add_identifier_history(vessel_id, "MMSI", profile_updates["current_mmsi"], source_type_code="AI_RECOGNITION")
        if capacity_updates:
            await self.repo.upsert_one_by_profile(VesselCapacityDimension, vessel_id, capacity_updates)

        await self._add_change_event(
            vessel_id,
            "CONFIRM_CERTIFICATE_IMAGE_RECOGNITION",
            "确认证件图片识别结果",
            before_cert,
            {
                "recognition_id": recognition.id,
                "certificate_updates": updates,
                "profile_updates": profile_updates,
                "capacity_updates": capacity_updates,
            },
            operator_id,
        )
        await self.db.flush()
        await self.db.commit()
        return (await self._certificates_with_files(vessel_id, certificate_id=certificate_id))[0]

    async def _store_owner_document(
        self,
        vessel_id: int,
        owner_id: int,
        file: UploadFile,
        *,
        document_type_code: str,
        operator_id: int | None,
    ) -> VesselOwnerDocument:
        storage_file = await FileStorageService(self.db).upload_file(
            file=file,
            object_prefix=f"vessels/{vessel_id}/owners/{owner_id}",
            uploaded_by=operator_id,
            allowed_content_types={"application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"},
        )
        now = datetime.utcnow()
        row = await self.repo.create_owner_document(
            {
                "vessel_profile_id": vessel_id,
                "vessel_owner_period_id": owner_id,
                "document_type_code": document_type_code or "OTHER",
                "storage_file_id": storage_file.id,
                "file_name": storage_file.original_file_name,
                "content_type": storage_file.content_type,
                "file_size": storage_file.file_size,
                "uploaded_by": operator_id,
                "uploaded_at": now,
                "created_at": now,
            }
        )
        await self._add_change_event(vessel_id, "UPLOAD_OWNER_DOCUMENT", "上传所有方证照", None, _row_dict(row), operator_id)
        return row

    async def _create_owner_document_image_recognition_record(
        self,
        vessel_id: int,
        owner_id: int,
        owner_document_id: int,
        storage_file_id: int,
        *,
        operator_id: int | None,
    ) -> VesselOwnerDocumentImageRecognition:
        return await self.repo.create_owner_document_image_recognition(
            {
                "vessel_profile_id": vessel_id,
                "vessel_owner_period_id": owner_id,
                "owner_document_id": owner_document_id,
                "storage_file_id": storage_file_id,
                "status_code": "QUEUED",
                "created_by": operator_id,
            }
        )

    async def _create_certificate_image_recognition_record(
        self,
        vessel_id: int,
        certificate_id: int,
        certificate_file_id: int,
        storage_file_id: int,
        *,
        operator_id: int | None,
    ) -> VesselCertificateImageRecognition:
        return await self.repo.create_image_recognition(
            {
                "vessel_profile_id": vessel_id,
                "vessel_certificate_id": certificate_id,
                "certificate_file_id": certificate_file_id,
                "storage_file_id": storage_file_id,
                "status_code": "QUEUED",
                "created_by": operator_id,
            }
        )

    async def _create_person_image_recognition_record(
        self,
        vessel_id: int,
        person_certificate_id: int,
        person_certificate_file_id: int,
        storage_file_id: int,
        *,
        operator_id: int | None,
    ) -> VesselPersonCertificateImageRecognition:
        return await self.repo.create_person_image_recognition(
            {
                "vessel_profile_id": vessel_id,
                "vessel_person_certificate_id": person_certificate_id,
                "person_certificate_file_id": person_certificate_file_id,
                "storage_file_id": storage_file_id,
                "status_code": "QUEUED",
                "created_by": operator_id,
            }
        )

    async def _dispatch_owner_document_recognition_or_fail(self, recognition: VesselOwnerDocumentImageRecognition) -> None:
        try:
            _dispatch_owner_document_recognition_task(int(recognition.id))
        except Exception as exc:  # noqa: BLE001
            recognition.status_code = "FAILED"
            recognition.error_message = f"所有方证照图片识别任务投递失败：{exc}"[:512]
            await self._add_change_event(
                int(recognition.vessel_profile_id),
                "IMAGE_RECOGNIZE_OWNER_DOCUMENT_FAILED",
                "所有方证照图片识别任务投递失败",
                None,
                {"recognition_id": recognition.id, "error_message": recognition.error_message},
                recognition.created_by,
            )
            await self.db.commit()

    async def process_certificate_image_recognition(self, recognition_id: int) -> dict[str, Any]:
        recognition = await self.repo.get_image_recognition(recognition_id)
        if recognition is None:
            raise NotFoundError("VesselCertificateImageRecognition", recognition_id)
        try:
            recognition.status_code = "PROCESSING"
            await self.db.flush()
            storage_file, file_result = await FileStorageService(self.db).download_file(recognition.storage_file_id)
            result = await VesselCertificateImageAssistant(self.runtime_config).recognize(
                content=file_result.content,
                content_type=file_result.content_type or storage_file.content_type,
                file_name=storage_file.original_file_name,
                scenario="vessel_certificate",
            )
            recognition.status_code = "NEED_CONFIRM"
            recognition.provider_code = result.provider
            recognition.model_name = result.model
            recognition.candidate_payload_json = self._normalize_recognition_payload(result.candidate_payload)
            recognition.raw_text = result.raw_text
            recognition.raw_response_json = result.raw_response
            recognition.confidence_score = result.confidence_score
            recognition.error_message = None
            await self._add_change_event(
                recognition.vessel_profile_id,
                "IMAGE_RECOGNIZE_CERTIFICATE",
                "识别证件图片",
                None,
                {"recognition_id": recognition.id, "status_code": recognition.status_code},
                recognition.created_by,
            )
        except Exception as exc:  # noqa: BLE001
            recognition.status_code = "FAILED"
            recognition.error_message = str(exc)[:512]
            await self._add_change_event(
                recognition.vessel_profile_id,
                "IMAGE_RECOGNIZE_CERTIFICATE_FAILED",
                "证件图片识别失败",
                None,
                {"recognition_id": recognition.id, "error_message": recognition.error_message},
                recognition.created_by,
            )
        await self.db.commit()
        return {"recognition_id": recognition.id, "status_code": recognition.status_code}

    async def process_person_certificate_image_recognition(self, recognition_id: int) -> dict[str, Any]:
        recognition = await self.repo.get_person_image_recognition(recognition_id)
        if recognition is None:
            raise NotFoundError("VesselPersonCertificateImageRecognition", recognition_id)
        try:
            recognition.status_code = "PROCESSING"
            await self.db.flush()
            storage_file, file_result = await FileStorageService(self.db).download_file(recognition.storage_file_id)
            result = await VesselCertificateImageAssistant(self.runtime_config).recognize(
                content=file_result.content,
                content_type=file_result.content_type or storage_file.content_type,
                file_name=storage_file.original_file_name,
                scenario="crew_competency_certificate",
            )
            recognition.status_code = "NEED_CONFIRM"
            recognition.provider_code = result.provider
            recognition.model_name = result.model
            recognition.candidate_payload_json = self._normalize_recognition_payload(result.candidate_payload)
            recognition.raw_text = result.raw_text
            recognition.raw_response_json = result.raw_response
            recognition.confidence_score = result.confidence_score
            recognition.error_message = None
            await self._add_change_event(
                recognition.vessel_profile_id,
                "IMAGE_RECOGNIZE_PERSON_CERTIFICATE",
                "识别人员证件图片",
                None,
                {"recognition_id": recognition.id, "status_code": recognition.status_code},
                recognition.created_by,
            )
        except Exception as exc:  # noqa: BLE001
            recognition.status_code = "FAILED"
            recognition.error_message = str(exc)[:512]
            await self._add_change_event(
                recognition.vessel_profile_id,
                "IMAGE_RECOGNIZE_PERSON_CERTIFICATE_FAILED",
                "人员证件图片识别失败",
                None,
                {"recognition_id": recognition.id, "error_message": recognition.error_message},
                recognition.created_by,
            )
        await self.db.commit()
        return {"recognition_id": recognition.id, "status_code": recognition.status_code}

    async def process_owner_document_image_recognition(self, recognition_id: int) -> dict[str, Any]:
        recognition = await self.repo.get_owner_document_image_recognition(recognition_id)
        if recognition is None:
            raise NotFoundError("VesselOwnerDocumentImageRecognition", recognition_id)
        try:
            recognition.status_code = "PROCESSING"
            await self.db.flush()
            storage_file, file_result = await FileStorageService(self.db).download_file(recognition.storage_file_id)
            result = await VesselCertificateImageAssistant(self.runtime_config).recognize(
                content=file_result.content,
                content_type=file_result.content_type or storage_file.content_type,
                file_name=storage_file.original_file_name,
                scenario="owner_document",
            )
            recognition.status_code = "NEED_CONFIRM"
            recognition.provider_code = result.provider
            recognition.model_name = result.model
            recognition.candidate_payload_json = self._normalize_recognition_payload(result.candidate_payload)
            recognition.raw_text = result.raw_text
            recognition.raw_response_json = result.raw_response
            recognition.confidence_score = result.confidence_score
            recognition.error_message = None
            await self._add_change_event(
                recognition.vessel_profile_id,
                "IMAGE_RECOGNIZE_OWNER_DOCUMENT",
                "识别所有方证照图片",
                None,
                {"recognition_id": recognition.id, "status_code": recognition.status_code},
                recognition.created_by,
            )
        except Exception as exc:  # noqa: BLE001
            recognition.status_code = "FAILED"
            recognition.error_message = str(exc)[:512]
            await self._add_change_event(
                recognition.vessel_profile_id,
                "IMAGE_RECOGNIZE_OWNER_DOCUMENT_FAILED",
                "所有方证照图片识别失败",
                None,
                {"recognition_id": recognition.id, "error_message": recognition.error_message},
                recognition.created_by,
            )
        await self.db.commit()
        return {"recognition_id": recognition.id, "status_code": recognition.status_code}

    def _normalize_recognition_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        normalized: dict[str, Any] = {key: _jsonable(value) for key, value in payload.items()}
        alias_groups = {
            "certificate_type_code": ["certificate_type_code", "certificate_type", "cert_type_code"],
            "certificate_no": ["certificate_no", "cert_no", "license_no", "document_no", "证件号"],
            "issuing_authority": ["issuing_authority", "issue_authority", "issuer", "发证机关"],
            "holder_name": ["holder_name", "person_name", "crew_name", "name", "姓名"],
            "valid_from": ["valid_from", "valid_start", "validity_start", "start_date", "issue_date", "签发日期"],
            "valid_to": ["valid_to", "valid_end", "validity_end", "expiry_date", "expire_date", "end_date", "有效期至"],
            "validity_text_raw": ["validity_text_raw", "validity_text", "valid_period", "validity", "有效期"],
            "is_long_term_valid": ["is_long_term_valid", "long_term_valid", "permanent", "valid_forever"],
        }
        for target_key, keys in alias_groups.items():
            value = _first_value(payload, keys)
            if value not in (None, "") and normalized.get(target_key) in (None, ""):
                normalized[target_key] = _jsonable(value)

        valid_to_raw = normalized.get("valid_to")
        validity_text = normalized.get("validity_text_raw")
        long_term_raw = normalized.get("is_long_term_valid")
        if _truthy(long_term_raw) or _looks_long_term(valid_to_raw) or _looks_long_term(validity_text):
            normalized["is_long_term_valid"] = True
            normalized["valid_to"] = None
        elif "is_long_term_valid" in normalized:
            normalized["is_long_term_valid"] = _truthy(normalized.get("is_long_term_valid"))
        return normalized

    def _adoption_updates_from_recognition(
        self,
        payload: dict[str, Any],
        fields: list[str],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        requested = {str(field).strip() for field in fields if str(field).strip()}
        profile_updates: dict[str, Any] = {}
        capacity_updates: dict[str, Any] = {}
        profile_field_map = {
            "ship_name": "ship_name",
            "mmsi": "current_mmsi",
            "ship_type_code": "ship_type_code",
        }
        capacity_field_map = {
            "deadweight_ton": "deadweight_ton",
            "total_tonnage": "total_tonnage",
            "net_tonnage": "net_tonnage",
            "length_m": "length_m",
            "width_m": "width_m",
            "depth_m": "depth_m",
            "design_draft_m": "design_draft_m",
        }
        for source_key, target_key in profile_field_map.items():
            if target_key in requested and payload.get(source_key) not in (None, ""):
                profile_updates[target_key] = payload[source_key]
        for source_key, target_key in capacity_field_map.items():
            if target_key in requested:
                value = _to_decimal(payload.get(source_key))
                if value is not None:
                    capacity_updates[target_key] = value
        return profile_updates, capacity_updates

    def _text_value(self, value: Any) -> str | None:
        if value in (None, ""):
            return None
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, (dict, list)):
            return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True)
        return str(value)

    async def _persist_recognition_diffs(
        self,
        *,
        vessel_id: int,
        recognition_object_type: str,
        recognition_id: int,
        target_object_type: str,
        target_object_id: int,
        diffs: dict[str, tuple[Any, Any]],
        confidence_score: int | None,
        evidence_text: str | None,
    ) -> list[VesselRecognitionFieldDiff]:
        await self.db.execute(
            delete(VesselRecognitionFieldDiff).where(
                VesselRecognitionFieldDiff.recognition_object_type == recognition_object_type,
                VesselRecognitionFieldDiff.recognition_id == recognition_id,
                VesselRecognitionFieldDiff.target_object_type == target_object_type,
                VesselRecognitionFieldDiff.target_object_id == target_object_id,
                VesselRecognitionFieldDiff.adopt_status_code == "REVIEW_REQUIRED",
            )
        )
        now = datetime.utcnow()
        rows: list[VesselRecognitionFieldDiff] = []
        for field_name, (current, recognized) in diffs.items():
            if recognized in (None, ""):
                continue
            if _normalized_text(current) == _normalized_text(recognized):
                continue
            row = VesselRecognitionFieldDiff(
                vessel_profile_id=vessel_id,
                recognition_object_type=recognition_object_type,
                recognition_id=recognition_id,
                target_object_type=target_object_type,
                target_object_id=target_object_id,
                field_name=field_name,
                current_value_text=self._text_value(current),
                recognized_value_text=self._text_value(recognized),
                confidence_score=confidence_score,
                evidence_text=evidence_text,
                adopt_status_code="REVIEW_REQUIRED",
                created_at=now,
                updated_at=now,
            )
            self.db.add(row)
            rows.append(row)
        await self.db.flush()
        return rows

    async def _recognition_review_diff_rows(self, recognition_object_type: str, recognition_id: int) -> list[VesselRecognitionFieldDiff]:
        return list(
            (
                await self.db.execute(
                    select(VesselRecognitionFieldDiff).where(
                        VesselRecognitionFieldDiff.recognition_object_type == recognition_object_type,
                        VesselRecognitionFieldDiff.recognition_id == recognition_id,
                        VesselRecognitionFieldDiff.adopt_status_code == "REVIEW_REQUIRED",
                    )
                )
            )
            .scalars()
            .all()
        )

    def _validate_ocr_adoption_selection(
        self,
        diff_rows: list[VesselRecognitionFieldDiff],
        selected_fields: set[str],
        reason: str | None,
    ) -> set[str]:
        if not diff_rows or not selected_fields:
            raise ConflictError(
                "OCR 字段差异尚未确认，请先获取 field-diff 并选择采纳字段",
                code="OCR_DIFF_REQUIRED",
            )
        diff_field_names = {row.field_name for row in diff_rows}
        applicable_fields = selected_fields & diff_field_names
        if not applicable_fields:
            raise ConflictError(
                "提交的采纳字段不在当前 OCR diff 中",
                code="OCR_DIFF_REQUIRED",
                detail={"diff_fields": sorted(diff_field_names), "selected_fields": sorted(selected_fields)},
            )
        low_confidence_fields = sorted(
            row.field_name
            for row in diff_rows
            if row.field_name in applicable_fields
            and row.confidence_score is not None
            and row.confidence_score < LOW_CONFIDENCE_SCORE_THRESHOLD
        )
        if low_confidence_fields and not reason:
            raise ValidationError(
                "低置信字段需要人工确认原因",
                code="LOW_CONFIDENCE_CONFIRM_REQUIRED",
                detail={"fields": low_confidence_fields, "threshold": LOW_CONFIDENCE_SCORE_THRESHOLD},
            )
        return applicable_fields

    async def _owner_document_recognition_diff_rows(
        self,
        vessel_id: int,
        owner: VesselOwnerPeriod,
        recognition: VesselOwnerDocumentImageRecognition,
        accepted: dict[str, Any],
    ) -> list[VesselRecognitionFieldDiff]:
        party_name = accepted.get("holder_name") or accepted.get("company_name") or accepted.get("party_name")
        diffs = {
            "party_name": (owner.party_name, party_name),
            "certificate_no": (owner.certificate_no, accepted.get("certificate_no") or accepted.get("document_no") or accepted.get("license_no")),
            "address": (owner.address, accepted.get("address")),
        }
        return await self._persist_recognition_diffs(
            vessel_id=vessel_id,
            recognition_object_type="OWNER_DOCUMENT_IMAGE_RECOGNITION",
            recognition_id=recognition.id,
            target_object_type="vessel_owner_period",
            target_object_id=owner.id,
            diffs=diffs,
            confidence_score=recognition.confidence_score,
            evidence_text=recognition.raw_text,
        )

    async def certificate_recognition_field_diff(
        self,
        vessel_id: int,
        certificate_id: int,
        recognition_id: int,
    ) -> list[VesselRecognitionFieldDiffResponse]:
        cert = await self.repo.get_certificate(certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselCertificate", certificate_id)
        recognition = await self.repo.get_image_recognition(recognition_id)
        if (
            recognition is None
            or recognition.vessel_profile_id != vessel_id
            or recognition.vessel_certificate_id != certificate_id
        ):
            raise NotFoundError("VesselCertificateImageRecognition", recognition_id)
        accepted = self._normalize_recognition_payload(recognition.candidate_payload_json or {})
        rows = await self._certificate_recognition_diff_rows(vessel_id, cert, recognition, accepted)
        return [VesselRecognitionFieldDiffResponse(**_row_dict(row)) for row in rows]

    async def adopt_certificate_recognition(
        self,
        vessel_id: int,
        certificate_id: int,
        recognition_id: int,
        payload,
        *,
        operator_id: int | None = None,
    ) -> VesselCertificateResponse:
        await self._require_profile(vessel_id)
        cert = await self.repo.get_certificate(certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselCertificate", certificate_id)
        recognition = await self.repo.get_image_recognition(recognition_id)
        if (
            recognition is None
            or recognition.vessel_profile_id != vessel_id
            or recognition.vessel_certificate_id != certificate_id
        ):
            raise NotFoundError("VesselCertificateImageRecognition", recognition_id)
        accepted = self._normalize_recognition_payload(payload.accepted_payload_json or recognition.candidate_payload_json or {})
        if not accepted:
            raise ValidationError("没有可确认的识别结果")
        diff_rows = await self._certificate_recognition_diff_rows(vessel_id, cert, recognition, accepted)
        before_cert = _row_dict(cert)
        requested_fields = set(getattr(payload, "adopt_fields", None) or [])
        requested_profile_fields = set(getattr(payload, "adopt_to_profile_fields", None) or [])
        applicable_fields = self._validate_ocr_adoption_selection(
            diff_rows,
            requested_fields | requested_profile_fields,
            getattr(payload, "reason", None),
        )
        updates = self._certificate_updates_from_recognition(accepted)
        updates = {key: value for key, value in updates.items() if key in requested_fields and key in applicable_fields}
        adopted_fields = sorted(updates)
        profile_updates, capacity_updates = self._adoption_updates_from_recognition(
            accepted,
            sorted(requested_profile_fields & applicable_fields),
        )
        if "current_mmsi" in profile_updates:
            profile = await self._require_profile(vessel_id)
            if profile.profile_status_code == ACTIVE_PROFILE_STATUS and profile_updates["current_mmsi"] != profile.current_mmsi:
                await self._assert_active_mmsi_available(
                    profile_updates["current_mmsi"],
                    exclude_vessel_id=vessel_id,
                    attempted_profile_id=vessel_id,
                    evidence_source="OCR_ADOPTION",
                )
        if updates:
            updates["structured_payload_json"] = accepted
            updates["verify_status_code"] = "VERIFIED"
            await self.repo.update_certificate(certificate_id, updates)
        if profile_updates:
            old_profile = await self._require_profile(vessel_id)
            await self.repo.update_profile(vessel_id, profile_updates)
            if "ship_name" in profile_updates:
                await self.repo.add_name_history(vessel_id, profile_updates["ship_name"], source_type_code="AI_RECOGNITION")
            if "current_mmsi" in profile_updates:
                await self._close_current_mmsi_history(vessel_id, old_profile.current_mmsi)
                await self.repo.add_identifier_history(vessel_id, "MMSI", profile_updates["current_mmsi"], source_type_code="AI_RECOGNITION")
            adopted_fields.extend(sorted(profile_updates))
        if capacity_updates:
            await self.repo.upsert_one_by_profile(VesselCapacityDimension, vessel_id, capacity_updates)
            adopted_fields.extend(sorted(capacity_updates))
        recognition.status_code = "CONFIRMED"
        recognition.confirmed_payload_json = accepted
        recognition.confirmed_by = operator_id
        recognition.confirmed_at = datetime.utcnow()
        event_id = await self._add_change_event(
            vessel_id,
            "ADOPT_CERTIFICATE_IMAGE_RECOGNITION",
            "采纳船舶证书识别结果",
            before_cert,
            {"recognition_id": recognition.id, "certificate_updates": updates, "profile_updates": profile_updates, "capacity_updates": capacity_updates},
            operator_id,
            object_type="vessel_certificate",
            object_id=certificate_id,
            reason=getattr(payload, "reason", None),
        )
        self.db.add(
            VesselRecognitionAdoptionRecord(
                vessel_profile_id=vessel_id,
                recognition_object_type="VESSEL_CERTIFICATE_IMAGE_RECOGNITION",
                recognition_id=recognition_id,
                target_object_type="vessel_certificate",
                target_object_id=certificate_id,
                adopted_fields_json=sorted(set(adopted_fields)),
                skipped_fields_json=sorted({row.field_name for row in diff_rows} - set(adopted_fields)),
                confirmed_by=operator_id,
                confirmed_at=datetime.utcnow(),
                reason=getattr(payload, "reason", None),
                change_event_id=event_id,
                created_at=datetime.utcnow(),
            )
        )
        adopted_set = set(adopted_fields)
        for diff in diff_rows:
            diff.adopt_status_code = "ADOPTED" if diff.field_name in adopted_set else "SKIPPED"
            diff.updated_at = datetime.utcnow()
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self._refresh_summary_best_effort(vessel_id)
        return (await self._certificates_with_files(vessel_id, certificate_id=certificate_id))[0]

    async def person_certificate_recognition_field_diff(
        self,
        vessel_id: int,
        person_certificate_id: int,
        recognition_id: int,
    ) -> list[VesselRecognitionFieldDiffResponse]:
        cert = await self.repo.get_person_certificate(person_certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselPersonCertificate", person_certificate_id)
        recognition = await self.repo.get_person_image_recognition(recognition_id)
        if (
            recognition is None
            or recognition.vessel_profile_id != vessel_id
            or recognition.vessel_person_certificate_id != person_certificate_id
        ):
            raise NotFoundError("VesselPersonCertificateImageRecognition", recognition_id)
        accepted = self._normalize_recognition_payload(recognition.candidate_payload_json or {})
        rows = await self._person_certificate_recognition_diff_rows(vessel_id, cert, recognition, accepted)
        return [VesselRecognitionFieldDiffResponse(**_row_dict(row)) for row in rows]

    async def adopt_person_certificate_recognition(
        self,
        vessel_id: int,
        person_certificate_id: int,
        recognition_id: int,
        payload,
        *,
        operator_id: int | None = None,
    ) -> VesselPersonCertificateResponse:
        cert = await self.repo.get_person_certificate(person_certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselPersonCertificate", person_certificate_id)
        recognition = await self.repo.get_person_image_recognition(recognition_id)
        if (
            recognition is None
            or recognition.vessel_profile_id != vessel_id
            or recognition.vessel_person_certificate_id != person_certificate_id
        ):
            raise NotFoundError("VesselPersonCertificateImageRecognition", recognition_id)
        accepted = self._normalize_recognition_payload(payload.accepted_payload_json or recognition.candidate_payload_json or {})
        if not accepted:
            raise ValidationError("没有可确认的识别结果")
        diff_rows = await self._person_certificate_recognition_diff_rows(vessel_id, cert, recognition, accepted)
        before = _row_dict(cert)
        requested_fields = set(getattr(payload, "adopt_fields", None) or [])
        applicable_fields = self._validate_ocr_adoption_selection(diff_rows, requested_fields, getattr(payload, "reason", None))
        updates = self._person_certificate_updates_from_recognition(accepted)
        updates = {key: value for key, value in updates.items() if key in requested_fields and key in applicable_fields}
        if updates:
            updates["structured_payload_json"] = accepted
            updates["verify_status_code"] = "VERIFIED"
            updates["source_type_code"] = "AI_RECOGNITION"
            updates["source_trace_id"] = f"PERSON_CERTIFICATE_IMAGE_RECOGNITION:{recognition_id}"
            updates["revision"] = int(cert.revision or 1) + 1
            await self.repo.update_person_certificate(person_certificate_id, updates)
        recognition.status_code = "CONFIRMED"
        recognition.confirmed_payload_json = accepted
        recognition.confirmed_by = operator_id
        recognition.confirmed_at = datetime.utcnow()
        adopted_fields = sorted(updates)
        event_id = await self._add_change_event(
            vessel_id,
            "ADOPT_PERSON_CERTIFICATE_IMAGE_RECOGNITION",
            "采纳人员证件图片识别结果",
            before,
            {"recognition_id": recognition.id, "certificate_updates": updates},
            operator_id,
            object_type="vessel_person_certificate",
            object_id=person_certificate_id,
            reason=getattr(payload, "reason", None),
        )
        self.db.add(
            VesselRecognitionAdoptionRecord(
                vessel_profile_id=vessel_id,
                recognition_object_type="PERSON_CERTIFICATE_IMAGE_RECOGNITION",
                recognition_id=recognition_id,
                target_object_type="vessel_person_certificate",
                target_object_id=person_certificate_id,
                adopted_fields_json=adopted_fields,
                skipped_fields_json=sorted({row.field_name for row in diff_rows} - set(adopted_fields)),
                confirmed_by=operator_id,
                confirmed_at=datetime.utcnow(),
                reason=getattr(payload, "reason", None),
                change_event_id=event_id,
                created_at=datetime.utcnow(),
            )
        )
        adopted_set = set(adopted_fields)
        for diff in diff_rows:
            diff.adopt_status_code = "ADOPTED" if diff.field_name in adopted_set else "SKIPPED"
            diff.updated_at = datetime.utcnow()
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self._refresh_summary_best_effort(vessel_id)
        return (await self._person_certificates_with_files(vessel_id, person_certificate_id=person_certificate_id))[0]

    async def owner_document_recognition_field_diff(
        self,
        vessel_id: int,
        owner_id: int,
        owner_document_id: int,
        recognition_id: int,
    ) -> list[VesselRecognitionFieldDiffResponse]:
        owner = await self.db.get(VesselOwnerPeriod, owner_id)
        if owner is None or owner.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselOwnerPeriod", owner_id)
        recognition = await self.repo.get_owner_document_image_recognition(recognition_id)
        if (
            recognition is None
            or recognition.vessel_profile_id != vessel_id
            or recognition.vessel_owner_period_id != owner_id
            or recognition.owner_document_id != owner_document_id
        ):
            raise NotFoundError("VesselOwnerDocumentImageRecognition", recognition_id)
        accepted = self._normalize_recognition_payload(recognition.candidate_payload_json or {})
        rows = await self._owner_document_recognition_diff_rows(vessel_id, owner, recognition, accepted)
        return [VesselRecognitionFieldDiffResponse(**_row_dict(row)) for row in rows]

    async def adopt_owner_document_recognition(
        self,
        vessel_id: int,
        owner_id: int,
        owner_document_id: int,
        recognition_id: int,
        payload,
        *,
        operator_id: int | None = None,
    ) -> VesselOwnerResponse:
        owner = await self.db.get(VesselOwnerPeriod, owner_id)
        if owner is None or owner.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselOwnerPeriod", owner_id)
        document = await self.repo.get_owner_document(owner_document_id)
        if document is None or document.vessel_owner_period_id != owner_id or document.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselOwnerDocument", owner_document_id)
        recognition = await self.repo.get_owner_document_image_recognition(recognition_id)
        if (
            recognition is None
            or recognition.vessel_profile_id != vessel_id
            or recognition.vessel_owner_period_id != owner_id
            or recognition.owner_document_id != owner_document_id
        ):
            raise NotFoundError("VesselOwnerDocumentImageRecognition", recognition_id)
        accepted = self._normalize_recognition_payload(payload.accepted_payload_json or recognition.candidate_payload_json or {})
        if not accepted:
            raise ValidationError("没有可确认的识别结果")
        diff_rows = await self._owner_document_recognition_diff_rows(vessel_id, owner, recognition, accepted)
        before = _row_dict(owner)
        updates: dict[str, Any] = {}
        skipped_fields: list[str] = []
        requested_fields = set(getattr(payload, "adopt_fields", None) or []) & OWNER_DOCUMENT_ADOPTABLE_FIELDS
        applicable_fields = self._validate_ocr_adoption_selection(diff_rows, requested_fields, getattr(payload, "reason", None))
        if getattr(payload, "apply_to_owner", True):
            party_name = accepted.get("holder_name") or accepted.get("company_name") or accepted.get("party_name")
            if party_name and _normalized_text(party_name) != _normalized_text(owner.party_name):
                skipped_fields.append("party_name")
                await self._upsert_quality_issue(
                    issue_type_code="OCR_UNCONFIRMED",
                    profile_id=vessel_id,
                    object_type="recognition",
                    object_id=recognition_id,
                    field_name="party_name",
                    normalized_key=f"recognition|{recognition_id}",
                    evidence_source="OWNER_DOCUMENT_OCR",
                    impact_scope=[{"owner_id": owner_id, "current_party_name": owner.party_name, "recognized_party_name": str(party_name)}],
                )
            for field_name, value in {
                "certificate_no": accepted.get("certificate_no") or accepted.get("document_no") or accepted.get("license_no"),
                "address": accepted.get("address"),
            }.items():
                if value in (None, ""):
                    continue
                if field_name not in requested_fields or field_name not in applicable_fields:
                    skipped_fields.append(field_name)
                    continue
                updates[field_name] = str(value).strip()
        if updates:
            for key, value in updates.items():
                setattr(owner, key, value)
            owner.source_type_code = "AI_RECOGNITION"
            owner.source_trace_id = f"OWNER_DOCUMENT_IMAGE_RECOGNITION:{recognition_id}"
            owner.revision = int(owner.revision or 1) + 1
        skipped_fields = sorted({row.field_name for row in diff_rows} - set(updates))
        recognition.status_code = "CONFIRMED"
        recognition.confirmed_payload_json = {**accepted, "skipped_fields": skipped_fields}
        recognition.confirmed_by = operator_id
        recognition.confirmed_at = datetime.utcnow()
        event_id = await self._add_change_event(
            vessel_id,
            "ADOPT_OWNER_DOCUMENT_IMAGE_RECOGNITION",
            "采纳所有方证照识别结果",
            before,
            {"recognition_id": recognition.id, "owner_updates": updates, "skipped_fields": skipped_fields},
            operator_id,
            object_type="vessel_owner_period",
            object_id=owner_id,
            reason=getattr(payload, "reason", None),
        )
        self.db.add(
            VesselRecognitionAdoptionRecord(
                vessel_profile_id=vessel_id,
                recognition_object_type="OWNER_DOCUMENT_IMAGE_RECOGNITION",
                recognition_id=recognition_id,
                target_object_type="vessel_owner_period",
                target_object_id=owner_id,
                adopted_fields_json=sorted(updates),
                skipped_fields_json=skipped_fields,
                confirmed_by=operator_id,
                confirmed_at=datetime.utcnow(),
                reason=getattr(payload, "reason", None),
                change_event_id=event_id,
                created_at=datetime.utcnow(),
            )
        )
        adopted_set = set(updates)
        for diff in diff_rows:
            if diff.field_name in adopted_set:
                diff.adopt_status_code = "ADOPTED"
            else:
                diff.adopt_status_code = "SKIPPED"
            diff.updated_at = datetime.utcnow()
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self._refresh_summary_best_effort(vessel_id)
        label_map = await _load_label_map(self.db)
        docs = await self._owner_documents_by_owner(vessel_id, label_map)
        response = self._owner_response(owner, label_map, documents=docs.get(owner.id, []))
        response.change_event_id = event_id
        return response

    async def _latest_owner_document_recognition(self, owner_document_id: int) -> VesselOwnerDocumentImageRecognition | None:
        return await self.db.scalar(
            select(VesselOwnerDocumentImageRecognition)
            .where(VesselOwnerDocumentImageRecognition.owner_document_id == owner_document_id)
            .order_by(VesselOwnerDocumentImageRecognition.created_at.desc(), VesselOwnerDocumentImageRecognition.id.desc())
        )

    def _owner_document_image_recognition_response(
        self,
        row: VesselOwnerDocumentImageRecognition,
        label_map: dict[str, dict[str, str]],
    ) -> VesselOwnerDocumentImageRecognitionResponse:
        return VesselOwnerDocumentImageRecognitionResponse(
            **_row_dict(row),
            status_name=label_map.get("VESSEL_CERTIFICATE_IMAGE_RECOGNITION_STATUS", {}).get(row.status_code),
        )

    async def list_recognition_queue(self, query: Any) -> PageResponse[VesselRecognitionQueueItemResponse]:
        rows: list[tuple[str, Any]] = []
        type_models = [
            ("certificate", VesselCertificateImageRecognition),
            ("person-certificate", VesselPersonCertificateImageRecognition),
            ("owner-document", VesselOwnerDocumentImageRecognition),
        ]
        for recognition_type, model in type_models:
            if getattr(query, "recognition_type", None) and query.recognition_type != recognition_type:
                continue
            stmt = select(model)
            if getattr(query, "status_code", None):
                stmt = stmt.where(model.status_code == query.status_code)
            if getattr(query, "vessel_id", None):
                stmt = stmt.where(model.vessel_profile_id == query.vessel_id)
            if getattr(query, "low_confidence", None) is True:
                stmt = stmt.where(model.confidence_score.is_not(None), model.confidence_score < LOW_CONFIDENCE_SCORE_THRESHOLD)
            elif getattr(query, "low_confidence", None) is False:
                stmt = stmt.where(or_(model.confidence_score.is_(None), model.confidence_score >= LOW_CONFIDENCE_SCORE_THRESHOLD))
            rows.extend((recognition_type, row) for row in (await self.db.scalars(stmt)).all())
        profiles = await self._profiles_by_ids([row.vessel_profile_id for _, row in rows])
        if getattr(query, "keyword", None):
            text = query.keyword.strip().lower()
            rows = [
                (recognition_type, row)
                for recognition_type, row in rows
                if text in recognition_type
                or text in str(row.id)
                or text in (profiles.get(row.vessel_profile_id).ship_name.lower() if profiles.get(row.vessel_profile_id) else "")
                or text in (profiles.get(row.vessel_profile_id).current_mmsi if profiles.get(row.vessel_profile_id) else "")
            ]
        rows.sort(key=lambda item: (item[1].updated_at, item[1].id), reverse=True)
        total = len(rows)
        paged = rows[(query.page - 1) * query.page_size : query.page * query.page_size]
        label_map = await _load_label_map(self.db)
        items = [await self._recognition_queue_item(recognition_type, row, profiles.get(row.vessel_profile_id), label_map) for recognition_type, row in paged]
        return PageResponse(total=total, page=query.page, page_size=query.page_size, items=items)

    async def unified_recognition_field_diff(self, recognition_type: str, recognition_id: int) -> list[VesselRecognitionFieldDiffResponse]:
        if recognition_type == "certificate":
            row = await self.repo.get_image_recognition(recognition_id)
            if row is None:
                raise NotFoundError("VesselCertificateImageRecognition", recognition_id)
            return await self.certificate_recognition_field_diff(row.vessel_profile_id, row.vessel_certificate_id, recognition_id)
        if recognition_type == "person-certificate":
            row = await self.repo.get_person_image_recognition(recognition_id)
            if row is None:
                raise NotFoundError("VesselPersonCertificateImageRecognition", recognition_id)
            return await self.person_certificate_recognition_field_diff(row.vessel_profile_id, row.vessel_person_certificate_id, recognition_id)
        if recognition_type == "owner-document":
            row = await self.repo.get_owner_document_image_recognition(recognition_id)
            if row is None:
                raise NotFoundError("VesselOwnerDocumentImageRecognition", recognition_id)
            return await self.owner_document_recognition_field_diff(row.vessel_profile_id, row.vessel_owner_period_id, row.owner_document_id, recognition_id)
        raise ValidationError("unsupported recognition_type")

    async def unified_recognition_adoption(self, recognition_type: str, recognition_id: int, payload: Any, *, operator_id: int | None = None) -> Any:
        if recognition_type == "certificate":
            row = await self.repo.get_image_recognition(recognition_id)
            if row is None:
                raise NotFoundError("VesselCertificateImageRecognition", recognition_id)
            return await self.adopt_certificate_recognition(row.vessel_profile_id, row.vessel_certificate_id, recognition_id, payload, operator_id=operator_id)
        if recognition_type == "person-certificate":
            row = await self.repo.get_person_image_recognition(recognition_id)
            if row is None:
                raise NotFoundError("VesselPersonCertificateImageRecognition", recognition_id)
            return await self.adopt_person_certificate_recognition(row.vessel_profile_id, row.vessel_person_certificate_id, recognition_id, payload, operator_id=operator_id)
        if recognition_type == "owner-document":
            row = await self.repo.get_owner_document_image_recognition(recognition_id)
            if row is None:
                raise NotFoundError("VesselOwnerDocumentImageRecognition", recognition_id)
            return await self.adopt_owner_document_recognition(row.vessel_profile_id, row.vessel_owner_period_id, row.owner_document_id, recognition_id, payload, operator_id=operator_id)
        raise ValidationError("unsupported recognition_type")

    async def _recognition_queue_item(
        self,
        recognition_type: str,
        row: Any,
        profile: VesselProfile | None,
        label_map: dict[str, dict[str, str]],
    ) -> VesselRecognitionQueueItemResponse:
        object_type = {
            "certificate": "VESSEL_CERTIFICATE_IMAGE_RECOGNITION",
            "person-certificate": "PERSON_CERTIFICATE_IMAGE_RECOGNITION",
            "owner-document": "OWNER_DOCUMENT_IMAGE_RECOGNITION",
        }[recognition_type]
        target_object_type = {
            "certificate": "vessel_certificate",
            "person-certificate": "vessel_person_certificate",
            "owner-document": "vessel_owner_period",
        }[recognition_type]
        target_id = getattr(row, "vessel_certificate_id", None) or getattr(row, "vessel_person_certificate_id", None) or getattr(row, "vessel_owner_period_id", None)
        pending_diff_count = int(
            await self.db.scalar(
                select(func.count(VesselRecognitionFieldDiff.id)).where(
                    VesselRecognitionFieldDiff.recognition_object_type == object_type,
                    VesselRecognitionFieldDiff.recognition_id == row.id,
                    VesselRecognitionFieldDiff.adopt_status_code == "REVIEW_REQUIRED",
                )
            )
            or 0
        )
        low_diff_count = int(
            await self.db.scalar(
                select(func.count(VesselRecognitionFieldDiff.id)).where(
                    VesselRecognitionFieldDiff.recognition_object_type == object_type,
                    VesselRecognitionFieldDiff.recognition_id == row.id,
                    VesselRecognitionFieldDiff.confidence_score.is_not(None),
                    VesselRecognitionFieldDiff.confidence_score < LOW_CONFIDENCE_SCORE_THRESHOLD,
                )
            )
            or 0
        )
        adoption_count = int(
            await self.db.scalar(
                select(func.count(VesselRecognitionAdoptionRecord.id)).where(
                    VesselRecognitionAdoptionRecord.recognition_object_type == object_type,
                    VesselRecognitionAdoptionRecord.recognition_id == row.id,
                )
            )
            or 0
        )
        return VesselRecognitionQueueItemResponse(
            id=f"{recognition_type}:{row.id}",
            recognition_type=recognition_type,
            recognition_object_type=object_type,
            recognition_id=row.id,
            vessel_profile_id=row.vessel_profile_id,
            vessel=self._vessel_signal_summary(profile, label_map),
            target_object_type=target_object_type,
            target_object_id=int(target_id or 0),
            status_code=row.status_code,
            status_name=label_map.get("VESSEL_CERTIFICATE_IMAGE_RECOGNITION_STATUS", {}).get(row.status_code),
            confidence_score=row.confidence_score,
            low_confidence=bool(row.confidence_score is not None and row.confidence_score < LOW_CONFIDENCE_SCORE_THRESHOLD),
            pending_diff_count=pending_diff_count,
            low_confidence_diff_count=low_diff_count,
            adoption_count=adoption_count,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
