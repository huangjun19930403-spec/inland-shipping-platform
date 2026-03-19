"""AI router helper tests."""

from app.ai.utils import normalize_corrected_fields


def test_normalize_corrected_fields_none():
    assert normalize_corrected_fields(None) == []


def test_normalize_corrected_fields_list():
    assert normalize_corrected_fields(["origin_node", "commodity"]) == [
        "origin_node",
        "commodity",
    ]


def test_normalize_corrected_fields_json_string():
    assert normalize_corrected_fields('["origin_node","commodity"]') == [
        "origin_node",
        "commodity",
    ]


def test_normalize_corrected_fields_invalid_string():
    assert normalize_corrected_fields("not-json") == []
