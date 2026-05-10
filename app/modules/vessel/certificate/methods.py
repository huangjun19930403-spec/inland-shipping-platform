"""Implementation methods for the vessel certificate domain."""

from __future__ import annotations

from app.modules.vessel.shared import base as _base

globals().update({name: getattr(_base, name) for name in dir(_base) if not name.startswith("__")})


class VesselCertificateMixin:
    """Implementation methods for the vessel certificate domain."""

    async def list_person_certificates(self, vessel_id: int) -> list[VesselPersonCertificateResponse]:
        await self._require_profile(vessel_id)
        return await self._person_certificates_with_files(vessel_id)

    async def _assert_replace_initialization_allowed(self, model: type[Any], vessel_id: int, resource_name: str) -> None:
        existing = await self.db.scalar(select(model.id).where(model.vessel_profile_id == vessel_id).limit(1))  # type: ignore[attr-defined]
        if existing is not None:
            raise ConflictError(
                f"{resource_name} 整组覆盖接口已废弃：仅允许空数据初始化，已有数据请使用增量新增/修改/结束/作废接口",
                code="REPLACE_API_DEPRECATED_UNSAFE",
                detail={"resource": resource_name},
            )

    def _raise_replace_gone(self, resource_name: str) -> None:
        raise AppException(
            status_code=410,
            code="REPLACE_API_GONE",
            message=f"{resource_name} 整组覆盖接口已退出 Round 2；请使用增量新增、修改、结束或作废接口",
            detail={"resource": resource_name},
        )

    async def replace_person_certificates(self, vessel_id: int, payload, *, operator_id: int | None = None) -> list[VesselPersonCertificateResponse]:
        await self._require_profile(vessel_id)
        _ = payload, operator_id
        raise AppException(
            status_code=410,
            code="REPLACE_API_GONE",
            message="人员适任证已纳入证书资产改造，不支持整组替换；请逐本新增、更新、补附件或作废",
        )

    async def create_person_certificate(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselPersonCertificateResponse:
        await self._require_profile(vessel_id)
        data = payload.model_dump(exclude_none=True)
        data.pop("revision", None)
        crew = await self._require_crew_assignment(vessel_id, data.get("crew_assignment_id"))
        data["crew_assignment_id"] = crew.id
        data["holder_name"] = data.get("holder_name") or crew.crew_name
        data["certificate_type_code"] = CREW_CERTIFICATE_TYPE
        data.setdefault("verify_status_code", "PENDING")
        data.setdefault("revision", 1)
        data.setdefault("source_type_code", "MANUAL")
        row = await self.repo.create_person_certificate(vessel_id, data)
        event_id = await self._add_change_event(
            vessel_id,
            "CREATE_PERSON_CERTIFICATE",
            "新增人员证件",
            None,
            _row_dict(row),
            operator_id,
            object_type="vessel_person_certificate",
            object_id=row.id,
        )
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        response = (await self._person_certificates_with_files(vessel_id, person_certificate_id=row.id))[0]
        response.change_event_id = event_id
        return response

    async def update_person_certificate(
        self,
        vessel_id: int,
        person_certificate_id: int,
        payload,
        *,
        operator_id: int | None = None,
    ) -> VesselPersonCertificateResponse:
        cert = await self.repo.get_person_certificate(person_certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselPersonCertificate", person_certificate_id)
        before = _row_dict(cert)
        updates = payload.model_dump(exclude_none=True)
        revision = updates.pop("revision", None)
        self._ensure_revision(cert, revision)
        if not updates:
            raise ValidationError("no update fields provided")
        if "crew_assignment_id" in updates:
            crew = await self._require_crew_assignment(vessel_id, updates["crew_assignment_id"])
            updates["holder_name"] = updates.get("holder_name") or crew.crew_name
        elif cert.crew_assignment_id is None:
            raise ValidationError("人员适任证必须绑定当前船员任职")
        if "certificate_type_code" in updates:
            updates["certificate_type_code"] = CREW_CERTIFICATE_TYPE
        updates["revision"] = int(cert.revision or 1) + 1
        row = await self.repo.update_person_certificate(person_certificate_id, updates)
        assert row is not None
        event_id = await self._add_change_event(
            vessel_id,
            "UPDATE_PERSON_CERTIFICATE",
            "更新人员证件",
            before,
            _row_dict(row),
            operator_id,
            object_type="vessel_person_certificate",
            object_id=row.id,
        )
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        response = (await self._person_certificates_with_files(vessel_id, person_certificate_id=row.id))[0]
        response.change_event_id = event_id
        return response

    async def void_person_certificate(
        self,
        vessel_id: int,
        person_certificate_id: int,
        *,
        reason: str | None = None,
        revision: int | None = None,
        operator_id: int | None = None,
    ) -> None:
        cert = await self.repo.get_person_certificate(person_certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselPersonCertificate", person_certificate_id)
        if revision is not None:
            self._ensure_revision(cert, revision)
        before = _row_dict(cert)
        now = datetime.utcnow()
        cert.voided_at = now
        cert.voided_by = operator_id
        cert.void_reason = reason or "人员适任证作废"
        cert.verify_status_code = "VOIDED"
        cert.revision = int(cert.revision or 1) + 1
        await self._add_change_event(
            vessel_id,
            "VOID_PERSON_CERTIFICATE",
            "作废人员适任证",
            before,
            _row_dict(cert),
            operator_id,
            object_type="vessel_person_certificate",
            object_id=cert.id,
            reason=reason,
        )
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)

    async def upload_person_certificate_file_first(
        self,
        vessel_id: int,
        file: UploadFile,
        *,
        crew_assignment_id: int,
        certificate_type_code: str = "CREW_COMPETENCY_CERT",
        operator_id: int | None = None,
    ) -> VesselPersonCertificateResponse:
        await self._require_profile(vessel_id)
        crew = await self._require_crew_assignment(vessel_id, crew_assignment_id)
        cert = await self.repo.create_person_certificate(
            vessel_id,
            {
                "crew_assignment_id": crew.id,
                "holder_name": crew.crew_name,
                "certificate_type_code": CREW_CERTIFICATE_TYPE,
                "verify_status_code": "PENDING",
                "remark": "由船员适任证附件上传创建，待识别或人工补录",
            },
        )
        file_row = await self._store_person_certificate_file(vessel_id, cert.id, file, operator_id=operator_id)
        recognition = None
        if file_row.content_type.lower().startswith("image/"):
            recognition = await self._create_person_image_recognition_record(
                vessel_id,
                cert.id,
                file_row.id,
                file_row.storage_file_id,
                operator_id=operator_id,
            )
        await self._add_change_event(vessel_id, "CREATE_PERSON_CERTIFICATE", "上传附件创建船员适任证草稿", None, _row_dict(cert), operator_id)
        await self.db.commit()
        if recognition is not None:
            await self._dispatch_person_recognition_or_fail(recognition)
        return (await self._person_certificates_with_files(vessel_id, person_certificate_id=cert.id))[0]

    async def upload_person_certificate_file(
        self,
        vessel_id: int,
        person_certificate_id: int,
        file: UploadFile,
        *,
        operator_id: int | None = None,
    ) -> VesselPersonCertificateFileResponse:
        await self._require_profile(vessel_id)
        cert = await self.repo.get_person_certificate(person_certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselPersonCertificate", person_certificate_id)
        row = await self._store_person_certificate_file(vessel_id, person_certificate_id, file, operator_id=operator_id)
        await self.db.commit()
        if row.content_type.lower().startswith("image/"):
            recognition = await self._create_person_image_recognition_record(
                vessel_id,
                person_certificate_id,
                row.id,
                row.storage_file_id,
                operator_id=operator_id,
            )
            await self.db.commit()
            await self._dispatch_person_recognition_or_fail(recognition)
        return self._person_file_response(row)

    async def void_person_certificate_file(
        self,
        vessel_id: int,
        person_certificate_id: int,
        file_id: int,
        *,
        reason: str | None = None,
        operator_id: int | None = None,
    ) -> None:
        cert = await self.repo.get_person_certificate(person_certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselPersonCertificate", person_certificate_id)
        row = await self.db.scalar(
            select(VesselPersonCertificateFile).where(
                VesselPersonCertificateFile.id == file_id,
                VesselPersonCertificateFile.vessel_person_certificate_id == person_certificate_id,
            )
        )
        if row is None:
            raise NotFoundError("VesselPersonCertificateFile", file_id)
        before = _row_dict(row)
        row.voided_at = datetime.utcnow()
        row.voided_by = operator_id
        row.void_reason = reason or "船员适任证附件作废"
        await self._add_change_event(vessel_id, "VOID_PERSON_CERTIFICATE_FILE", "作废船员适任证附件", before, _row_dict(row), operator_id)
        await self.db.commit()

    async def list_certificates(self, vessel_id: int) -> list[VesselCertificateResponse]:
        await self._require_profile(vessel_id)
        return await self._certificates_with_files(vessel_id)

    async def get_certificate_ledger(self, vessel_id: int) -> list[VesselCertificateLedgerItemResponse]:
        await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        certs = await self._certificates_with_files(vessel_id, label_map=label_map)
        by_type: dict[str, VesselCertificateResponse] = {}
        for cert in certs:
            by_type.setdefault(cert.certificate_type_code, cert)
        return [
            VesselCertificateLedgerItemResponse(
                certificate_type_code=code,
                certificate_type_name=label_map.get("VESSEL_CERTIFICATE_TYPE", {}).get(code),
                required=True,
                status_code=self._certificate_ledger_status(by_type.get(code)),
                status_name=self._certificate_ledger_status_name(self._certificate_ledger_status(by_type.get(code))),
                certificate=by_type.get(code),
            )
            for code in REQUIRED_VESSEL_CERTIFICATE_TYPES
        ]

    async def create_certificate(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselCertificateResponse:
        await self._require_profile(vessel_id)
        data = payload.model_dump(exclude_none=True)
        self._validate_vessel_certificate_type(data.get("certificate_type_code"))
        row = await self.repo.create_certificate(vessel_id, data)
        await self._add_change_event(vessel_id, "CREATE_CERTIFICATE", "新增船舶证件", None, _row_dict(row), operator_id)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self._refresh_summary_best_effort(vessel_id)
        return (await self._certificates_with_files(vessel_id, certificate_id=row.id))[0]

    async def update_certificate(self, vessel_id: int, certificate_id: int, payload, *, operator_id: int | None = None) -> VesselCertificateResponse:
        cert = await self.repo.get_certificate(certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselCertificate", certificate_id)
        before = _row_dict(cert)
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        if "certificate_type_code" in updates:
            self._validate_vessel_certificate_type(updates.get("certificate_type_code"))
        row = await self.repo.update_certificate(certificate_id, updates)
        assert row is not None
        await self._add_change_event(row.vessel_profile_id, "UPDATE_CERTIFICATE", "更新船舶证件", before, _row_dict(row), operator_id)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self._refresh_summary_best_effort(vessel_id)
        return (await self._certificates_with_files(row.vessel_profile_id, certificate_id=row.id))[0]

    async def void_certificate(
        self,
        vessel_id: int,
        certificate_id: int,
        *,
        reason: str | None = None,
        operator_id: int | None = None,
    ) -> None:
        cert = await self.repo.get_certificate(certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselCertificate", certificate_id)
        before = _row_dict(cert)
        cert.voided_at = datetime.utcnow()
        cert.voided_by = operator_id
        cert.void_reason = reason or "船舶证书作废"
        cert.verify_status_code = "VOIDED"
        await self._add_change_event(vessel_id, "VOID_CERTIFICATE", "作废船舶证书", before, _row_dict(cert), operator_id)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self._refresh_summary_best_effort(vessel_id)

    async def upload_certificate_file_first(
        self,
        vessel_id: int,
        file: UploadFile,
        *,
        certificate_type_code: str = "UNKNOWN",
        operator_id: int | None = None,
    ) -> VesselCertificateResponse:
        await self._require_profile(vessel_id)
        self._validate_vessel_certificate_type(certificate_type_code)
        cert = await self.repo.create_certificate(
            vessel_id,
            {
                "certificate_type_code": certificate_type_code or "UNKNOWN",
                "verify_status_code": "PENDING",
                "remark": "由附件上传创建，待识别或人工补录",
            },
        )
        file_row = await self._store_certificate_file(vessel_id, cert.id, file, operator_id=operator_id)
        recognition = None
        if file_row.content_type.lower().startswith("image/"):
            recognition = await self._create_certificate_image_recognition_record(
                vessel_id,
                cert.id,
                file_row.id,
                file_row.storage_file_id,
                operator_id=operator_id,
            )
        await self._add_change_event(vessel_id, "CREATE_CERTIFICATE", "上传附件创建证件草稿", None, _row_dict(cert), operator_id)
        await self.db.commit()
        if recognition is not None:
            await self._dispatch_certificate_recognition_or_fail(recognition)
        return (await self._certificates_with_files(vessel_id, certificate_id=cert.id))[0]

    async def upload_certificate_file(
        self,
        vessel_id: int,
        certificate_id: int,
        file: UploadFile,
        *,
        operator_id: int | None = None,
    ) -> VesselCertificateFileResponse:
        await self._require_profile(vessel_id)
        cert = await self.repo.get_certificate(certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselCertificate", certificate_id)
        row = await self._store_certificate_file(vessel_id, certificate_id, file, operator_id=operator_id)
        await self.db.commit()
        if row.content_type.lower().startswith("image/"):
            recognition = await self._create_certificate_image_recognition_record(
                vessel_id,
                certificate_id,
                row.id,
                row.storage_file_id,
                operator_id=operator_id,
            )
            await self.db.commit()
            await self._dispatch_certificate_recognition_or_fail(recognition)
        return self._file_response(row)

    async def void_certificate_file(
        self,
        vessel_id: int,
        certificate_id: int,
        file_id: int,
        *,
        reason: str | None = None,
        operator_id: int | None = None,
    ) -> None:
        cert = await self.repo.get_certificate(certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselCertificate", certificate_id)
        row = await self.db.scalar(
            select(VesselCertificateFile).where(
                VesselCertificateFile.id == file_id,
                VesselCertificateFile.vessel_certificate_id == certificate_id,
            )
        )
        if row is None:
            raise NotFoundError("VesselCertificateFile", file_id)
        before = _row_dict(row)
        row.voided_at = datetime.utcnow()
        row.voided_by = operator_id
        row.void_reason = reason or "船舶证书附件作废"
        await self._add_change_event(vessel_id, "VOID_CERTIFICATE_FILE", "作废船舶证书附件", before, _row_dict(row), operator_id)
        await self.db.commit()

    async def _store_certificate_file(
        self,
        vessel_id: int,
        certificate_id: int,
        file: UploadFile,
        *,
        operator_id: int | None,
    ) -> VesselCertificateFile:
        storage_file = await FileStorageService(self.db).upload_file(
            file=file,
            object_prefix=f"vessels/{vessel_id}/certificates/{certificate_id}",
            uploaded_by=operator_id,
            allowed_content_types={"application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"},
        )
        now = datetime.utcnow()
        row = await self.repo.create_certificate_file(
            {
                "vessel_certificate_id": certificate_id,
                "storage_file_id": storage_file.id,
                "file_name": storage_file.original_file_name,
                "content_type": storage_file.content_type,
                "file_size": storage_file.file_size,
                "uploaded_by": operator_id,
                "uploaded_at": now,
                "created_at": now,
            }
        )
        await self._add_change_event(vessel_id, "UPLOAD_CERTIFICATE_FILE", "上传证件附件", None, _row_dict(row), operator_id)
        return row

    async def _store_person_certificate_file(
        self,
        vessel_id: int,
        person_certificate_id: int,
        file: UploadFile,
        *,
        operator_id: int | None,
    ) -> VesselPersonCertificateFile:
        storage_file = await FileStorageService(self.db).upload_file(
            file=file,
            object_prefix=f"vessels/{vessel_id}/person-certificates/{person_certificate_id}",
            uploaded_by=operator_id,
            allowed_content_types={"application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"},
        )
        now = datetime.utcnow()
        row = await self.repo.create_person_certificate_file(
            {
                "vessel_person_certificate_id": person_certificate_id,
                "storage_file_id": storage_file.id,
                "file_name": storage_file.original_file_name,
                "content_type": storage_file.content_type,
                "file_size": storage_file.file_size,
                "uploaded_by": operator_id,
                "uploaded_at": now,
                "created_at": now,
            }
        )
        await self._add_change_event(vessel_id, "UPLOAD_PERSON_CERTIFICATE_FILE", "上传人员证件附件", None, _row_dict(row), operator_id)
        return row

    async def _dispatch_certificate_recognition_or_fail(self, recognition: VesselCertificateImageRecognition) -> None:
        try:
            _dispatch_certificate_recognition_task(int(recognition.id))
        except Exception as exc:  # noqa: BLE001
            recognition.status_code = "FAILED"
            recognition.error_message = f"证件图片识别任务投递失败：{exc}"[:512]
            await self._add_change_event(
                int(recognition.vessel_profile_id),
                "IMAGE_RECOGNIZE_CERTIFICATE_FAILED",
                "证件图片识别任务投递失败",
                None,
                {"recognition_id": recognition.id, "error_message": recognition.error_message},
                recognition.created_by,
            )
            await self.db.commit()

    async def _dispatch_person_recognition_or_fail(self, recognition: VesselPersonCertificateImageRecognition) -> None:
        try:
            _dispatch_person_recognition_task(int(recognition.id))
        except Exception as exc:  # noqa: BLE001
            recognition.status_code = "FAILED"
            recognition.error_message = f"人员证件图片识别任务投递失败：{exc}"[:512]
            await self._add_change_event(
                int(recognition.vessel_profile_id),
                "IMAGE_RECOGNIZE_PERSON_CERTIFICATE_FAILED",
                "人员证件图片识别任务投递失败",
                None,
                {"recognition_id": recognition.id, "error_message": recognition.error_message},
                recognition.created_by,
            )
            await self.db.commit()

    def _certificate_updates_from_recognition(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = self._normalize_recognition_payload(payload)
        updates: dict[str, Any] = {}
        for source_key, target_key in {
            "certificate_type_code": "certificate_type_code",
            "certificate_no": "certificate_no",
            "issuing_authority": "issuing_authority",
            "validity_text_raw": "validity_text_raw",
        }.items():
            value = payload.get(source_key)
            if value not in (None, ""):
                updates[target_key] = value
        valid_from = _to_date(payload.get("valid_from"))
        valid_to = _to_date(payload.get("valid_to"))
        if valid_from:
            updates["valid_from"] = valid_from
        if payload.get("is_long_term_valid") is True:
            updates["is_long_term_valid"] = True
            updates["valid_to"] = None
        elif valid_to:
            updates["valid_to"] = valid_to
        if "is_long_term_valid" in payload:
            updates["is_long_term_valid"] = bool(payload.get("is_long_term_valid"))
        return updates

    def _person_certificate_updates_from_recognition(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = self._normalize_recognition_payload(payload)
        updates: dict[str, Any] = {}
        for source_key, target_key in {
            "holder_name": "holder_name",
            "certificate_type_code": "certificate_type_code",
            "certificate_no": "certificate_no",
            "validity_text_raw": "validity_text_raw",
        }.items():
            value = payload.get(source_key)
            if value not in (None, ""):
                updates[target_key] = value
        valid_from = _to_date(payload.get("valid_from"))
        valid_to = _to_date(payload.get("valid_to"))
        if valid_from:
            updates["valid_from"] = valid_from
        if payload.get("is_long_term_valid") is True:
            updates["is_long_term_valid"] = True
            updates["valid_to"] = None
        elif valid_to:
            updates["valid_to"] = valid_to
        if "is_long_term_valid" in payload:
            updates["is_long_term_valid"] = bool(payload.get("is_long_term_valid"))
        return updates

    async def _certificate_recognition_diff_rows(
        self,
        vessel_id: int,
        cert: VesselCertificate,
        recognition: VesselCertificateImageRecognition,
        accepted: dict[str, Any],
    ) -> list[VesselRecognitionFieldDiff]:
        cert_updates = self._certificate_updates_from_recognition(accepted)
        profile_updates, capacity_updates = self._adoption_updates_from_recognition(
            accepted,
            sorted(CERTIFICATE_PROFILE_ADOPTION_FIELDS),
        )
        profile = await self._require_profile(vessel_id)
        capacity = await self.repo.get_one_by_profile(VesselCapacityDimension, vessel_id)
        diffs: dict[str, tuple[Any, Any]] = {key: (getattr(cert, key, None), value) for key, value in cert_updates.items()}
        diffs.update({key: (getattr(profile, key, None), value) for key, value in profile_updates.items()})
        diffs.update({key: (getattr(capacity, key, None) if capacity else None, value) for key, value in capacity_updates.items()})
        return await self._persist_recognition_diffs(
            vessel_id=vessel_id,
            recognition_object_type="VESSEL_CERTIFICATE_IMAGE_RECOGNITION",
            recognition_id=recognition.id,
            target_object_type="vessel_certificate",
            target_object_id=cert.id,
            diffs=diffs,
            confidence_score=recognition.confidence_score,
            evidence_text=recognition.raw_text,
        )

    async def _person_certificate_recognition_diff_rows(
        self,
        vessel_id: int,
        cert: VesselPersonCertificate,
        recognition: VesselPersonCertificateImageRecognition,
        accepted: dict[str, Any],
    ) -> list[VesselRecognitionFieldDiff]:
        updates = self._person_certificate_updates_from_recognition(accepted)
        diffs = {key: (getattr(cert, key, None), value) for key, value in updates.items()}
        return await self._persist_recognition_diffs(
            vessel_id=vessel_id,
            recognition_object_type="PERSON_CERTIFICATE_IMAGE_RECOGNITION",
            recognition_id=recognition.id,
            target_object_type="vessel_person_certificate",
            target_object_id=cert.id,
            diffs=diffs,
            confidence_score=recognition.confidence_score,
            evidence_text=recognition.raw_text,
        )

    def _validate_vessel_certificate_type(self, certificate_type_code: str | None) -> None:
        code = certificate_type_code or "UNKNOWN"
        if code not in VALID_VESSEL_CERTIFICATE_TYPES:
            raise ValidationError("船舶证书类型必须从船舶证书目录中选择")

    def _certificate_ledger_status(self, cert: VesselCertificateResponse | None) -> str:
        if cert is None:
            return "MISSING"
        if cert.voided_at is not None:
            return "VOIDED"
        current = cert.current_image_recognition
        if current is not None and current.status_code == "NEED_CONFIRM":
            return "NEED_CONFIRM"
        if current is not None and current.status_code in ACTIVE_RECOGNITION_STATUSES:
            return current.status_code
        if current is not None and current.status_code == "FAILED":
            return "RECOGNITION_FAILED"
        has_core_fields = bool(cert.certificate_no) and (cert.is_long_term_valid or cert.valid_to is not None)
        if not cert.files and not has_core_fields:
            return "DRAFT"
        if cert.verify_status_code != "VERIFIED" or not has_core_fields:
            return "ARCHIVED" if cert.files else "DRAFT"
        if cert.verify_status_code == "VERIFIED":
            if cert.is_long_term_valid:
                return "VERIFIED"
            if cert.valid_to is not None:
                today = date.today()
                if cert.valid_to < today:
                    return "EXPIRED"
                if cert.valid_to <= today + timedelta(days=30):
                    return "EXPIRING"
            return "VERIFIED"
        return "ARCHIVED"

    def _certificate_ledger_status_name(self, status_code: str) -> str:
        return {
            "MISSING": "缺失",
            "DRAFT": "草稿",
            "ARCHIVED": "已归档",
            "QUEUED": "排队识别",
            "PROCESSING": "识别中",
            "NEED_CONFIRM": "待确认",
            "RECOGNITION_FAILED": "识别失败",
            "VERIFIED": "已核验",
            "EXPIRING": "即将到期",
            "EXPIRED": "已过期",
            "VOIDED": "已作废",
        }.get(status_code, status_code)

    async def _require_crew_assignment(self, vessel_id: int, crew_assignment_id: int | None) -> VesselCrewAssignment:
        if crew_assignment_id is None:
            raise ValidationError("船员适任证必须绑定当前船员任职")
        crew = await self.db.get(VesselCrewAssignment, crew_assignment_id)
        if crew is None or crew.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselCrewAssignment", crew_assignment_id)
        if not crew.is_current:
            raise ValidationError("船员适任证只能绑定当前任职船员")
        return crew

    async def _certificates_by_profile(self, ids: list[int]) -> dict[int, list[VesselCertificate]]:
        if not ids:
            return {}
        rows = (
            await self.db.execute(select(VesselCertificate).where(VesselCertificate.vessel_profile_id.in_(ids)))
        ).scalars().all()
        result: dict[int, list[VesselCertificate]] = defaultdict(list)
        for row in rows:
            result[row.vessel_profile_id].append(row)
        return result

    async def _certificates_with_files(
        self,
        vessel_id: int,
        *,
        certificate_id: int | None = None,
        label_map: dict[str, dict[str, str]] | None = None,
    ) -> list[VesselCertificateResponse]:
        label_map = label_map or await _load_label_map(self.db)
        stmt = select(VesselCertificate).where(
            VesselCertificate.vessel_profile_id == vessel_id,
            VesselCertificate.voided_at.is_(None),
        )
        if certificate_id:
            stmt = stmt.where(VesselCertificate.id == certificate_id)
        certs = (await self.db.execute(stmt.order_by(VesselCertificate.id.desc()))).scalars().all()
        if not certs:
            return []
        files = (
            await self.db.execute(
                select(VesselCertificateFile).where(
                    VesselCertificateFile.vessel_certificate_id.in_([row.id for row in certs]),
                    VesselCertificateFile.voided_at.is_(None),
                )
            )
        ).scalars().all()
        file_map: dict[int, list[VesselCertificateFileResponse]] = defaultdict(list)
        for item in files:
            file_map[item.vessel_certificate_id].append(self._file_response(item))
        recognition_rows = (
            await self.db.execute(
                select(VesselCertificateImageRecognition)
                .where(VesselCertificateImageRecognition.vessel_certificate_id.in_([row.id for row in certs]))
                .order_by(VesselCertificateImageRecognition.id.desc())
            )
        ).scalars().all()
        latest_recognition_map: dict[int, VesselCertificateImageRecognition] = {}
        current_recognition_map: dict[int, VesselCertificateImageRecognition] = {}
        latest_confirmed_recognition_map: dict[int, VesselCertificateImageRecognition] = {}
        has_recognition_history: set[int] = set()
        for row in recognition_rows:
            has_recognition_history.add(row.vessel_certificate_id)
            if row.vessel_certificate_id not in latest_recognition_map:
                latest_recognition_map[row.vessel_certificate_id] = row
                if row.status_code in CURRENT_RECOGNITION_STATUSES:
                    current_recognition_map[row.vessel_certificate_id] = row
            if row.status_code == "CONFIRMED":
                latest_confirmed_recognition_map.setdefault(row.vessel_certificate_id, row)
        return [
            self._certificate_response(
                cert,
                files=file_map.get(cert.id, []),
                label_map=label_map,
                latest_recognition=latest_recognition_map.get(cert.id),
                current_recognition=current_recognition_map.get(cert.id),
                latest_confirmed_recognition=latest_confirmed_recognition_map.get(cert.id),
                has_recognition_history=cert.id in has_recognition_history,
            )
            for cert in certs
        ]

    def _file_response(self, row: VesselCertificateFile) -> VesselCertificateFileResponse:
        return VesselCertificateFileResponse(**_row_dict(row), download_url=f"/api/v1/files/{row.storage_file_id}/content")

    async def _person_certificates_with_files(
        self,
        vessel_id: int,
        *,
        person_certificate_id: int | None = None,
        label_map: dict[str, dict[str, str]] | None = None,
    ) -> list[VesselPersonCertificateResponse]:
        label_map = label_map or await _load_label_map(self.db)
        stmt = select(VesselPersonCertificate).where(
            VesselPersonCertificate.vessel_profile_id == vessel_id,
            VesselPersonCertificate.voided_at.is_(None),
        )
        if person_certificate_id:
            stmt = stmt.where(VesselPersonCertificate.id == person_certificate_id)
        certs = (await self.db.execute(stmt.order_by(VesselPersonCertificate.id.desc()))).scalars().all()
        if not certs:
            return []
        files = (
            await self.db.execute(
                select(VesselPersonCertificateFile).where(
                    VesselPersonCertificateFile.vessel_person_certificate_id.in_([row.id for row in certs]),
                    VesselPersonCertificateFile.voided_at.is_(None),
                )
            )
        ).scalars().all()
        file_map: dict[int, list[VesselPersonCertificateFileResponse]] = defaultdict(list)
        for item in files:
            file_map[item.vessel_person_certificate_id].append(self._person_file_response(item))
        recognition_rows = (
            await self.db.execute(
                select(VesselPersonCertificateImageRecognition)
                .where(
                    VesselPersonCertificateImageRecognition.vessel_person_certificate_id.in_(
                        [row.id for row in certs]
                    )
                )
                .order_by(VesselPersonCertificateImageRecognition.id.desc())
            )
        ).scalars().all()
        latest_recognition_map: dict[int, VesselPersonCertificateImageRecognition] = {}
        current_recognition_map: dict[int, VesselPersonCertificateImageRecognition] = {}
        latest_confirmed_recognition_map: dict[int, VesselPersonCertificateImageRecognition] = {}
        has_recognition_history: set[int] = set()
        for row in recognition_rows:
            has_recognition_history.add(row.vessel_person_certificate_id)
            if row.vessel_person_certificate_id not in latest_recognition_map:
                latest_recognition_map[row.vessel_person_certificate_id] = row
                if row.status_code in CURRENT_RECOGNITION_STATUSES:
                    current_recognition_map[row.vessel_person_certificate_id] = row
            if row.status_code == "CONFIRMED":
                latest_confirmed_recognition_map.setdefault(row.vessel_person_certificate_id, row)
        return [
            self._person_certificate_response(
                cert,
                label_map,
                files=file_map.get(cert.id, []),
                latest_recognition=latest_recognition_map.get(cert.id),
                current_recognition=current_recognition_map.get(cert.id),
                latest_confirmed_recognition=latest_confirmed_recognition_map.get(cert.id),
                has_recognition_history=cert.id in has_recognition_history,
            )
            for cert in certs
        ]

    def _person_file_response(self, row: VesselPersonCertificateFile) -> VesselPersonCertificateFileResponse:
        return VesselPersonCertificateFileResponse(
            **_row_dict(row),
            download_url=f"/api/v1/files/{row.storage_file_id}/content",
        )

    def _person_certificate_response(
        self,
        row: VesselPersonCertificate,
        label_map: dict[str, dict[str, str]],
        *,
        files: list[VesselPersonCertificateFileResponse] | None = None,
        latest_recognition: VesselPersonCertificateImageRecognition | None = None,
        current_recognition: VesselPersonCertificateImageRecognition | None = None,
        latest_confirmed_recognition: VesselPersonCertificateImageRecognition | None = None,
        has_recognition_history: bool = False,
    ) -> VesselPersonCertificateResponse:
        return VesselPersonCertificateResponse(
            **_row_dict(row),
            certificate_type_name=label_map.get("CREW_CERTIFICATE_TYPE", {}).get(row.certificate_type_code)
            or label_map.get("CERTIFICATE_TYPE", {}).get(row.certificate_type_code),
            verify_status_name=label_map.get("CERTIFICATE_VERIFY_STATUS", {}).get(row.verify_status_code),
            source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
            files=files or [],
            latest_image_recognition=(
                self._person_image_recognition_response(latest_recognition, label_map)
                if latest_recognition is not None
                else None
            ),
            current_image_recognition=(
                self._person_image_recognition_response(current_recognition, label_map)
                if current_recognition is not None
                else None
            ),
            latest_confirmed_image_recognition=(
                self._person_image_recognition_response(latest_confirmed_recognition, label_map)
                if latest_confirmed_recognition is not None
                else None
            ),
            has_recognition_history=has_recognition_history,
        )

    def _image_recognition_response(
        self,
        row: VesselCertificateImageRecognition,
        label_map: dict[str, dict[str, str]],
    ) -> VesselCertificateImageRecognitionResponse:
        return VesselCertificateImageRecognitionResponse(
            **_row_dict(row),
            status_name=label_map.get("VESSEL_CERTIFICATE_IMAGE_RECOGNITION_STATUS", {}).get(row.status_code),
        )

    def _person_image_recognition_response(
        self,
        row: VesselPersonCertificateImageRecognition,
        label_map: dict[str, dict[str, str]],
    ) -> VesselPersonCertificateImageRecognitionResponse:
        return VesselPersonCertificateImageRecognitionResponse(
            **_row_dict(row),
            status_name=label_map.get("VESSEL_CERTIFICATE_IMAGE_RECOGNITION_STATUS", {}).get(row.status_code),
        )

    def _certificate_response(
        self,
        row: VesselCertificate,
        *,
        files: list[VesselCertificateFileResponse],
        label_map: dict[str, dict[str, str]],
        latest_recognition: VesselCertificateImageRecognition | None = None,
        current_recognition: VesselCertificateImageRecognition | None = None,
        latest_confirmed_recognition: VesselCertificateImageRecognition | None = None,
        has_recognition_history: bool = False,
    ) -> VesselCertificateResponse:
        recognition_status = current_recognition.status_code if current_recognition is not None else "NOT_STARTED"
        confirmation_status = "CONFIRMED" if latest_confirmed_recognition is not None else "UNCONFIRMED"
        return VesselCertificateResponse(
            **_row_dict(row),
            certificate_type_name=label_map.get("VESSEL_CERTIFICATE_TYPE", {}).get(row.certificate_type_code)
            or label_map.get("CERTIFICATE_TYPE", {}).get(row.certificate_type_code),
            verify_status_name=label_map.get("CERTIFICATE_VERIFY_STATUS", {}).get(row.verify_status_code),
            recognition_status_code=recognition_status,
            recognition_status_name=label_map.get("VESSEL_CERTIFICATE_IMAGE_RECOGNITION_STATUS", {}).get(recognition_status),
            confirmation_status_code=confirmation_status,
            confirmation_status_name=label_map.get("VESSEL_CERTIFICATE_IMAGE_RECOGNITION_STATUS", {}).get(confirmation_status),
            files=files,
            latest_image_recognition=(
                self._image_recognition_response(latest_recognition, label_map) if latest_recognition is not None else None
            ),
            current_image_recognition=(
                self._image_recognition_response(current_recognition, label_map) if current_recognition is not None else None
            ),
            latest_confirmed_image_recognition=(
                self._image_recognition_response(latest_confirmed_recognition, label_map)
                if latest_confirmed_recognition is not None
                else None
            ),
            has_recognition_history=has_recognition_history,
        )
