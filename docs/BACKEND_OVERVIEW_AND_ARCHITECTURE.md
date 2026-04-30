# Backend Overview And Architecture

## 定位

后端是内河航运数据分析平台的生产级本地基线。系统围绕真实业务对象建模，不再保留旧演示接口、旧统计表格接口或 E2E 命名主数据。

## 架构

- `app/api/v1`: API router 聚合
- `app/core`: 配置、数据库、异常、日志、安全
- `app/integrations`: 地图、外部路径、通义千问、HTTP 客户端等集成边界
- `app/models`: ORM 数据模型
- `app/modules`: 各业务域的 router/service/repository/schema
- `scripts`: seed、清理和验收脚本
- `alembic`: 数据库迁移

## 业务域

- 基础数据：字典、行政区划、业务区域、运输节点、通航约束点、标准货品
- 船舶管理：主档、尺度载重、AIS/MMSI、运营、主体联系人、证照、历史
- 货源采集：正式货源、来源接入、通义千问解析任务、线索、候选、人工反馈
- 航线规划：航线、运输方案、路线、路线节点、路线段、轨迹
- 数据分析：指标定义、分桶、事实表、快照、任务、图表和地图接口
- 审核治理：审核任务、对象快照、字段差异、审核记录
- 系统管理：用户、角色、菜单、配置、日志

## 配置边界

- 启动级配置来自环境变量和 `.env`。
- `system_config` 仅保存运行期可维护配置和占位配置。
- 敏感项如 `DASHSCOPE_API_KEY`、地图 key 通过接口脱敏展示，真实值优先从环境变量读取。
- 前端地图配置通过 `/api/v1/system/frontend-map-config` 获取，不返回后端 WebService 密钥。

## 初始化与验收

最终本地链路：

1. `alembic upgrade head`
2. `python -m scripts.seed_system_init`
3. `python -m scripts.verify_local_acceptance`
4. `uvicorn main:app --host 0.0.0.0 --port 8000 --reload`

`verify_local_acceptance` 会校验核心数据量、废弃表和废弃接口删除、菜单无旧入口、主业务数据无 `E2E_%` 编码。
