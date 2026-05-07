from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.storage import StorageFile


class StorageFileRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_file(self, data: dict[str, Any]) -> StorageFile:
        entity = StorageFile(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def get_file(self, file_id: int) -> StorageFile | None:
        return await self.db.scalar(select(StorageFile).where(StorageFile.id == file_id))

    async def delete_file(self, file_id: int) -> bool:
        entity = await self.get_file(file_id)
        if entity is None:
            return False
        await self.db.delete(entity)
        await self.db.flush()
        return True
