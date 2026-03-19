"""Excel 文件解析工具"""
from io import BytesIO
from typing import Any
from zipfile import BadZipFile


# Excel 船舶导入模板列名（与 Vessel 模型字段对应）
VESSEL_COLUMNS = [
    "vessel_no",       # 必填：船舶检验证书号
    "vessel_name",     # 必填：船名
    "mmsi",            # AIS/MMSI编号
    "call_sign",       # 呼号
    "vessel_type_id",  # 船舶类型ID
    "deadweight",      # 载重吨(DWT)
    "gross_tonnage",   # 总吨
    "net_tonnage",     # 净吨
    "length",          # 船长(m)
    "breadth",         # 船宽(m)
    "depth",           # 型深(m)
    "max_draft",       # 最大吃水(m)
    "build_year",      # 建造年份
    "build_country",   # 建造国家
    "build_city",      # 建造地
    "home_port",       # 船籍港
    "flag",            # 船旗国
    "owner_name",      # 船东名称
    "contact_phone",   # 联系电话
]

# 需要转为整数的列
_INT_COLS = {"vessel_type_id", "deadweight", "build_year"}
# 需要转为浮点数的列
_FLOAT_COLS = {"gross_tonnage", "net_tonnage", "length", "breadth", "depth", "max_draft"}


def _coerce(col: str, value: Any) -> Any:
    """根据列名做类型转换"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if col in _INT_COLS:
        try:
            return int(float(s))
        except (ValueError, TypeError):
            return None
    if col in _FLOAT_COLS:
        try:
            return float(s)
        except (ValueError, TypeError):
            return None
    return s


def parse_vessel_excel(content: bytes) -> list[dict]:
    """
    解析船舶批量导入 Excel 文件。
    第一行为表头（列名与 VESSEL_COLUMNS 对应，顺序不限），
    后续每行为一条船舶记录。
    返回字段字典列表，空行自动跳过。
    """
    import openpyxl
    from openpyxl.utils.exceptions import InvalidFileException

    try:
        wb = openpyxl.load_workbook(BytesIO(content), data_only=True)
    except (BadZipFile, InvalidFileException, OSError, ValueError) as exc:
        raise ValueError("Excel 文件格式错误，请上传有效的 .xlsx 文件") from exc
    ws = wb.active

    rows_iter = ws.iter_rows(values_only=True)
    # 读取表头
    try:
        header_row = next(rows_iter)
    except StopIteration:
        return []

    headers = [str(h).strip().lower() if h is not None else "" for h in header_row]

    records = []
    for row in rows_iter:
        if all(v is None for v in row):
            continue
        record: dict[str, Any] = {}
        for col_name, value in zip(headers, row):
            if not col_name:
                continue
            coerced = _coerce(col_name, value)
            if coerced is not None:
                record[col_name] = coerced
        if record:
            records.append(record)

    return records
