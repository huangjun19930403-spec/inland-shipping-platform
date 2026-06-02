from __future__ import annotations

import json
import zipfile
from pathlib import Path

import shapefile
from shapely.geometry import LineString

from app.modules.navigation.production_pipeline.centerline_builder import (
    derive_boundary_centerline,
    validate_centerline_against_boundary,
)
from app.modules.navigation.production_pipeline.graph_builder import CenterlineAsset, build_graph_seed_rows
from app.modules.navigation.production_pipeline.seed_exporter import _bbox_from_source_report
from app.modules.navigation.production_pipeline.source_reader import read_revier_zip_to_sink
from app.modules.navigation.production_pipeline.water_area_normalizer import (
    classify_water_type,
    routing_candidate_flag,
)


def _polygon(min_lng: float = 120.0, min_lat: float = 31.0, max_lng: float = 120.2, max_lat: float = 31.04) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [min_lng, min_lat],
                [max_lng, min_lat],
                [max_lng, max_lat],
                [min_lng, max_lat],
                [min_lng, min_lat],
            ]
        ],
    }


def _write_polygon_layer(base_path: Path, *, layer_name: str = "一级水系") -> None:
    writer = shapefile.Writer(str(base_path), shapeType=shapefile.POLYGON)
    writer.field("OBJECTID", "N")
    writer.field("NAME", "C", size=128)
    writer.field("REMARK", "C", size=128)
    writer.field("Shape_Leng", "F", decimal=8)
    writer.field("Shape_Area", "F", decimal=8)
    writer.poly(
        [
            [
                [120.0, 31.0],
                [120.2, 31.0],
                [120.2, 31.04],
                [120.0, 31.04],
                [120.0, 31.0],
            ]
        ]
    )
    writer.record(1, "测试双线河", "常年双线河", 0.48, 0.008)
    writer.close()
    base_path.with_suffix(".cpg").write_text("UTF-8", encoding="utf-8")
    base_path.with_suffix(".prj").write_text(
        'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
        'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]',
        encoding="utf-8",
    )
    assert base_path.name == layer_name


def test_read_revier_zip_to_sink_supports_chinese_layer_and_bbox(tmp_path: Path) -> None:
    layer_base = tmp_path / "一级水系"
    _write_polygon_layer(layer_base)
    zip_path = tmp_path / "sample_revier_min.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in tmp_path.glob("一级水系.*"):
            archive.write(path, arcname=path.name)

    rows: list[dict] = []
    report = read_revier_zip_to_sink(
        source_zip=zip_path,
        layers=("一级水系",),
        source_code="TEST_REVIER",
        sink=rows.append,
    )

    assert report["totals"]["feature_count"] == 1
    assert report["layers"][0]["crs_code"] == "EPSG:4326"
    assert report["layers"][0]["bbox"] == {"min_lng": 120.0, "min_lat": 31.0, "max_lng": 120.2, "max_lat": 31.04}
    assert rows[0]["source_layer_code"] == "WATER_LEVEL_1"
    assert rows[0]["water_type_code"] == "PERENNIAL_DOUBLE_LINE_RIVER"
    assert rows[0]["raw_properties_json"]["routing_candidate_flag"] is True


def test_water_area_normalizer_keeps_non_routing_water_out_of_graph_candidates() -> None:
    assert classify_water_type("京杭运河", None, "rx") == "CANAL"
    assert classify_water_type("鄱阳湖", None, "一级水系") == "LAKE"
    assert routing_candidate_flag(
        {
            "geometry_status_code": "VALID",
            "is_low_value": False,
            "water_type_code": "PERENNIAL_DOUBLE_LINE_RIVER",
            "area_km2": 0.5,
        }
    ) is True
    assert routing_candidate_flag(
        {
            "geometry_status_code": "VALID",
            "is_low_value": False,
            "water_type_code": "LAKE",
            "area_km2": 0.5,
        }
    ) is False


def test_centerline_validation_rejects_lines_outside_boundary() -> None:
    boundary = _polygon()
    line = derive_boundary_centerline(boundary)
    assert line is not None
    assert validate_centerline_against_boundary(line, boundary)["status_code"] == "READY"

    outside_line = LineString([(120.0, 31.2), (120.2, 31.2)])
    validation = validate_centerline_against_boundary(outside_line, boundary)

    assert validation["status_code"] == "FAILED"
    assert "CENTERLINE_OUTSIDE_BOUNDARY" in validation["blocking_issue_codes"]


def test_build_graph_seed_rows_splits_centerline_with_transport_node_connectors(tmp_path: Path) -> None:
    transport_path = tmp_path / "transport_nodes.json"
    transport_path.write_text(
        json.dumps(
            [
                {"code": "TN-A", "name": "A 作业区", "longitude": 120.0, "latitude": 31.001, "status": 1},
                {"code": "TN-B", "name": "B 作业区", "longitude": 120.1, "latitude": 31.001, "status": 1},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assets = [
        CenterlineAsset(
            channel_code="NC-TEST",
            centerline_code="REVCL-NC-TEST",
            line=LineString([(120.0, 31.0), (120.1, 31.0)]),
            channel_name="测试航道",
            channel_type_code="CANAL",
        )
    ]

    nodes, edges, report = build_graph_seed_rows(
        assets=assets,
        transport_node_seed_path=transport_path,
        max_transport_snap_m=500.0,
    )

    assert report["snapped_transport_node_count"] == 2
    assert len(nodes) >= 4
    assert {edge["source_type_code"] for edge in edges} == {"REVIER_WATER_AREA_CENTERLINE", "TRANSPORT_NODE_CONNECTOR"}
    assert all(edge["length_km"] > 0 for edge in edges)


def test_bbox_from_source_report_uses_layer_bounds() -> None:
    assert _bbox_from_source_report(
        {
            "layers": [
                {"bbox": {"min_lng": 120.0, "min_lat": 31.0, "max_lng": 120.2, "max_lat": 31.1}},
                {"bbox": {"min_lng": 119.8, "min_lat": 30.9, "max_lng": 120.4, "max_lat": 31.2}},
            ]
        }
    ) == {"min_lng": 119.8, "min_lat": 30.9, "max_lng": 120.4, "max_lat": 31.2}
