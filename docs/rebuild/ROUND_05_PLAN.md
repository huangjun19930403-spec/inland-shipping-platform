# Round 05 Plan - Freight Workbench and Action Closure

## Goal

把 Round 04 的运输机会读模型继续推进成货源洞察中心的业务闭环：用户从一条正式货源进入后，能看到它为什么可算、为什么不可算、哪些数据要修、能否匹配船、能否报价，以及每个动作对应的后端入口。

## Work Items

1. 收敛货源业务入口。
   - 明确 `/freight/opportunities` 是货源洞察中心的默认业务入口。
   - 旧 `/freight` 只保留为底层资源列表，不再承载分析口径。
   - 盘点旧货源接口的前端消费关系，列出第一批可删除候选。

2. 补齐 opportunity detail 的证据面板。
   - 加入候选来源原文摘要、AI 解析版本、人工确认记录摘要。
   - 加入未完成清洗建议列表和影响字段。
   - 加入最近一次船货适配分析摘要。
   - 加入报价证据摘要，不使用样例价格冒充生产依据。

3. 建立动作闭环。
   - `OPEN_FREIGHT_CLEANING` 必须能定位到该货源的清洗建议。
   - `OPEN_CANDIDATE_VESSELS` 必须能带 `context_type_code=FREIGHT_SAMPLE&freight_id=...` 进入或创建适配分析。
   - `OPEN_QUOTE_SIMULATOR` 必须携带货源上下文，并在缺字段时返回明确不可计算原因。

4. 测试。
   - 服务测试覆盖完整机会、缺节点、缺货品、缺价格、已有适配分析、有清洗问题五类样本。
   - API 测试覆盖列表、详情、空结果和不存在货源。

## Exit Criteria

- 一条货源详情能从来源血缘、质量问题、航线、运力、报价五个角度解释当前状态。
- 所有动作要么可执行，要么带明确 `disabled_reason`。
- 新增 service 继续保持小对象边界，不向旧 `FreightService` 追加编排逻辑。

