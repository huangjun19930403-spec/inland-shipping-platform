"""内置标准字典初始化脚本。"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.dictionary import StdDict, StdDictItem


def _item(
    code: str,
    name: str,
    *,
    name_en: str | None = None,
    color: str | None = None,
    description: str | None = None,
    is_default: bool = False,
) -> dict[str, Any]:
    return {
        "item_code": code,
        "item_name": name,
        "item_name_en": name_en or code,
        "color": color,
        "description": description,
        "is_default": is_default,
    }


def _items(*pairs: tuple[str, str] | str) -> list[dict[str, Any]]:
    return [
        _item(raw[0], raw[1]) if isinstance(raw, tuple) else _item(raw, raw)
        for raw in pairs
    ]


BUILTIN_DICTS: list[dict[str, Any]] = [
    {"dict_code": "NODE_TYPE", "dict_name": "节点类型", "items": _items(("PORT", "港口"), ("TERMINAL", "码头"), ("ANCHORAGE", "锚地"), ("LOCK", "船闸"), ("LOGISTICS_PARK", "物流园"), ("RAIL_STATION", "铁路货站"), ("HIGHWAY_PORT", "公路港"), ("INTERMODAL_HUB", "多式联运枢纽"), ("OTHER", "其他节点"))},
    {"dict_code": "BUSINESS_CATEGORY", "dict_name": "业务类别", "items": _items(("LOADING", "装货"), ("UNLOADING", "卸货"), ("TRANSFER", "中转"), ("TRANSSHIPMENT", "换装"), ("STORAGE", "仓储"), ("PASSAGE", "通行"), ("COMPREHENSIVE", "综合服务"))},
    {"dict_code": "PACKAGING_FORM", "dict_name": "包装形式", "items": _items(("BULK", "散装"), ("TON_BAG", "吨袋"), ("BAGGED", "袋装"), ("BOXED", "箱装"), ("CONTAINER", "集装箱"), ("GENERAL_CARGO", "件杂货"))},
    {"dict_code": "NODE_CONTACT_TYPE", "dict_name": "节点联系人类型", "items": _items(("OPERATIONS", "运营联系人"), ("DISPATCH", "调度联系人"), ("BUSINESS", "商务联系人"), ("SETTLEMENT", "结算联系人"), ("SAFETY", "安全联系人"), ("EMERGENCY", "应急联系人"))},
    {"dict_code": "NODE_PHOTO_TYPE", "dict_name": "节点实况照片类型", "items": _items(("OVERVIEW", "全景"), ("WORK_AREA", "码头作业区"), ("YARD", "堆场"), ("BERTH", "泊位"), ("ENTRANCE", "入口"), ("OTHER", "其他"))},
    {"dict_code": "COMMODITY_UNIT", "dict_name": "货品主单位", "items": [_item("TON", "吨", is_default=True), _item("CUBIC_METER", "立方米"), _item("PIECE", "件"), _item("BOX", "箱"), _item("TRUCK", "车"), _item("VOYAGE", "船次"), _item("OTHER", "其他")]},
    {"dict_code": "COMMODITY_CARGO_FORM", "dict_name": "货物形态", "items": [_item("BULK_GRANULAR", "散状颗粒", is_default=True), _item("POWDER", "粉状"), _item("BLOCK", "块状"), _item("LIQUID", "液体"), _item("BAGGED", "袋装"), _item("CONTAINERIZED", "箱装/单元化"), _item("ROLL", "卷状"), _item("EQUIPMENT", "设备/大件"), _item("OTHER", "其他")]},
    {"dict_code": "COMMODITY_ALIAS_TYPE", "dict_name": "货品别名类型", "items": [_item("COMMON_NAME", "俗称", is_default=True), _item("SHORT_NAME", "简称"), _item("LOCAL_NAME", "地方叫法"), _item("SYSTEM_NAME", "外部系统名"), _item("HISTORICAL_NAME", "历史名称"), _item("AI_KEYWORD", "AI 识别关键词")]},
    {"dict_code": "COMMODITY_IMAGE_TYPE", "dict_name": "货品图片类型", "items": [_item("OVERVIEW", "货品示意图", is_default=True), _item("SPEC_SAMPLE", "规格样例"), _item("PACKAGING", "包装形态"), _item("LOADING_SCENE", "装卸场景"), _item("QUALITY_DOC", "质检/单证"), _item("OTHER", "其他")]},
    {"dict_code": "COMMODITY_RULE_TYPE", "dict_name": "货品能力规则类型", "items": [_item("RECOMMENDED", "推荐", color="success"), _item("ALLOWED", "允许", color="primary", is_default=True), _item("FORBIDDEN", "禁止", color="danger")]},
    {"dict_code": "COMMODITY_OPERATION_SIDE", "dict_name": "货品节点适用环节", "items": [_item("ANY", "不限", is_default=True), _item("LOADING", "装货"), _item("UNLOADING", "卸货"), _item("TRANSFER", "中转"), _item("STORAGE", "仓储")]},
    {"dict_code": "POLLUTION_RISK_LEVEL", "dict_name": "污染风险等级", "items": [_item("LOW", "低", color="success", is_default=True), _item("MEDIUM", "中", color="warning"), _item("HIGH", "高", color="danger"), _item("UNKNOWN", "未知", color="info")]},
    {"dict_code": "COMMODITY_ATTRIBUTE_GROUP", "dict_name": "货品属性分组", "items": [_item("PHYSICAL", "物理属性", is_default=True), _item("QUALITY", "质量指标"), _item("TRANSPORT", "运输要求"), _item("SAFETY", "安全环保"), _item("BUSINESS", "业务识别")]},
    {"dict_code": "DANGEROUS_GOODS_LEVEL", "dict_name": "危险货物等级", "items": [_item("NON_DANGEROUS", "非危险品", is_default=True), _item("CLASS_1", "第1类 爆炸品"), _item("CLASS_2", "第2类 气体"), _item("CLASS_3", "第3类 易燃液体"), _item("CLASS_4", "第4类 易燃固体"), _item("CLASS_5", "第5类 氧化性物质"), _item("CLASS_6", "第6类 毒性和感染性物质"), _item("CLASS_7", "第7类 放射性物质"), _item("CLASS_8", "第8类 腐蚀性物质"), _item("CLASS_9", "第9类 杂项危险物质")]},
    {"dict_code": "HANDLING_MODE", "dict_name": "装卸方式", "items": _items(("GRAB", "抓斗"), ("PIPELINE", "管输"), ("CONVEYOR", "皮带机"), ("CRANE", "吊装"), ("MANUAL", "人工/叉车"), ("SELF_UNLOADING", "自卸"), ("OTHER", "其他"))},
    {"dict_code": "SHIP_TYPE", "dict_name": "船型", "items": _items(("DRY_BULK", "干散货船"), ("GENERAL_CARGO", "普通货船"), ("SELF_UNLOADING_SAND", "自卸砂石船"), ("BULK_CEMENT", "散装水泥船"), ("CONTAINER", "集装箱船"), ("BULK_CONTAINER", "散改集船"), ("MULTI_PURPOSE", "多用途船"), ("OIL_TANKER", "油船"), ("CHEMICAL_TANKER", "化学品船"), ("ENGINEERING", "工程船"), ("TUG", "拖轮"), ("OTHER", "其他船型"))},
    {"dict_code": "SHIP_OPERATION_STATUS", "dict_name": "船舶运营状态", "items": [_item("OPERATING", "运营中", color="success"), _item("IN_PORT", "在港待装", color="warning"), _item("MAINTENANCE", "检修中", color="info"), _item("SUSPENDED", "暂停运营", color="danger")]},
    {"dict_code": "PARTY_SUBJECT_TYPE", "dict_name": "主体类型", "items": [_item("COMPANY", "公司", color="primary"), _item("PERSON", "个人", color="success"), _item("OTHER", "其他", color="info"), _item("UNKNOWN", "未确认", color="warning", is_default=True)]},
    {"dict_code": "CONTACT_SCOPE", "dict_name": "船舶联系人归属", "items": _items(("GENERAL", "通用联系人"), ("OWNER", "所有方联系人"), ("OPERATOR", "运营方联系人"), ("CREW", "船员联系人"))},
    {"dict_code": "CONTACT_ROLE", "dict_name": "船舶业务联系人角色", "items": _items(("BUSINESS_CONTACT", "业务联系人"), ("OWNER_CONTACT", "所有方联系人"), ("OPERATOR_CONTACT", "运营方联系人"), ("CREW_CONTACT", "船员联系人"), ("SETTLEMENT_CONTACT", "结算联系人"), ("SAFETY_CONTACT", "安全联系人"), ("EMERGENCY_CONTACT", "应急联系人"), ("OTHER", "其他联系人"))},
    {"dict_code": "VESSEL_CREW_ROLE", "dict_name": "船员角色", "items": _items(("CAPTAIN", "船长"), ("CHIEF_ENGINEER", "轮机长"), ("DECK_CREW", "甲板船员"), ("ENGINE_CREW", "轮机船员"), ("OTHER", "其他船员"))},
    {"dict_code": "CERTIFICATE_TYPE", "dict_name": "证件类型", "items": _items(("UNKNOWN", "待识别"), ("VESSEL_OWNERSHIP_CERT", "船舶所有权证书"), ("VESSEL_NATIONALITY_CERT", "船舶国籍证书"), ("VESSEL_OPERATION_CERT", "船舶营业运输证"), ("VESSEL_INSPECTION_BOOK", "船检簿子"), ("VESSEL_SEAWORTHINESS_CERT", "适航证"), ("VESSEL_AIS_CERT", "船舶 AIS 证书"), ("CREW_COMPETENCY_CERT", "船员适任证"), ("OTHER", "其他证照"))},
    {"dict_code": "OWNER_DOCUMENT_TYPE", "dict_name": "所有方证照类型", "items": _items(("PERSON_ID_FRONT", "身份证正面"), ("PERSON_ID_BACK", "身份证反面"), ("BUSINESS_LICENSE", "营业执照"), ("PERSON_VESSEL_PHOTO", "人船合影"), ("VESSEL_PHOTO", "船照"), ("OTHER", "其他证明"))},
    {"dict_code": "CERTIFICATE_VERIFY_STATUS", "dict_name": "证件核验状态", "items": [_item("PENDING", "待核验", color="warning", is_default=True), _item("VERIFIED", "已核验", color="success"), _item("CONFLICT", "存在冲突", color="danger"), _item("REJECTED", "已驳回", color="info")]},
    {"dict_code": "VESSEL_PROFILE_STATUS", "dict_name": "船舶档案状态", "items": [_item("ACTIVE", "可用", color="success", is_default=True), _item("INACTIVE", "停用", color="info"), _item("TRANSFERRED", "已转移", color="primary"), _item("ARCHIVED", "归档", color="info"), _item("DECOMMISSIONED", "退役", color="danger")]},
    {"dict_code": "VESSEL_IDENTITY_STATUS", "dict_name": "船舶身份状态", "items": [_item("UNLINKED", "未关联", color="warning", is_default=True), _item("CANDIDATE", "有候选", color="primary"), _item("LINKED", "已关联", color="success"), _item("CONFLICT", "冲突", color="danger")]},
    {"dict_code": "VESSEL_CERTIFICATE_IMAGE_RECOGNITION_STATUS", "dict_name": "船舶证件图片识别状态", "items": [_item("NOT_STARTED", "未识别", color="info"), _item("PROCESSING", "识别中", color="primary"), _item("NEED_CONFIRM", "待人工确认", color="warning"), _item("CONFIRMED", "已确认", color="success"), _item("UNCONFIRMED", "未确认", color="info"), _item("FAILED", "识别失败", color="danger")]},
    {"dict_code": "VESSEL_POSITION_SOURCE_STATUS", "dict_name": "实时船位状态", "items": [_item("AVAILABLE", "实时船位可用", color="success"), _item("EMPTY", "暂无实时船位", color="info"), _item("UNCONFIGURED", "实时 ES 未配置", color="warning"), _item("ERROR", "实时船位异常", color="danger")]},
    {"dict_code": "VESSEL_CHANGE_EVENT_TYPE", "dict_name": "船舶变更事件类型", "items": _items(("CREATE", "新增船舶档案"), ("UPDATE_PROFILE", "更新主档"), ("UPSERT_REGISTRATION", "维护船籍信息"), ("UPSERT_CAPACITY", "维护船舶尺寸信息"), ("UPSERT_BUILD_INFO", "维护建造信息"), ("REPLACE_OWNERS", "维护所有方"), ("UPLOAD_OWNER_DOCUMENT", "上传所有方证照"), ("IMAGE_RECOGNIZE_OWNER_DOCUMENT", "识别所有方证照"), ("IMAGE_RECOGNIZE_OWNER_DOCUMENT_FAILED", "所有方证照识别失败"), ("CONFIRM_OWNER_DOCUMENT_IMAGE_RECOGNITION", "确认所有方证照识别"), ("REPLACE_OPERATORS", "维护运营方"), ("REPLACE_CONTACTS", "维护联系人"), ("REPLACE_CREW", "维护船员任职"), ("REPLACE_PERSON_CERTIFICATES", "维护人员证书"), ("CREATE_PERSON_CERTIFICATE", "新增人员证件"), ("UPDATE_PERSON_CERTIFICATE", "更新人员证件"), ("DELETE_PERSON_CERTIFICATE", "删除人员证件"), ("UPLOAD_PERSON_CERTIFICATE_FILE", "上传人员证件附件"), ("IMAGE_RECOGNIZE_PERSON_CERTIFICATE", "识别人员证件图片"), ("IMAGE_RECOGNIZE_PERSON_CERTIFICATE_FAILED", "人员证件图片识别失败"), ("CONFIRM_PERSON_CERTIFICATE_IMAGE_RECOGNITION", "确认人员证件图片识别"), ("CREATE_CERTIFICATE", "新增证件"), ("UPDATE_CERTIFICATE", "更新证件"), ("UPLOAD_CERTIFICATE_FILE", "上传证件附件"), ("IMAGE_RECOGNIZE_CERTIFICATE", "识别证件图片"), ("IMAGE_RECOGNIZE_CERTIFICATE_FAILED", "证件图片识别失败"), ("CONFIRM_CERTIFICATE_IMAGE_RECOGNITION", "确认证件图片识别"), ("OWNER_TRANSFER_OUT", "所有方转移出"), ("OWNER_TRANSFER_IN", "所有方转移入"), ("SEED_CREATE", "样例生成"))},
    {"dict_code": "BOUNDARY_SOURCE_TYPE", "dict_name": "边界来源类型", "items": _items(("OFFICIAL_GIS_SERVICE", "官方地理服务"), ("STANDARD_MAP_EXTRACTION", "标准地图提取"), ("PLATFORM_DEFINED", "平台定义"), ("THIRD_PARTY_AUTHORIZED", "授权三方数据"))},
    {"dict_code": "REGION_TYPE", "dict_name": "区域类型", "items": _items(("SHIPPING_ANALYSIS_REGION", "航运分析区"), ("OPERATION_REGION", "运营管理区"), ("MARKET_REGION", "市场片区"))},
    {"dict_code": "REGION_RELATION_TYPE", "dict_name": "区域关系类型", "items": _items(("INCLUDED", "包含"), ("PRIMARY", "主归属"), ("ASSIST", "辅助归属"))},
    {"dict_code": "TRANSPORT_MODE_ELEMENT", "dict_name": "运输方式要素", "items": _items(("WATER", "水运"), ("ROAD", "公路"), ("RAIL", "铁路"), ("MANUAL", "人工维护"), ("UNKNOWN", "未知"))},
    {"dict_code": "TRANSPORT_ORG_TYPE", "dict_name": "运输组织类型", "items": _items(("SINGLE_MODE", "单一运输"), ("MULTIMODAL", "多式联运"))},
    {"dict_code": "MULTIMODAL_COMBINATION", "dict_name": "联运组合", "items": _items(("WATER_ROAD", "水公联运"), ("WATER_RAIL", "水铁联运"), ("ROAD_RAIL", "公铁联运"), ("WATER_ROAD_RAIL", "水公铁联运"))},
    {"dict_code": "ROUTE_PLAN_TYPE", "dict_name": "运输方案类型", "items": _items(("STANDARD", "标准方案"), ("SEASONAL", "季节方案"), ("EMERGENCY", "应急方案"), ("MANUAL", "人工方案"))},
    {"dict_code": "ROUTE_LINE_ROLE", "dict_name": "路线角色", "items": _items(("MAIN", "主线"), ("ALTERNATE", "备选"), ("DETOUR", "绕行"), ("EMERGENCY", "应急"))},
    {"dict_code": "ROUTE_LINE_NODE_TYPE", "dict_name": "路线节点类型", "items": _items(("TRANSPORT_NODE", "运输节点"), ("CONSTRAINT_POINT", "通航约束点"), ("MANUAL_POINT", "手工点位"))},
    {"dict_code": "ROUTE_LINE_TRACK_STATUS", "dict_name": "路线轨迹状态", "items": _items(("NOT_GENERATED", "未生成"), ("READY", "已就绪"), ("PARTIAL", "部分生成"), ("FAILED", "生成失败"))},
    {"dict_code": "ROUTE_GEOMETRY_SOURCE", "dict_name": "路线轨迹来源", "items": _items(("AMAP", "高德"), ("HIFLEET", "HiFleet"), ("MANUAL", "人工"), ("FALLBACK", "兜底轨迹"))},
    {"dict_code": "NAVIGATION_CONSTRAINT_TYPE", "dict_name": "通航约束类型", "items": _items(("LOCK", "船闸"), ("BRIDGE", "桥梁"), ("SHALLOW", "浅滩"), ("RESTRICTED_AREA", "限制区"), ("FORBIDDEN_AREA", "禁航区"), ("DRAFT_LIMIT", "吃水限制"), ("WIDTH_LIMIT", "船宽限制"), ("HEIGHT_LIMIT", "净空限制"), ("LOW_BRIDGE", "低桥"), ("PASSAGE_RESTRICTION", "通行限制"))},
    {"dict_code": "SOURCE_TYPE", "dict_name": "来源类型", "items": _items(("MANUAL", "人工录入"), ("IMPORT", "文件导入"), ("TMS", "TMS 接入"), ("WECHAT", "微信采集"), ("SYSTEM", "系统生成"), ("LOCAL_SAMPLE", "本地样例"), ("AI_RECOGNITION", "AI 识别"))},
    {"dict_code": "SOURCE_CHANNEL", "dict_name": "来源渠道", "items": _items(("MANUAL_FORM", "手工表单"), ("IMPORT_FILE", "导入文件"), ("TMS_API", "TMS 接口"), ("WECHAT_TEXT", "微信文本"), ("SYSTEM_SYNC", "系统同步"))},
    {"dict_code": "PROVIDER_CODE", "dict_name": "提供方编码", "items": _items(("AMAP", "高德地图"), ("HIFLEET", "HiFleet"), ("DASHSCOPE_QWEN", "通义千问"))},
    {"dict_code": "FREIGHT_STATUS", "dict_name": "货源状态", "items": [_item("DRAFT", "草稿", color="info"), _item("PUBLISHED", "已发布", color="success"), _item("MATCHING", "匹配中", color="warning"), _item("EXPIRED", "已过期", color="danger"), _item("CLOSED", "已关闭", color="info")]},
    {"dict_code": "FREIGHT_BATCH_STATUS", "dict_name": "微信采集批次状态", "items": [_item("NEW", "待解析", color="info"), _item("QUEUED", "排队中", color="warning"), _item("PARSING", "解析中", color="warning"), _item("PARSED", "已解析", color="success"), _item("PARTIAL_FAILED", "部分失败", color="danger"), _item("FAILED", "解析失败", color="danger"), _item("IGNORED", "已忽略", color="info")]},
    {"dict_code": "FREIGHT_BATCH_REVIEW_FLOW", "dict_name": "采集批次处理流转", "items": [_item("REVIEWING", "本批次确认", color="warning"), _item("QUEUED_FOR_REVIEW", "已移交待确认", color="primary"), _item("COMPLETED", "已完成", color="success")]},
    {"dict_code": "FREIGHT_TMS_INBOUND_STATUS", "dict_name": "TMS 入站状态", "items": [_item("NEW", "待解析", color="info"), _item("QUEUED", "排队中", color="warning"), _item("PARSING", "解析中", color="warning"), _item("PARSED", "已解析", color="success"), _item("PARTIAL_FAILED", "部分失败", color="danger"), _item("FAILED", "解析失败", color="danger"), _item("IGNORED", "已忽略", color="info")]},
    {"dict_code": "FREIGHT_CLUE_STATUS", "dict_name": "货源线索状态", "items": [_item("NEW", "新线索", color="info"), _item("CANDIDATE_CREATED", "已生成候选", color="success"), _item("IGNORED", "已忽略", color="info"), _item("FAILED", "处理失败", color="danger")]},
    {"dict_code": "FREIGHT_CANDIDATE_STATUS", "dict_name": "候选货源状态", "items": [_item("PENDING", "待确认", color="warning"), _item("CONFIRMED", "已确认", color="success"), _item("REJECTED", "已驳回", color="danger"), _item("MERGED", "已合并", color="info")]},
    {"dict_code": "FREIGHT_AVAILABILITY_STATUS", "dict_name": "候选可发状态", "items": [_item("READY", "可确认", color="success"), _item("DEFERRED", "稍后再发", color="warning"), _item("FULL", "船已够", color="danger"), _item("UNKNOWN", "需人工判断", color="info")]},
    {"dict_code": "FREIGHT_AI_REVIEW_STATUS", "dict_name": "AI 复核状态", "items": [_item("PASS", "AI 已可确认", color="success"), _item("REVIEW_REQUIRED", "需人工判断", color="warning"), _item("MANUAL_ACCEPTED", "人工已接受", color="primary")]},
    {"dict_code": "FREIGHT_CONFIRM_ACTION", "dict_name": "候选确认动作", "items": [_item("CONFIRM", "确认入库", color="success"), _item("EDIT_CONFIRM", "编辑后确认", color="success"), _item("REJECT", "驳回", color="danger"), _item("MERGE", "合并", color="info")]},
    {"dict_code": "FREIGHT_MATCH_LEVEL", "dict_name": "货源匹配层级", "items": [_item("RAW", "原文级", color="info"), _item("NODE", "节点级", color="success"), _item("CITY", "城市级", color="warning"), _item("REGION", "区域级", color="warning"), _item("STANDARD", "标准货品级", color="success"), _item("UNMATCHED", "未匹配", color="danger")]},
    {"dict_code": "FREIGHT_HALL_STATUS", "dict_name": "货源大厅状态", "items": [_item("NOT_LISTED", "未上架", color="info", is_default=True), _item("READY", "待上架", color="warning"), _item("PUBLISHED", "已上架", color="success"), _item("UNPUBLISHED", "已下架", color="info"), _item("EXPIRED", "已过期", color="danger")]},
    {"dict_code": "FREIGHT_NORMALIZATION_TASK_STATUS", "dict_name": "清洗任务执行状态", "items": [_item("QUEUED", "排队中", color="info"), _item("RUNNING", "执行中", color="warning"), _item("SUCCESS", "执行完成", color="success"), _item("PARTIAL_SUCCESS", "部分完成", color="warning"), _item("FAILED", "执行失败", color="danger")]},
    {"dict_code": "FREIGHT_NORMALIZATION_REVIEW_STATUS", "dict_name": "清洗任务闭环状态", "items": [_item("NOT_REQUIRED", "无需确认", color="success"), _item("PENDING_REVIEW", "待确认", color="warning"), _item("COMPLETED", "已闭环", color="success")]},
    {"dict_code": "FREIGHT_NORMALIZATION_SUGGESTION_STATUS", "dict_name": "清洗建议状态", "items": [_item("PENDING", "待确认", color="warning"), _item("APPLIED", "已应用", color="success"), _item("AUTO_APPLIED", "自动完成", color="primary"), _item("REJECTED", "已拒绝", color="info")]},
    {"dict_code": "FREIGHT_TAG", "dict_name": "货源标签", "items": _items(("URGENT", "急货"), ("HIGH_VALUE", "高价值"), ("FIXED_ROUTE", "固定线路"), ("LONG_TERM", "长期货源"))},
    {"dict_code": "DATA_SCOPE_TYPE", "dict_name": "数据权限类型", "items": _items(("ALL_DATA", "全部数据"), ("REGION_DATA", "区域数据"), ("CITY_DATA", "城市数据"), ("NODE_DATA", "节点数据"), ("SELF_DATA", "本人数据"))},
    {"dict_code": "USER_STATUS", "dict_name": "用户状态", "items": [_item("ACTIVE", "启用", color="success"), _item("DISABLED", "停用", color="info"), _item("LOCKED", "锁定", color="danger")]},
    {"dict_code": "AUDIT_STATUS", "dict_name": "审核状态", "items": [_item("PENDING", "待审核", color="warning"), _item("APPROVED", "已通过", color="success"), _item("REJECTED", "已驳回", color="danger"), _item("CANCELED", "已取消", color="info")]},
    {"dict_code": "AUDIT_OBJECT_TYPE", "dict_name": "审核对象类型", "items": [_item("TRANSPORT_NODE", "运输节点", color="primary"), _item("REGION", "业务区域", color="success"), _item("COMMODITY_STANDARD", "标准货品", color="warning"), _item("VESSEL_PROFILE", "船舶档案", color="info"), _item("FREIGHT", "正式货源", color="danger")]},
    {"dict_code": "AUDIT_CHANGE_TYPE", "dict_name": "审核变更类型", "items": [_item("CREATE", "新增", color="success"), _item("UPDATE", "修改", color="warning"), _item("DELETE", "删除", color="danger"), _item("ENABLE", "启用", color="success"), _item("DISABLE", "停用", color="info")]},
    {"dict_code": "AUDIT_ACTION", "dict_name": "审核动作", "items": [_item("SUBMIT", "提交", color="info"), _item("ASSIGN", "指派", color="primary"), _item("APPROVE", "通过", color="success"), _item("REJECT", "驳回", color="danger"), _item("CANCEL", "取消", color="info")]},
    {"dict_code": "CERTIFICATE_STATUS", "dict_name": "证件状态", "items": _items(("VALID", "有效"), ("EXPIRING", "即将到期"), ("EXPIRED", "已过期"), ("INVALID", "无效"))},
    {"dict_code": "VERIFY_STATUS", "dict_name": "校验状态", "items": _items(("UNVERIFIED", "未校验"), ("VERIFIED", "已校验"), ("FAILED", "校验失败"))},
    {"dict_code": "FILE_STORAGE_PROVIDER", "dict_name": "文件存储提供方", "items": _items(("TENCENT_COS", "腾讯云 COS"), ("MINIO", "MinIO"), ("LOCAL", "本地存储"))},
    {"dict_code": "LOGIN_RESULT", "dict_name": "登录结果", "items": _items(("SUCCESS", "成功"), ("FAILED", "失败"), ("LOGOUT", "退出"))},
    {"dict_code": "PROFILE_STATUS", "dict_name": "档案状态", "items": [_item("ACTIVE", "启用", color="success"), _item("INACTIVE", "停用", color="info"), _item("ARCHIVED", "归档", color="warning")]},
    {"dict_code": "STAT_JOB_STATUS", "dict_name": "统计任务状态", "items": [_item("QUEUED", "排队中", color="info"), _item("RUNNING", "运行中", color="warning"), _item("SUCCESS", "成功", color="success"), _item("PARTIAL_SUCCESS", "部分成功", color="warning"), _item("FAILED", "失败", color="danger")]},
    {"dict_code": "VALUE_TYPE", "dict_name": "值类型", "items": _items(("STRING", "字符串"), ("NUMBER", "数值"), ("BOOLEAN", "布尔值"), ("JSON", "JSON"), ("DATE", "日期"), ("DATETIME", "日期时间"))},
    {"dict_code": "CONFIG_GROUP", "dict_name": "配置分组", "items": _items(("SYSTEM", "系统"), ("INTEGRATION", "外部集成"), ("AI", "AI 配置"), ("MAP", "地图"), ("FREIGHT", "货源"), ("SHIP", "船舶"), ("ANALYSIS", "分析"), ("FILE_STORAGE", "文件存储"))},
]

STRICT_ITEM_DICTS = {
    "CERTIFICATE_TYPE",
    "CONTACT_SCOPE",
    "CONTACT_ROLE",
    "OWNER_DOCUMENT_TYPE",
    "VESSEL_CHANGE_EVENT_TYPE",
}


async def seed_builtin_dicts() -> None:
    async with AsyncSessionLocal() as session:
        for dict_payload in BUILTIN_DICTS:
            dict_code = dict_payload["dict_code"]
            dictionary = await session.scalar(select(StdDict).where(StdDict.dict_code == dict_code))
            if dictionary is None:
                dictionary = StdDict(
                    dict_code=dict_code,
                    dict_name=dict_payload["dict_name"],
                    dict_name_en=dict_payload.get("dict_name_en"),
                    description=dict_payload.get("description"),
                    is_system=True,
                    status=1,
                    sort_order=dict_payload.get("sort_order", 0),
                )
                session.add(dictionary)
                await session.flush()
            else:
                dictionary.dict_name = dict_payload["dict_name"]
                dictionary.dict_name_en = dict_payload.get("dict_name_en")
                dictionary.description = dict_payload.get("description")
                dictionary.is_system = True
                dictionary.status = 1
                dictionary.sort_order = dict_payload.get("sort_order", 0)

            desired_item_codes = {item["item_code"] for item in dict_payload.get("items", [])}
            if dict_code in STRICT_ITEM_DICTS and desired_item_codes:
                existing_items = (
                    await session.execute(select(StdDictItem).where(StdDictItem.dict_id == dictionary.id))
                ).scalars().all()
                for existing in existing_items:
                    if existing.item_code not in desired_item_codes:
                        existing.status = 0

            for item in dict_payload.get("items", []):
                existed_item = await session.scalar(
                    select(StdDictItem).where(
                        StdDictItem.dict_id == dictionary.id,
                        StdDictItem.item_code == item["item_code"],
                    )
                )
                if existed_item is not None:
                    existed_item.item_name = item["item_name"]
                    existed_item.item_name_en = item.get("item_name_en")
                    existed_item.item_value = item.get("item_value")
                    existed_item.color = item.get("color")
                    existed_item.description = item.get("description")
                    existed_item.is_default = bool(item.get("is_default", False))
                    existed_item.is_system = True
                    existed_item.status = 1
                    existed_item.sort_order = item.get("sort_order", 0)
                    continue
                session.add(
                    StdDictItem(
                        dict_id=dictionary.id,
                        item_code=item["item_code"],
                        item_name=item["item_name"],
                        item_name_en=item.get("item_name_en"),
                        item_value=item.get("item_value"),
                        color=item.get("color"),
                        description=item.get("description"),
                        is_default=bool(item.get("is_default", False)),
                        is_system=True,
                        status=1,
                        sort_order=item.get("sort_order", 0),
                    )
                )

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_builtin_dicts())
