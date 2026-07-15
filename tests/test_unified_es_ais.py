from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.integrations.es.realtime_client import RealtimeEsClient
from app.modules.vessel.ais.service import VesselAisService
from app.modules.vessel.spatial_service import VesselSpatialAnalysisService


@pytest.mark.asyncio
async def test_realtime_positions_normalize_geo_point_location(monkeypatch: pytest.MonkeyPatch) -> None:
    service = VesselAisService.__new__(VesselAisService)

    class RuntimeConfig:
        async def get_value(self, key, default=None, *, profile_code=None):  # noqa: ANN001
            return "ship_main_data"

    async def search(_self, index, query_body):  # noqa: ANN001
        assert index == "ship_main_data"
        assert "location" in query_body["_source"]
        return {
            "hits": {
                "hits": [
                    {
                        "_index": "ship_main_data",
                        "_source": {
                            "shipMmsi": "413847931",
                            "location": {"lon": 120.301268, "lat": 30.504255},
                            "posTime": 1782429614000,
                            "speed": 4.3,
                            "cog": 93.9,
                            "head": 93,
                            "shipName": "远洋6655",
                            "shipTypeCode": "0201",
                        },
                    }
                ]
            }
        }

    service.runtime_config = RuntimeConfig()
    service._ais_es_request_timeout_seconds = lambda: asyncio.sleep(0, result=1.0)  # type: ignore[method-assign]
    monkeypatch.setattr(RealtimeEsClient, "search", search)

    result = await service._search_realtime_positions(["413847931"], max_hits=10)

    assert result["413847931"]["longitude"] == Decimal("120.301268")
    assert result["413847931"]["latitude"] == Decimal("30.504255")
    assert result["413847931"]["source_index"] == "ship_main_data"
    assert result["413847931"]["heading_deg"] == 93


@pytest.mark.asyncio
async def test_history_search_uses_unified_es_fields_without_keyword() -> None:
    now = datetime.utcnow()

    class RuntimeConfig:
        async def get_value(self, key, default=None, *, profile_code=None):  # noqa: ANN001
            values = {
                "ES_HOST": "local.zchytc.store",
                "ES_HISTORY_INDEX_PREFIX": "ship_main_data",
            }
            return values.get(key, default)

        async def get_int(self, key, default=0, *, profile_code=None):  # noqa: ANN001
            return default

    class HistoryClient:
        async def search(self, index, body):  # noqa: ANN001
            assert index == "ship_main_data"
            filters = body["query"]["bool"]["filter"]
            mmsi_should = filters[0]["bool"]["should"]
            assert {"terms": {"shipMmsi": ["412000001"]}} in mmsi_should
            assert {"terms": {"mmsi.keyword": ["412000001"]}} in mmsi_should
            assert "location" in body["_source"]
            return {
                "hits": {
                    "hits": [
                        {
                            "_index": "ship_main_data",
                            "_source": {
                                "shipMmsi": "412000001",
                                "location": {"lon": 118.781, "lat": 32.041},
                                "posTime": int((now - timedelta(hours=2)).timestamp() * 1000),
                                "speed": 5.0,
                                "cog": 90,
                                "head": 91,
                            },
                        },
                        {
                            "_index": "ship_main_data",
                            "_source": {
                                "shipMmsi": "412000001",
                                "location": {"lon": 118.782, "lat": 32.042},
                                "posTime": int((now - timedelta(hours=1)).timestamp() * 1000),
                                "speed": 5.2,
                                "cog": 92,
                                "head": 93,
                            },
                        },
                    ]
                }
            }

    service = VesselSpatialAnalysisService.__new__(VesselSpatialAnalysisService)
    service.runtime_config = RuntimeConfig()
    service.history_client = HistoryClient()

    result = await service._search_history_positions(["412000001"], now - timedelta(hours=3), now)

    assert result.source_status_code == "AVAILABLE"
    assert len(result.points_by_mmsi["412000001"]) == 2
    assert result.points_by_mmsi["412000001"][0]["longitude"] == 118.781
    assert result.points_by_mmsi["412000001"][0]["heading_deg"] == 91


@pytest.mark.asyncio
async def test_history_search_does_not_treat_latest_point_as_track() -> None:
    now = datetime.utcnow()

    class RuntimeConfig:
        async def get_value(self, key, default=None, *, profile_code=None):  # noqa: ANN001
            values = {
                "ES_HOST": "local.zchytc.store",
                "ES_HISTORY_INDEX_PREFIX": "ship_main_data",
            }
            return values.get(key, default)

        async def get_int(self, key, default=0, *, profile_code=None):  # noqa: ANN001
            return default

    class HistoryClient:
        async def search(self, index, body):  # noqa: ANN001
            return {
                "hits": {
                    "hits": [
                        {
                            "_index": "ship_main_data",
                            "_source": {
                                "shipMmsi": "412000001",
                                "location": {"lon": 118.781, "lat": 32.041},
                                "posTime": int(now.timestamp() * 1000),
                            },
                        }
                    ]
                }
            }

    service = VesselSpatialAnalysisService.__new__(VesselSpatialAnalysisService)
    service.runtime_config = RuntimeConfig()
    service.history_client = HistoryClient()

    result = await service._search_history_positions(["412000001"], now - timedelta(hours=3), now)

    assert result.source_status_code == "PARTIAL"
    assert result.partial is True
    assert result.points_by_mmsi == {}
    assert result.failed_batches[0]["error_code"] == "HISTORICAL_AIS_INSUFFICIENT"
