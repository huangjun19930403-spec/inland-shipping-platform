from __future__ import annotations

import io
from datetime import datetime

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import BigInteger
from starlette.datastructures import Headers, UploadFile

import app.models  # noqa: F401
from app.core.exceptions import ValidationError
from app.integrations.config_keys import (
    COS_ACCESS_KEY,
    COS_BUCKET_NAME,
    COS_CONFIG_PROFILE,
    COS_ENABLED,
    COS_IMAGE_MAX_SIZE_MB,
    COS_REGION,
    COS_SECRET_KEY,
)
from app.integrations.storage import ObjectStorageResult
from app.models.address import AdminRegion, TransportNode, TransportNodeContact
from app.models.base import Base
from app.models.system import SystemConfig
from app.modules.address.schemas import TransportNodeContactItem, TransportNodeContactReplaceRequest
from app.modules.address.service import TransportNodeService
from app.modules.storage.router import _content_disposition_header
from app.modules.storage.service import FileStorageService


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(element, compiler, **kw) -> str:
    _ = element, compiler, kw
    return "INTEGER"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


class FakeObjectStorageClient:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.deleted: list[tuple[str, str]] = []

    async def put_object(self, *, bucket: str, key: str, body: bytes, content_type: str) -> None:
        self.objects[(bucket, key)] = (body, content_type)

    async def get_object(self, *, bucket: str, key: str) -> ObjectStorageResult:
        body, content_type = self.objects[(bucket, key)]
        return ObjectStorageResult(content=body, content_type=content_type)

    async def delete_object(self, *, bucket: str, key: str) -> None:
        self.deleted.append((bucket, key))
        self.objects.pop((bucket, key), None)


async def _seed_node(session: AsyncSession) -> TransportNode:
    city = AdminRegion(
        code="320100",
        name="南京市",
        short_name="南京",
        level=2,
        province_code="320000",
        city_code="320100",
        status=1,
    )
    session.add(city)
    await session.flush()
    node = TransportNode(
        code="ND-COS",
        name="南京测试码头",
        node_type_code="TERMINAL",
        province_code="320000",
        city_code="320100",
        city_region_id=city.id,
        status=1,
        lifecycle_status_code="ACTIVE",
        audit_status="APPROVED",
    )
    session.add(node)
    await session.commit()
    return node


def _system_config(key: str, value: str, value_type: str, sensitive: int = 0) -> SystemConfig:
    now = datetime.utcnow()
    return SystemConfig(
        config_key=key,
        config_name=key,
        config_value=value,
        value_type_code=value_type,
        config_group_code="FILE_STORAGE",
        config_profile_code=COS_CONFIG_PROFILE,
        sensitive_flag=sensitive,
        encrypted_flag=0,
        editable_flag=1,
        sort_order=0,
        config_status_code="ACTIVE",
        updated_at=now,
        created_at=now,
    )


async def _seed_cos_config(session: AsyncSession) -> None:
    session.add_all(
        [
            _system_config(COS_ENABLED, "true", "BOOLEAN"),
            _system_config(COS_BUCKET_NAME, "unit-test-bucket-0000000000", "STRING"),
            _system_config(COS_REGION, "ap-nanjing", "STRING"),
            _system_config(COS_ACCESS_KEY, "test-secret-id", "STRING", 1),
            _system_config(COS_SECRET_KEY, "test-secret-key", "STRING", 1),
            _system_config(COS_IMAGE_MAX_SIZE_MB, "1", "INTEGER"),
        ]
    )
    await session.commit()


def _image_upload(filename: str = "node.jpg", content_type: str = "image/jpeg") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(b"\xff\xd8test-image\xff\xd9"),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def test_file_content_disposition_supports_chinese_filename() -> None:
    header = _content_disposition_header("船舶证件资料.pdf")

    assert "船舶证件资料" not in header
    assert 'filename="download.pdf"' in header
    assert "filename*=UTF-8''%E8%88%B9%E8%88%B6%E8%AF%81%E4%BB%B6%E8%B5%84%E6%96%99.pdf" in header
    header.encode("latin-1")


@pytest.mark.asyncio
async def test_replace_node_contacts_keeps_single_primary(session: AsyncSession) -> None:
    node = await _seed_node(session)
    service = TransportNodeService(session)

    result = await service.replace_node_contacts(
        node.id,
        TransportNodeContactReplaceRequest(
            contacts=[
                TransportNodeContactItem(
                    contact_name="运营值班",
                    contact_type_code="OPERATIONS",
                    mobile_phone="025-88000000",
                    is_primary=False,
                ),
                TransportNodeContactItem(
                    contact_name="商务值班",
                    contact_type_code="BUSINESS",
                    mobile_phone="13800000000",
                    is_primary=False,
                ),
            ]
        ),
    )

    assert [item.contact_name for item in result] == ["运营值班", "商务值班"]
    assert [item.is_primary for item in result] == [True, False]

    rows = (await session.execute(sa.select(TransportNodeContact).where(TransportNodeContact.node_id == node.id))).scalars().all()
    assert sum(1 for row in rows if row.is_primary) == 1


def test_current_baseline_contains_node_contact_tables_without_legacy_profile_columns() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        inspector = sa.inspect(conn)
        columns = {column["name"] for column in inspector.get_columns("transport_node_profile")}
        tables = set(inspector.get_table_names())

    assert "contact_person" not in columns
    assert "contact_phone" not in columns
    assert "transport_node_contact" in tables
    assert "transport_node_photo" in tables


@pytest.mark.asyncio
async def test_image_upload_uses_injected_cos_adapter(session: AsyncSession) -> None:
    await _seed_cos_config(session)
    fake_client = FakeObjectStorageClient()
    service = FileStorageService(session, object_client=fake_client)

    entity = await service.upload_image(
        file=_image_upload(),
        object_prefix="transport-nodes/1/photos",
        uploaded_by=7,
    )
    await session.commit()

    assert entity.bucket_name == "unit-test-bucket-0000000000"
    assert entity.object_key.startswith("transport-nodes/1/photos/")
    assert entity.content_type == "image/jpeg"
    assert fake_client.objects[(entity.bucket_name, entity.object_key)][0].startswith(b"\xff\xd8")

    _, downloaded = await service.download_file(entity.id)
    assert downloaded.content_type == "image/jpeg"
    assert downloaded.content.endswith(b"\xff\xd9")


@pytest.mark.asyncio
async def test_image_upload_fails_without_enabled_cos_config(session: AsyncSession) -> None:
    service = FileStorageService(session, object_client=FakeObjectStorageClient())

    with pytest.raises(ValidationError, match="COS 文件存储未启用"):
        await service.upload_image(file=_image_upload(), object_prefix="transport-nodes/1/photos")
