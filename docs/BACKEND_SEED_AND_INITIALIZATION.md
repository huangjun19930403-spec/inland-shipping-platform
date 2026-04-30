# Backend Seed And Initialization

## 入口

```bash
alembic upgrade head
python -m scripts.seed_system_init
python -m scripts.verify_local_acceptance
```

## seed 顺序

`scripts.seed_system_init` 按固定顺序执行：

1. `seed_builtin_dicts`
2. `seed_code_sequences`
3. `seed_admin_regions`
4. `seed_commodity_taxonomy`
5. `seed_commodity_standards`
6. `seed_foundation_samples`
7. `purge_legacy_e2e_data`
8. `seed_ship_samples`
9. `seed_freight_samples`
10. `seed_analysis_samples`
11. `seed_system_base`
12. `seed_audit_samples`
13. `seed_navigation_constraints`
14. `seed_route_samples`

## 数据边界

- seed 必须幂等，重复运行应更新或跳过同一业务编码。
- 货品分类和货品类型作为标准货品依赖的基础元数据保留，不提供复杂业务 CRUD。
- 船舶导入批次、旧统计表和旧 E2E 航线数据已从最终初始化链移除。
- `purge_legacy_e2e_data` 会清理旧 `E2E_%` 主业务数据，避免污染本地验收。
- 通义千问、地图等密钥只写入占位配置；真实密钥必须来自环境变量。

## 样例数据

- 行政区划和城市边界用于地址、区域和地图。
- 业务区域、运输节点、节点别名、标准货品、货品别名支撑基础数据验证。
- 船舶样例支撑船舶列表、详情和分布图表。
- 货源、来源接入、解析任务、候选和反馈支撑货源采集主链。
- 分析事实数据支撑船舶、货源、区域、流向和运价分析。
- 审核样例支撑待审核、已审核、差异对比和审核记录。
- 航线样例使用真实感内河节点和通航约束点，不使用 E2E 编码。

## 最终验收脚本

`scripts.verify_local_acceptance` 是只读验收脚本，检查：

- 核心表数据量达到本地验证要求。
- 废弃表不存在。
- 废弃接口未注册。
- 菜单不包含旧入口。
- 主业务数据不包含 `E2E_%` 编码。
