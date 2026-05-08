from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from main import app
from app.modules.vessel.service import (
    CURRENT_CITY_SOURCE_ADMIN_BOUNDARY,
    CURRENT_CITY_SOURCE_INVALID_POSITION,
    CURRENT_CITY_SOURCE_UNKNOWN,
    UNKNOWN_CITY_NAME,
    VesselService,
    _CityBoundary,
    _boundary_paths_for_precision,
    _build_city_boundary_grid,
)


def test_vessel_certificate_update_route_uses_json_body() -> None:
    operation = app.openapi()["paths"]["/api/v1/vessels/{vessel_id}/certificates/{certificate_id}"]["put"]

    assert "requestBody" in operation
    assert all(item["name"] != "body" for item in operation.get("parameters", []))


def test_vessel_dashboard_routes_removed() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/vessels/dashboard" not in paths
    assert "/api/v1/vessels/statistics/overview" not in paths


def test_vessel_person_certificate_upload_first_routes_exist() -> None:
    paths = app.openapi()["paths"]

    upload_operation = paths["/api/v1/vessels/{vessel_id}/person-certificate-files"]["post"]
    assert "post" in paths["/api/v1/vessels/{vessel_id}/person-certificate-files"]
    request_body = upload_operation.get("requestBody", {}).get("content", {}).get("multipart/form-data", {})
    schema_ref = request_body.get("schema", {}).get("$ref", "")
    schema_name = schema_ref.rsplit("/", 1)[-1]
    schema = app.openapi()["components"]["schemas"].get(schema_name, {})
    assert "crew_assignment_id" in schema.get("required", [])
    assert "post" in paths[
        "/api/v1/vessels/{vessel_id}/person-certificates/{person_certificate_id}/image-recognitions"
    ]
    assert "post" in paths[
        "/api/v1/vessels/{vessel_id}/person-certificates/{person_certificate_id}/image-recognitions/{recognition_id}/confirm"
    ]
    assert "get" in paths[
        "/api/v1/vessels/{vessel_id}/person-certificates/{person_certificate_id}/image-recognitions"
    ]


def test_vessel_owner_document_routes_exist() -> None:
    paths = app.openapi()["paths"]

    assert "post" in paths["/api/v1/vessels/{vessel_id}/owners/{owner_id}/documents"]
    assert "delete" in paths["/api/v1/vessels/{vessel_id}/owners/{owner_id}/documents/{owner_document_id}"]
    assert "post" in paths[
        "/api/v1/vessels/{vessel_id}/owners/{owner_id}/documents/{owner_document_id}/image-recognitions/{recognition_id}/confirm"
    ]
    assert "get" in paths[
        "/api/v1/vessels/{vessel_id}/owners/{owner_id}/documents/{owner_document_id}/image-recognitions"
    ]


def test_vessel_certificate_ledger_and_void_routes_exist() -> None:
    paths = app.openapi()["paths"]

    assert "get" in paths["/api/v1/vessels/{vessel_id}/certificates/ledger"]
    assert "get" in paths["/api/v1/vessels/position-monitor/city-situation"]
    assert "get" in paths["/api/v1/vessels/position-monitor/city-vessels"]
    assert "get" in paths["/api/v1/vessels/position-monitor/vessels/{vessel_id}/situation-card"]
    assert "get" in paths[
        "/api/v1/vessels/{vessel_id}/certificates/{certificate_id}/image-recognitions"
    ]
    assert "delete" in paths["/api/v1/vessels/{vessel_id}/certificates/{certificate_id}"]
    assert "delete" in paths["/api/v1/vessels/{vessel_id}/certificates/{certificate_id}/files/{file_id}"]
    assert "delete" in paths[
        "/api/v1/vessels/{vessel_id}/person-certificates/{person_certificate_id}/files/{file_id}"
    ]


def test_vessel_certificate_risk_query_removed() -> None:
    paths = app.openapi()["paths"]
    list_parameters = paths["/api/v1/vessels"]["get"].get("parameters", [])
    monitor_parameters = paths["/api/v1/vessels/position-monitor"]["get"].get("parameters", [])

    assert all(item["name"] != "certificate_risk" for item in list_parameters)
    assert all(item["name"] != "certificate_risk" for item in monitor_parameters)


def test_vessel_recognition_long_term_validity_is_normalized() -> None:
    service = object.__new__(VesselService)

    updates = service._certificate_updates_from_recognition(
        {"certificate_no": "ABC-1", "valid_from": "2026-01-01", "valid_to": "长期"}
    )
    person_updates = service._person_certificate_updates_from_recognition(
        {"holder_name": "张三", "certificate_no": "CREW-1", "validity_text_raw": "2024-01-01 至 长期有效"}
    )

    assert updates["is_long_term_valid"] is True
    assert updates["valid_to"] is None
    assert str(updates["valid_from"]) == "2026-01-01"
    assert person_updates["is_long_term_valid"] is True
    assert person_updates["valid_to"] is None


def test_vessel_certificate_ledger_status_uses_current_task_not_history() -> None:
    service = object.__new__(VesselService)
    confirmed_history = SimpleNamespace(status_code="CONFIRMED")
    failed_current = SimpleNamespace(status_code="FAILED")

    verified_certificate = SimpleNamespace(
        voided_at=None,
        current_image_recognition=None,
        latest_image_recognition=confirmed_history,
        verify_status_code="VERIFIED",
        certificate_no="CERT-1",
        valid_to=None,
        is_long_term_valid=True,
        files=[object()],
    )
    failed_after_confirm = SimpleNamespace(
        voided_at=None,
        current_image_recognition=failed_current,
        latest_image_recognition=failed_current,
        latest_confirmed_image_recognition=confirmed_history,
        verify_status_code="VERIFIED",
        certificate_no="CERT-1",
        valid_to=None,
        is_long_term_valid=True,
        files=[object()],
    )

    assert service._certificate_ledger_status(verified_certificate) == "VERIFIED"
    assert service._certificate_ledger_status(failed_after_confirm) == "RECOGNITION_FAILED"


def test_owner_document_completeness_depends_on_party_type() -> None:
    service = object.__new__(VesselService)

    personal_owner = SimpleNamespace(party_type_code="PERSON")
    company_owner = SimpleNamespace(party_type_code="COMPANY")
    unknown_owner = SimpleNamespace(party_type_code="UNKNOWN")

    personal_partial = service._owner_document_completeness(
        personal_owner,
        [SimpleNamespace(document_type_code="PERSON_ID_FRONT")],
    )
    company_complete = service._owner_document_completeness(
        company_owner,
        [SimpleNamespace(document_type_code="BUSINESS_LICENSE")],
    )
    unknown = service._owner_document_completeness(unknown_owner, [])

    assert personal_partial.status_code == "INCOMPLETE"
    assert personal_partial.missing_document_type_codes == ["PERSON_ID_BACK"]
    assert company_complete.status_code == "COMPLETE"
    assert unknown.status_code == "UNKNOWN_OWNER_TYPE"


def test_vessel_city_resolution_uses_boundary_not_external_city_fields() -> None:
    service = object.__new__(VesselService)
    large_city = _CityBoundary(
        code="320500",
        name="大边界市",
        center_longitude=Decimal("120.00"),
        center_latitude=Decimal("31.00"),
        area_km2=Decimal("100"),
        bbox=(0.0, 0.0, 10.0, 10.0),
        bbox_area=100.0,
        polygons=[[[ (0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0) ]]],
    )
    small_city = _CityBoundary(
        code="320501",
        name="小边界市",
        center_longitude=Decimal("121.00"),
        center_latitude=Decimal("32.00"),
        area_km2=Decimal("1"),
        bbox=(1.0, 1.0, 2.0, 2.0),
        bbox_area=1.0,
        polygons=[[[ (1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0), (1.0, 1.0) ]]],
    )

    resolved = service._resolve_current_city_from_boundaries(Decimal("1.5"), Decimal("1.5"), [large_city, small_city])

    assert resolved.city_code == "320501"
    assert resolved.city_name == "小边界市"
    assert resolved.current_city_source == CURRENT_CITY_SOURCE_ADMIN_BOUNDARY
    assert resolved.matched_city_candidates is not None
    assert [item["city_code"] for item in resolved.matched_city_candidates] == ["320501", "320500"]


def test_vessel_city_resolution_unknown_and_invalid() -> None:
    service = object.__new__(VesselService)

    invalid = service._resolve_current_city_from_boundaries(Decimal("200"), Decimal("31"), [])
    unknown = service._resolve_current_city_from_boundaries(Decimal("120"), Decimal("31"), [])

    assert invalid.city_name == UNKNOWN_CITY_NAME
    assert invalid.current_city_source == CURRENT_CITY_SOURCE_INVALID_POSITION
    assert unknown.city_name == UNKNOWN_CITY_NAME
    assert unknown.current_city_source == CURRENT_CITY_SOURCE_UNKNOWN


def test_vessel_city_boundary_paths_are_simplified_for_situation_payload() -> None:
    points = [(float(index) / 100, 0.0) for index in range(100)]
    ring = points + [(1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
    paths = _boundary_paths_for_precision([[ring]], "low")

    assert paths
    assert len(paths[0]) < len(ring)
    assert paths[0][0] == paths[0][-1]


def test_vessel_city_situation_marks_boundary_coverage() -> None:
    service = object.__new__(VesselService)
    generated_at = datetime.now()

    def make_item(identifier: int, city_code: str | None, city_name: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=identifier,
            current_city_code=city_code,
            city_code=None,
            current_city_name=city_name,
            city_name=None,
            city_center_longitude=Decimal("120.00") if city_code else None,
            city_center_latitude=Decimal("31.00") if city_code else None,
            longitude=Decimal("120.10") if city_code else None,
            latitude=Decimal("31.10") if city_code else None,
            position_time=generated_at,
            contact_available=True,
            ship_age=Decimal("6"),
            deadweight_ton=Decimal("1000"),
            ship_type_code="DRY_CARGO",
            ship_type_name="干货船",
        )

    cities = service._city_situation_items(
        [
            make_item(1, "320500", "有边界市"),
            make_item(2, "320600", "缺边界市"),
            make_item(3, None, UNKNOWN_CITY_NAME),
        ],
        {},
        generated_at,
        1440,
        3,
        2,
        1,
        0,
        1,
        False,
        None,
        {"320500": [[(120.0, 31.0), (120.2, 31.0), (120.2, 31.2), (120.0, 31.2), (120.0, 31.0)]]},
        "low",
    )
    by_name = {city.city_name: city for city in cities}

    assert by_name["有边界市"].has_boundary is True
    assert by_name["有边界市"].boundary_precision == "low"
    assert by_name["有边界市"].boundary_paths
    assert by_name["缺边界市"].has_boundary is False
    assert by_name["缺边界市"].boundary_paths is None
    assert by_name[UNKNOWN_CITY_NAME].has_boundary is False
    assert by_name[UNKNOWN_CITY_NAME].boundary_precision is None


def test_vessel_city_resolution_uses_grid_candidates_when_available() -> None:
    service = object.__new__(VesselService)
    city = _CityBoundary(
        code="320500",
        name="网格市",
        center_longitude=Decimal("120.00"),
        center_latitude=Decimal("31.00"),
        area_km2=Decimal("100"),
        bbox=(120.0, 31.0, 121.0, 32.0),
        bbox_area=1.0,
        polygons=[[[ (120.0, 31.0), (121.0, 31.0), (121.0, 32.0), (120.0, 32.0), (120.0, 31.0) ]]],
    )

    resolved = service._resolve_current_city_from_boundaries(
        Decimal("120.5"),
        Decimal("31.5"),
        [city],
        _build_city_boundary_grid([city]),
    )

    assert resolved.city_code == "320500"
    assert resolved.current_city_source == CURRENT_CITY_SOURCE_ADMIN_BOUNDARY
