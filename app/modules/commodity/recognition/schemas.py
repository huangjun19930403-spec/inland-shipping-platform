"""Schemas for standard commodity recognition."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CommodityRecognitionCreateRequest(BaseModel):
    raw_name: str = Field(min_length=1, max_length=128)
    context_note: str | None = Field(default=None, max_length=1000)
    category_hint_id: int | None = None
    type_hint_id: int | None = None
    enable_ai: bool = True


class CommodityRecognitionAttributeSuggestion(BaseModel):
    attribute_definition_id: int | None = None
    attribute_code: str | None = None
    attribute_name: str | None = None
    attribute_value: str | None = None
    unit_code: str | None = None
    unit_name: str | None = None
    confidence_score: int | None = Field(default=None, ge=0, le=100)
    reason: str | None = None


class CommodityRecognitionCandidate(BaseModel):
    standard_id: int
    standard_code: str
    standard_name: str
    category_id: int | None = None
    category_name: str | None = None
    type_id: int
    type_name: str | None = None
    matched_text: str
    match_field: str
    match_level_code: str
    basis: str
    confidence_score: int = Field(ge=0, le=100)
    already_alias: bool = False
    capability_summary: str | None = None
    attributes: list[CommodityRecognitionAttributeSuggestion] = Field(default_factory=list)


class CommodityRecognitionDefaultRuleSuggestion(BaseModel):
    code: str
    name: str | None = None
    is_default: bool = False
    is_enabled: bool = True
    remark: str | None = None


class CommodityRecognitionDecisionRuleSuggestion(BaseModel):
    code: str
    name: str | None = None
    rule_type_code: str = "ALLOWED"
    rule_type_name: str | None = None
    priority: int = Field(default=50, ge=0, le=999)
    operation_side_code: str | None = None
    operation_side_name: str | None = None
    is_enabled: bool = True
    rule_desc: str | None = None


class CommodityRecognitionStandardSuggestion(BaseModel):
    name: str
    category_id: int | None = None
    category_name: str | None = None
    type_id: int | None = None
    type_name: str | None = None
    short_name: str | None = None
    english_name: str | None = None
    main_unit_code: str = "TON"
    main_unit_name: str | None = None
    specification: str | None = None
    cargo_form_code: str | None = None
    cargo_form_name: str | None = None
    density_range_desc: str | None = None
    dangerous_grade_code: str | None = None
    dangerous_grade_name: str | None = None
    is_bulk_cargo: bool = True
    is_container_suitable: bool = False
    is_hazardous: bool = False
    pollution_risk_level_code: str | None = None
    pollution_risk_level_name: str | None = None
    recognition_priority: int = Field(default=50, ge=0, le=999)
    aliases: list[str] = Field(default_factory=list)
    attributes: list[CommodityRecognitionAttributeSuggestion] = Field(default_factory=list)
    packaging_forms: list[CommodityRecognitionDefaultRuleSuggestion] = Field(default_factory=list)
    transport_modes: list[CommodityRecognitionDefaultRuleSuggestion] = Field(default_factory=list)
    ship_type_rules: list[CommodityRecognitionDecisionRuleSuggestion] = Field(default_factory=list)
    node_type_rules: list[CommodityRecognitionDecisionRuleSuggestion] = Field(default_factory=list)
    handling_mode_rules: list[CommodityRecognitionDecisionRuleSuggestion] = Field(default_factory=list)
    confidence_score: int | None = Field(default=None, ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CommodityRecognitionResponse(BaseModel):
    id: int
    raw_name: str
    normalized_name: str
    context_note: str | None = None
    category_hint_id: int | None = None
    type_hint_id: int | None = None
    status_code: str
    suggested_action_code: str
    ai_status_code: str
    ai_error_message: str | None = None
    deterministic_candidates: list[CommodityRecognitionCandidate]
    ai_suggestion: dict[str, Any] | None = None
    standard_suggestion: CommodityRecognitionStandardSuggestion | None = None
    warnings: list[str] = Field(default_factory=list)
    adopted_action_code: str | None = None
    adopted_standard_id: int | None = None
    adopted_alias_id: int | None = None
    adopted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CommodityRecognitionAliasAdoptRequest(BaseModel):
    standard_id: int
    alias_name: str | None = Field(default=None, max_length=128)
    alias_type_code: str = Field(default="AI_KEYWORD", max_length=64)
    match_weight: int = Field(default=88, ge=0, le=100)
    remark: str | None = Field(default=None, max_length=512)


class CommodityRecognitionStandardAdoptRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    category_id: int
    type_id: int
    short_name: str | None = Field(default=None, max_length=64)
    english_name: str | None = Field(default=None, max_length=256)
    main_unit_code: str = Field(default="TON", min_length=1, max_length=32)
    specification: str | None = Field(default=None, max_length=256)
    cargo_form_code: str | None = Field(default=None, max_length=64)
    density_range_desc: str | None = Field(default=None, max_length=128)
    dangerous_grade_code: str | None = Field(default=None, max_length=64)
    is_bulk_cargo: bool = True
    is_container_suitable: bool = False
    is_hazardous: bool = False
    pollution_risk_level_code: str | None = Field(default=None, max_length=64)
    recognition_priority: int = Field(default=50, ge=0, le=999)
    remark: str | None = None
    aliases: list[str] = Field(default_factory=list)
    attributes: list[CommodityRecognitionAttributeSuggestion] = Field(default_factory=list)
    packaging_forms: list[CommodityRecognitionDefaultRuleSuggestion] = Field(default_factory=list)
    transport_modes: list[CommodityRecognitionDefaultRuleSuggestion] = Field(default_factory=list)
    ship_type_rules: list[CommodityRecognitionDecisionRuleSuggestion] = Field(default_factory=list)
    node_type_rules: list[CommodityRecognitionDecisionRuleSuggestion] = Field(default_factory=list)
    handling_mode_rules: list[CommodityRecognitionDecisionRuleSuggestion] = Field(default_factory=list)


class CommodityRecognitionAdoptionResponse(BaseModel):
    action_code: str
    standard_id: int
    standard_code: str
    standard_name: str
    alias_id: int | None = None
    recognition: CommodityRecognitionResponse
