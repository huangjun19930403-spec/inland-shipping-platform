# 船舶管理 Migration 策略

## 当前决策

生产删除式重构采用当前态干净基线：`alembic/versions/001_initial_schema.py` 是唯一 active Alembic migration，`down_revision = None`。旧补丁链已退出 active 迁移目录，不再作为本地调试或准生产初始化路径。

本轮明确不做旧库在线升级，不迁移旧 `ship_*` 数据，也不在新基线中创建 `ship_profile`、`ship_owner`、`ship_operation`、`ship_certificate`、`ship_import_*`、旧 `stat_ship_*` 或旧 `stat_cargo_*` 表。已有旧库如需保留数据，必须单独立项做离线迁移、核验和回滚方案，不能把破坏性数据切换混进当前基线。

## 本地标准入口

空库初始化必须使用同一条链路：

```bash
alembic upgrade head
python -m scripts.seed_system_init
python scripts/verify_foundation_data_acceptance.py
python scripts/verify_local_acceptance.py
```

`scripts.seed_system_init` 是本地可调试环境的标准入口，seed 顺序保持为：字典、编码序列、行政区、货品、基础样例、E2E 脏数据清理、船舶样例、货源样例、分析样例、系统菜单/权限、本地配置、审核样例、航行限制、航线样例。

seed 必须可重复运行。连续执行两次 `python -m scripts.seed_system_init` 后，两个验收脚本仍必须通过，不能产生重复唯一键、孤儿外键或页面缺调试数据。

## 红线

- active Alembic 目录只允许 `001_initial_schema.py`。
- 新基线不得出现旧 `ship_*`、`ship_import_*`、旧 `stat_ship_*`、旧 `stat_cargo_*`、`cargo_channel*` 表。
- `scripts/check_vessel_redlines.py` 会扫描单基线、legacy 表引用、领域 service 动态代理和 `service.py` 是否重新长出实现体。
- 若未来需要新增 schema，先明确是否继续重建当前态基线；除非重新做迁移策略评审，否则不得恢复补丁式版本链。
