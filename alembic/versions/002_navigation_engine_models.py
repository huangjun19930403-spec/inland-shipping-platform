"""navigation_engine_models

Revision ID: 002_navigation_engine_models
Revises: 001_initial_schema
Create Date: 2026-05-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "002_navigation_engine_models"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "navigation_water_area",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_code", sa.String(length=64), nullable=False),
        sa.Column("source_layer_name", sa.String(length=128), nullable=False),
        sa.Column("source_object_id", sa.String(length=64), nullable=False),
        sa.Column("water_name", sa.String(length=128), nullable=True),
        sa.Column("normalized_water_name", sa.String(length=128), nullable=True),
        sa.Column("alias_names", sa.JSON(), nullable=True),
        sa.Column("water_level", sa.Integer(), nullable=True),
        sa.Column("water_type_code", sa.String(length=64), nullable=False),
        sa.Column("remark", sa.String(length=512), nullable=True),
        sa.Column("geometry_json", sa.JSON(), nullable=False),
        sa.Column("geometry_status_code", sa.String(length=32), nullable=False),
        sa.Column("simplified_geometry_low_json", sa.JSON(), nullable=True),
        sa.Column("simplified_geometry_mid_json", sa.JSON(), nullable=True),
        sa.Column("simplified_geometry_high_json", sa.JSON(), nullable=True),
        sa.Column("bbox_min_lng", sa.Numeric(precision=11, scale=8), nullable=True),
        sa.Column("bbox_min_lat", sa.Numeric(precision=10, scale=8), nullable=True),
        sa.Column("bbox_max_lng", sa.Numeric(precision=11, scale=8), nullable=True),
        sa.Column("bbox_max_lat", sa.Numeric(precision=10, scale=8), nullable=True),
        sa.Column("center_lng", sa.Numeric(precision=11, scale=8), nullable=True),
        sa.Column("center_lat", sa.Numeric(precision=10, scale=8), nullable=True),
        sa.Column("shape_length_degree", sa.Numeric(precision=24, scale=15), nullable=True),
        sa.Column("shape_area_degree", sa.Numeric(precision=24, scale=15), nullable=True),
        sa.Column("area_km2", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("is_low_value", sa.Boolean(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_code",
            "source_layer_name",
            "source_object_id",
            name="uk_navigation_water_area_source_object",
        ),
    )
    op.create_index("ix_navigation_water_area_bbox", "navigation_water_area", ["bbox_min_lng", "bbox_min_lat", "bbox_max_lng", "bbox_max_lat"])
    op.create_index("ix_navigation_water_area_enabled", "navigation_water_area", ["is_enabled"])
    op.create_index("ix_navigation_water_area_name", "navigation_water_area", ["normalized_water_name"])
    op.create_index("ix_navigation_water_area_source", "navigation_water_area", ["source_code", "source_layer_name"])
    op.create_index("ix_navigation_water_area_type", "navigation_water_area", ["water_type_code"])

    op.create_table(
        "navigation_channel_centerline",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("segment_id", sa.BigInteger(), nullable=True),
        sa.Column("centerline_code", sa.String(length=96), nullable=False),
        sa.Column("centerline_name", sa.String(length=128), nullable=True),
        sa.Column("geometry_json", sa.JSON(), nullable=False),
        sa.Column("source_type_code", sa.String(length=64), nullable=False),
        sa.Column("direction_code", sa.String(length=32), nullable=False),
        sa.Column("is_main_line", sa.Boolean(), nullable=False),
        sa.Column("confidence_score", sa.Integer(), nullable=False),
        sa.Column("quality_code", sa.String(length=64), nullable=False),
        sa.Column("review_status_code", sa.String(length=64), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("parent_centerline_id", sa.BigInteger(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("source_trace_json", sa.JSON(), nullable=True),
        sa.Column("approved_by", sa.BigInteger(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("bbox_min_lng", sa.Numeric(precision=11, scale=8), nullable=True),
        sa.Column("bbox_min_lat", sa.Numeric(precision=10, scale=8), nullable=True),
        sa.Column("bbox_max_lng", sa.Numeric(precision=11, scale=8), nullable=True),
        sa.Column("bbox_max_lat", sa.Numeric(precision=10, scale=8), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["channel_id"], ["navigation_channel.id"]),
        sa.ForeignKeyConstraint(["parent_centerline_id"], ["navigation_channel_centerline.id"]),
        sa.ForeignKeyConstraint(["segment_id"], ["navigation_channel_segment.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("centerline_code", name="uk_navigation_channel_centerline_code"),
    )
    op.create_index("ix_navigation_channel_centerline_bbox", "navigation_channel_centerline", ["bbox_min_lng", "bbox_min_lat", "bbox_max_lng", "bbox_max_lat"])
    op.create_index("ix_navigation_channel_centerline_channel", "navigation_channel_centerline", ["channel_id"])
    op.create_index("ix_navigation_channel_centerline_current", "navigation_channel_centerline", ["is_current"])
    op.create_index("ix_navigation_channel_centerline_quality", "navigation_channel_centerline", ["quality_code"])
    op.create_index("ix_navigation_channel_centerline_review", "navigation_channel_centerline", ["review_status_code"])
    op.create_index("ix_navigation_channel_centerline_source", "navigation_channel_centerline", ["source_type_code"])

    op.create_table(
        "navigation_graph_version",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("version_code", sa.String(length=96), nullable=False),
        sa.Column("version_name", sa.String(length=128), nullable=False),
        sa.Column("scope_code", sa.String(length=64), nullable=False),
        sa.Column("source_summary_json", sa.JSON(), nullable=True),
        sa.Column("node_count", sa.Integer(), nullable=False),
        sa.Column("edge_count", sa.Integer(), nullable=False),
        sa.Column("channel_count", sa.Integer(), nullable=False),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("built_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("build_scope_bbox_json", sa.JSON(), nullable=True),
        sa.Column("build_config_json", sa.JSON(), nullable=True),
        sa.Column("validation_report_json", sa.JSON(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_code", name="uk_navigation_graph_version_code"),
    )
    op.create_index("ix_navigation_graph_version_active", "navigation_graph_version", ["is_active"])
    op.create_index("ix_navigation_graph_version_scope", "navigation_graph_version", ["scope_code"])
    op.create_index("ix_navigation_graph_version_status", "navigation_graph_version", ["status_code"])

    op.create_table(
        "navigation_graph_node",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("graph_version_id", sa.BigInteger(), nullable=False),
        sa.Column("node_code", sa.String(length=128), nullable=False),
        sa.Column("node_name", sa.String(length=128), nullable=True),
        sa.Column("node_type_code", sa.String(length=64), nullable=False),
        sa.Column("longitude", sa.Numeric(precision=11, scale=8), nullable=False),
        sa.Column("latitude", sa.Numeric(precision=10, scale=8), nullable=False),
        sa.Column("geometry_json", sa.JSON(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column("related_transport_node_id", sa.BigInteger(), nullable=True),
        sa.Column("related_constraint_point_id", sa.BigInteger(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("quality_code", sa.String(length=64), nullable=False),
        sa.Column("source_type_code", sa.String(length=64), nullable=False),
        sa.Column("snap_distance_m", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("snap_confidence", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["channel_id"], ["navigation_channel.id"]),
        sa.ForeignKeyConstraint(["graph_version_id"], ["navigation_graph_version.id"]),
        sa.ForeignKeyConstraint(["related_constraint_point_id"], ["navigation_constraint_point.id"]),
        sa.ForeignKeyConstraint(["related_transport_node_id"], ["transport_node.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("graph_version_id", "node_code", name="uk_navigation_graph_node_code"),
    )
    op.create_index("ix_navigation_graph_node_channel", "navigation_graph_node", ["channel_id"])
    op.create_index("ix_navigation_graph_node_enabled", "navigation_graph_node", ["is_enabled"])
    op.create_index("ix_navigation_graph_node_graph_version", "navigation_graph_node", ["graph_version_id"])
    op.create_index("ix_navigation_graph_node_location", "navigation_graph_node", ["longitude", "latitude"])
    op.create_index("ix_navigation_graph_node_quality", "navigation_graph_node", ["quality_code"])
    op.create_index("ix_navigation_graph_node_type", "navigation_graph_node", ["node_type_code"])

    op.create_table(
        "navigation_graph_edge",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("graph_version_id", sa.BigInteger(), nullable=False),
        sa.Column("edge_code", sa.String(length=128), nullable=False),
        sa.Column("from_node_id", sa.BigInteger(), nullable=False),
        sa.Column("to_node_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column("centerline_id", sa.BigInteger(), nullable=True),
        sa.Column("geometry_json", sa.JSON(), nullable=False),
        sa.Column("length_km", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("direction_code", sa.String(length=32), nullable=False),
        sa.Column("technical_grade_code", sa.String(length=32), nullable=True),
        sa.Column("min_depth_m", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("min_width_m", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("max_allowed_draft_m", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("max_allowed_tonnage", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("max_air_draft_m", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("max_beam_m", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("max_length_m", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("lock_required", sa.Boolean(), nullable=False),
        sa.Column("bridge_count", sa.Integer(), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=True),
        sa.Column("base_cost", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("routing_enabled", sa.Boolean(), nullable=False),
        sa.Column("quality_code", sa.String(length=64), nullable=False),
        sa.Column("source_type_code", sa.String(length=64), nullable=False),
        sa.Column("confidence_score", sa.Integer(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("unknown_constraint_flag", sa.Boolean(), nullable=False),
        sa.Column("validation_summary_json", sa.JSON(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["centerline_id"], ["navigation_channel_centerline.id"]),
        sa.ForeignKeyConstraint(["channel_id"], ["navigation_channel.id"]),
        sa.ForeignKeyConstraint(["from_node_id"], ["navigation_graph_node.id"]),
        sa.ForeignKeyConstraint(["graph_version_id"], ["navigation_graph_version.id"]),
        sa.ForeignKeyConstraint(["to_node_id"], ["navigation_graph_node.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("graph_version_id", "edge_code", name="uk_navigation_graph_edge_code"),
    )
    op.create_index("ix_navigation_graph_edge_centerline", "navigation_graph_edge", ["centerline_id"])
    op.create_index("ix_navigation_graph_edge_channel", "navigation_graph_edge", ["channel_id"])
    op.create_index("ix_navigation_graph_edge_direction", "navigation_graph_edge", ["direction_code"])
    op.create_index("ix_navigation_graph_edge_from_node", "navigation_graph_edge", ["from_node_id"])
    op.create_index("ix_navigation_graph_edge_graph_version", "navigation_graph_edge", ["graph_version_id"])
    op.create_index("ix_navigation_graph_edge_quality", "navigation_graph_edge", ["quality_code"])
    op.create_index("ix_navigation_graph_edge_routing", "navigation_graph_edge", ["routing_enabled"])
    op.create_index("ix_navigation_graph_edge_source", "navigation_graph_edge", ["source_type_code"])
    op.create_index("ix_navigation_graph_edge_to_node", "navigation_graph_edge", ["to_node_id"])

    op.create_table(
        "navigation_graph_edge_constraint",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("edge_id", sa.BigInteger(), nullable=False),
        sa.Column("constraint_type_code", sa.String(length=64), nullable=False),
        sa.Column("constraint_name", sa.String(length=128), nullable=True),
        sa.Column("effective_from", sa.DateTime(), nullable=True),
        sa.Column("effective_to", sa.DateTime(), nullable=True),
        sa.Column("rule_json", sa.JSON(), nullable=True),
        sa.Column("severity_level", sa.String(length=32), nullable=False),
        sa.Column("warning_message", sa.String(length=512), nullable=True),
        sa.Column("is_blocking", sa.Boolean(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("data_completeness_code", sa.String(length=64), nullable=False),
        sa.Column("source_trace_json", sa.JSON(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["edge_id"], ["navigation_graph_edge.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_navigation_graph_edge_constraint_edge", "navigation_graph_edge_constraint", ["edge_id"])
    op.create_index("ix_navigation_graph_edge_constraint_enabled", "navigation_graph_edge_constraint", ["is_enabled"])
    op.create_index("ix_navigation_graph_edge_constraint_type", "navigation_graph_edge_constraint", ["constraint_type_code"])

    op.create_table(
        "navigation_route_request",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("request_no", sa.String(length=96), nullable=False),
        sa.Column("origin_lng", sa.Numeric(precision=11, scale=8), nullable=False),
        sa.Column("origin_lat", sa.Numeric(precision=10, scale=8), nullable=False),
        sa.Column("origin_name", sa.String(length=128), nullable=True),
        sa.Column("origin_ref_type_code", sa.String(length=64), nullable=True),
        sa.Column("origin_ref_id", sa.BigInteger(), nullable=True),
        sa.Column("destination_lng", sa.Numeric(precision=11, scale=8), nullable=False),
        sa.Column("destination_lat", sa.Numeric(precision=10, scale=8), nullable=False),
        sa.Column("destination_name", sa.String(length=128), nullable=True),
        sa.Column("destination_ref_type_code", sa.String(length=64), nullable=True),
        sa.Column("destination_ref_id", sa.BigInteger(), nullable=True),
        sa.Column("vessel_profile_json", sa.JSON(), nullable=True),
        sa.Column("routing_preference_code", sa.String(length=64), nullable=False),
        sa.Column("graph_version_id", sa.BigInteger(), nullable=True),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["graph_version_id"], ["navigation_graph_version.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_no", name="uk_navigation_route_request_no"),
    )
    op.create_index("ix_navigation_route_request_graph_version", "navigation_route_request", ["graph_version_id"])
    op.create_index("ix_navigation_route_request_request_no", "navigation_route_request", ["request_no"])
    op.create_index("ix_navigation_route_request_status", "navigation_route_request", ["status_code"])

    op.create_table(
        "navigation_route_result",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=False),
        sa.Column("result_no", sa.Integer(), nullable=False),
        sa.Column("result_type_code", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("geometry_json", sa.JSON(), nullable=True),
        sa.Column("distance_km", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("estimated_duration_hour", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("edge_ids", sa.JSON(), nullable=True),
        sa.Column("channel_ids", sa.JSON(), nullable=True),
        sa.Column("passed_node_ids", sa.JSON(), nullable=True),
        sa.Column("passed_lock_count", sa.Integer(), nullable=False),
        sa.Column("passed_bridge_count", sa.Integer(), nullable=False),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("quality_code", sa.String(length=64), nullable=False),
        sa.Column("quality_summary_json", sa.JSON(), nullable=True),
        sa.Column("provider_code", sa.String(length=64), nullable=True),
        sa.Column("engine_code", sa.String(length=64), nullable=True),
        sa.Column("reference_result_id", sa.BigInteger(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["reference_result_id"], ["navigation_route_result.id"]),
        sa.ForeignKeyConstraint(["request_id"], ["navigation_route_request.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", "result_no", name="uk_navigation_route_result_no"),
    )
    op.create_index("ix_navigation_route_result_quality", "navigation_route_result", ["quality_code"])
    op.create_index("ix_navigation_route_result_request", "navigation_route_result", ["request_id"])
    op.create_index("ix_navigation_route_result_type", "navigation_route_result", ["result_type_code"])

    op.create_table(
        "navigation_annotation_task",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_no", sa.String(length=96), nullable=False),
        sa.Column("task_type_code", sa.String(length=64), nullable=False),
        sa.Column("target_type_code", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column("graph_version_id", sa.BigInteger(), nullable=True),
        sa.Column("geometry_json", sa.JSON(), nullable=True),
        sa.Column("priority_code", sa.String(length=32), nullable=False),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("issue_summary", sa.Text(), nullable=False),
        sa.Column("suggestion_json", sa.JSON(), nullable=True),
        sa.Column("assigned_to", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("resolution_type_code", sa.String(length=64), nullable=True),
        sa.Column("resolution_target_type_code", sa.String(length=64), nullable=True),
        sa.Column("resolution_target_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["channel_id"], ["navigation_channel.id"]),
        sa.ForeignKeyConstraint(["graph_version_id"], ["navigation_graph_version.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_no", name="uk_navigation_annotation_task_no"),
    )
    op.create_index("ix_navigation_annotation_task_channel", "navigation_annotation_task", ["channel_id"])
    op.create_index("ix_navigation_annotation_task_graph_version", "navigation_annotation_task", ["graph_version_id"])
    op.create_index("ix_navigation_annotation_task_status", "navigation_annotation_task", ["status_code"])
    op.create_index("ix_navigation_annotation_task_type", "navigation_annotation_task", ["task_type_code"])

    op.create_table(
        "navigation_route_quality_issue",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("route_result_id", sa.BigInteger(), nullable=False),
        sa.Column("issue_type_code", sa.String(length=128), nullable=False),
        sa.Column("severity_code", sa.String(length=32), nullable=False),
        sa.Column("geometry_json", sa.JSON(), nullable=True),
        sa.Column("message", sa.String(length=512), nullable=False),
        sa.Column("suggestion", sa.String(length=512), nullable=True),
        sa.Column("related_edge_id", sa.BigInteger(), nullable=True),
        sa.Column("related_node_id", sa.BigInteger(), nullable=True),
        sa.Column("related_annotation_task_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["related_annotation_task_id"], ["navigation_annotation_task.id"]),
        sa.ForeignKeyConstraint(["related_edge_id"], ["navigation_graph_edge.id"]),
        sa.ForeignKeyConstraint(["related_node_id"], ["navigation_graph_node.id"]),
        sa.ForeignKeyConstraint(["route_result_id"], ["navigation_route_result.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_navigation_route_quality_issue_annotation", "navigation_route_quality_issue", ["related_annotation_task_id"])
    op.create_index("ix_navigation_route_quality_issue_edge", "navigation_route_quality_issue", ["related_edge_id"])
    op.create_index("ix_navigation_route_quality_issue_result", "navigation_route_quality_issue", ["route_result_id"])
    op.create_index("ix_navigation_route_quality_issue_severity", "navigation_route_quality_issue", ["severity_code"])
    op.create_index("ix_navigation_route_quality_issue_type", "navigation_route_quality_issue", ["issue_type_code"])


def downgrade() -> None:
    op.drop_table("navigation_route_quality_issue")
    op.drop_table("navigation_annotation_task")
    op.drop_table("navigation_route_result")
    op.drop_table("navigation_route_request")
    op.drop_table("navigation_graph_edge_constraint")
    op.drop_table("navigation_graph_edge")
    op.drop_table("navigation_graph_node")
    op.drop_table("navigation_graph_version")
    op.drop_table("navigation_channel_centerline")
    op.drop_table("navigation_water_area")
