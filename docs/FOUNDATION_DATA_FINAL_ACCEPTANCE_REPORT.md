# 基础数据模块最终验收报告

## 范围

本报告对应 Round 1-7 的基础数据生产级整改收口，覆盖货品基础数据、地址基础数据、字典与编码、边界地图和节点地图选址。后端当前工作分支为 `refactor/foundation-production`。

## 能力闭环

- 基础数据 `commodity`、`address`、`dictionary` 路由已统一接入登录认证，包含字典 options、编码序列、地图 geocode/reverse-geocode 等接口。
- 标准货品、业务区域、运输节点、通航约束点新增流程不再依赖前端传入业务编码；编码由 `CodeSequenceService` 统一生成。
- 标准货品主单位收敛为 `main_unit_code`，单位、危险等级、包装形式、运输方式、船型、节点类型、作业方式、属性值类型均由字典提供中文展示。
- 标准货品详情返回结构化规则明细，包含中文 label、默认项、允许/禁止和规则说明。
- 行政区划边界与业务区域边界接口统一返回可渲染 GeoJSON，并提供 current boundary 语义。
- 地址地图服务通过后端 AMap WebService key 完成 geocode/reverse-geocode，前端不暴露服务端 key。
- 节点 create/update 不要求前端传 `city_region_id`，后端根据 `city_code` 解析。
- seed 支持重复执行，验收脚本检查关键唯一编码无重复和旧 WKT 包装污染。

## 验收命令

后端最终验收按以下顺序执行：

```bash
python -m compileall app scripts
alembic upgrade head
.venv/bin/python -m scripts.seed_system_init
.venv/bin/python -m scripts.seed_system_init
.venv/bin/python -m scripts.verify_foundation_data_acceptance
.venv/bin/python -m scripts.verify_local_acceptance
git diff --check
```

`scripts.verify_foundation_data_acceptance` 覆盖：

- 基础数据路由登录保护。
- 编码序列写接口存在且需要登录。
- 编码序列可生成编码且验收过程中不会污染当前值。
- 单位、危险等级和规则字典中文 label。
- 标准货品详情结构化规则中文 label。
- 节点行政区划映射和 `city_region_id` 后端解析。
- 地图候选地址标准响应字段和行政区划映射。
- 行政区划、业务区域当前边界 GeoJSON。
- seed 幂等后的关键唯一编码重复检查。

## 真实联调边界

- 无 AMap WebService key 时，验收脚本使用 fixture/mock 风格的 `GeocodeCandidate` 验证标准地址结构和行政区划映射；真实 provider 联网检查需要部署环境提供 key。
- 本轮不新增数据库 migration，不新增业务 API；仅增强验收脚本和最终报告。
- 前端页面交互验收由前端仓库 Playwright 用例覆盖，后端只保证接口、seed、认证和响应契约。
