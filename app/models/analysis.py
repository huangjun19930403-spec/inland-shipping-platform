from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text
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
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
