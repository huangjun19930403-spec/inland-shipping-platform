from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AnalysisIndicatorDefinition(Base):
    __tablename__ = "analysis_indicator_definition"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    module_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    indicator_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    indicator_name: Mapped[str] = mapped_column(String(128), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    chart_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AnalysisBucketDefinition(Base):
    __tablename__ = "analysis_bucket_definition"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bucket_group_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    bucket_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    bucket_name: Mapped[str] = mapped_column(String(128), nullable=False)
    min_value: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    max_value: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AnalysisJobDefinition(Base):
    __tablename__ = "analysis_job_definition"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    job_name: Mapped[str] = mapped_column(String(128), nullable=False)
    module_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    module_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_tables_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    target_tables_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    default_parameters_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    schedule_cron: Mapped[str | None] = mapped_column(String(128), nullable=True)
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    last_run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    last_status_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_result_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AnalysisJobRun(Base):
    __tablename__ = "analysis_job_run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    job_name: Mapped[str] = mapped_column(String(128), nullable=False)
    module_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    module_name: Mapped[str] = mapped_column(String(128), nullable=False)
    stat_date_from: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    stat_date_to: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    status_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status_name: Mapped[str] = mapped_column(String(64), nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    affected_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parameters_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AnalysisSnapshot(Base):
    __tablename__ = "analysis_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    module_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    snapshot_name: Mapped[str] = mapped_column(String(128), nullable=False)
    stat_date_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    stat_date_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    generated_by_job_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("analysis_job_run.id"), nullable=True, index=True
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FactFreightDaily(Base):
    __tablename__ = "fact_freight_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    freight_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confirmed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_inbound_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tonnage: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    total_estimated_amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    avg_unit_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FactFreightFlowDaily(Base):
    __tablename__ = "fact_freight_flow_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    origin_node_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("transport_node.id"), nullable=True, index=True)
    destination_node_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("transport_node.id"), nullable=True, index=True)
    origin_region_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("region.id"), nullable=True, index=True)
    destination_region_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("region.id"), nullable=True, index=True)
    origin_city_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    destination_city_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    commodity_standard_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("commodity_standard.id"), nullable=True, index=True)
    freight_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tonnage: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    avg_unit_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    min_unit_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    max_unit_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FactFreightCommodityDaily(Base):
    __tablename__ = "fact_freight_commodity_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    commodity_standard_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("commodity_standard.id"), nullable=False, index=True)
    commodity_category_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("commodity_category.id"), nullable=True, index=True)
    commodity_type_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("commodity_type.id"), nullable=True, index=True)
    freight_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tonnage: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    avg_unit_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FactFreightCityDaily(Base):
    __tablename__ = "fact_freight_city_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    city_code: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    city_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    primary_region_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("region.id"), nullable=True, index=True)
    freight_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inbound_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outbound_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tonnage: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    avg_unit_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    heat_value: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FactFreightNodeDaily(Base):
    __tablename__ = "fact_freight_node_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    node_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("transport_node.id"), nullable=False, index=True)
    node_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    city_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    primary_region_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("region.id"), nullable=True, index=True)
    freight_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inbound_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outbound_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tonnage: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    avg_unit_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    heat_value: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FactFreightPriceDaily(Base):
    __tablename__ = "fact_freight_price_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    price_bucket_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    price_bucket_name: Mapped[str] = mapped_column(String(128), nullable=False)
    min_unit_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    max_unit_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    freight_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tonnage: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    avg_unit_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FactShipDaily(Base):
    __tablename__ = "fact_ship_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    ship_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    registry_city_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    business_region_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("region.id"), nullable=True, index=True)
    operation_status_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    age_bucket_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    age_bucket_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    deadweight_bucket_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    deadweight_bucket_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ship_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_ship_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_deadweight_ton: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_layer_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    sample_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence_level: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    not_computable_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uncertainty_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_versions_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FactShipCityDaily(Base):
    __tablename__ = "fact_ship_city_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    city_code: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    city_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    primary_region_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("region.id"), nullable=True, index=True)
    ship_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_ship_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_deadweight_ton: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    heat_value: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_layer_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    sample_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence_level: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    not_computable_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uncertainty_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_versions_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FactShipFlowDaily(Base):
    __tablename__ = "fact_ship_flow_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    origin_node_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("transport_node.id"), nullable=True, index=True)
    destination_node_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("transport_node.id"), nullable=True, index=True)
    origin_region_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("region.id"), nullable=True, index=True)
    destination_region_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("region.id"), nullable=True, index=True)
    origin_city_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    destination_city_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    ship_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    voyage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_deadweight_ton: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_layer_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    sample_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence_level: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    not_computable_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uncertainty_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_versions_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FactRegionDaily(Base):
    __tablename__ = "fact_region_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    region_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("region.id"), nullable=True, index=True)
    node_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("transport_node.id"), nullable=True, index=True)
    freight_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inbound_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outbound_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tonnage: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    ship_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_unit_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    heat_value: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_layer_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    sample_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence_level: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    not_computable_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uncertainty_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_versions_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FactVesselAssetDaily(Base):
    __tablename__ = "fact_vessel_asset_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    ship_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    quality_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    profile_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trusted_profile_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_quality_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_layer_code: Mapped[str] = mapped_column(String(64), nullable=False, default="VESSEL_PROFILE_SUMMARY", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    not_computable_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uncertainty_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_versions_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    job_run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("analysis_job_run.id"), nullable=True, index=True)


class FactVesselAisFreshnessDaily(Base):
    __tablename__ = "fact_vessel_ais_freshness_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    city_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    city_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ship_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    freshness_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    match_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    vessel_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_profile_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unmatched_mmsi_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_snapshot_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("vessel_ais_snapshot.snapshot_id"), nullable=True, index=True)
    source_layer_code: Mapped[str] = mapped_column(String(64), nullable=False, default="AIS_SNAPSHOT", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    not_computable_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uncertainty_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_versions_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    job_run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("analysis_job_run.id"), nullable=True, index=True)


class FactVesselTrajectoryDaily(Base):
    __tablename__ = "fact_vessel_trajectory_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    vessel_profile_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("vessel_profile.id"), nullable=True, index=True)
    mmsi: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    ship_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    track_coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    gap_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    anomaly_point_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stay_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    route_match_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latest_position_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_layer_code: Mapped[str] = mapped_column(String(64), nullable=False, default="SPATIAL_OBSERVATION", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    not_computable_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uncertainty_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_versions_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    job_run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("analysis_job_run.id"), nullable=True, index=True)


class FactVesselNodeDaily(Base):
    __tablename__ = "fact_vessel_node_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    node_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("transport_node.id"), nullable=True, index=True)
    node_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    city_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    radius_km: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    ship_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    deadweight_bucket_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    active_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stay_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passby_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_confidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_spatial_snapshot_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("vessel_spatial_observation_snapshot.snapshot_id"), nullable=True, index=True)
    source_layer_code: Mapped[str] = mapped_column(String(64), nullable=False, default="SPATIAL_OBSERVATION", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    not_computable_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uncertainty_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_versions_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    job_run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("analysis_job_run.id"), nullable=True, index=True)


class FactVesselRouteSegmentDaily(Base):
    __tablename__ = "fact_vessel_route_segment_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    route_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("shipping_route.id"), nullable=True, index=True)
    line_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("shipping_route_line.id"), nullable=True, index=True)
    route_segment_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("shipping_route_line_segment.id"), nullable=True, index=True)
    segment_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    direction_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    ship_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reliable_match_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    covered_ratio: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    avg_direction_consistency: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    gap_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_confidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_spatial_snapshot_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("vessel_spatial_observation_snapshot.snapshot_id"), nullable=True, index=True)
    source_layer_code: Mapped[str] = mapped_column(String(64), nullable=False, default="SPATIAL_OBSERVATION", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    not_computable_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uncertainty_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_versions_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    job_run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("analysis_job_run.id"), nullable=True, index=True)


class FactVesselQualityDaily(Base):
    __tablename__ = "fact_vessel_quality_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    issue_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    opened_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    closed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resolved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    voided_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_close_hours: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    source_layer_code: Mapped[str] = mapped_column(String(64), nullable=False, default="QUALITY_ISSUE", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    not_computable_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uncertainty_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_versions_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    job_run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("analysis_job_run.id"), nullable=True, index=True)


class FactVesselRiskDaily(Base):
    __tablename__ = "fact_vessel_risk_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    risk_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    risk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unknown_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    closed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    high_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_close_hours: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    source_layer_code: Mapped[str] = mapped_column(String(64), nullable=False, default="RISK_SIGNAL", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    not_computable_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uncertainty_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_versions_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    job_run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("analysis_job_run.id"), nullable=True, index=True)


class FactCandidateFitDaily(Base):
    __tablename__ = "fact_candidate_fit_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    context_type_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    candidate_value_level: Mapped[str] = mapped_column(String(32), nullable=False, default="LOW", index=True)
    analysis_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidate_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    not_computable_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_confidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    annotation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    annotation_distribution_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    risk_reason_distribution_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    avg_fit_score: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    avg_coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    source_layer_code: Mapped[str] = mapped_column(String(64), nullable=False, default="CANDIDATE_ANALYSIS", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    not_computable_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uncertainty_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_versions_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    job_run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("analysis_job_run.id"), nullable=True, index=True)


class FactRegionSupplyDemandDaily(Base):
    __tablename__ = "fact_region_supply_demand_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    region_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("region.id"), nullable=True, index=True)
    city_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    cargo_category_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ship_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    demand_layer_code: Mapped[str] = mapped_column(String(64), nullable=False, default="STANDARD_FREIGHT_SAMPLE", index=True)
    supply_layer_code: Mapped[str] = mapped_column(String(64), nullable=False, default="AIS_SUPPLY_SAMPLE", index=True)
    demand_sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    demand_tonnage: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    ais_supply_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trusted_profile_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_risk_supply_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unmatched_mmsi_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trusted_supply: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tension_index: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    source_layer_code: Mapped[str] = mapped_column(String(64), nullable=False, default="REGION_SUPPLY_DEMAND", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    not_computable_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uncertainty_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_versions_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    job_run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("analysis_job_run.id"), nullable=True, index=True)
