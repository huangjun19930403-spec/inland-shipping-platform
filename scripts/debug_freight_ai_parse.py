"""Local freight AI parsing debugger.

Usage:
    python -m scripts.debug_freight_ai_parse --file /tmp/wechat.txt
    python -m scripts.debug_freight_ai_parse --sample
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from app.core.database import AsyncSessionLocal
from app.integrations.ai import DashScopeQwenFreightParserClient
from app.modules.freight.service import FreightBatchTaskService
from app.modules.system.runtime_config import RuntimeConfigService

SAMPLE_TEXT = """建德—平湖：塘渣
建德—嘉兴：塘渣
建德—德清：塘渣
下雨天正常装卸
建德—绍兴：机沙
运费18元装卸快
联系19521552671陈 富阳到绍兴新能源石子
富阳到绍兴十九号石子
桐庐到五杭临平机沙石子装卸快
桐庐到杭州石子大船
桐庐到上海塘渣
桐庐到嘉兴塘渣
桐庐到海宁塘渣
江阴到绍兴沙运费，过几天要，这几天船已经够了
建德到绍兴港石子
建德到绍兴新能源石子机沙
建德到五杭临平石子装卸快
建德到嘉兴石子大船可以安排一条
建德到杭州石子50米以内
装卸快，现金结算
电话联系15381664761蒋姐
金汇闸口——北沙港 1300吨左右 装卸快 现金
丹阳龙江钢厂发绍兴上虞钢坯3500吨，随到随装，联系电话13815161412王"""


def _read_text(args: argparse.Namespace) -> str:
    if args.sample:
        return SAMPLE_TEXT
    if args.file:
        return Path(args.file).read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("请通过 --file、--sample 或 stdin 提供待解析文本")


async def _match_segment(service: FreightBatchTaskService, segment: dict[str, Any]) -> dict[str, Any]:
    commodity_text = str(segment.get("commodity_name") or segment.get("cargo_name") or "")
    origin_text = str(segment.get("origin_text") or segment.get("loading_place") or "")
    destination_text = str(segment.get("destination_text") or segment.get("unloading_place") or "")
    commodity_id, commodity_score, commodity_level, commodity_options, commodity_basis = await service._match_commodity(commodity_text)
    origin, origin_options, origin_basis = await service._match_location(origin_text)
    destination, destination_options, destination_basis = await service._match_location(destination_text)
    return {
        "commodity": {
            "raw": commodity_text,
            "standard_id": commodity_id,
            "score": str(commodity_score) if commodity_score is not None else None,
            "level": commodity_level,
            "options": commodity_options,
            "basis": commodity_basis,
        },
        "origin": {"raw": origin_text, "matched": {**origin, "match_score": str(origin.get("match_score")) if origin.get("match_score") is not None else None}, "options": origin_options, "basis": origin_basis},
        "destination": {"raw": destination_text, "matched": {**destination, "match_score": str(destination.get("match_score")) if destination.get("match_score") is not None else None}, "options": destination_options, "basis": destination_basis},
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="调试微信群/TMS 货源 AI 解析链路")
    parser.add_argument("--file", help="待解析文本文件")
    parser.add_argument("--sample", action="store_true", help="使用内置微信群样例")
    parser.add_argument("--source", default="WECHAT", choices=["WECHAT", "TMS"], help="来源类型")
    args = parser.parse_args()
    raw_text = _read_text(args)
    async with AsyncSessionLocal() as db:
        runtime_config = RuntimeConfigService(db)
        ai_client = DashScopeQwenFreightParserClient(runtime_config=runtime_config)
        parsed = await ai_client.parse(raw_text, source_type_code=args.source)
        service = FreightBatchTaskService(db)
        output = {
            "provider": parsed.provider,
            "model": parsed.model,
            "prompt_version": parsed.prompt_version,
            "segment_count": len(parsed.segments),
            "segments": [],
        }
        for index, segment in enumerate(parsed.segments, start=1):
            output["segments"].append(
                {
                    "index": index,
                    "segment": segment,
                    "match_suggestions": await _match_segment(service, segment),
                }
            )
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
