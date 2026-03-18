"""实体数据 TTL 缓存

替代原来的 NodeQueryTool / CommodityQueryTool（每次解析都全量 SELECT 的性能问题）。
缓存 TTL=10 分钟，asyncio.Lock 保证并发下只有一次刷新操作。

节点或商品数据变更后，调用 invalidate_entity_cache() 强制下次刷新。
"""
import asyncio
import logging
import time
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# 模块级缓存状态
_nodes: Optional[list[dict]] = None
_nodes_loaded_at: float = 0.0
_commodities: Optional[list[dict]] = None
_commodities_loaded_at: float = 0.0
_lock = asyncio.Lock()
_CACHE_TTL = 600  # 10 分钟


async def get_nodes(db: AsyncSession) -> list[dict]:
    """获取所有运输节点（含别名），TTL 缓存。

    返回格式：[{"id", "name", "code", "aliases": list[str], "waterway_id", "region_id"}]
    """
    global _nodes, _nodes_loaded_at
    async with _lock:
        if _nodes is None or time.monotonic() - _nodes_loaded_at > _CACHE_TTL:
            _nodes = await _load_nodes(db)
            _nodes_loaded_at = time.monotonic()
            logger.info("[EntityCache] nodes refreshed count=%d", len(_nodes))
    return _nodes


async def get_commodities(db: AsyncSession) -> list[dict]:
    """获取所有商品标准（含别名），TTL 缓存。

    返回格式：[{"id", "name", "aliases": list[str], "type_id"}]
    """
    global _commodities, _commodities_loaded_at
    async with _lock:
        if _commodities is None or time.monotonic() - _commodities_loaded_at > _CACHE_TTL:
            _commodities = await _load_commodities(db)
            _commodities_loaded_at = time.monotonic()
            logger.info("[EntityCache] commodities refreshed count=%d", len(_commodities))
    return _commodities


def invalidate_entity_cache() -> None:
    """强制使实体缓存失效（节点或商品数据变更时调用）"""
    global _nodes, _commodities
    _nodes = None
    _commodities = None
    logger.info("[EntityCache] cache invalidated")


async def _load_nodes(db: AsyncSession) -> list[dict]:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models.address import TransportNode

    result = await db.execute(
        select(TransportNode)
        .where(TransportNode.deleted_at.is_(None))
        .options(selectinload(TransportNode.aliases))
    )
    nodes = result.scalars().unique().all()
    return [
        {
            "id": n.id,
            "name": n.name,
            "code": getattr(n, "code", "") or "",
            "aliases": [a.alias_name for a in (n.aliases or [])],
            "waterway_id": getattr(n, "waterway_id", None),
            "region_id": getattr(n, "region_id", None),
        }
        for n in nodes
    ]


async def _load_commodities(db: AsyncSession) -> list[dict]:
    from sqlalchemy import select
    from app.models.cargo import CommodityStandard, CommodityAlias

    alias_result = await db.execute(
        select(CommodityAlias).where(CommodityAlias.status == 1)
    )
    id_to_aliases: dict[int, list[str]] = {}
    for a in alias_result.scalars().all():
        id_to_aliases.setdefault(a.commodity_id, []).append(a.alias_name)

    std_result = await db.execute(
        select(CommodityStandard).where(CommodityStandard.deleted_at.is_(None))
    )
    return [
        {
            "id": s.id,
            "name": s.name,
            "aliases": id_to_aliases.get(s.id, []),
            "type_id": s.type_id,
        }
        for s in std_result.scalars().all()
    ]
