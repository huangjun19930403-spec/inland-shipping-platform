# Round 5 船舶生产清洗

## 本轮完成

- 新增生产船舶清洗工具 `scripts/seed_tools/curate_vessel_seed.py`，默认 dry-run 输出合并、剔除、异常值和货源船名覆盖报告；传入 `--write-curated` 后写入最终 curated seed。
- 新增生产结果文件 `scripts/seed_data/vessel/production_vessels.json`，最终沉淀 71,831 条生产船舶档案；原始 CSV 与中间清洗表不入仓库。
- 新增生产 seed 脚本 `scripts/seed_production_vessels.py`，写入船舶身份、主档、MMSI/外部编码历史、船名历史、登记信息、运力尺度、建造信息、TMS 联系人和船舶摘要。
- 更新 production manifest 与 runner，将 `production_vessels` 放在 `transport_nodes` 之后、`production_freights` 之前；production 仍不读取 `seed_vessel_samples.py` 或 demo/sample 船舶数据。
- `SOURCE_TYPE` 新增 `HIGH_VALUE_INLAND` 与 `TMS_HIGH_VALUE`，用于区分高价值内河船舶档案与两源合并档案。

## 数据输入与清洗结果

- 输入文件：
  - `/Users/hj/Downloads/船舶数据.csv`：TMS 船舶 18,335 行。
  - `/Users/hj/Downloads/高价值内河船舶档案.csv`：高价值内河船舶档案 69,111 行。
- AIS/MMSI 处理：
  - TMS `mmsi` 与 `ais_code` 同义处理；同时存在 18,166 行，0 个冲突。
  - 高价值档案使用 `MMSI(AIS通信码)` 作为 MMSI；`平台唯一ID(aisId)` 仅作为来源追踪，不写入 MMSI 标识。
- 合并结果：
  - `TMS_HIGH_VALUE`：15,095 条。
  - `TMS`：2,724 条。
  - `HIGH_VALUE_INLAND`：54,012 条。
  - 总计：71,831 条。
- 剔除结果：
  - TMS 无有效 9 位 MMSI：169 行。
  - 合并后缺少可用船名：6 组。
- 重复合并：
  - TMS 重复 MMSI 值 153 组。
  - 高价值档案重复 MMSI 值 4 组。
  - 同 MMSI 多船名保留在船名历史，当前船名优先 TMS 货源命中/TMS 当前名，其次高价值档案中文名。
- 行政区划：
  - 船籍港/原始注册地成功匹配城市 68,189 条。
  - 未唯一匹配 3,642 条，仅保留原始船籍港名称，不伪造城市 code。
- 货源船名关联：
  - Round 4 生产货源唯一船名 1,393 个。
  - 本轮船舶命中 1,392 个。
  - 未命中样例：`鲁济宁货8878`。

## 数据质量处理

- 明显异常数值置空，不做猜测换算；例如 `680680.0` 这类超出生产合理区间的载重吨不写入容量字段。
- 异常值计数：长度 425、宽度 428、型深 594、主机功率 627、设计吃水 23,796、满载吃水 175、航速 56,482、载重吨 56、总吨 5、净吨 6。
- 船型优先使用高价值档案 `船舶类型` 映射到现有 `SHIP_TYPE`；TMS-only 船舶保守推断，无法可靠判断写 `OTHER`。
- TMS 联系人按用户确认原文入库；摘要表仅写脱敏手机号用于列表展示。
- 生产 seed 不生成假 AIS 位置、风险叙事、治理任务或候选分析样例。

## 变更文件

- `scripts/seed_tools/curate_vessel_seed.py`
- `scripts/seed_production_vessels.py`
- `scripts/seed_data/vessel/production_vessels.json`
- `scripts/seed_data/production_manifest.json`
- `scripts/seeds/production.py`
- `scripts/seed_builtin_dicts.py`
- `tests/test_vessel_seed_round5.py`
- `tests/test_seed_profiles.py`
- `docs/seed-refactor/ROUND_05_VESSEL_PRODUCTION_CLEANING.md`

## 校验结果

- 清洗工具 dry-run 与写入模式均通过静态校验：MMSI 唯一且 9 位，profile/identity code 唯一且不超长，船型与来源 code 可解析。
- 生产船舶 seed 文件不含 `LOCAL_SAMPLE`、`SEED_AIS_CURRENT`、样例 AIS、风险叙事或候选分析样例。
- 已执行：
  - `python3 -m py_compile scripts/seed_tools/curate_vessel_seed.py scripts/seed_production_vessels.py`
  - `.venv/bin/python -m pytest tests/test_vessel_seed_round5.py tests/test_seed_profiles.py`
- 测试结果：13 passed。

## 遗留风险

- `鲁济宁货8878` 未在两份船舶源中命中；Round 6 如需演示或分析闭环，可由用户补充船舶档案或提供船名映射。
- 3,642 条船籍港未唯一匹配行政区划；当前不做地理猜测，后续可通过用户补充注册地映射表增量修正。
- 联系人原文已按用户选择进入生产 seed，后续如切换到脱敏策略，需要重新生成 curated 文件并调整 seed。

## 下一轮做什么

- Round 6 基于生产节点、航道、货品、船舶、货源重建 demo/test seed。
- demo seed 可复用本轮生产船舶基础档案，但演示 AIS 位置、候选分析、报价、航线、风险样例必须保留 demo 标识，不得写入 production runner。
- 测试夹具应独立放入 test fixtures，E2E 不再假设 production 存在样例船位、样例航线或样例候选分析。
