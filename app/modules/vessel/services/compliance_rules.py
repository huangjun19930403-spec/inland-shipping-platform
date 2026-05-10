"""Compliance risk action rules.

Frontend pages consume recommended actions from the API. Keeping the matching
table here prevents route targets and required evidence fields from being
scattered through UI code or ad hoc service branches.
"""

from __future__ import annotations

from typing import Any, TypedDict


class ComplianceRiskActionRule(TypedDict, total=False):
    rule_code: str
    match_keywords: tuple[str, ...]
    evidence_keys: tuple[str, ...]
    label: str
    target_path: str
    required_fields: list[str]


COMPLIANCE_RISK_ACTION_RULES: tuple[ComplianceRiskActionRule, ...] = (
    {
        "rule_code": "CONTROLLER",
        "match_keywords": ("CONTROLLER",),
        "label": "补充控制人证据",
        "target_path": "/vessels/{vessel_id}/relations?tab=controller&risk_signal_id={risk_id}",
        "required_fields": ["controller_party", "evidence_summary", "verified_status_code"],
    },
    {
        "rule_code": "AFFILIATION",
        "match_keywords": ("AFFILIATION",),
        "label": "补充挂靠/授权证据",
        "target_path": "/vessels/{vessel_id}/relations?tab=affiliation&risk_signal_id={risk_id}",
        "required_fields": [
            "affiliated_party_name",
            "counterparty_name",
            "effective_period",
            "verified_status_code",
        ],
    },
    {
        "rule_code": "SUBJECT_RELATION",
        "match_keywords": ("OWNER", "OPERATOR", "SUBJECT"),
        "label": "核对主体关系",
        "target_path": "/vessels/{vessel_id}/relations?tab=owners&risk_signal_id={risk_id}",
        "required_fields": [],
    },
    {
        "rule_code": "OCR",
        "match_keywords": ("OCR",),
        "evidence_keys": ("recognition_id",),
        "label": "确认 OCR 证据",
        "target_path": "/vessels/recognitions?vessel_id={vessel_id}&risk_signal_id={risk_id}",
        "required_fields": ["recognition_id", "field_name", "adopt_status_code"],
    },
    {
        "rule_code": "CERTIFICATE",
        "match_keywords": ("CERT",),
        "label": "补充或核验证照",
        "target_path": "/vessels/{vessel_id}/compliance?tab=certificates&risk_signal_id={risk_id}",
        "required_fields": ["certificate_type_code", "certificate_no", "valid_to", "verify_status_code"],
    },
    {
        "rule_code": "BLACKLIST",
        "match_keywords": ("BLACKLIST",),
        "evidence_keys": ("blacklist_signal_id",),
        "label": "复核名单信号",
        "target_path": "/vessels/blacklist-signals?risk_signal_id={risk_id}&vessel_id={vessel_id}",
        "required_fields": [],
    },
)

DEFAULT_RISK_ACTION_RULE: ComplianceRiskActionRule = {
    "rule_code": "DEFAULT",
    "label": "处理合规风险",
    "target_path": "/vessels/{vessel_id}/compliance?risk_signal_id={risk_id}",
    "required_fields": [],
}


def resolve_compliance_risk_action_rule(row: Any) -> ComplianceRiskActionRule:
    risk_type = str(getattr(row, "risk_type_code", "") or "")
    evidence = getattr(row, "evidence_json", None) or {}
    if not isinstance(evidence, dict):
        evidence = {}
    for rule in COMPLIANCE_RISK_ACTION_RULES:
        if any(keyword in risk_type for keyword in rule.get("match_keywords", ())):
            return rule
        if any(evidence.get(key) for key in rule.get("evidence_keys", ())):
            return rule
    return DEFAULT_RISK_ACTION_RULE


def compliance_risk_action_path(row: Any) -> str:
    rule = resolve_compliance_risk_action_rule(row)
    evidence = getattr(row, "evidence_json", None) or {}
    if not isinstance(evidence, dict):
        evidence = {}
    path = rule["target_path"].format(
        vessel_id=getattr(row, "vessel_profile_id", ""),
        risk_id=getattr(row, "id", ""),
    )
    if rule.get("rule_code") == "BLACKLIST" and evidence.get("blacklist_signal_id"):
        path = f"{path}&blacklist_signal_id={evidence['blacklist_signal_id']}"
    return path


def compliance_risk_action_label(row: Any) -> str:
    return resolve_compliance_risk_action_rule(row)["label"]


def compliance_risk_required_fields(row: Any) -> list[str]:
    return list(resolve_compliance_risk_action_rule(row).get("required_fields", []))
