from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.storage.service import FileStorageService

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/{file_id}/content")
async def get_file_content(
    file_id: int,
    db: AsyncSession = Depends(get_db),
):
    entity, result = await FileStorageService(db).download_file(file_id)
    content_type = result.content_type or entity.content_type or "application/octet-stream"
    headers = {
        "Cache-Control": "private, max-age=3600",
        "Content-Disposition": f'inline; filename="{entity.original_file_name}"',
    }
    return Response(content=result.content, media_type=content_type, headers=headers)
