# 货源采集生产化重构报告

日期：2026-05-07

## 重构目标

本次重构将货源模块拆为两条主线：

- 货源分析：只消费已确认的正式货源 `freight`，面向城市、区域、运输节点、货品结构、运价和流向分析。
- 货源发布/采集：支持手工录入、微信文本、TMS 入站三种来源，通过“线索切分 -> 标准化匹配 -> 人工确认 -> 正式货源”闭环入库，并预留货源大厅发布字段。

## 后端模型

- 删除旧采集链路表：`freight_source_inbound`、`freight_ai_parse_task`、`freight_candidate_feedback`。
- 重建采集链表：`freight_batch_task`、`freight_tms_inbound`、`freight_clue`、`freight_candidate`、`freight_candidate_manual_feedback`。
- 保留正式货源主表 `freight`，补充来源追溯字段：`source_batch_id`、`source_tms_inbound_id`、`source_clue_id`、`source_candidate_id`。
- 补充货源大厅预留字段：`hall_status_code`、`hall_published_at`、`hall_unpublished_at`、`hall_visible_until`。
- 新增节点日事实表 `fact_freight_node_daily`，用于运输节点维度分析。

## AI 与匹配链路

- 微信采集升级为 `freight_wechat_dashscope_stream_v4`：使用 DashScope SDK 流式调用，快模型负责读取完整原文并由 AI 切分线索，再由 AI 抽取字段，低置信度候选交给强模型复核。
- 后端不使用正则、关键词或本地规则拆解微信群原文；本地代码只做 JSON schema 校验、标准主数据匹配、候选入库和错误处理。
- TMS 入站升级为 `freight_tms_dashscope_stream_v4`，继续处理单条消息内多条标准运单或运单数组。
- 解析接口改为投递 Celery `freight_ai` 后台任务，批次状态支持 `QUEUED`、`PARSING`、`PARSED`、`PARTIAL_FAILED`、`FAILED`，避免复杂群消息同步请求超时。
- 批次新增解析进度字段：`parse_stage_code`、`parse_stage_name`、`parse_stage_message`、`parse_progress_percent`、`parse_heartbeat_at`、`ai_elapsed_seconds`，前端可展示真实阶段和心跳。
- 解析结果先写入 `freight_clue`，再通过匹配服务查找运输节点、城市、区域和标准货品，生成 `freight_candidate`。
- 候选货源同时保存原文级、节点级、城市级、区域级和标准货品级推荐，并增加可发状态：`READY`、`DEFERRED`、`FULL`、`UNKNOWN`。非 `READY` 候选不能一键确认，必须编辑确认或驳回。

## API 变化

- 手工录入：`POST /freight/manual`。
- 微信批次：`POST /freight/batches/wechat`、`GET /freight/batches`、`GET /freight/batches/{id}`、`POST /freight/batches/{id}/parse`。
- 微信批量确认：`POST /freight/batches/{id}/candidates/bulk-confirm`。
- TMS 入站：`POST /freight/tms-inbounds`、`GET /freight/tms-inbounds`、`GET /freight/tms-inbounds/{id}`、`POST /freight/tms-inbounds/{id}/parse`。
- 候选确认：`GET /freight/candidates`、`GET /freight/candidates/{id}`、`PUT /freight/candidates/{id}`、`POST /freight/candidates/{id}/confirm`、`POST /freight/candidates/{id}/reject`。
- 正式货源：保留 `GET /freight`、`GET /freight/{id}`、`PUT /freight/{id}`、状态、联系人、附件和标签接口。
- 已移除旧 `/freight/source-inbounds*` 和 `/freight/ai/parse-tasks*`。

## 分析与 Seed 影响

- 货源分析继续以 `freight` 为正式事实源，采集批次和候选仅用于接入量、候选量等采集过程指标。
- 新增 `ANALYSIS_FREIGHT_NODE_DAILY` 任务和 `/analysis/freight/node-ranking` 接口。
- 更新 `seed_builtin_dicts`、`seed_code_sequences`、`seed_system_base`、`seed_freight_samples`、`seed_analysis_samples`、`verify_local_acceptance`。
- 新增 AI 配置：`DASHSCOPE_FAST_MODEL`、`DASHSCOPE_STREAM_TIMEOUT_SECONDS`、`DASHSCOPE_STRONG_REVIEW_ENABLED`、`FREIGHT_AI_STALE_HEARTBEAT_SECONDS`。
- 菜单调整为：微信采集、采集批次、待确认货源、手工录入、正式货源、TMS 入站。
- 验收脚本会校验旧表和旧接口删除、新表数据量、节点事实数据、菜单无旧入口。

## 验证结果

本轮重构已完成本地验证：

- `.venv/bin/python -m pytest -q`：18 passed。
- `.venv/bin/alembic upgrade head`：已升级至 `0011_freight_ai_progress`。
- `.venv/bin/python -m scripts.seed_system_init`：通过，包含新 AI 配置和货源样例 seed。
- `.venv/bin/python -m scripts.verify_local_acceptance`：通过，旧接口/旧表删除、新采集链、菜单、分析任务和本地私有配置校验均为 OK。
