from __future__ import annotations

import json
from pathlib import Path

from scripts.seeds.curation.vessel_seed import curate_vessels, validate_curated_vessels


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_curate_vessels_merges_ais_mmsi_and_keeps_platform_id_as_source_only() -> None:
    tms_rows = [
        {
            "ship_id": "1",
            "name": "测试船A",
            "mmsi": "123456789",
            "ais_code": "123456789",
            "ship_code": "CB-TMS-001",
            "ship_type": "1",
            "contact_name": "张三",
            "contact_phone": "13800000000",
            "contact_wechat": "wx-zhangsan",
            "deadweight_tonnage": "",
        },
        {
            "ship_id": "2",
            "name": "冲突船",
            "mmsi": "223456789",
            "ais_code": "323456789",
        },
    ]
    high_value_rows = [
        {
            "平台唯一ID(aisId)": "999999999",
            "MMSI(AIS通信码)": "123456789",
            "船舶中文名": "测试船A档案",
            "船舶类型": "散货船",
            "船籍港": "南京",
            "载重吨(t)": "680680.0",
            "船长(m)": "88.8",
            "船宽(m)": "15.2",
            "建造年份": "2020",
            "国籍": "中国",
            "机构名称": "南京市交通运输局",
        }
    ]
    admin_rows = [
        {"adcode": "320100", "name": "南京市", "short_name": "南京", "level": "city"},
    ]

    vessels, report = curate_vessels(
        tms_rows,
        high_value_rows,
        admin_rows=admin_rows,
        freight_ship_names={"测试船A"},
    )

    validate_curated_vessels(vessels)
    assert len(vessels) == 1
    vessel = vessels[0]
    assert vessel["mmsi"] == "123456789"
    assert vessel["source_type_code"] == "TMS_HIGH_VALUE"
    assert vessel["ship_name"] == "测试船A"
    assert vessel["ship_type_code"] == "DRY_BULK"
    assert vessel["registry_city_code"] == "320100"
    assert vessel["capacity"].get("deadweight_ton") is None
    assert vessel["capacity"]["length_m"] == 88.8
    assert vessel["contacts"][0]["mobile_phone"] == "13800000000"
    assert vessel["contacts"][0]["wechat"] == "wx-zhangsan"
    assert "999999999" not in {item["identifier_value"] for item in vessel["extra_identifiers"]}
    assert report["excluded"]["tms_mmsi_ais_conflict"] == 1
    assert report["freight_ship_names_matched"] == 1


def test_production_vessel_seed_json_is_static_clean_and_unique() -> None:
    path = PROJECT_ROOT / "scripts" / "seed_data" / "vessel" / "production_vessels.json"
    rows = json.loads(path.read_text(encoding="utf-8"))

    validate_curated_vessels(rows)
    assert len(rows) >= 70000
    assert len({row["mmsi"] for row in rows}) == len(rows)
    assert {"TMS", "HIGH_VALUE_INLAND", "TMS_HIGH_VALUE"} <= {
        row["source_type_code"] for row in rows
    }
    payload = json.dumps(rows[:200], ensure_ascii=False)
    assert "LOCAL_SAMPLE" not in payload
    assert "SEED_AIS_CURRENT" not in payload
