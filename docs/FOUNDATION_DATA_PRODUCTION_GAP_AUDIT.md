# 基础数据模块生产级重构审计

- 审计日期：2026-04-30
- 审计范围：后端基础数据模块
- 工作分支：`refactor/foundation-production`
- 基准分支：`V3`
- Round 1 结论：本轮仅新增审计文档，不修改业务代码、不调整数据库结构、不变更 seed 执行结果、不改变 API 行为。

## 1. 当前基础数据模块页面、接口、表模型清单

### 1.1 货品基础数据

表模型：
- `CommodityCategory`：货品分类。
- `CommodityType`：货品类型。
- `CommodityStandard`：标准货品主表。
- `CommodityAlias`：货品别名。
- `CommodityStandardAttribute`：货品属性。
- `CommodityPackagingForm`：包装形式适配。
- `CommodityTransportMode`：运输方式适配。
- `CommodityShipTypeRule`：船型适配规则。
- `CommodityNodeTypeRule`：节点类型适配规则。
- `CommodityHandlingModeRule`：作业方式适配规则。

接口模块：
- `app/modules/commodity/router.py`
- `app/modules/commodity/schemas.py`
- `app/modules/commodity/service.py`
- `app/modules/commodity/repository.py`

主要接口：
- `GET /commodity/categories`
- `GET /commodity/types`
- `GET /commodity/standards`
- `POST /commodity/standards`
- `GET /commodity/standards/{standard_id}`
- `PUT /commodity/standards/{standard_id}`
- `PUT /commodity/standards/{standard_id}/aliases`
- `PUT /commodity/standards/{standard_id}/attributes`
- `PUT /commodity/standards/{standard_id}/rules`
- `DELETE /commodity/standards/{standard_id}`

### 1.2 地址基础数据

表模型：
- `AdminRegion`：行政区划。
- `AdminRegionBoundary`：行政区划边界。
- `Region`：业务区域。
- `RegionBoundaryVersion`：业务区域边界版本。
- `RegionCityRelation`：区域-城市关系。
- `TransportNode`：地址节点/运输节点。
- `TransportNodeProfile`：节点能力档案。
- `NodeAlias`：节点别名。
- `TransportNodeBusinessCategory`：节点业务分类。
- `TransportNodePackagingForm`：节点包装能力。
- `TransportNodeHandlingMode`：节点作业能力。
- `NavigationConstraintPoint`：通航约束点。
- `NavigationConstraintProfile`：通航约束点能力参数。

接口模块：
- `app/modules/address/router.py`
- `app/modules/address/schemas.py`
- `app/modules/address/service.py`
- `app/modules/address/repository.py`

主要接口：
- `GET /address/admin-regions`
- `GET /address/admin-regions/{admin_code}`
- `GET /address/admin-regions/{admin_code}/children`
- `GET /address/admin-regions/options/cities`
- `GET /address/admin-regions/options/cities/{city_code}/districts`
- `GET /address/regions`
- `POST /address/regions`
- `GET /address/regions/{region_id}`
- `PUT /address/regions/{region_id}`
- `POST /address/regions/{region_id}/boundaries`
- `GET /address/regions/{region_id}/boundaries`
- `POST /address/regions/{region_id}/boundaries/{boundary_id}/activate`
- `GET /address/nodes`
- `POST /address/nodes`
- `GET /address/nodes/{node_id}`
- `PUT /address/nodes/{node_id}`
- `PUT /address/nodes/{node_id}/profile`
- `PUT /address/nodes/{node_id}/support`
- `GET /address/constraint-points`
- `POST /address/constraint-points`
- `GET /address/constraint-points/{point_id}`
- `PUT /address/constraint-points/{point_id}`
- `PUT /address/constraint-points/{point_id}/profile`

### 1.3 字典与编码

表模型：
- `StdDict`：标准字典。
- `StdDictItem`：标准字典项。
- `CodeSequence`：自动编码序列。

接口模块：
- `app/modules/dictionary/router.py`
- `app/modules/dictionary/schemas.py`
- `app/modules/dictionary/service.py`
- `app/modules/dictionary/repository.py`

主要接口：
- `GET /dictionary/dicts`
- `POST /dictionary/dicts`
- `PUT /dictionary/dicts/{dict_id}`
- `DELETE /dictionary/dicts/{dict_id}`
- `GET /dictionary/dicts/{dict_id}/items`
- `POST /dictionary/dicts/{dict_id}/items`
- `PUT /dictionary/items/{item_id}`
- `DELETE /dictionary/items/{item_id}`
- `GET /dictionary/options`
- `GET /dictionary/code-sequences`
- `GET /dictionary/code-sequences/{sequence_id}`

### 1.4 地图集成与文档、脚本

集成模块：
- `app/integrations/amap/geocode_client.py`

种子与验收脚本：
- `scripts/seed_builtin_dicts.py`
- `scripts/seed_code_sequences.py`
- `scripts/seed_admin_regions.py`
- `scripts/seed_foundation_samples.py`
- `scripts/seed_commodity_taxonomy.py`
- `scripts/seed_commodity_standards.py`
- `scripts/seed_navigation_constraints.py`
- `scripts/seed_system_base.py`
- `scripts/verify_local_acceptance.py`

数据库迁移：
- `alembic/versions/*`

已有文档：
- `docs/BACKEND_API_REFERENCE.md`
- `docs/BACKEND_DATA_MODEL_AND_SEQUENCE.md`
- `docs/BACKEND_SEED_AND_INITIALIZATION.md`
- `docs/V3_FOUNDATION_AND_AUDIT_GAP_AUDIT.md`

## 2. 已完成能力

- 货品主数据的分类、类型、标准货品、别名、属性、包装、运输方式、船型、节点类型、作业方式等表结构已经具备。
- 地址主数据的行政区划、行政区划边界、业务区域、业务区域边界、区域-城市关系、运输节点、节点能力、通航约束点等表结构已经具备。
- `CodeSequenceService` 已支持按序列生成业务编码，且存在 `COMMODITY_STANDARD_CODE`、`REGION_CODE`、`NODE_CODE`、`NAV_CONSTRAINT_POINT_CODE` 等 seed。
- 字典模块已经提供字典、字典项、选项查询能力，部分基础字典具备中文名称。
- 业务区域边界已经有保存、查询、激活能力，`seed_foundation_samples.py` 中存在可渲染的 GeoJSON 样例。
- AMap WebService 逆地理编码客户端已有雏形，后端已能从运行配置读取服务端地图 key。

## 3. 未完成能力

- commodity、address、dictionary 基础数据 router 未统一接入登录认证。
- 标准货品、业务区域、地址节点、通航约束点创建接口仍允许前端传入业务编码。
- 主单位仍为 `main_unit` 自由字符串，缺少生产级单位字典和中文 label 响应。
- 危险等级仍为 `dangerous_grade_code` 字符串，缺少危险等级字典和中文 label 响应。
- 标准货品详情的适配规则仅返回 code 数组，未返回 `{ code, name, is_default, allow_flag, rule_desc }` 等结构化明细。
- 行政区划边界只有模型和 seed，没有 `GET /address/admin-regions/{admin_code}/boundaries` 与 `GET /address/admin-regions/{admin_code}/current-boundary`。
- 后端缺少 `/address/map/geocode` 与 `/address/map/reverse-geocode` 统一地址解析接口。
- 节点创建链路不能通过 city_code 自动匹配 `city_region_id`。
- seed 与验收脚本没有覆盖基础数据生产级关键链路。

## 4. 设计不合理点

- 标准货品创建 schema 同时承载核心字段和补充字段，不适合作为生产级新增入口。
- `CommodityStandardCreateRequest.code`、`BusinessRegionCreateRequest.code`、`TransportNodeCreateRequest.code`、`NavigationConstraintPointCreateRequest.code` 保留为普通输入字段，弱化了后端自动编码权威性。
- `main_unit` 使用自由文本，不利于检索、统计和跨模块一致展示。
- 危险等级使用裸 code，不利于业务人员维护。
- 标准货品适配规则更新接口只传 code 列表，丢失默认项、允许/禁止、规则说明等业务语义。
- 基础数据详情接口缺少字典 label 聚合，导致前端需要反复自行拼字典。
- 行政区划边界 seed 中部分数据以 WKT 包裹在 `geometry_json` 内，和前端 GeoJSON 渲染契约不一致。

## 5. 前后端字段不一致点

- 标准货品后端返回 `main_unit`，前端页面按文本直接展示；目标应收敛为 `main_unit_code` 和 `main_unit_name`。
- 标准货品后端返回 `dangerous_grade_code`，前端直接作为输入框维护；目标应补充 `dangerous_grade_name`。
- 标准货品详情后端返回 `packaging_form_codes`、`transport_mode_codes`、`ship_type_codes`、`node_type_codes`、`handling_mode_codes`，前端需要自行查字典；目标应由后端返回结构化中文明细。
- 地址节点后端返回 `province_code`、`city_code`、`district_code`、`node_type_code`、`lifecycle_status`、`status`，缺少 `province_name`、`city_name`、`district_name`、`node_type_name`、`lifecycle_status_name`、`status_name`。
- 通航约束点后端返回 `constraint_type_code`、`city_code` 等 raw code，缺少业务展示所需中文名。

## 6. 中英文混合展示问题

- 当前后端响应没有统一提供中文 label，前端详情和列表容易出现 `BULK_CARRIER`、`GENERAL_CARGO`、`NODE_TYPE`、`LOCK`、`BRIDGE` 等 code。
- 字典项虽然有中文名，但 commodity/address 响应没有把字典 label 合并到业务对象中。
- 后续应约定：code 只作为辅助字段，业务主视觉默认展示中文名；如需查看编码，应由前端提供“显示编码”开关或 tooltip。

## 7. 自动编码暴露问题

- `CommodityStandardService.create_standard` 仅在未传 code 时调用 `CodeSequenceService.next_code("COMMODITY_STANDARD_CODE")`，仍允许外部传 code。
- `AddressService.create_region`、`create_node`、`create_constraint_point` 同样是“未传则自动生成”，并未从 schema 和服务层彻底收口。
- 生产级目标：新增接口不依赖前端传入自动编码；如保留兼容字段，只能内部兼容，不在前端展示，不作为业务主路径。

## 8. 详情/编辑职责混淆问题

- 后端目前没有明显区分“详情只读响应”和“编辑保存请求”的资源视角。
- 标准货品的基础信息、别名、属性、适配规则支持在详情页直接保存，导致前端详情页天然变成复合编辑页。
- 节点 profile、support、alias 以及区域边界、城市关系等能力也更适合进入明确编辑态后维护。
- 后续 API 可保留资源更新能力，但前端交互必须改为详情只读、独立编辑页或明确编辑 Drawer。

## 9. 地图边界与选址链路缺口

- 行政区划边界模型 `AdminRegionBoundary` 已存在，但接口层缺少边界查询能力。
- 业务区域边界接口存在，但缺少清晰的 current boundary 查询契约。
- 地图选址缺少后端统一 geocode/reverse-geocode 接口，现有 AMap 客户端只实现逆地理编码。
- 后端需要返回统一地址结构：经纬度、格式化地址、省市区名称与编码、adcode、provider、confidence/level。
- 服务端应持有 WebService key，前端不应直接承担核心地理编码业务逻辑。

## 10. 字典、seed、验收脚本缺口

- `seed_builtin_dicts.py` 缺少 `COMMODITY_UNIT` 或 `MEASURE_UNIT` 字典，也缺少 `DANGEROUS_GOODS_LEVEL`。
- `seed_commodity_standards.py` 和 `seed_foundation_samples.py` 仍写入中文文本形式的 `main_unit`。
- `seed_admin_regions.py` 的边界数据契约需统一为可渲染 GeoJSON 或由后端规范化输出。
- `verify_local_acceptance.py` 未检查自动编码序列、单位和危险等级中文字典、标准货品详情中文规则、行政区划边界接口、地图接口、基础数据 router 认证、seed 幂等。

## 11. 删除清单

后续整改应删除或停用：
- 创建标准货品、业务区域、地址节点、通航约束点时外部传入业务编码的主路径。
- 标准货品新增入口中的英文名、密度/规格、危险等级、属性、别名、适配规则等非核心字段。
- 标准货品适配规则仅以 code 数组作为详情展示数据的响应模式。
- 地址节点创建时手工输入 `city_region_id` 的业务入口。
- 行政区划边界以不可渲染 WKT 包装直接暴露给前端地图的契约。

## 12. 修改清单

后续整改应修改：
- commodity/address/dictionary router：统一增加登录认证依赖。
- commodity schema/service/response：区分创建核心字段、补充信息、详情结构化规则。
- `CommodityStandard.main_unit`：收敛为 `main_unit_code`，并通过字典返回中文名。
- 危险等级：使用 `DANGEROUS_GOODS_LEVEL` 字典，响应补充中文名。
- address schema/service/response：补充行政区划、节点类型、生命周期、状态、约束类型等中文名。
- seed：补齐单位、危险等级、节点类型、作业方式、包装形式等中文字典，并保证幂等。
- 验收脚本：新增基础数据生产级关键链路检查。

## 13. 新增清单

后续整改应新增：
- `GET /address/admin-regions/{admin_code}/boundaries`
- `GET /address/admin-regions/{admin_code}/current-boundary`
- `GET /address/map/geocode`
- `GET /address/map/reverse-geocode`
- `COMMODITY_UNIT` 字典，建议包含吨、立方米、件、箱、车、船次。
- `DANGEROUS_GOODS_LEVEL` 字典。
- 标准货品详情结构化规则响应。
- 基础数据验收脚本，例如 `scripts/verify_foundation_data_acceptance.py`。

## 14. 分轮整改计划

- Round 1：新增本审计文档，冻结后端生产级整改方案。
- Round 2：完成字典、编码、中文展示基础能力整改，并将基础数据 router 接入认证。
- Round 3：重构标准货品模型、schema、service、详情响应与适配规则。
- Round 4：重构行政区划、业务区域边界接口和地图展示契约。
- Round 5：重构地址节点地图选址链路，新增后端地理编码与逆地理编码接口。
- Round 6：统一基础数据详情只读与明确编辑态。
- Round 7：新增基础数据验收脚本并形成最终收口报告。

## 15. 每轮预期提交内容

### Round 1

- 变更：新增 `docs/FOUNDATION_DATA_PRODUCTION_GAP_AUDIT.md`。
- Migration：不涉及。
- Seed：不涉及。
- API：不涉及。
- 联调：不需要。
- 检查：`git diff --check`。

### Round 2

- 变更：字典、编码、中文 label、认证依赖、响应字段、前端新增表单隐藏自动编码。
- Migration：可能涉及 `main_unit` 字段重命名或新增 `main_unit_code`。
- Seed：涉及，补齐单位和危险等级字典。
- API：涉及，响应新增中文名字段；创建接口收口自动编码。
- 联调：需要。
- 检查：Alembic、seed、后端测试或验收脚本、前端 type-check/build。

### Round 3

- 变更：标准货品生产级主数据维护，详情结构化规则，补充信息与核心字段分离。
- Migration：涉及。
- Seed：涉及。
- API：涉及。
- 联调：需要。
- 检查：标准货品创建、详情、编辑、规则维护链路。

### Round 4

- 变更：行政区划边界接口、当前边界接口、业务区域边界契约校准。
- Migration：视边界字段规范化结果决定。
- Seed：涉及，补充可验证边界样例。
- API：涉及。
- 联调：需要。
- 检查：地图 polygon 真实渲染。

### Round 5

- 变更：地图 geocode/reverse-geocode 后端接口、节点选址回填、节点新增/编辑表单简化。
- Migration：视地址标准化字段决定。
- Seed：可能涉及。
- API：涉及。
- 联调：需要。
- 检查：地址搜索、候选选择、地图点击逆地理、city_region_id 自动匹配。

### Round 6

- 变更：基础数据详情只读、独立编辑模式、未保存离开确认、旧混合表单清理。
- Migration：不一定涉及。
- Seed：不一定涉及。
- API：可能补齐编辑接口。
- 联调：需要。
- 检查：列表、详情、编辑、保存、取消、离开确认。

### Round 7

- 变更：新增基础数据验收脚本、文档、最终报告。
- Migration：验证 `alembic upgrade head`。
- Seed：验证重复执行幂等。
- API：验证关键接口可用和认证生效。
- 联调：需要。
- 检查：后端验收脚本、前端 type-check/build、核心页面最小交互验证。
