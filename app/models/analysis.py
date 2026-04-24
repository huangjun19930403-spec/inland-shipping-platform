from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StatCargoDaily(Base):
    __tablename__ = "stat_cargo_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_freight_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tonnage: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    total_estimated_amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class StatCargoCityDaily(Base):
    __tablename__ = "stat_cargo_city_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    city_code: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    freight_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tonnage: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    loading_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unloading_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class StatCargoFlowDaily(Base):
    __tablename__ = "stat_cargo_flow_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    origin_city_code: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    destination_city_code: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    freight_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tonnage: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class StatCargoCommodityDaily(Base):
    __tablename__ = "stat_cargo_commodity_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    commodity_standard_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("commodity_standard.id"), nullable=False, index=True
    )
    freight_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tonnage: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    avg_unit_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class StatShipCityDaily(Base):
    __tablename__ = "stat_ship_city_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    city_code: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    active_ship_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_deadweight_ton: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class StatShipFlowDaily(Base):
    __tablename__ = "stat_ship_flow_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    origin_city_code: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    destination_city_code: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    ship_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    voyage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_deadweight_ton: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CargoChannelDaily(Base):
    __tablename__ = "cargo_channel_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    incoming_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confirmed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    formalized_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class StatJobRun(Base):
    __tablename__ = "stat_job_run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    scope_desc: Mapped[str | None] = mapped_column(String(256), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status_code: Mapped[str] = mapped_column(String(64), nullable=False)
    affected_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
