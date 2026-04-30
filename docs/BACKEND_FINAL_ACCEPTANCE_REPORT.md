# Backend Final Acceptance Report

## 最终验收命令

```bash
alembic upgrade head
python -m compileall -q app scripts alembic
python -m scripts.seed_system_init
python -m scripts.verify_local_acceptance
```

## 验收范围

- 迁移到 Alembic head。
- 全量 seed 可重复执行。
- 基础数据、船舶、货源、分析、审核样例数据达到本地验证数量。
- 废弃表已删除。
- 废弃接口未注册。
- 菜单无旧入口。
- 主业务数据无 `E2E_%` 编码。

## 保留主链

- 基础数据：行政区划、区域、节点、通航约束点、标准货品。
- 船舶：船舶主档、尺度载重、运营、联系人、证照、历史。
- 货源：正式货源、来源接入、通义千问解析任务、候选确认。
- 航线：航线、方案、路线结构和轨迹。
- 分析：事实表、指标、分桶、图表/地图接口、分析任务。
- 审核：治理队列、对象快照、字段差异、审核记录。

## 已清理对象

- 船舶导入批次产品对象和接口。
- 货品分类/类型复杂业务 CRUD 接口。
- 旧分析表格接口和旧统计表。
- 旧航线和通航约束专用自动化 seed、测试和文档。

## 外部依赖说明

- 通义千问真实调用依赖 `DASHSCOPE_API_KEY`。
- 高德地图展示依赖前端地图配置。
- 未配置密钥时，系统保留 seed 样例和清晰错误提示，不伪造成功调用。
