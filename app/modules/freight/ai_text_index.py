"""Line-only indexing for freight AI source text."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FreightIndexedText:
    raw_text: str
    indexed_text: str
    line_map: dict[str, str]

    @property
    def line_refs(self) -> list[str]:
        return list(self.line_map)


class FreightTextIndexer:
    """Add stable line labels without changing source semantics."""

    def index(self, raw_text: str) -> FreightIndexedText:
        text = raw_text or ""
        lines = text.split("\n")
        line_map = {f"L{index}": line for index, line in enumerate(lines, start=1)}
        indexed_text = "\n".join(f"{line_ref} {line}" for line_ref, line in line_map.items())
        return FreightIndexedText(raw_text=text, indexed_text=indexed_text, line_map=line_map)
