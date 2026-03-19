"""Audit service constants tests."""

from app.services.audit_service import _TARGET_TABLE_MAP


def test_target_map_contains_cargo_freight():
    assert _TARGET_TABLE_MAP["CARGO_FREIGHT"] == "cargo_freight"


def test_legacy_target_maps_to_cargo_freight():
    assert _TARGET_TABLE_MAP["CARGO_OPPORTUNITY"] == "cargo_freight"

