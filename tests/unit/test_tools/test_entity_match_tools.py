"""
EntityMatchTool单元测试
验证核心模糊匹配逻辑
"""
import pytest
from app.tools.entity_match_tools import EntityMatchTool


@pytest.fixture
def tool():
    return EntityMatchTool()


@pytest.fixture
def sample_entities():
    return [
        {"id": 1, "name": "南京港", "aliases": ["南京", "宁港"]},
        {"id": 2, "name": "武汉港", "aliases": ["汉口", "武汉"]},
        {"id": 3, "name": "上海港", "aliases": ["上海", "申港"]},
    ]


@pytest.mark.asyncio
async def test_exact_match(tool, sample_entities):
    result = await tool.execute(text="南京港", entities=sample_entities)
    assert result.success
    assert result.data["best_match"].entity_id == 1
    assert result.data["match_confidence"] == 100


@pytest.mark.asyncio
async def test_alias_match(tool, sample_entities):
    result = await tool.execute(text="汉口", entities=sample_entities)
    assert result.success
    assert result.data["best_match"].entity_id == 2


@pytest.mark.asyncio
async def test_fuzzy_match(tool, sample_entities):
    result = await tool.execute(text="武汉码头", entities=sample_entities)
    assert result.success
    # 模糊匹配应返回武汉相关节点
    assert result.data["best_match"] is not None


@pytest.mark.asyncio
async def test_empty_text(tool, sample_entities):
    result = await tool.execute(text="", entities=sample_entities)
    assert result.success
    assert result.data["best_match"] is None


@pytest.mark.asyncio
async def test_no_match(tool, sample_entities):
    result = await tool.execute(
        text="完全不存在的地名XYZ", entities=sample_entities, threshold=90
    )
    assert result.success
    assert result.data["best_match"] is None
