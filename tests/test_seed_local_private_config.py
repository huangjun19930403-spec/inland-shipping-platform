from __future__ import annotations

import pytest

from app.integrations.config_keys import (
    AMAP_JS_API_KEY,
    AMAP_ROUTE_GEOMETRY_MODE,
    AMAP_ROUTE_GEOMETRY_TIMEOUT_SECONDS,
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
    ES_HISTORY_INDEX_PREFIX,
    ES_HISTORY_TIMEOUT_SECONDS,
    ES_HOST,
    ES_PASSWORD,
    ES_PORT,
    ES_R_HOST,
    ES_R_INDEX,
    ES_R_PASSWORD,
    ES_R_PORT,
    ES_R_SCHEME,
    ES_R_USER,
    ES_SCHEME,
    ES_TIMEOUT_SECONDS,
    ES_USER,
    HIFLEET_BASE_URL,
    HIFLEET_CHECK_LOGIN_COOLDOWN_SECONDS,
    HIFLEET_CHECK_LOGIN_URL,
    HIFLEET_DUPLICATE_LOGIN_RECOVERY_ENABLED,
    VESSEL_IMAGE_AI_API_KEY,
    VESSEL_IMAGE_AI_BASE_URL,
    VESSEL_IMAGE_AI_MODEL,
    VESSEL_IMAGE_AI_PROVIDER,
    VESSEL_IMAGE_AI_TIMEOUT_SECONDS,
    HIFLEET_ENABLED,
    HIFLEET_LOGIN_URL,
    HIFLEET_LOGOUT_URL,
    HIFLEET_PASSWORD,
    HIFLEET_RELOGIN_CHECK_ENABLED,
    HIFLEET_ROUTE_URL,
    HIFLEET_SESSION_COOKIE_TTL_SECONDS,
    HIFLEET_SESSION_IDLE_LOGOUT_SECONDS,
    HIFLEET_SESSION_LOCK_TTL_SECONDS,
    HIFLEET_SESSION_LOGOUT_ON_SHUTDOWN,
    HIFLEET_SESSION_WARMUP_ON_START,
    HIFLEET_TIMEOUT_SECONDS,
    HIFLEET_USERNAME,
)
from scripts.seed_local_private_config import (
    LOCAL_PRIVATE_CONFIG_KEYS,
    export_local_private_vault,
    load_local_private_vault,
    _normalize_config_value,
)
from scripts.seed_system_base import SYSTEM_CONFIGS


def test_local_private_seed_key_set_includes_runtime_credentials() -> None:
    assert {
        AMAP_ROUTE_WEB_API_KEY,
        AMAP_ROUTE_GEOMETRY_MODE,
        AMAP_ROUTE_GEOMETRY_TIMEOUT_SECONDS,
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
        VESSEL_IMAGE_AI_PROVIDER,
        VESSEL_IMAGE_AI_BASE_URL,
        VESSEL_IMAGE_AI_MODEL,
        VESSEL_IMAGE_AI_API_KEY,
        VESSEL_IMAGE_AI_TIMEOUT_SECONDS,
        ES_R_SCHEME,
        ES_R_HOST,
        ES_R_PORT,
        ES_R_USER,
        ES_R_PASSWORD,
        ES_R_INDEX,
        ES_SCHEME,
        ES_HOST,
        ES_PORT,
        ES_USER,
        ES_PASSWORD,
        ES_HISTORY_INDEX_PREFIX,
        ES_HISTORY_TIMEOUT_SECONDS,
        ES_TIMEOUT_SECONDS,
        HIFLEET_ENABLED,
        HIFLEET_BASE_URL,
        HIFLEET_LOGIN_URL,
        HIFLEET_LOGOUT_URL,
        HIFLEET_ROUTE_URL,
        HIFLEET_CHECK_LOGIN_URL,
        HIFLEET_USERNAME,
        HIFLEET_PASSWORD,
        HIFLEET_TIMEOUT_SECONDS,
        HIFLEET_CHECK_LOGIN_COOLDOWN_SECONDS,
        HIFLEET_SESSION_IDLE_LOGOUT_SECONDS,
        HIFLEET_RELOGIN_CHECK_ENABLED,
        HIFLEET_SESSION_WARMUP_ON_START,
        HIFLEET_SESSION_LOGOUT_ON_SHUTDOWN,
        HIFLEET_SESSION_LOCK_TTL_SECONDS,
        HIFLEET_SESSION_COOKIE_TTL_SECONDS,
        HIFLEET_DUPLICATE_LOGIN_RECOVERY_ENABLED,
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
        VESSEL_IMAGE_AI_PROVIDER,
        VESSEL_IMAGE_AI_BASE_URL,
        VESSEL_IMAGE_AI_MODEL,
        VESSEL_IMAGE_AI_API_KEY,
        VESSEL_IMAGE_AI_TIMEOUT_SECONDS,
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


def test_local_private_vault_roundtrip_without_plaintext(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("LOCAL_SEED_MASTER_KEY", raising=False)
    env_file = tmp_path / ".env.local"
    vault_file = tmp_path / "local.private.enc"
    key_file = tmp_path / "local.seed.key"
    env_file.write_text(
        "\n".join(
            [
                "ES_R_HOST=es-realtime.local",
                "ES_R_PWD=realtime-secret",
                "ES_HOST=es-history.local",
                "ES_PWD=history-secret",
                "HIFLEET_ENABLED=1",
                "HIFLEET_PASSWORD=hifleet-secret",
                "ROUTE_GEOMETRY_MODE=real",
            ]
        ),
        encoding="utf-8",
    )

    exported_keys = export_local_private_vault(
        env_file=env_file,
        vault_file=vault_file,
        key_file=key_file,
        include_process_env=False,
    )
    vault_bytes = vault_file.read_bytes()

    assert ES_R_HOST in exported_keys
    assert ES_R_PASSWORD in exported_keys
    assert ES_PASSWORD in exported_keys
    assert b"realtime-secret" not in vault_bytes
    assert b"hifleet-secret" not in vault_bytes

    loaded = load_local_private_vault(vault_file=vault_file, key_file=key_file)
    assert loaded[ES_R_HOST] == "es-realtime.local"
    assert loaded[ES_R_PASSWORD] == "realtime-secret"
    assert loaded[ES_PASSWORD] == "history-secret"
    assert loaded[HIFLEET_ENABLED] == "true"
