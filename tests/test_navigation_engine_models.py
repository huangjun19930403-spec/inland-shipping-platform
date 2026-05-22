from __future__ import annotations

import sqlalchemy as sa

import app.models  # noqa: F401
from app.models import (
    NavigationAnnotationTask,
    NavigationChannelCenterline,
    NavigationGraphEdge,
    NavigationGraphEdgeConstraint,
    NavigationGraphNode,
    NavigationGraphVersion,
    NavigationRouteQualityIssue,
    NavigationRouteRequest,
    NavigationRouteResult,
    NavigationWaterArea,
)
from app.models.address import NavigationChannel
from app.models.base import Base


NAVIGATION_ENGINE_TABLES = {
    "navigation_water_area",
    "navigation_channel_centerline",
    "navigation_graph_version",
    "navigation_graph_node",
    "navigation_graph_edge",
    "navigation_graph_edge_constraint",
    "navigation_route_request",
    "navigation_route_result",
    "navigation_route_quality_issue",
    "navigation_annotation_task",
}


def test_navigation_engine_models_are_registered_without_moving_legacy_channels() -> None:
    assert NavigationChannel.__tablename__ == "navigation_channel"
    assert NavigationWaterArea.__tablename__ == "navigation_water_area"
    assert NavigationChannelCenterline.__tablename__ == "navigation_channel_centerline"
    assert NavigationGraphVersion.__tablename__ == "navigation_graph_version"
    assert NavigationGraphNode.__tablename__ == "navigation_graph_node"
    assert NavigationGraphEdge.__tablename__ == "navigation_graph_edge"
    assert NavigationGraphEdgeConstraint.__tablename__ == "navigation_graph_edge_constraint"
    assert NavigationRouteRequest.__tablename__ == "navigation_route_request"
    assert NavigationRouteResult.__tablename__ == "navigation_route_result"
    assert NavigationRouteQualityIssue.__tablename__ == "navigation_route_quality_issue"
    assert NavigationAnnotationTask.__tablename__ == "navigation_annotation_task"


def test_navigation_engine_tables_create_in_sqlite_memory() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        inspector = sa.inspect(conn)
        tables = set(inspector.get_table_names())

        assert NAVIGATION_ENGINE_TABLES <= tables

        water_columns = {column["name"] for column in inspector.get_columns("navigation_water_area")}
        edge_columns = {column["name"] for column in inspector.get_columns("navigation_graph_edge")}
        result_columns = {column["name"] for column in inspector.get_columns("navigation_route_result")}

        assert {
            "source_code",
            "source_layer_name",
            "source_object_id",
            "geometry_json",
            "bbox_min_lng",
            "bbox_max_lat",
        } <= water_columns
        assert {
            "graph_version_id",
            "from_node_id",
            "to_node_id",
            "centerline_id",
            "routing_enabled",
            "unknown_constraint_flag",
        } <= edge_columns
        assert {"edge_ids", "channel_ids", "quality_code", "reference_result_id"} <= result_columns

    engine.dispose()


def test_navigation_engine_foreign_keys_preserve_asset_boundaries() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        inspector = sa.inspect(conn)

        centerline_fks = {
            fk["referred_table"]
            for fk in inspector.get_foreign_keys("navigation_channel_centerline")
        }
        edge_fks = {
            fk["referred_table"]
            for fk in inspector.get_foreign_keys("navigation_graph_edge")
        }
        issue_fks = {
            fk["referred_table"]
            for fk in inspector.get_foreign_keys("navigation_route_quality_issue")
        }

    assert {"navigation_channel", "navigation_channel_segment"} <= centerline_fks
    assert {
        "navigation_graph_version",
        "navigation_graph_node",
        "navigation_channel",
        "navigation_channel_centerline",
    } <= edge_fks
    assert {
        "navigation_route_result",
        "navigation_graph_edge",
        "navigation_graph_node",
        "navigation_annotation_task",
    } <= issue_fks
    engine.dispose()
