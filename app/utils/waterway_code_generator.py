"""
中国水系层级编码自动生成工具

编码结构：WW-LL-NNN
  WW  = 一级流域编码（01~08），见 BASIN_KEYWORDS
  LL  = 水系等级代码（01 主干 / 02 支流 / 03 运河·人工水道）
  NNN = 同 parent_id 下顺序号（001 起步，由数据库原子序列提供）

参考标准：HJ 932-2017 / SL/T 213-2020（为航运业务作了简化处理）

编码示例：
  长江          → 01-01-001
  赣江（长江支流）→ 01-02-001
  湘江（长江支流）→ 01-02-002
  京杭运河      → 08-03-001

并发安全说明：
  序号（NNN）由调用方通过数据库原子序列（code_sequence 表的 upsert）提前获取，
  本工具类不再访问数据库，也不含任何重试逻辑。
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class WaterwayCodeGenerator:
    """
    水系编码生成器（无状态纯工具类）。

    设计原则
    --------
    - 无 I/O 依赖：序号由调用方传入，便于单元测试与替换。
    - 无副作用：相同输入始终产生相同结果。
    - 易扩展：流域关键词映射与等级映射均为可覆盖的类属性。

    使用方式
    --------
    generator = WaterwayCodeGenerator()
    code = generator.generate(
        name="赣江",
        level=2,
        parent_id=1,
        parent_code="01-01-001",
        seq=2,           # 由数据库原子序列提供，已保证唯一
    )
    # → "01-02-002"
    """

    # ── 流域关键词映射 ──────────────────────────────────────────────────────
    # 每个 key 为流域编码（WW），value 为触发该流域匹配的关键词列表。
    # 注意：长串关键词应放在短串前面，避免歧义；运河体系优先级最高（08）。
    # dict 迭代顺序在 Python 3.7+ 中与插入顺序一致，请勿随意调换。
    BASIN_KEYWORDS: dict[str, list[str]] = {
        "08": ["运河", "人工水道", "灌渠", "引水渠", "引水工程", "输水干线"],
        "07": ["海河", "永定河", "大清河", "子牙河", "漳卫河", "潮白河", "北运河"],
        "06": ["松花江", "嫩江", "牡丹江", "呼兰河", "拉林河"],
        "05": ["黑龙江", "乌苏里江", "图们江", "绥芬河", "额尔古纳河"],
        "04": ["珠江", "西江", "北江", "东江", "韩江", "桂江", "柳江", "郁江"],
        "03": ["黄河", "渭河", "汾河", "洛河", "湟水", "伊河", "无定河", "泾河"],
        "02": ["淮河", "颍河", "沙河", "涡河", "史河", "濉河"],
        "01": [
            "长江", "金沙江", "岷江", "嘉陵江", "汉江", "赣江", "湘江",
            "沱江", "乌江", "雅砻江", "大渡河", "清江", "资水", "沅江",
            "洞庭", "鄱阳",
        ],
    }

    # 未能匹配任何关键词时的默认流域（长江），调用方应记录警告
    DEFAULT_BASIN: str = "01"

    # ── 等级代码 ────────────────────────────────────────────────────────────
    LEVEL_TRUNK: str = "01"       # 主干水系（顶级，parent_id 为 NULL 且 level≠3）
    LEVEL_TRIBUTARY: str = "02"   # 支流水系（有父级且 level≠3）
    LEVEL_CANAL: str = "03"       # 运河 / 人工水道（level == 3）

    # ── 编码格式 ────────────────────────────────────────────────────────────
    CODE_SEPARATOR: str = "-"
    SEQ_WIDTH: int = 3            # NNN 补零位数（001~999）

    # ──────────────────────────────────────────────────────────────────────
    # 公开接口
    # ──────────────────────────────────────────────────────────────────────

    def generate(
        self,
        *,
        name: str,
        level: int,
        parent_id: Optional[int],
        parent_code: Optional[str],
        seq: int,
    ) -> str:
        """
        生成符合规范的水系编码。

        Parameters
        ----------
        name        水系名称，用于识别所属流域（WW 段）
        level       水系层级（1=主干, 2=支流, 3=运河/人工水道）
        parent_id   父级水系 ID；NULL 表示顶级水系
        parent_code 父级水系已有编码，用于继承 WW 段；无父级时传 None
        seq         本次插入的序号（由 code_sequence 原子序列提供，已保证唯一）

        Returns
        -------
        str  格式为 ``WW-LL-NNN`` 的编码，例如 ``01-02-003``
        """
        basin = self._resolve_basin(name, parent_code)
        level_seg = self._resolve_level_segment(level, parent_id)
        code = f"{basin}{self.CODE_SEPARATOR}{level_seg}{self.CODE_SEPARATOR}{seq:0{self.SEQ_WIDTH}d}"
        logger.debug(
            "WaterwayCodeGenerator: name=%r level=%d parent_id=%s seq=%d → %s",
            name, level, parent_id, seq, code,
        )
        return code

    # ──────────────────────────────────────────────────────────────────────
    # 内部方法（可在子类中按需覆盖）
    # ──────────────────────────────────────────────────────────────────────

    def _resolve_basin(self, name: str, parent_code: Optional[str]) -> str:
        """
        确定流域段（WW）。
        优先从父级编码继承（子水系与父水系同属一个流域），
        否则按名称关键词识别，识别失败时返回 DEFAULT_BASIN 并记录警告。
        """
        if parent_code:
            parts = parent_code.split(self.CODE_SEPARATOR)
            if len(parts) == 3 and parts[0].isdigit() and len(parts[0]) == 2:
                return parts[0]
        return self._detect_basin_by_name(name)

    def _detect_basin_by_name(self, name: str) -> str:
        """按关键词识别流域编码；未匹配时使用默认值并记录警告。"""
        for basin_code, keywords in self.BASIN_KEYWORDS.items():
            for kw in keywords:
                if kw in name:
                    return basin_code
        logger.warning(
            "WaterwayCodeGenerator: 无法从名称 %r 识别流域，已使用默认值 %s（长江流域），请人工核查",
            name, self.DEFAULT_BASIN,
        )
        return self.DEFAULT_BASIN

    def _resolve_level_segment(self, level: int, parent_id: Optional[int]) -> str:
        """
        确定等级段（LL）。
        level=3 → 运河/人工水道（03）
        parent_id 为 None → 主干水系（01）
        其余 → 支流水系（02）
        """
        if level == 3:
            return self.LEVEL_CANAL
        if parent_id is None:
            return self.LEVEL_TRUNK
        return self.LEVEL_TRIBUTARY
