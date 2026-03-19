# 数据库表结构总览

## 1. 系统与权限

- `sys_role`: 角色字典（SUPER_ADMIN / ADMIN / OPERATOR / COLLECTOR）
- `sys_user`: 用户主表
- `sys_user_role`: 用户-角色关联

## 2. 地址与地理节点

- `waterway`: 水系
- `region`: 商业区域
- `admin_region`: 行政区划
- `node_type`: 节点类型
- `transport_node`: 运输节点（港口/码头/船闸等）
- `node_alias`: 节点别名
- `region_address_relation`: 区域与节点关系
- `code_sequence`: 编码原子序列表（`region`/`ww:*`）

## 3. 货品与货源

- `commodity_category`: 货品大类
- `commodity_type`: 货品类型
- `commodity_standard`: 标准货品
- `commodity_alias`: 标准货品别名
- `cargo_raw_message`: 原始文本（微信群/TMS/手工）
- `cargo_ai_parse_result`: AI 解析结构化结果
- `cargo_freight`: 确认后的货源主表
- `tms_cargo_raw`: TMS 原始货源

## 4. 船舶

- `vessel_type_dict`: 船型字典
- `vessel`: 船舶主表
- `vessel_name_history`: 船名历史
- `vessel_ais_history`: AIS 历史
- `vessel_dynamic`: 船舶最新动态

## 5. 航线路径

- `shipping_route`: 航线主表
- `shipping_route_path`: 路径（一条航线可多路径）
- `shipping_route_path_node`: 路径节点序列

## 6. 审核

- `audit_task`: 当前待办审核任务
- `audit_record`: 审核历史日志

## 7. 统计分析

- `cargo_city_heatmap`: 城市热力聚合
- `cargo_stat_daily`: 日级总览统计
- `cargo_commodity_stat_daily`: 日级货品统计
- `cargo_od_daily`: 日级OD统计
- `cargo_channel_daily`: 日级渠道统计
- `ship_stat_region`: 船舶区域统计
- `ship_stat_city`: 船舶城市统计
- `ship_stat_dwt`: 船舶吨级统计
- `ship_stat_age`: 船龄统计

## 8. AI 管理

- `ai_prompt_template`: 提示词模板
- `ai_prompt_version`: 模板版本
- `ai_call_log`: AI 调用日志

## 9. 建库与初始化建议流程

1. `alembic upgrade head`（当前仅一个最终版脚本 `0001_final`）
2. `python -m scripts.seed_data`（统一初始化基础字典 + 测试货源 + 统计）
3. 启动服务 `uvicorn main:app --reload --host 0.0.0.0 --port 8000`
