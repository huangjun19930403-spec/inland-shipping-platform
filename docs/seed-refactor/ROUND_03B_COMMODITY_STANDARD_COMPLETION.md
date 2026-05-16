# Round 3B 货品标准体系补齐复核

## 本轮完成

- 复核发现上一轮 92 个标准货品只满足当前 TMS CSV 覆盖，不等于国家/行业核心货类已完整沉淀。
- 将生产货品 seed 从 8 个业务大类、52 个业务类型、92 个标准货品扩展为 22 个大类、126 个中类、169 个标准货品。
- 保留当前 TMS 已入库货源引用的标准货品编码，不重写货源 curated JSON；只调整标准货品所属分类/类型并补齐缺口项。
- 每个货品类型至少有 1 个可入库标准货品；TMS CSV 仍保持 114 个有效唯一货品名全覆盖，4 个固定排除项不入库。

## 依据

- 国家市场监管总局说明 GB/T 42820-2023《多式联运货物分类与代码》给出 19 个大类、116 个中类，用于多式联运货物信息的统计、处理与交换。
- 交通运输部港口综合统计报表制度保留港口货类口径，包含煤炭及制品、石油/天然气及制品、金属矿石、钢铁、矿建材料、水泥、木材、非金属矿石、化肥及农药、盐、粮食、机械设备电器、化工原料及制品、有色金属、轻工医药、农林牧渔产品等核心货类。
- JT/T 1110-2017《多式联运货物分类与代码》的公开表格提供了完整中类名称，作为 GB/T 42820 公开全文不足时的生产 seed 补齐底表。

参考链接：

- https://www.samr.gov.cn/xw/zj/art/2023/art_bc4ef78b583f44008e888c359ebd3d82.html
- https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno=0C0B0B4E21C9372BC0B815616DB6AD46&refer=outter
- https://xxgk.mot.gov.cn/2020/jigou/zhghs/202006/P020200630644654080404.pdf

## 变更文件

- `scripts/seed_data/commodity/commodity_categories.json`
- `scripts/seed_data/commodity/commodity_types.json`
- `scripts/seed_data/commodity/commodity_standards.json`
- `tests/test_commodity_seed_round3.py`
- `docs/SEED_AND_INITIALIZATION.md`

## 校验结果

```bash
.venv/bin/python -m scripts.seeds.curation.commodity_seed --input /Users/hj/Downloads/货品数据.csv
```

- rows: 126
- unique_names: 118
- covered_names: 114
- excluded_names: 4
- unmatched_names: 0
- duplicate_terms: 0

```bash
.venv/bin/python -m pytest tests/test_commodity_seed_round3.py -q
```

- 6 passed

## 遗留风险

- 本轮没有改数据库 schema。GB/T 42820 的原始国家标准正文如后续可提供，应把 22/126 的行业增强表与 GB 19/116 正文逐项做一次严格对照压缩或标注。
- 当前补齐项以“可解释、可匹配、可导入”为优先，部分低频货类使用中类名称作为兜底标准货品，后续可按真实业务继续拆分规格级标准货品。

## 下一步

- 重新跑本地 production seed，让本地 SQLite 中的标准货品从旧 92 条更新为 169 条。
- 后续 Round 4/6 货源、演示和测试数据继续按标准货品 code 关联，不直接依赖分类名称，避免分类补齐影响已有货源。
