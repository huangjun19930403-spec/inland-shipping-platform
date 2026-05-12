from __future__ import annotations

import mimetypes
import posixpath
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.integrations.config_keys import (
    COS_ACCESS_KEY,
    COS_BUCKET_NAME,
    COS_CONFIG_PROFILE,
    COS_ENABLED,
    COS_ENDPOINT,
    COS_IMAGE_MAX_SIZE_MB,
    COS_REGION,
    COS_SECRET_KEY,
)
from app.integrations.storage import (
    CosObjectStorageClient,
    LocalObjectStorageClient,
    ObjectStorageClient,
    ObjectStorageResult,
)
from app.models.storage import StorageFile
from app.modules.storage.repository import StorageFileRepository
from app.modules.system.runtime_config import RuntimeConfigService


IMAGE_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}

DOCUMENT_CONTENT_TYPES = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
}

DEFAULT_FILE_CONTENT_TYPES = IMAGE_CONTENT_TYPES | DOCUMENT_CONTENT_TYPES


@dataclass(frozen=True)
class ObjectStorageSettings:
    provider_code: str
    bucket_name: str
    region: str | None
    endpoint: str | None
    access_key: str
    secret_key: str
    max_file_size_bytes: int
    local_root_dir: str | None = None


def _safe_original_name(filename: str | None) -> str:
    value = Path(filename or "upload").name.strip()
    return value or "upload"


def _clean_content_type(value: str | None, filename: str | None) -> str:
    content_type = (value or "").split(";")[0].strip().lower()
    if not content_type:
        guessed, _ = mimetypes.guess_type(filename or "")
        content_type = (guessed or "").lower()
    return content_type


def _object_key(prefix: str, filename: str, content_type: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in DEFAULT_FILE_CONTENT_TYPES.values():
        ext = DEFAULT_FILE_CONTENT_TYPES.get(content_type, ".bin")
    prefix_clean = re.sub(r"[^0-9A-Za-z/_-]+", "-", prefix.strip("/"))
    return posixpath.join(prefix_clean, f"{uuid.uuid4().hex}{ext}")


class FileStorageService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        object_client: ObjectStorageClient | None = None,
    ) -> None:
        self.db = db
        self.repo = StorageFileRepository(db)
        self.runtime_config = RuntimeConfigService(db)
        self._object_client = object_client

    async def _settings(self) -> ObjectStorageSettings:
        enabled = await self.runtime_config.get_bool(COS_ENABLED, False, profile_code=COS_CONFIG_PROFILE)
        max_mb = await self.runtime_config.get_int(COS_IMAGE_MAX_SIZE_MB, 10, profile_code=COS_CONFIG_PROFILE)
        if not enabled:
            return ObjectStorageSettings(
                provider_code="LOCAL",
                bucket_name="local",
                region=None,
                endpoint=None,
                access_key="",
                secret_key="",
                max_file_size_bytes=max(1, max_mb) * 1024 * 1024,
                local_root_dir=app_settings.LOCAL_FILE_STORAGE_DIR,
            )

        bucket_name = (await self.runtime_config.get_value(COS_BUCKET_NAME, "", profile_code=COS_CONFIG_PROFILE) or "").strip()
        access_key = (await self.runtime_config.get_value(COS_ACCESS_KEY, "", profile_code=COS_CONFIG_PROFILE) or "").strip()
        secret_key = (await self.runtime_config.get_value(COS_SECRET_KEY, "", profile_code=COS_CONFIG_PROFILE) or "").strip()
        region = (await self.runtime_config.get_value(COS_REGION, "", profile_code=COS_CONFIG_PROFILE) or "").strip() or None
        endpoint = (await self.runtime_config.get_value(COS_ENDPOINT, "", profile_code=COS_CONFIG_PROFILE) or "").strip() or None

        if not bucket_name:
            raise ValidationError("COS_BUCKET_NAME 未配置")
        if not access_key or not secret_key:
            raise ValidationError("COS 访问密钥未配置")
        if not region and not endpoint:
            raise ValidationError("COS_REGION 或 COS_ENDPOINT 至少需要配置一个")

        return ObjectStorageSettings(
            provider_code="TENCENT_COS",
            bucket_name=bucket_name,
            region=region,
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            max_file_size_bytes=max(1, max_mb) * 1024 * 1024,
        )

    def _client(self, settings: ObjectStorageSettings) -> ObjectStorageClient:
        if self._object_client is not None:
            return self._object_client
        if settings.provider_code == "LOCAL":
            return LocalObjectStorageClient(settings.local_root_dir or app_settings.LOCAL_FILE_STORAGE_DIR)
        return CosObjectStorageClient(
            region=settings.region,
            endpoint=settings.endpoint,
            secret_id=settings.access_key,
            secret_key=settings.secret_key,
        )

    async def upload_image(
        self,
        *,
        file: UploadFile,
        object_prefix: str,
        uploaded_by: int | None = None,
    ) -> StorageFile:
        return await self.upload_file(
            file=file,
            object_prefix=object_prefix,
            uploaded_by=uploaded_by,
            allowed_content_types=set(IMAGE_CONTENT_TYPES),
            unsupported_message="仅支持 jpg、png、gif、webp、bmp 图片",
        )

    async def upload_file(
        self,
        *,
        file: UploadFile,
        object_prefix: str,
        uploaded_by: int | None = None,
        allowed_content_types: set[str] | None = None,
        unsupported_message: str = "仅支持图片或 PDF 文件",
    ) -> StorageFile:
        settings = await self._settings()
        original_name = _safe_original_name(file.filename)
        content_type = _clean_content_type(file.content_type, original_name)
        allowed = allowed_content_types or set(DEFAULT_FILE_CONTENT_TYPES)
        if content_type not in allowed:
            raise ValidationError(unsupported_message)

        content = await file.read()
        if not content:
            raise ValidationError("上传文件不能为空")
        if len(content) > settings.max_file_size_bytes:
            raise ValidationError("文件大小超过限制")

        key = _object_key(object_prefix, original_name, content_type)
        await self._client(settings).put_object(
            bucket=settings.bucket_name,
            key=key,
            body=content,
            content_type=content_type,
        )
        return await self.repo.create_file(
            {
                "bucket_name": settings.bucket_name,
                "object_key": key,
                "original_file_name": original_name,
                "content_type": content_type,
                "file_size": len(content),
                "storage_provider_code": settings.provider_code,
                "uploaded_by": uploaded_by,
                "checksum": None,
                "status": 1,
            }
        )

    async def download_file(self, file_id: int) -> tuple[StorageFile, ObjectStorageResult]:
        entity = await self.repo.get_file(file_id)
        if entity is None:
            raise NotFoundError("StorageFile", file_id)
        settings = await self._settings()
        result = await self._client(settings).get_object(
            bucket=entity.bucket_name,
            key=entity.object_key,
        )
        return entity, result

    async def delete_file_entity(self, entity: StorageFile) -> None:
        settings = await self._settings()
        await self._client(settings).delete_object(bucket=entity.bucket_name, key=entity.object_key)
        await self.repo.delete_file(entity.id)
