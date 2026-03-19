"""核心 API smoke tests（Phase 6）。"""
import pytest


@pytest.mark.asyncio
async def test_standard_data_api_smoke(client):
    create_resp = await client.post(
        "/api/v1/standard-data/address/waterway",
        json={
            "name": "测试水系",
            "level": 1,
            "status": 1,
        },
    )
    assert create_resp.status_code == 200
    create_data = create_resp.json()
    assert create_data["code"] == 200
    assert create_data["data"]["code"]

    list_resp = await client.get("/api/v1/standard-data/address/waterway")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["code"] == 200
    assert len(list_data["data"]) >= 1


@pytest.mark.asyncio
async def test_ingestion_api_smoke(client):
    resp = await client.post(
        "/api/v1/ingestion/vessel/dynamic/412345678",
        json={
            "data_source": "AIS",
            "current_longitude": 118.78,
            "current_latitude": 32.04,
            "current_city_code": "320100",
            "position_match_type": "UNKNOWN",
            "vessel_status": "UNDERWAY",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["code"] == 200
    assert payload["data"]["mmsi"] == "412345678"


@pytest.mark.asyncio
async def test_analysis_api_smoke(client):
    resp = await client.get("/api/v1/analysis/dashboard")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["code"] == 200
    assert "cargo_total" in payload["data"]
    assert "active_vessels" in payload["data"]
