# 船舶数据资产中心 Migration 策略

## 原则

默认保护现有数据，不做破坏式重置。当前船舶资产中心已经沉淀了资产、证据、风险、治理任务、AIS、候选分析和分析事实表，后续 migration 优先采用可回滚、可审计、可兼容既有环境的增量变更。

## 两种路径

1. 保留数据路径：用于已有测试、演示或生产数据的环境。新增字段、索引、约束必须可回滚；涉及历史数据修正时，需要提供数据回填说明和失败恢复方式。
2. 干净基线路径：只有在确认没有生产数据、没有需要保留的演示数据，并经项目负责人确认后，才允许另建干净基线 migration。

## 补丁式 helper 约束

新 migration 不鼓励继续使用 `_has_table`、`_has_column`、`_add_column_if_missing`、`_create_index_if_missing` 这类补丁式 helper。若确实需要兼容多环境 schema 差异，文件头部必须写明：

```python
# MIGRATION_COMPATIBILITY_REASON: 说明为什么必须兼容已有 schema 差异，以及如何验证最终结构一致。
```

`scripts/check_vessel_redlines.py` 会对 0036 及之后的新 migration 做扫描，没有该注释的补丁式 helper 会失败。

## 后续收敛

- 对高价值表逐步补强唯一约束、外键、活跃 fingerprint 约束和任务源关联约束。
- 对旧的物理删除和 replace 路径持续保持生产禁用。
- 每次新增业务表前，必须先更新 `docs/vessel_asset_center_issue_ledger.md`，说明它服务于哪个闭环，而不是只服务一个页面。
