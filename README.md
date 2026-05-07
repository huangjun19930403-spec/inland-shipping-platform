# Inland Shipping Platform Backend

内河航运数据分析平台后端，采用 FastAPI + SQLAlchemy + Alembic 的模块化单体结构。当前基线覆盖基础数据、船舶、货源采集、航线规划、数据分析、审核治理和系统管理，支持本地一键重建 seed 并运行最终验收脚本。

## Modules

- `dictionary`: 字典、字典项、编码序列
- `system` / `auth`: 登录、用户、角色、菜单、配置、日志
- `audit`: 审核队列、对象快照、字段差异、审核记录
- `address`: 行政区划、业务区域、运输节点、通航约束点
- `commodity`: 货品分类/类型只读元数据、标准货品、别名和规则
- `ship`: 船舶主档、尺度载重、运营、主体联系人、证照、历史
- `freight`: 正式货源、来源接入、通义千问解析任务、候选确认
- `route`: 航线、运输方案、路线结构、轨迹预览
- `analysis`: 指标、事实表、快照、分析任务和图表/地图接口

## Local Setup

```bash
alembic upgrade head
python -m scripts.seed_system_init
python -m scripts.verify_local_acceptance
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

- OpenAPI: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

本地私有集成配置可写入 `.env.local` 或运行时环境变量。`.env.local` 已被 Git 忽略，
`python -m scripts.seed_system_init` 会在基础 seed 后把这些值覆盖写入本地 `system_config`；
基础 seed 重复执行时不会清空已有敏感配置。

```bash
ROUTE_AMAP_WEB_API_KEY=
AMAP_JS_API_KEY=
AMAP_SECURITY_JS_CODE=
AI_PROVIDER=DASHSCOPE_QWEN
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_API_KEY=
DASHSCOPE_STREAM_TIMEOUT_SECONDS=120
FREIGHT_AI_SEMANTIC_MODEL=qwen-plus
FREIGHT_AI_DETAIL_MODEL=qwen-turbo
FREIGHT_AI_REVIEW_MODEL=qwen-plus
FREIGHT_AI_DETAIL_BATCH_SIZE=8
FREIGHT_AI_DETAIL_CONCURRENCY=2
FREIGHT_AI_REVIEW_CONFIDENCE_THRESHOLD=0.80
FREIGHT_AI_WARN_RAW_CHARS=20000
FREIGHT_AI_STALE_HEARTBEAT_SECONDS=180
HIFLEET_ENABLED=true
HIFLEET_USERNAME=
HIFLEET_PASSWORD=
```

## Final Docs

1. [BACKEND_OVERVIEW_AND_ARCHITECTURE.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/BACKEND_OVERVIEW_AND_ARCHITECTURE.md)
2. [BACKEND_DATA_MODEL_AND_SEQUENCE.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/BACKEND_DATA_MODEL_AND_SEQUENCE.md)
3. [BACKEND_SEED_AND_INITIALIZATION.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/BACKEND_SEED_AND_INITIALIZATION.md)
4. [BACKEND_API_REFERENCE.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/BACKEND_API_REFERENCE.md)
5. [BACKEND_FINAL_ACCEPTANCE_REPORT.md](/Users/hj/Documents/paltform_data_V2/inland-shipping-platform/docs/BACKEND_FINAL_ACCEPTANCE_REPORT.md)
