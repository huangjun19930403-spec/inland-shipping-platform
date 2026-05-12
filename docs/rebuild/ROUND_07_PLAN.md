# Round 07 Plan - Four-State Maps and Legacy Service Split

## Goal

把地图和外部服务失败态做成生产口径，同时开始拆分旧超大 service，避免第六轮形成的新工作台被旧大对象继续拖住。

## Work Items

1. 地图四态后端契约。
   - 统一 `READY / PENDING / FAILED / NOT_COMPUTABLE`。
   - 响应必须包含 provider、刷新时间、错误原因、缺失字段、重试动作和业务影响。
   - 禁止生产分析用 `LOCAL_SAMPLE` 或直线轨迹冒充真实航线依据。

2. 拆分 `app/modules/analysis/service.py`。
   - 按货源、运力、区域流向、价格、证据面板拆成小 service 或 query builder。
   - 每个新 service 低于 800 行，并有明确业务问题。
   - 保留 router 对外契约，内部实现不做壳式转发。

3. 迁移旧 `/freight` 消费方。
   - 仪表盘最近货源改用机会摘要或专门 summary API。
   - 船货适配远程选择器改用轻量 opportunity/resource selector。
   - 完成后删除旧列表字段中的后台展示冗余项。

4. 机会落表准备。
   - 给出 `shipping_opportunity` 最小状态机。
   - 明确哪些 evidence 必须快照，哪些继续实时计算。
   - 如状态机闭合，更新单一 `001_initial_schema`。

5. 测试。
   - 覆盖地图四态和外部服务不可用。
   - 覆盖旧 `/freight` 消费迁移后无悬空调用。
   - 覆盖拆分后分析响应仍包含 context、metrics、insights、lineage、quality、actions。

## Exit Criteria

- 地图不再用空白表达失败。
- `analysis/service.py` 不再作为 1900 行总服务承载所有分析问题。
- `/freight` 旧列表接口可以进入删除或降级为内部资源接口。
