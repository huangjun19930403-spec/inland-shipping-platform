"""航线/路线编码自动生成工具"""
import uuid


def gen_route_code() -> str:
    """生成航线编码，格式：RT-XXXXXXXXXXXX（12位大写十六进制）"""
    return f"RT-{uuid.uuid4().hex[:12].upper()}"


def gen_route_path_code() -> str:
    """生成路线编码，格式：RP-XXXXXXXXXXXX（12位大写十六进制）"""
    return f"RP-{uuid.uuid4().hex[:12].upper()}"
