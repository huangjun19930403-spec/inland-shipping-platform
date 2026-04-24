# BACKEND SEED AND INITIALIZATION

## 1. 正式 seed 与 demo 数据边界

### 1.1 正式初始化链（线上/测试/本地统一）

正式初始化链包含：

1. `seed_builtin_dicts`
2. `seed_code_sequences`
3. `seed_admin_regions`
4. `seed_commodity_taxonomy`
5. `seed_commodity_standards`
6. `seed_system_base`

统一入口：

- `python -m scripts.seed_system_init`

### 1.2 demo 数据边界

demo freight/ship/route/analysis 数据不在正式初始化链中。  
当前后端初始化默认不加载演示数据。

## 2. seed 数据目录

正式数据源位于 `scripts/seed_data/`：

- 行政区划：
  - `scripts/seed_data/admin_region/admin_region_raw.json`
  - `scripts/seed_data/admin_region/admin_region_boundary_city_raw.json`
- 货品：
  - `scripts/seed_data/commodity/commodity_categories.json`
  - `scripts/seed_data/commodity/commodity_types.json`
  - `scripts/seed_data/commodity/commodity_standards.json`

说明：

- 行政区划 seed 运行时只读取 `scripts/seed_data/admin_region/*`
- 不再从历史 `docs/v3/*` 目录读取 seed 数据

## 3. 各 seed 脚本职责

- `scripts/seed_builtin_dicts.py`
  - 初始化 `std_dict / std_dict_item` 的正式基础字典

- `scripts/seed_code_sequences.py`
  - 初始化 `code_sequence`
  - 包含 `REGION_CODE/NODE_CODE/ROUTE_CODE/FREIGHT_NO/...` 等业务编码序列

- `scripts/seed_admin_regions.py`
  - 初始化 `admin_region` 与行政区划边界信息

- `scripts/seed_commodity_taxonomy.py`
  - 初始化 `commodity_category / commodity_type`

- `scripts/seed_commodity_standards.py`
  - 初始化首版 `commodity_standard / commodity_alias`

- `scripts/seed_system_base.py`
  - 初始化系统基础对象（管理员、角色、权限、菜单、系统配置最小集合）

- `scripts/seed_system_init.py`
  - 统一串联上述正式初始化步骤

## 4. 初始化执行方式

### 4.1 本地命令

```bash
alembic upgrade head
PYTHONPATH=. python -m scripts.seed_system_init
```

### 4.2 容器入口

`docker/entrypoint.sh` 默认执行：

1. 数据库可达等待
2. `alembic upgrade head`
3. `python -m scripts.seed_system_init`
4. `uvicorn main:app ...`

## 5. 幂等与顺序约束

- 正式初始化应按固定顺序执行，避免外键与字典依赖冲突
- 同一环境重复执行时，脚本应尽量幂等（按唯一键更新或跳过）
- `code_sequence` 与系统基础对象初始化必须在业务数据写入前完成
