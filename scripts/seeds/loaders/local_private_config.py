"""Load local-only integration credentials into system_config.

Local credentials can come from a git-ignored .env.local file or from a
git-ignored encrypted vault.  The vault protects the seed source at rest on a
developer machine; values are still written to system_config as runtime values
because the application currently expects plain text configuration values.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cryptography.fernet import Fernet, InvalidToken
from dotenv import dotenv_values
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.integrations.config_keys import (
    AMAP_JS_API_KEY,
    AMAP_ROUTE_GEOMETRY_MODE,
    AMAP_ROUTE_GEOMETRY_TIMEOUT_SECONDS,
    AMAP_ROUTE_WEB_API_KEY,
    AMAP_SECURITY_JS_CODE,
    AI_PROVIDER,
    COS_ACCESS_KEY,
    COS_BUCKET_NAME,
    COS_ENABLED,
    COS_ENDPOINT,
    COS_IMAGE_MAX_SIZE_MB,
    COS_PATH_STYLE_ACCESS,
    COS_REGION,
    COS_SECRET_KEY,
    COMMODITY_RECOGNITION_AI_MODEL,
    DASHSCOPE_API_KEY,
    DASHSCOPE_BASE_URL,
    DASHSCOPE_STREAM_TIMEOUT_SECONDS,
    DASHSCOPE_TIMEOUT_SECONDS,
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
    FREIGHT_AI_DETAIL_BATCH_SIZE,
    FREIGHT_AI_DETAIL_CONCURRENCY,
    FREIGHT_AI_DETAIL_MODEL,
    FREIGHT_AI_REVIEW_CONFIDENCE_THRESHOLD,
    FREIGHT_AI_REVIEW_MODEL,
    FREIGHT_AI_SEMANTIC_MODEL,
    FREIGHT_AI_STALE_HEARTBEAT_SECONDS,
    FREIGHT_AI_WARN_RAW_CHARS,
    HIFLEET_BASE_URL,
    HIFLEET_CHECK_LOGIN_COOLDOWN_SECONDS,
    HIFLEET_CHECK_LOGIN_URL,
    HIFLEET_DUPLICATE_LOGIN_RECOVERY_ENABLED,
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
    VESSEL_IMAGE_AI_API_KEY,
    VESSEL_IMAGE_AI_BASE_URL,
    VESSEL_IMAGE_AI_MODEL,
    VESSEL_IMAGE_AI_PROVIDER,
    VESSEL_IMAGE_AI_TIMEOUT_SECONDS,
)
from app.models.system import SystemConfig
from scripts.seeds.loaders.system_base import SYSTEM_CONFIGS


LOCAL_ENV_FILE = PROJECT_ROOT / ".env.local"
LOCAL_SEED_DIR = PROJECT_ROOT / ".seed"
LOCAL_PRIVATE_VAULT_FILE = LOCAL_SEED_DIR / "local.private.enc"
LOCAL_SEED_KEY_FILE = LOCAL_SEED_DIR / "local.seed.key"
LOCAL_SEED_MASTER_KEY_ENV = "LOCAL_SEED_MASTER_KEY"

LOCAL_ENVIRONMENTS = {"local", "dev", "development", "test", "testing"}

LOCAL_PRIVATE_CONFIG_KEYS = {
    AMAP_ROUTE_WEB_API_KEY,
    AMAP_ROUTE_GEOMETRY_TIMEOUT_SECONDS,
    AMAP_ROUTE_GEOMETRY_MODE,
    AMAP_JS_API_KEY,
    AMAP_SECURITY_JS_CODE,
    AI_PROVIDER,
    DASHSCOPE_BASE_URL,
    DASHSCOPE_API_KEY,
    DASHSCOPE_TIMEOUT_SECONDS,
    DASHSCOPE_STREAM_TIMEOUT_SECONDS,
    FREIGHT_AI_SEMANTIC_MODEL,
    FREIGHT_AI_DETAIL_MODEL,
    FREIGHT_AI_REVIEW_MODEL,
    FREIGHT_AI_DETAIL_BATCH_SIZE,
    FREIGHT_AI_DETAIL_CONCURRENCY,
    FREIGHT_AI_REVIEW_CONFIDENCE_THRESHOLD,
    FREIGHT_AI_WARN_RAW_CHARS,
    FREIGHT_AI_STALE_HEARTBEAT_SECONDS,
    COMMODITY_RECOGNITION_AI_MODEL,
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
}

LOCAL_PRIVATE_CONFIG_ALIASES = {
    "ES_R_PWD": ES_R_PASSWORD,
    "ES_PWD": ES_PASSWORD,
}

CONFIG_METADATA_BY_KEY = {item["config_key"]: item for item in SYSTEM_CONFIGS}

PrivateConfigSource = Literal["auto", "vault", "env"]


def _assert_plain_local_env_allowed() -> None:
    app_env = (settings.APP_ENV or "").strip().lower()
    seed_profile = (os.getenv("SEED_PROFILE") or "").strip().lower()
    if app_env in LOCAL_ENVIRONMENTS or seed_profile == "local-demo":
        return
    raise RuntimeError(
        ".env.local can only be read in local/demo seed contexts "
        "(APP_ENV=local/dev/test or SEED_PROFILE=local-demo)"
    )


def _apply_aliases(values: dict[str, str]) -> dict[str, str]:
    normalized = dict(values)
    for alias, target_key in LOCAL_PRIVATE_CONFIG_ALIASES.items():
        if alias in normalized and target_key not in normalized:
            normalized[target_key] = normalized[alias]
        env_alias_value = os.getenv(alias)
        if env_alias_value is not None and target_key not in normalized:
            normalized[target_key] = env_alias_value
    return normalized


def _merged_local_values(
    *,
    env_file: Path = LOCAL_ENV_FILE,
    include_process_env: bool = True,
) -> dict[str, str]:
    values: dict[str, str] = {}
    if env_file.exists():
        for key, value in dotenv_values(env_file).items():
            if value is not None:
                values[key] = value

    if include_process_env:
        for key in LOCAL_PRIVATE_CONFIG_KEYS:
            env_value = os.getenv(key)
            if env_value is not None:
                values[key] = env_value

    return _apply_aliases(values)


def _normalize_config_value(key: str, value: str, value_type_code: str) -> str:
    value_clean = str(value).strip()
    if not value_clean:
        return ""

    if value_type_code == "BOOLEAN":
        normalized = value_clean.lower()
        if normalized in {"true", "1", "yes", "y", "on", "enabled"}:
            return "true"
        if normalized in {"false", "0", "no", "n", "off", "disabled"}:
            return "false"
        raise RuntimeError(f"invalid boolean local private config: {key}")

    if value_type_code == "INTEGER":
        try:
            return str(int(value_clean))
        except ValueError as exc:
            raise RuntimeError(f"invalid integer local private config: {key}") from exc

    if value_type_code == "FLOAT":
        try:
            return str(float(value_clean))
        except ValueError as exc:
            raise RuntimeError(f"invalid float local private config: {key}") from exc

    return value_clean


def _target_local_values(values: dict[str, str]) -> dict[str, str]:
    target_values = {
        key: str(value)
        for key, value in _apply_aliases(values).items()
        if key in LOCAL_PRIVATE_CONFIG_KEYS and str(value).strip()
    }
    normalized: dict[str, str] = {}
    for key, raw_value in sorted(target_values.items()):
        metadata = CONFIG_METADATA_BY_KEY.get(key)
        if metadata is None:
            continue
        normalized[key] = _normalize_config_value(
            key,
            raw_value,
            metadata["value_type_code"],
        )
    return normalized


def _read_or_create_master_key(
    *,
    key_file: Path = LOCAL_SEED_KEY_FILE,
    create: bool = False,
) -> bytes:
    env_key = os.getenv(LOCAL_SEED_MASTER_KEY_ENV)
    if env_key:
        key = env_key.strip().encode("utf-8")
    elif key_file.exists():
        key = key_file.read_bytes().strip()
    elif create:
        key = Fernet.generate_key()
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(key + b"\n")
        key_file.chmod(0o600)
    else:
        raise RuntimeError(
            f"local seed key not found: set {LOCAL_SEED_MASTER_KEY_ENV} "
            f"or create {key_file}"
        )

    try:
        Fernet(key)
    except ValueError as exc:
        raise RuntimeError("invalid local seed master key") from exc
    return key


def export_local_private_vault(
    *,
    env_file: Path = LOCAL_ENV_FILE,
    vault_file: Path = LOCAL_PRIVATE_VAULT_FILE,
    key_file: Path = LOCAL_SEED_KEY_FILE,
    include_process_env: bool = True,
) -> list[str]:
    _assert_plain_local_env_allowed()
    values = _target_local_values(
        _merged_local_values(
            env_file=env_file,
            include_process_env=include_process_env,
        )
    )
    if not values:
        raise RuntimeError("no local private values found to export")

    key = _read_or_create_master_key(key_file=key_file, create=True)
    payload = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "values": values,
    }
    token = Fernet(key).encrypt(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    vault_file.parent.mkdir(parents=True, exist_ok=True)
    vault_file.write_bytes(token + b"\n")
    vault_file.chmod(0o600)
    return sorted(values)


def load_local_private_vault(
    *,
    vault_file: Path = LOCAL_PRIVATE_VAULT_FILE,
    key_file: Path = LOCAL_SEED_KEY_FILE,
) -> dict[str, str]:
    if not vault_file.exists():
        raise RuntimeError(f"local private vault not found: {vault_file}")
    key = _read_or_create_master_key(key_file=key_file, create=False)
    try:
        decrypted = Fernet(key).decrypt(vault_file.read_bytes().strip())
    except InvalidToken as exc:
        raise RuntimeError("local private vault cannot be decrypted with current key") from exc

    try:
        payload = json.loads(decrypted.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("local private vault payload is invalid JSON") from exc

    if payload.get("version") != 1 or not isinstance(payload.get("values"), dict):
        raise RuntimeError("local private vault payload version is unsupported")
    return _target_local_values({str(key): str(value) for key, value in payload["values"].items()})


def load_local_private_values(
    *,
    source: PrivateConfigSource = "auto",
    env_file: Path = LOCAL_ENV_FILE,
    vault_file: Path = LOCAL_PRIVATE_VAULT_FILE,
    key_file: Path = LOCAL_SEED_KEY_FILE,
    create_vault_from_env: bool = False,
) -> dict[str, str]:
    if source not in {"auto", "vault", "env"}:
        raise RuntimeError(f"unsupported local private config source: {source}")

    if source == "vault":
        return load_local_private_vault(vault_file=vault_file, key_file=key_file)

    if source == "env":
        _assert_plain_local_env_allowed()
        return _target_local_values(_merged_local_values(env_file=env_file))

    if vault_file.exists():
        return load_local_private_vault(vault_file=vault_file, key_file=key_file)

    if create_vault_from_env and env_file.exists():
        export_local_private_vault(env_file=env_file, vault_file=vault_file, key_file=key_file)
        return load_local_private_vault(vault_file=vault_file, key_file=key_file)

    _assert_plain_local_env_allowed()
    return _target_local_values(_merged_local_values(env_file=env_file))


async def import_local_private_values(values: dict[str, str]) -> list[str]:
    if not values:
        return []

    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)
        applied_keys: list[str] = []

        for key, value in sorted(values.items()):
            metadata = CONFIG_METADATA_BY_KEY.get(key)
            if metadata is None:
                continue

            config = await session.scalar(
                select(SystemConfig).where(SystemConfig.config_key == key)
            )
            if config is None:
                config = SystemConfig(
                    config_key=key,
                    config_name=metadata["config_name"],
                    config_value=value,
                    value_type_code=metadata["value_type_code"],
                    config_group_code=metadata["config_group_code"],
                    config_profile_code=metadata["config_profile_code"],
                    sensitive_flag=metadata["sensitive_flag"],
                    encrypted_flag=metadata["encrypted_flag"],
                    editable_flag=metadata["editable_flag"],
                    sort_order=metadata["sort_order"],
                    config_status_code=metadata["config_status_code"],
                    last_test_status_code=None,
                    last_test_message=None,
                    last_tested_at=None,
                    description=metadata["description"],
                    updated_by=None,
                    updated_at=now,
                    created_at=now,
                )
                session.add(config)
            else:
                config.config_value = value
                config.value_type_code = metadata["value_type_code"]
                config.config_group_code = metadata["config_group_code"]
                config.config_profile_code = metadata["config_profile_code"]
                config.sensitive_flag = metadata["sensitive_flag"]
                config.encrypted_flag = metadata["encrypted_flag"]
                config.editable_flag = metadata["editable_flag"]
                config.config_status_code = "ACTIVE"
                config.updated_at = now

            applied_keys.append(key)

        await session.commit()
    return applied_keys


async def seed_local_private_config(
    *,
    source: PrivateConfigSource = "auto",
    create_vault_from_env: bool = False,
    require_values: bool = False,
) -> list[str]:
    local_values = load_local_private_values(
        source=source,
        create_vault_from_env=create_vault_from_env,
    )
    if not local_values:
        if require_values:
            raise RuntimeError("no local private values found")
        print("seed_local_private_config skipped: no local private values found")
        return []

    applied_keys = await import_local_private_values(local_values)
    print(
        "seed_local_private_config completed: "
        f"applied={len(applied_keys)} keys={','.join(applied_keys)}"
    )
    return applied_keys


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage local private seed config")
    subparsers = parser.add_subparsers(dest="command")

    export_parser = subparsers.add_parser("export-vault")
    export_parser.add_argument("--env-file", type=Path, default=LOCAL_ENV_FILE)
    export_parser.add_argument("--vault-file", type=Path, default=LOCAL_PRIVATE_VAULT_FILE)
    export_parser.add_argument("--key-file", type=Path, default=LOCAL_SEED_KEY_FILE)

    import_parser = subparsers.add_parser("import-vault")
    import_parser.add_argument("--vault-file", type=Path, default=LOCAL_PRIVATE_VAULT_FILE)
    import_parser.add_argument("--key-file", type=Path, default=LOCAL_SEED_KEY_FILE)

    seed_parser = subparsers.add_parser("seed")
    seed_parser.add_argument("--source", choices=["auto", "vault", "env"], default="auto")
    seed_parser.add_argument("--create-vault-from-env", action="store_true")
    seed_parser.add_argument("--require-values", action="store_true")

    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.command == "export-vault":
        keys = export_local_private_vault(
            env_file=args.env_file,
            vault_file=args.vault_file,
            key_file=args.key_file,
        )
        print(f"local private vault exported: keys={','.join(keys)}")
        return

    if args.command == "import-vault":
        values = load_local_private_vault(
            vault_file=args.vault_file,
            key_file=args.key_file,
        )
        applied_keys = asyncio.run(import_local_private_values(values))
        print(f"local private vault imported: keys={','.join(applied_keys)}")
        return

    source = args.source if args.command == "seed" else "auto"
    create_vault_from_env = bool(getattr(args, "create_vault_from_env", False))
    require_values = bool(getattr(args, "require_values", False))
    asyncio.run(
        seed_local_private_config(
            source=source,
            create_vault_from_env=create_vault_from_env,
            require_values=require_values,
        )
    )


if __name__ == "__main__":
    main()
