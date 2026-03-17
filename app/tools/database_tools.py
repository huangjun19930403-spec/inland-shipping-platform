"""
数据库查询工具
职责：为AI Agent提供只读的数据库查询能力
AI模块通过此Tool访问数据，而不直接操作SQLAlchemy Session
"""
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import BaseTool, ToolResult
from app.repositories.address_repository import AddressRepository
from app.repositories.cargo_repository import CargoRepository

logger = logging.getLogger(__name__)


class NodeQueryTool(BaseTool):
    """
    节点查询工具

    为AI Agent提供运输节点数据的只读访问。
    不提供写操作——AI不修改节点数据。
    """

    name = "node_query"
    description = "查询内河运输节点数据（港口、码头等），用于实体匹配"

    def __init__(self, db: AsyncSession) -> None:
        self._repo = AddressRepository(db)

    async def execute(
        self,
        include_aliases: bool = True,
        **kwargs: Any,
    ) -> ToolResult:
        """
        获取所有节点数据供AI匹配使用

        Returns:
            ToolResult.data = list[{
                "id": int,
                "name": str,
                "code": str,
                "aliases": list[str]
            }]
        """
        try:
            nodes = await self._repo.get_all_nodes_with_aliases()
            entity_list = []
            for node in nodes:
                aliases = []
                if include_aliases and hasattr(node, "aliases"):
                    aliases = [a.alias_name for a in node.aliases]
                entity_list.append({
                    "id": node.id,
                    "name": node.name,
                    "code": getattr(node, "code", ""),
                    "aliases": aliases,
                    "waterway_id": getattr(node, "waterway_id", None),
                    "region_id": getattr(node, "region_id", None),
                })
            return ToolResult(success=True, data=entity_list)
        except Exception as e:
            logger.error(f"[NodeQueryTool] Error: {e}")
            return ToolResult(success=False, error=str(e), data=[])


class CommodityQueryTool(BaseTool):
    """
    商品查询工具

    为AI Agent提供商品/货物数据的只读访问。
    """

    name = "commodity_query"
    description = "查询商品/货物标准数据，用于货名实体匹配"

    def __init__(self, db: AsyncSession) -> None:
        self._repo = CargoRepository(db)

    async def execute(
        self,
        include_aliases: bool = True,
        **kwargs: Any,
    ) -> ToolResult:
        """
        获取所有商品数据供AI匹配使用

        Returns:
            ToolResult.data = list[{
                "id": int,
                "name": str,
                "type_name": str,
                "aliases": list[str]
            }]
        """
        try:
            aliases = await self._repo.aliases.get_all_aliases()

            # 构建id→aliases映射
            id_to_aliases: dict[int, list[str]] = {}
            for alias in aliases:
                sid = alias.commodity_id
                if sid not in id_to_aliases:
                    id_to_aliases[sid] = []
                id_to_aliases[sid].append(alias.alias_name)

            # 获取所有商品标准
            standards = await self._repo.standards.get_all()

            entity_list = []
            for std in standards:
                entity_list.append({
                    "id": std.id,
                    "name": std.name,
                    "aliases": id_to_aliases.get(std.id, []),
                    "type_id": std.type_id,
                })

            return ToolResult(success=True, data=entity_list)
        except Exception as e:
            logger.error(f"[CommodityQueryTool] Error: {e}")
            return ToolResult(success=False, error=str(e), data=[])
