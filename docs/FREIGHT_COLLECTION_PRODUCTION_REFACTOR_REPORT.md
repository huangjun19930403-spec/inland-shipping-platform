# 货源采集生产化重构报告

日期：2026-05-07

## 重构目标

本次重构将货源模块拆为两条主线：

- 货源分析：只消费已确认的正式货源 `freight`，正式货源总量包含节点级、城市级和原文级货源。
- 货源采集/发布：支持手工录入、微信文本、TMS 入站三种来源，通过“AI 线索切分 -> 标准化匹配 -> 人工确认 -> 正式货源”闭环入库，并预留货源大厅发布字段。

## 正式货源语义

- `freight` 支持装货地、卸货地的三类层级：`NODE` 节点级、`CITY` 城市级、`RAW` 原文级。
- `freight` 支持货品两类层级：`STANDARD` 标准货品级、`RAW` 原文货品级。
- 新增正式货源字段：`raw_origin_text`、`raw_destination_text`、`raw_commodity_name`、`raw_tonnage_text`、`origin_match_level_code`、`destination_match_level_code`、`commodity_match_level_code`。
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
- 微信提示词版本升级为 `freight_wechat_dashscope_stream_v8`。AI 第一阶段输出拆为 `route_clues`、`context_blocks`、`context_notes` 和 `ignored_notes`；公告、联系人、价格、结算、装卸备注、吨位等上下文只允许进入上下文结构，不能单独生成候选。
- `context_blocks` 显式记录公共上下文覆盖的 `route_clue_ids`、联系人、电话、公共吨位/价格、装卸备注、证据和继承原因。后端只依据 AI 输出的结构化 block 做字段传播，不对微信群原文做规则拆分。
- 强模型复核输入扩展为完整原文、线索、上下文块和候选结果，用于检查“末尾电话只继承到一条候选”、上下文-only 误入候选、召回不足和吨位误入价格。
- v8 采用召回优先策略：只要有装货地和卸货地，就保留为路线线索；缺货品时生成“需补充”候选，不能一键确认，但业务人员可以在编辑确认中补齐货品后入库。
- AI 在切分和抽取阶段输出装卸地粒度建议：`NODE`、`CITY`、`RAW`。只有明确港口、码头、闸口、厂矿、装卸点等具体设施才建议节点级；只有城市名或简称时建议城市级。
- `freight_candidate` 与 `freight` 新增 `raw_tonnage_text`，保留 `1500-2000内`、`2000左右`、`2-3500吨` 等微信群原始吨位表达；单点吨位写入 `estimated_tonnage`，范围吨位写入 `min_tonnage`、`max_tonnage`。
- v6 提示词和强模型复核补充吨位归类约束：没有“元/运费/价格”等价格语义时，路线货品附近数字优先按吨位解析；`2-3500吨` 这类微信群简写由 AI 复核为 `2000-3500吨`，无法确认时只保留原文吨位并要求人工判断。
- 结构化 schema hint 已移除真实姓名、手机号、地点、货品等示例值，统一使用中性占位说明，避免模型把提示词样例抄入解析结果。
- 后端不使用正则、关键词或本地规则拆解微信群原文；本地代码只做 JSON schema 校验、证据约束、主数据匹配、候选入库和错误处理。
- 候选生成前增加质量门禁：缺少装货地、卸货地、货品主体的 AI segment 会作为 `IGNORED` 线索保留审计记录，但不生成 `freight_candidate`；无原文证据的联系人、电话、地点、货品、价格字段会被清空并进入人工判断。
- 强模型复核职责补充为：检查候选数量异常、上下文-only 片段误入候选、字段证据不足和 schema 占位污染；可把错误 segment 标记为 `is_freight_candidate=false`。
- TMS 入站继续处理单条消息内多条标准运单或运单数组。
- 解析接口投递 Celery `freight_ai` 后台任务，批次状态支持 `QUEUED`、`PARSING`、`PARSED`、`PARTIAL_FAILED`、`FAILED`。
- 批次解析进度字段：`parse_stage_code`、`parse_stage_name`、`parse_stage_message`、`parse_progress_percent`、`parse_heartbeat_at`、`ai_elapsed_seconds`。
- 候选确认接口允许显式清空节点、城市、标准货品字段，支持切换到原文级后确认入库。
- 候选查询接口支持 `source_batch_id`，微信采集完成后既可在本批次内确认，也可进入跨批次“待确认货源”队列筛选处理。
- 批次重新解析增加保护：只要该批次存在已确认候选或已生成正式货源，后端拒绝重新解析，避免历史确认结果被新解析覆盖。
- 装卸地匹配改为“AI 粒度建议 + 主数据置信度”共同决策：节点名称/别名精确命中仍优先；城市全称/简称精确命中优先于节点弱包含；弱节点匹配只进入候选建议，不再把“马鞍山”这类城市简称自动落到具体港口。

## 批次状态与待确认队列

- `freight_batch_task` 新增 `review_flow_status_code`，用于区分 `REVIEWING` 本批次确认、`QUEUED_FOR_REVIEW` 已移交待确认队列、`COMPLETED` 已完成。
- 批次详情返回 `parse_is_stale`、`parse_heartbeat_age_seconds`、`next_action_code`、`next_action_name`，前端可从批次列表恢复到解析进度、确认页或待确认队列。
- 新增接口 `POST /freight/batches/{batch_id}/handoff-review`。该接口不生成正式货源，只把未处理候选保留到跨批次“待确认货源”队列，并禁止该批次再次重新解析。
- `POST /freight/batches/{batch_id}/parse` 对未超时的 `PARSING` 批次只返回当前状态；心跳超时后允许重新投递任务；已有正式入库或已移交待确认队列的批次拒绝重新解析。

## 清洗任务

- 新增 `freight_normalization_suggestion`，记录原文级装卸地/货品的匹配建议、置信度、应用状态和应用前后快照。
- 新增 `freight_normalization_task`，记录清洗任务号、Celery task id、状态、阶段、进度、扫描数、建议数、自动应用数、失败原因和耗时。
- 新增接口：
  - `GET /freight/normalization-suggestions`
  - `POST /freight/normalization-suggestions/bulk-apply`
  - `POST /freight/normalization-suggestions/{id}/apply`
  - `POST /freight/normalization-suggestions/{id}/reject`
  - `GET /freight/normalization/tasks`
  - `GET /freight/normalization/tasks/{id}`
  - `GET /freight/normalization/quality`
  - `POST /freight/normalization/clean`
- `POST /freight/normalization/clean` 改为投递 Celery `freight.clean_normalization` 后台任务并立即返回任务信息；前端通过任务列表和质量接口查看进度。
- 清洗服务扫描正式货源中 `RAW` 或缺标准维度的数据。高置信建议自动回填，低置信建议保留为待人工确认，并支持勾选批量应用和当前筛选全部应用。
- 清洗回填后会触发受影响日期范围内的货源流向、城市、节点、货品事实重算。

## 分析口径

- 正式货源总量继续统计所有 `freight`，包括原文级货源。
- 城市、节点、标准货品、流向分析只统计已标准化字段，避免把原文级数据误归类。
- 货源分析总览新增待清洗数量指标，帮助业务看到仍停留在原文级的数据质量缺口。
- `run_freight_commodity_daily` 跳过未标准化货品，节点/城市/流向事实按已有标准字段聚合。

## Seed 与验收

- 新增 Alembic 迁移：`0012_freight_raw_level_normalization`、`0013_freight_raw_tonnage_text`、`0014_freight_batch_review_flow`、`0015_freight_normalization_task`。
- 更新 `seed_system_base`，菜单增加“数据清洗”，货源菜单为：微信采集、采集批次、待确认货源、手工录入、正式货源、数据清洗、TMS 入站。
- 更新 `seed_freight_samples`，保留节点级、城市级、原文级正式货源样例，并写入清洗任务、清洗建议样例和原文吨位字段。
- 更新 `verify_local_acceptance`，校验新 API、清洗建议、原文级正式货源 seed、原文吨位 seed 和旧入口删除。

## 验证结果

本轮重构已完成本地验证：

- `.venv/bin/python -m py_compile ...`：通过。
- `.venv/bin/python -m pytest tests/test_freight_collection_rework.py -q`：21 passed，覆盖 schema 防污染、上下文-only 忽略、缺货品路线保留、公共上下文继承、建德样例 4 条候选、微信群吨位范围样例 9 条候选、批次恢复进度、移交待确认队列、批次重解析保护、按批次筛选待确认队列和城市简称优先匹配。
- `.venv/bin/python -m pytest -q`：34 passed。
- `.venv/bin/alembic upgrade head`：已升级至 `0014_freight_batch_review_flow`。
- `.venv/bin/python -m scripts.seed_system_init`：通过。
- `.venv/bin/python -m scripts.verify_local_acceptance`：通过，包含清洗建议、原文级正式货源、原文吨位、菜单和新接口校验。
