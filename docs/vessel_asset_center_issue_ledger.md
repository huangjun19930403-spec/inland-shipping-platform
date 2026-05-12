# 船舶管理问题台账

本文档用于持久记录船舶管理审计问题、当前状态、已完成批次和剩余动作。后续每一轮优化都必须先更新本台账，再说明当轮覆盖哪些问题。

状态说明：

- 完成：当前代码已覆盖核心闭环，并有回归保护或红线扫描。
- 部分完成：已有基础能力，但业务工作流、页面产品化或架构收敛仍未达到生产级。
- 未完成：仍是主要待修复项。

## 当前批次

- P0-closure：已完成 GET 去副作用、显式任务同步批次、质量/风险重校验、主体结论层、名单预警入口、人员选择器和高危 replace/delete 页面调用封存。
- P1-workflow-2026-05-10：本轮推进用户工作流与页面闭环，补充工作台事项、解释字段、证据缺口、下一步动作、资产/画像/质量/风险/任务深链接语义。
- P1-relation-evidence-2026-05-10：本轮推进主体证据生产化和候选选择器生产化，补充控制人/挂靠结构化 payload、结论引用、证据完整度、审核缺口提示、档案/主体入口定责，以及候选分析远程搜索和深链接回显。
- P1-boundary-cleanup-2026-05-10：本轮推进边界收敛，清除 `vesselLegacy.ts` 双轨 API，建立 schema/router 兼容拆分入口，并拆出主体证据 payload 工具与候选远程选择器 composable。
- P1-domain-split-components-2026-05-10：本轮将 schema/router 从兼容拆分推进为领域文件，并拆出主体关系结论面板、候选筛选面板、编辑页 OCR 差异弹窗等前端组件。
- P2-service-boundary-components-2026-05-10：本轮推进服务边界收敛和剩余大组件拆分，新增资产、质量、合规、主体、识别、治理任务领域 service，router 改为依赖领域 service，并继续拆出候选结果/解释面板、主体关系表格组件和船舶证书台账组件。
- P2-cross-module-closure-2026-05-10：本轮推进审核中心、分析中心、货源/节点/航线跨模块闭环，建立证据审核桥接、候选分析历史复盘、上下文质量缺口和 migration 策略红线。
- P2-workflow-service-completion-2026-05-10：本轮补齐治理工作台 SLA/规则解释/同步批次详情、质量批量重校验、合规证明链、风险/名单审核中心边界、画像证据抽屉业务化，并将质量、治理任务、合规服务从 facade 推进为显式方法边界。
- P2-business-closure-final-2026-05-10：本轮完成业务人员可见闭环，新增字段级定位 composable、资产台账行展开和批量治理、摘要批量刷新 diff、主体证据附件上传/预览/作废、结论冲突处理、候选分析业务边界提示和候选-节点距离图层。
- P2-architecture-closure-final-2026-05-10：本轮完成维护边界闭环，新增 `0036_vessel_relation_evidence_attachment.py` 数据保护型迁移，领域 service 删除 `__getattr__` fallback，红线脚本补服务显式方法和 0036+ vessel migration 台账记录检查。
- P3-clean-baseline-service-split-2026-05-10：本轮按 V3 当前态收束 Alembic 为单一 `0001_platform_current_schema.py`，移除 active 旧补丁链和 legacy `ship_*` 基线风险；seed 补齐船舶画像、质量、合规、识别、AIS、候选和治理样例；`VesselService` 拆成 shared aggregate + asset/certificate/relation/recognition/quality/compliance/ais/profile_card domain methods。
- P4-production-delete-rebuild-2026-05-12：生产删除式重构分支将 active Alembic 进一步收束为单一 `001_initial_schema.py`，把水系基础表、菜单权限码等补丁迁移并入初始结构，后续只允许围绕生产主线更新单一初始迁移。

## 全量问题台账

| 编号 | 问题 | 状态 | 已完成批次 | 剩余动作 |
|---|---|---|---|---|
| 1 | 数据资产中心更像功能堆叠，缺业务工作链 | 完成 | P0-closure, P1-workflow-2026-05-10, P2-business-closure-final-2026-05-10 | 已形成资产台账、画像、质量、合规、主体、候选和治理任务的“发现问题 -> 定位字段/证据 -> 修复/审核 -> 重校验 -> 指标改善”工作链；后续只做口径优化 |
| 2 | 治理看板只是指标展示，不是工作台 | 完成 | P1-workflow-2026-05-10, P2-workflow-service-completion-2026-05-10 | 已增加 SLA、超期等级、处理人负载、今日优先级、同步批次详情和规则说明；后续只做指标口径优化 |
| 3 | 指标不能下钻到任务/船/字段 | 完成 | P0-closure | 回归保护深链接参数 |
| 4 | 看板刷新暗中触发任务同步 | 完成 | P0-closure | 红线扫描 GET 不调用 sync/commit |
| 5 | 任务来源、生成规则、生成原因不清 | 完成 | P0-closure, P1-workflow-2026-05-10, P2-cross-module-closure-2026-05-10, P2-workflow-service-completion-2026-05-10 | 已补同步批次详情、规则解释字典、审核状态、审核任务号、审核入口和业务同步结果；后续只做规则文案优化 |
| 6 | 任务执行只是改状态，不是真修复 | 完成 | P0-closure, P2-workflow-service-completion-2026-05-10 | 质量/风险 resolve 强制重校验，风险/名单/证据复核不能绕过审核中心；后续按新增问题类型扩展专用校验器 |
| 7 | “去修复”只是粗跳页面 | 完成 | P0-closure, P1-workflow-2026-05-10, P2-business-closure-final-2026-05-10 | 已新增 `useVesselAnchorFocus`，质量、合规、主体证据支持 `field/quality_issue_id/risk_signal_id/evidence_id/anchor` 深链接滚动和高亮；后续扩展更多字段锚点即可 |
| 8 | 任务指派只能输入数字 ID | 完成 | P0-closure | 补部门/角色过滤和通知 |
| 9 | 数据质量页只是问题列表 | 完成 | P0-closure, P1-workflow-2026-05-10, P2-workflow-service-completion-2026-05-10 | 已补任务关系、验收状态、推荐动作、单条/批量重校验和失败原因；后续增强字段视觉高亮 |
| 10 | 质量问题和治理任务关系不清 | 完成 | P0-closure | 回归保护任务关系展示 |
| 11 | 合规风险页仍不是真正合规工作台 | 完成 | P0-closure, P1-workflow-2026-05-10, P2-cross-module-closure-2026-05-10, P2-workflow-service-completion-2026-05-10 | 已补证明链、证据缺口、审核入口、复核提交和后端推荐动作；后续可将规则映射迁入数据库/字典配置 |
| 12 | 风险修复靠前端字符串判断 | 完成 | P0-closure, P2-service-boundary-components-2026-05-10 | 已将后端风险动作收敛到 `services/compliance_rules.py` 规则映射表；后续可迁入数据库/字典配置 |
| 13 | Controller/Affiliation 表单太薄 | 完成 | P1-relation-evidence-2026-05-10, P2-business-closure-final-2026-05-10 | 已补结构化 payload、有效期、确认链、审核意见、真实附件上传/预览/作废、缺口提示和冲突处理动作 |
| 14 | Controller/Affiliation 没有结论层 | 完成 | P0-closure | 回归保护候选、冲突、当前、作废链路 |
| 15 | 前端没体现审核、revision、证据能力 | 完成 | P0-closure, P1-workflow-2026-05-10, P1-relation-evidence-2026-05-10, P2-cross-module-closure-2026-05-10, P2-workflow-service-completion-2026-05-10, P2-business-closure-final-2026-05-10 | 已展示结论引用、完整度、缺口、revision、附件、预览、审核历史、审核任务号、审核入口和业务同步状态 |
| 16 | 黑名单后端有能力但前端无产品化入口 | 完成 | P0-closure | 补批量复核和到合规证明链的更多联动 |
| 17 | 资产台账还是大列表，缺治理引导 | 完成 | P1-workflow-2026-05-10, P2-business-closure-final-2026-05-10 | 已增加行展开治理详情、低可信原因、影响说明、下一步动作、最近校验和批量刷新/批量重校验/进入任务入口 |
| 18 | “刷新摘要”对业务人员解释不足 | 完成 | P1-workflow-2026-05-10, P2-business-closure-final-2026-05-10 | 已新增单条/批量摘要刷新差异、失败原因和业务解释，不再只是调试按钮 |
| 19 | 新增船舶过于简单，缺数据来源 | 完成 | P0-closure | 回归保护来源类型必填 |
| 20 | 画像页只是卡片汇总，治理动作弱 | 完成 | P1-workflow-2026-05-10, P2-workflow-service-completion-2026-05-10 | 已补待处理问题面板、推荐动作、证据缺口、审核入口和轻量治理动作 |
| 21 | 证据抽屉偏研发展示 | 完成 | P1-workflow-2026-05-10, P2-workflow-service-completion-2026-05-10 | 已按证据类型模板化展示业务字段、证据充分性、缺失字段、附件引用、审核历史和结论引用；后续接入真实附件预览组件 |
| 22 | 船东/经营人和档案编辑页入口重复 | 完成 | P1-workflow-2026-05-10, P1-relation-evidence-2026-05-10, P2-business-closure-final-2026-05-10 | 已将主体证据、关系、结论、附件和冲突处理集中到主体关系页；档案页保留基础资料与治理入口 |
| 23 | 所有人变更和所有方维护逻辑冲突 | 完成 | P1-workflow-2026-05-10, P1-relation-evidence-2026-05-10, P2-business-closure-final-2026-05-10 | 已在 UI 和服务入口区分资料修正、关系结束、所有权转移，所有权转移继续只走 owner-transfer |
| 24 | 候选适配像找船，不像分析产品 | 完成 | P0-closure, P2-cross-module-closure-2026-05-10, P2-business-closure-final-2026-05-10 | 已补不代表可接货/不产生运输承诺的边界提示、历史复盘、分析中心入口、上下文质量缺口和不确定性解释 |
| 25 | 候选地图空间分析不足 | 完成 | P0-closure, P2-cross-module-closure-2026-05-10, P2-business-closure-final-2026-05-10 | 已展示候选船位置、候选船到节点距离线、空间快照、节点/航线/区域质量缺口和区域供需说明 |
| 26 | 选择器固定加载，不适合生产数据 | 完成 | P1-relation-evidence-2026-05-10 | 候选分析节点、航线、区域、正式货源、候选货源已改远程搜索并支持深链接回显；后续可补最近使用 |
| 27 | GET 查询存在写入副作用 | 完成 | P0-closure | 红线扫描 |
| 28 | GovernanceService 过重 | 完成 | P2-service-boundary-components-2026-05-10, P2-workflow-service-completion-2026-05-10, P2-architecture-closure-final-2026-05-10 | 治理相关 router 已依赖领域 service 显式方法，`__getattr__` fallback 删除并纳入红线；后续只做内部实现继续拆细 |
| P0-1 | VesselService 过大 | 完成 | P2-service-boundary-components-2026-05-10, P2-workflow-service-completion-2026-05-10, P2-architecture-closure-final-2026-05-10, P3-clean-baseline-service-split-2026-05-10 | `VesselService` 已降为兼容聚合入口，具体实现拆入 asset、certificate、relation、recognition、quality、compliance、ais、profile_card 和 shared methods；红线禁止重新在 `service.py` 增加实现体或动态代理 |
| P0-2 | GovernanceService 过大 | 完成 | P2-service-boundary-components-2026-05-10, P2-workflow-service-completion-2026-05-10, P2-architecture-closure-final-2026-05-10 | 同问题 28 |
| P0-3 | GET 自动 sync/commit | 完成 | P0-closure | 红线扫描 |
| P0-4 | replace/delete 物理删除路径风险 | 完成 | P0-closure | 继续禁止生产页面调用 |
| P0-5 | vesselLegacy.ts 债务 | 完成 | P1-boundary-cleanup-2026-05-10 | 已迁移识别、资产、详情、所有方转移、系统首页调用并删除 legacy 文件；保留红线扫描禁止新增 import |
| P0-6 | 表结构增长快、领域未收敛 | 完成 | P0-closure, P2-architecture-closure-final-2026-05-10, P3-clean-baseline-service-split-2026-05-10, P4-production-delete-rebuild-2026-05-12 | active Alembic 已收束为 `001_initial_schema.py` 单基线，旧补丁链不再参与空库初始化；红线禁止恢复 legacy 表和多版本补丁链 |
| P1-1 | router.py 过大 | 完成 | P1-boundary-cleanup-2026-05-10, P1-domain-split-components-2026-05-10 | 已按资产、质量、合规、主体、治理、AIS、候选、识别拆入领域 router；后续只做小文件内的进一步整理 |
| P1-2 | schemas.py 过大 | 完成 | P1-boundary-cleanup-2026-05-10, P1-domain-split-components-2026-05-10 | 已按 base、asset、relation、quality、compliance、governance、recognition、ais、candidate、profile_card 拆入领域 schema；后续只做类型归属微调 |
| P1-3 | 前端大页面单文件过大 | 完成 | P1-boundary-cleanup-2026-05-10, P1-domain-split-components-2026-05-10, P2-service-boundary-components-2026-05-10, P2-workflow-service-completion-2026-05-10, P2-business-closure-final-2026-05-10 | 已拆主体证据 payload 工具、关系结论面板、关系/证据表格、候选远程选择器、候选筛选面板、候选结果/地图、候选解释/标注、编辑页 OCR 差异弹窗、船舶证书台账、文件预览和通用治理动作面板；剩余只做 UI 细粒度优化 |
| P1-4 | API 类型重复 | 完成 | P1-boundary-cleanup-2026-05-10, P1-domain-split-components-2026-05-10, P2-service-boundary-components-2026-05-10, P2-workflow-service-completion-2026-05-10, P2-business-closure-final-2026-05-10 | 已消除 legacy 双轨，领域新增类型进入领域 API，通用类型保留在 sharedTypes，红线禁止恢复 `vesselLegacy` |
| P1-5 | 页面交互范式不统一 | 完成 | P0-closure, P1-workflow-2026-05-10, P1-boundary-cleanup-2026-05-10, P1-domain-split-components-2026-05-10, P2-service-boundary-components-2026-05-10, P2-workflow-service-completion-2026-05-10 | 已通过通用治理动作面板统一质量、合规、任务、画像的来源、任务、推荐动作、验收状态、证据缺口和审核入口呈现；后续只做视觉微调 |
| P1-6 | analysis 模块和 vessel 边界模糊 | 完成 | P2-cross-module-closure-2026-05-10, P2-business-closure-final-2026-05-10 | 候选明细由船舶中心生成，事实聚合由分析中心 `ANALYSIS_CANDIDATE_FIT_DAILY` 负责，船舶页面只展示分析中心入口、来源解释和数据新鲜度 |
| P2-1 | 船舶中心和审核中心职责交叉 | 完成 | P2-cross-module-closure-2026-05-10, P2-workflow-service-completion-2026-05-10 | 证据审核、风险复核、黑名单解除/作废均走审核中心；治理任务只做提醒、定位和状态镜像 |
| P2-2 | 船舶中心和分析中心职责交叉 | 完成 | P2-cross-module-closure-2026-05-10, P2-business-closure-final-2026-05-10 | 同 P1-6，候选事实口径已收敛，船舶侧不直接写分析事实 |
| P2-3 | 货源/节点/航线弱关联 | 完成 | P2-cross-module-closure-2026-05-10, P2-business-closure-final-2026-05-10 | 货源、候选货源、节点、航线可进入候选分析，候选历史可按来源反查，节点/航线/区域/空间快照缺口可跳治理入口 |
| P2-4 | migration 补丁化 | 完成 | P2-cross-module-closure-2026-05-10, P2-architecture-closure-final-2026-05-10, P3-clean-baseline-service-split-2026-05-10, P4-production-delete-rebuild-2026-05-12 | 已改为 V3 当前态干净基线，active Alembic 只保留 `001_initial_schema.py`，不再创建或回填 legacy `ship_*` 表 |
| P2-5 | 表和页面先行、业务闭环后补 | 完成 | P0-closure, P1-workflow-2026-05-10, P2-architecture-closure-final-2026-05-10 | 红线要求新增 vessel migration 记录台账；本轮新增表服务于主体证据附件闭环并复用 storage_file |

## 本轮目标

本轮覆盖并完成所有剩余“部分完成”项：1、7、13、17、18、22、23、24、25、28、P0-1、P0-2、P0-6、P1-3、P1-4、P1-6、P2-2、P2-3、P2-4、P2-5，并回归保护 P0-5、12、26、27。

本轮已完成：

- 新增 `useVesselAnchorFocus`，统一处理 `field、quality_issue_id、risk_signal_id、task_id、evidence_id、conclusion_id、blacklist_signal_id、anchor` 深链接定位和高亮。
- active Alembic 收束为 `001_initial_schema.py`，旧补丁链退出 active 目录；新基线不包含 legacy `ship_*` 表，并内置水系基础表和菜单权限码。
- seed 补齐船舶页面真实调试数据：画像汇总、AIS 快照/点位、质量问题、风险信号、治理任务、识别差异、候选分析、主体证据样例。
- 新增主体证据附件接口和冲突结论处理接口；主体关系页接入上传、预览、作废、冲突采信。
- 资产台账增加行展开治理详情、批量刷新摘要、批量质量重校验、批量进入治理任务；摘要刷新展示差异和失败原因。
- 新增 `POST /api/v1/vessels/summaries/refresh-batch`，返回摘要刷新前后变化、失败原因和刷新结果明细。
- 候选分析页补业务边界说明，候选结果展示不确定性、空间快照、区域供需说明、节点质量缺口和候选船到节点距离线。
- 候选分析响应追加可选 `boundary_notice、uncertainty_explain、route_layers、regional_supply_demand`。
- 资产、证照、主体、识别、质量、合规、AIS、画像领域 service 均改为真实目录和方法实现，`VesselService` 只作为兼容聚合入口。
- 红线脚本新增单基线、legacy 表引用、领域 service 动态代理、`service.py` 重新长实现体的禁止项。

## 后续优先级

当前台账已无“部分完成”或“未完成”项。后续进入回归保护和精修阶段：补充更多 E2E、将规则映射逐步配置化、继续降低超级 service 内部实现体积，但这些不再阻断船舶管理作为生产基线。
