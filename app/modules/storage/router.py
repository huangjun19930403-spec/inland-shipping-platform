from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.storage.service import FileStorageService

router = APIRouter(dependencies=[Depends(get_current_user)])


def _content_disposition_header(filename: str | None) -> str:
    safe_name = Path(filename or "download").name.strip() or "download"
    safe_name = safe_name.replace("\r", "").replace("\n", "")
    safe_path = Path(safe_name)
    ascii_stem = re.sub(r"[^0-9A-Za-z._-]+", "_", safe_path.stem).strip("._")
    ascii_suffix = safe_path.suffix if re.fullmatch(r"\.[0-9A-Za-z]+", safe_path.suffix or "") else ""
    ascii_fallback = f"{ascii_stem or 'download'}{ascii_suffix}"
    encoded_name = quote(safe_name, safe="")
    return f'inline; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded_name}'


@router.get("/{file_id}/content")
async def get_file_content(
    file_id: int,
    db: AsyncSession = Depends(get_db),
):
    entity, result = await FileStorageService(db).download_file(file_id)
    content_type = result.content_type or entity.content_type or "application/octet-stream"
    headers = {
        "Cache-Control": "private, max-age=3600",
        "Content-Disposition": _content_disposition_header(entity.original_file_name),
    }
    return Response(content=result.content, media_type=content_type, headers=headers)
