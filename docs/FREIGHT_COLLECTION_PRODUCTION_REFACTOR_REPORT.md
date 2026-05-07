# 货源采集生产化重构报告

日期：2026-05-07

## 重构目标

本次重构将货源模块拆为两条主线：

- 货源分析：只消费已确认的正式货源 `freight`，正式货源总量包含节点级、城市级和原文级货源。
- 货源采集/发布：支持手工录入、微信文本、TMS 入站三种来源，通过“AI 线索切分 -> 标准化匹配 -> 人工确认 -> 正式货源”闭环入库，并预留货源大厅发布字段。

## 正式货源语义

- `freight` 支持装货地、卸货地的三类层级：`NODE` 节点级、`CITY` 城市级、`RAW` 原文级。
- `freight` 支持货品两类层级：`STANDARD` 标准货品级、`RAW` 原文货品级。
- 新增正式货源字段：`raw_origin_text`、`raw_destination_text`、`raw_commodity_name`、`origin_match_level_code`、`destination_match_level_code`、`commodity_match_level_code`。
- `commodity_standard_id`、装卸城市/省份字段改为可空。平台未建节点、城市或标准货品时，业务人员仍可用原文级信息确认入库。
- 入库最低门槛调整为：有装货地原文/城市/节点、卸货地原文/城市/节点，以及货品标题/原文货品/标准货品。
- 选择节点级时后端自动回填城市和业务区域；选择城市级时自动回填省份和业务区域；选择原文级时清空对应标准化字段并保留原文。

## 采集链路

- 删除旧采集链路表：`freight_source_inbound`、`freight_ai_parse_task`、`freight_candidate_feedback`。
- 重建采集链表：`freight_batch_task`、`freight_tms_inbound`、`freight_clue`、`freight_candidate`、`freight_candidate_manual_feedback`。
- 保留正式货源主表 `freight`，补充来源追溯字段：`source_batch_id`、`source_tms_inbound_id`、`source_clue_id`、`source_candidate_id`。
- 补充货源大厅预留字段：`hall_status_code`、`hall_published_at`、`hall_unpublished_at`、`hall_visible_until`。

## AI 与匹配链路

- 微信采集使用 DashScope SDK 流式调用，快模型读取完整原文并由 AI 切分线索，低置信候选交给强模型复核。
- 微信提示词版本升级为 `freight_wechat_dashscope_stream_v5`。AI 第一阶段输出拆为 `freight_clues` 和 `context_notes`，公告、联系人、价格、结算、装卸备注等上下文只允许进入 `context_notes`，不能单独生成候选。
- 结构化 schema hint 已移除真实姓名、手机号、地点、货品等示例值，统一使用中性占位说明，避免模型把提示词样例抄入解析结果。
- 后端不使用正则、关键词或本地规则拆解微信群原文；本地代码只做 JSON schema 校验、证据约束、主数据匹配、候选入库和错误处理。
- 候选生成前增加质量门禁：缺少装货地、卸货地、货品主体的 AI segment 会作为 `IGNORED` 线索保留审计记录，但不生成 `freight_candidate`；无原文证据的联系人、电话、地点、货品、价格字段会被清空并进入人工判断。
- 强模型复核职责补充为：检查候选数量异常、上下文-only 片段误入候选、字段证据不足和 schema 占位污染；可把错误 segment 标记为 `is_freight_candidate=false`。
- TMS 入站继续处理单条消息内多条标准运单或运单数组。
- 解析接口投递 Celery `freight_ai` 后台任务，批次状态支持 `QUEUED`、`PARSING`、`PARSED`、`PARTIAL_FAILED`、`FAILED`。
- 批次解析进度字段：`parse_stage_code`、`parse_stage_name`、`parse_stage_message`、`parse_progress_percent`、`parse_heartbeat_at`、`ai_elapsed_seconds`。
- 候选确认接口允许显式清空节点、城市、标准货品字段，支持切换到原文级后确认入库。

## 清洗任务

- 新增 `freight_normalization_suggestion`，记录原文级装卸地/货品的匹配建议、置信度、应用状态和应用前后快照。
- 新增接口：
  - `GET /freight/normalization-suggestions`
  - `POST /freight/normalization-suggestions/{id}/apply`
  - `POST /freight/normalization-suggestions/{id}/reject`
  - `GET /freight/normalization/quality`
  - `POST /freight/normalization/clean`
- 清洗服务扫描正式货源中 `RAW` 或缺标准维度的数据。高置信建议自动回填，低置信建议保留为待人工确认。
- 清洗回填后会触发受影响日期范围内的货源流向、城市、节点、货品事实重算。

## 分析口径

- 正式货源总量继续统计所有 `freight`，包括原文级货源。
- 城市、节点、标准货品、流向分析只统计已标准化字段，避免把原文级数据误归类。
- 货源分析总览新增待清洗数量指标，帮助业务看到仍停留在原文级的数据质量缺口。
- `run_freight_commodity_daily` 跳过未标准化货品，节点/城市/流向事实按已有标准字段聚合。

## Seed 与验收

- 新增 Alembic 迁移：`0012_freight_raw_level_normalization`。
- 更新 `seed_system_base`，菜单增加“数据清洗”，货源菜单为：微信采集、采集批次、待确认货源、手工录入、正式货源、数据清洗、TMS 入站。
- 更新 `seed_freight_samples`，保留节点级、城市级、原文级正式货源样例，并写入清洗建议样例。
- 更新 `verify_local_acceptance`，校验新 API、清洗建议、原文级正式货源 seed 和旧入口删除。

## 验证结果

本轮重构已完成本地验证：

- `.venv/bin/python -m py_compile ...`：通过。
- `.venv/bin/python -m pytest tests/test_freight_collection_rework.py -q`：12 passed，覆盖 schema 防污染、上下文-only 忽略、公共上下文继承和建德样例 4 条候选。
- `.venv/bin/python -m pytest -q`：25 passed。
- `.venv/bin/alembic upgrade head`：已升级至 `0012_freight_raw_level_normalization`。
- `.venv/bin/python -m scripts.seed_system_init`：通过。
- `.venv/bin/python -m scripts.verify_local_acceptance`：通过，包含清洗建议、原文级正式货源、菜单和新接口校验。
