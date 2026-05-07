from __future__ import annotations

import pytest

from app.integrations.config_keys import (
    AMAP_JS_API_KEY,
    AMAP_ROUTE_WEB_API_KEY,
    AMAP_SECURITY_JS_CODE,
    COS_ACCESS_KEY,
    COS_BUCKET_NAME,
    COS_ENABLED,
    COS_ENDPOINT,
    COS_IMAGE_MAX_SIZE_MB,
    COS_PATH_STYLE_ACCESS,
    COS_REGION,
    COS_SECRET_KEY,
    DASHSCOPE_API_KEY,
    FREIGHT_AI_DETAIL_BATCH_SIZE,
    FREIGHT_AI_DETAIL_CONCURRENCY,
    FREIGHT_AI_DETAIL_MODEL,
    FREIGHT_AI_REVIEW_CONFIDENCE_THRESHOLD,
    FREIGHT_AI_REVIEW_MODEL,
    FREIGHT_AI_SEMANTIC_MODEL,
    FREIGHT_AI_WARN_RAW_CHARS,
    HIFLEET_ENABLED,
    HIFLEET_PASSWORD,
    HIFLEET_USERNAME,
)
from scripts.seed_local_private_config import (
    LOCAL_PRIVATE_CONFIG_KEYS,
    _normalize_config_value,
)
from scripts.seed_system_base import SYSTEM_CONFIGS


def test_local_private_seed_key_set_includes_runtime_credentials() -> None:
    assert {
        AMAP_ROUTE_WEB_API_KEY,
        AMAP_JS_API_KEY,
        AMAP_SECURITY_JS_CODE,
        DASHSCOPE_API_KEY,
        FREIGHT_AI_SEMANTIC_MODEL,
        FREIGHT_AI_DETAIL_MODEL,
        FREIGHT_AI_REVIEW_MODEL,
        FREIGHT_AI_DETAIL_BATCH_SIZE,
        FREIGHT_AI_DETAIL_CONCURRENCY,
        FREIGHT_AI_REVIEW_CONFIDENCE_THRESHOLD,
        FREIGHT_AI_WARN_RAW_CHARS,
        HIFLEET_ENABLED,
        HIFLEET_USERNAME,
        HIFLEET_PASSWORD,
        COS_ENABLED,
        COS_BUCKET_NAME,
        COS_REGION,
        COS_ENDPOINT,
        COS_ACCESS_KEY,
        COS_SECRET_KEY,
        COS_PATH_STYLE_ACCESS,
        COS_IMAGE_MAX_SIZE_MB,
    }.issubset(LOCAL_PRIVATE_CONFIG_KEYS)
    assert "DASHSCOPE_FAST_MODEL" not in LOCAL_PRIVATE_CONFIG_KEYS
    assert "DASHSCOPE_MODEL" not in LOCAL_PRIVATE_CONFIG_KEYS
    assert "DASHSCOPE_STRONG_REVIEW_ENABLED" not in LOCAL_PRIVATE_CONFIG_KEYS


def test_system_seed_uses_freight_ai_specific_model_keys() -> None:
    seeded_keys = {item["config_key"] for item in SYSTEM_CONFIGS}

    assert {
        FREIGHT_AI_SEMANTIC_MODEL,
        FREIGHT_AI_DETAIL_MODEL,
        FREIGHT_AI_REVIEW_MODEL,
        FREIGHT_AI_DETAIL_BATCH_SIZE,
        FREIGHT_AI_DETAIL_CONCURRENCY,
        FREIGHT_AI_REVIEW_CONFIDENCE_THRESHOLD,
        FREIGHT_AI_WARN_RAW_CHARS,
    }.issubset(seeded_keys)
    assert "DASHSCOPE_FAST_MODEL" not in seeded_keys
    assert "DASHSCOPE_MODEL" not in seeded_keys
    assert "DASHSCOPE_STRONG_REVIEW_ENABLED" not in seeded_keys


def test_local_private_seed_normalizes_boolean_values() -> None:
    assert _normalize_config_value(HIFLEET_ENABLED, "1", "BOOLEAN") == "true"
    assert _normalize_config_value(HIFLEET_ENABLED, "off", "BOOLEAN") == "false"


def test_local_private_seed_rejects_invalid_typed_values() -> None:
    with pytest.raises(RuntimeError):
        _normalize_config_value(HIFLEET_ENABLED, "maybe", "BOOLEAN")
    with pytest.raises(RuntimeError):
        _normalize_config_value("ROUTE_GEOMETRY_TIMEOUT_SECONDS", "slow", "FLOAT")
