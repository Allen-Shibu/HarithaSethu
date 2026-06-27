from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IndexValues(BaseModel):
    ndvi: float
    ndwi: float


class TileLayer(BaseModel):
    url: str | None = None
    attribution: str = "Google Earth Engine / Sentinel-2 SR Harmonized"
    min: float | None = None
    max: float | None = None
    palette: list[str] = Field(default_factory=list)


class TimeseriesPoint(BaseModel):
    month: str
    ndvi: float
    ndwi: float | None = None


class Alert(BaseModel):
    level: str
    type: str
    title: str
    message: str
    metric: float | None = None


class SummaryMetrics(BaseModel):
    green_cover_percent: float
    water_bodies_percent: float
    built_up_percent: float
    environmental_score: int


class ApiData(BaseModel):
    panchayat: str = "Chakkittapara Grama Panchayat"
    district: str = "Kozhikode"
    state: str = "Kerala"
    generated_at: str | None = None
    source: str = "sample"
    indices: IndexValues
    tiles: dict[str, TileLayer] = Field(default_factory=dict)
    timeseries: list[TimeseriesPoint] = Field(default_factory=list)
    summary: SummaryMetrics
    alerts: list[Alert] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
