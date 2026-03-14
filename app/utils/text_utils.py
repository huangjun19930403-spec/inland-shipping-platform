"""文本处理工具"""
import re
from typing import Optional


def clean_text(text: str) -> str:
    """清理文本：去除多余空白、统一标点"""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text.strip())
    text = text.replace("，", ",").replace("。", ".")
    return text


def extract_phone(text: str) -> Optional[str]:
    """从文本中提取手机号"""
    pattern = r"1[3-9]\d{9}"
    match = re.search(pattern, text)
    return match.group() if match else None


def normalize_tonnage(text: str) -> Optional[float]:
    """将各种吨位表达转换为数字"""
    if not text:
        return None
    text = text.replace("万吨", "0000").replace("千吨", "000")
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if match:
        return float(match.group(1))
    return None
