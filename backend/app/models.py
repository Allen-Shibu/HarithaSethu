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


class BuildupCluster(BaseModel):
    lat: float
    lon: float
    area_m2: float


class BuildupResult(BaseModel):
    method: str = "sentinel1_sar_ndvi_fusion"
    tile_url: str | None = None
    vv_change_tile_url: str | None = None
    new_built_area_ha: float = 0.0
    cluster_count: int = 0
    clusters: list[BuildupCluster] = Field(default_factory=list)
    thresholds: dict[str, Any] = Field(default_factory=dict)
    periods: dict[str, Any] = Field(default_factory=dict)


class SummaryMetrics(BaseModel):
    green_cover_percent: float
    water_bodies_percent: float
    built_up_area_ha: float = 0.0   # renamed from built_up_percent (was incorrectly in ha)
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
    buildup: BuildupResult = Field(default_factory=BuildupResult)
    alerts: list[Alert] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MetricChange(BaseModel):
    before: float
    after: float
    change: float
    avg_before: float | None = None
    avg_after: float | None = None


class CompareStats(BaseModel):
    green_cover: MetricChange
    water: MetricChange
    built_up: MetricChange
    environmental_score: int
    vegetation_loss_area_ha: float
    water_change_area_ha: float
    built_up_expansion_area_ha: float
    total_built_up_area_ha: float
    panchayat_area_ha: float
    donut_ndvi_change: dict[str, float]


class CompareResponse(BaseModel):
    panchayat: str = "Chakkittapara Grama Panchayat"
    monthA: str
    monthB: str
    generated_at: str
    tiles: dict[str, str]
    stats: CompareStats
    polygons: dict[str, Any]
    report: dict[str, str]
    alerts: list[Alert]
