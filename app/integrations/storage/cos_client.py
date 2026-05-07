from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ObjectStorageResult:
    content: bytes
    content_type: str | None = None


class ObjectStorageClient(Protocol):
    async def put_object(self, *, bucket: str, key: str, body: bytes, content_type: str) -> None:
        ...

    async def get_object(self, *, bucket: str, key: str) -> ObjectStorageResult:
        ...

    async def delete_object(self, *, bucket: str, key: str) -> None:
        ...


class CosObjectStorageClient:
    def __init__(
        self,
        *,
        region: str | None,
        secret_id: str,
        secret_key: str,
        endpoint: str | None = None,
        scheme: str = "https",
    ) -> None:
        self.region = region or None
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.endpoint = endpoint or None
        self.scheme = scheme
        self._client = None

    def _sync_client(self):
        if self._client is not None:
            return self._client

        from qcloud_cos import CosConfig, CosS3Client

        config_kwargs = {
            "Region": self.region,
            "SecretId": self.secret_id,
            "SecretKey": self.secret_key,
            "Token": None,
            "Scheme": self.scheme,
        }
        if self.endpoint:
            config_kwargs["Endpoint"] = self.endpoint
        self._client = CosS3Client(CosConfig(**config_kwargs))
        return self._client

    async def put_object(self, *, bucket: str, key: str, body: bytes, content_type: str) -> None:
        def _put() -> None:
            self._sync_client().put_object(
                Bucket=bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
            )

        await asyncio.to_thread(_put)

    async def get_object(self, *, bucket: str, key: str) -> ObjectStorageResult:
        def _get() -> ObjectStorageResult:
            response = self._sync_client().get_object(Bucket=bucket, Key=key)
            body = response.get("Body")
            if body is None:
                return ObjectStorageResult(content=b"", content_type=response.get("Content-Type"))
            raw_stream = body.get_raw_stream() if hasattr(body, "get_raw_stream") else body
            content = raw_stream.read()
            content_type = response.get("Content-Type") or response.get("ContentType")
            return ObjectStorageResult(content=content, content_type=content_type)

        return await asyncio.to_thread(_get)

    async def delete_object(self, *, bucket: str, key: str) -> None:
        def _delete() -> None:
            self._sync_client().delete_object(Bucket=bucket, Key=key)

        await asyncio.to_thread(_delete)
