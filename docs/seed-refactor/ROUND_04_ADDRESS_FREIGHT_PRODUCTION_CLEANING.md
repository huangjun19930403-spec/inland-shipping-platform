# Round 4 地址节点与运单货源生产清洗

## 本轮完成

- 新增生产清洗工具 `scripts/seed_tools/curate_address_freight_seed.py`，默认 dry-run，只在传入 `--write-curated` 时写出 curated JSON。
- 基于 `/Users/hj/Downloads/地址数据.csv` 和 `/Users/hj/Downloads/运单数据-修正.csv` 生成生产结果数据：
  - `scripts/seed_data/address/business_regions.json`
  - `scripts/seed_data/address/transport_nodes.json`
  - `scripts/seed_data/freight/tms_freights.json`
- 新增生产 seed 脚本：
  - `scripts/seed_business_regions.py`
  - `scripts/seed_transport_nodes.py`
  - `scripts/seed_production_freights.py`
- 更新 production manifest 和 production runner，使生产 seed 在货品、航道基础数据之后导入业务区域、运输节点和 TMS 历史货源。
- 对 Round 3 货品 seed 做运单回归补丁：`碎石`、`水泥`、`玉米` 可稳定命中标准货品；`吨包/吨袋` 仍保持包装-only，不作为货品入库。
- 更新 `verify_foundation_data_acceptance.py`，生产 curated 节点不再要求伪造联系人；demo 节点仍可继续通过联系人检查。

## 数据输入摘要

- 地址 CSV：1189 行，1189 个唯一地址编码，1180 个唯一名称，9 组重名；地址城市 72 个，均可在现有行政区划中解析。
- 运单 CSV：9926 行，8168 个唯一运单编码，2284 个船名，35 个货品名，322 个非空唯一装卸端点。
- 原始 CSV 未提交仓库；仓库只保留最终 curated JSON 和可复跑工具。

## 清洗结果

- 运输节点：1181 个。
  - 同名、同城、同类型且坐标距离 3km 内的地址合并，保留全部来源地址编码。
  - `码头/厂区 -> TERMINAL`，`闸口 -> LOCK`，`锚地 -> ANCHORAGE`，`服务区 -> LOGISTICS_PARK`，`加油站 -> OTHER`。
  - 上海、重庆等直辖市使用省级行政区记录作为城市级关联。
- 业务区域：6 个。
  - 按省份归并为长三角、皖江、长江中游、华北华中、长江上游、东南沿海联运节点区。
- TMS 历史货源：4081 条。
  - 按 `运单编码` 聚合为唯一货源。
  - `freight_no=FR-TMS-<运单编码去掉YD前缀>`，`source_ref_no=原运单编码`。
  - 状态为 `CLOSED`，大厅状态为 `NOT_LISTED`，避免污染演示/交易大厅数据。
  - 所有入库货源均有标准货品、装货节点、卸货节点、城市和业务区域关联。

## 剔除口径

- `EXCLUDED_COMMODITY`：149 个运单组，包含测试货品、包装-only 货品等。
- `NULL_KEY_FIELD`：2 个运单组，货品或装卸地关键字段为空。
- `CORE_FIELD_CONFLICT`：2 个运单组，同一运单编码下核心业务字段冲突。
- `UNMATCHED_ORIGIN_NODE`：1520 个运单组，装货地无法唯一匹配生产地址节点。
- `UNMATCHED_DESTINATION_NODE`：2414 个运单组，卸货地无法唯一匹配生产地址节点。

无法唯一匹配到地址主数据的端点不创建猜测节点；后续如补充端点映射或修正地址文件，可复跑工具增量提高入库率。

## 验证结果

- `python3 scripts/seed_tools/curate_address_freight_seed.py --addresses /Users/hj/Downloads/地址数据.csv --waybills /Users/hj/Downloads/运单数据-修正.csv`
  - dry-run 成功，货品未匹配为 0。
- `.venv/bin/pytest tests/test_commodity_seed_round3.py tests/test_address_freight_seed_round4.py tests/test_seed_profiles.py`
  - 20 passed。
- 临时库验证：
  - `env DATABASE_URL=sqlite+aiosqlite:////private/tmp/round4_seed_acceptance.db .venv/bin/alembic upgrade head`
  - `env DATABASE_URL=sqlite+aiosqlite:////private/tmp/round4_seed_acceptance.db .venv/bin/python -m scripts.seeds.production`
  - production seed 成功，导入 6 个业务区域、1181 个节点、4081 条货源；后续货品复核已把标准货品从 92 个补齐到 169 个。
  - `env DATABASE_URL=sqlite+aiosqlite:////private/tmp/round4_seed_acceptance.db .venv/bin/python -m scripts.seeds.validation.foundation_data_acceptance`
  - 验收通过。

## 遗留风险

- 当前不调用地图 API 或网络检索补节点，未匹配端点不会自动生成生产节点。
- 地址 CSV 不含联系人、泊位、吃水、吞吐能力等实测经营字段，本轮生产节点不生成虚假联系人或虚构能力，只保留基础能力标签。
- 运单中的船名已保留在 curated freight JSON 的 `source_ship_name` / `normalized_ship_name`，但当前 `freight` 表无结构化船舶关联字段，需 Round 5 船舶生产清洗后再建立船舶侧关联策略。

## 下一轮做什么

Round 5 进入船舶生产清洗。开始前需要用户提供：

- 当前 TMS 船舶数据。
- 高价值内河船舶档案数据。

Round 5 将以 MMSI/AIS 号、船名、尺度、吨位、证书/档案字段为核心做去重合并，产出生产船舶身份、档案、容量和历史标识 seed；同时复用本轮货源中的 `source_ship_name` / `normalized_ship_name`，评估哪些历史货源可以在生产 seed 中建立到船舶档案的可解释关联。
