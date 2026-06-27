from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Alert, ApiData, BuildupResult, IndexValues, SummaryMetrics, TileLayer, TimeseriesPoint

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT_DIR / "data" / "output.json"
BOUNDARY_FILE = ROOT_DIR / "Chakkittapara Grama Panchayat - Boundaries.geojson"
_DATA_CACHE: tuple[int, ApiData] | None = None


def _sample_data() -> ApiData:
    return ApiData(
        generated_at=None,
        source="sample",
        indices=IndexValues(ndvi=0.768, ndwi=-0.689),
        tiles={
            "true_color_before": TileLayer(
                url=None,
                min=0,
                max=3000,
                palette=[],
            ),
            "true_color_after": TileLayer(
                url=None,
                min=0,
                max=3000,
                palette=[],
            ),
            "ndvi_change": TileLayer(
                url=None,
                min=-0.5,
                max=0.5,
                palette=["#d73027", "#fc8d59", "#fee08b", "#d9ef8b", "#1a9850"],
            ),
            "new_construction": TileLayer(
                url=None,
                min=0,
                max=1,
                palette=["#FF0000"],
            )
        },
        timeseries=[
            TimeseriesPoint(month="2024-01", ndvi=0.71, ndwi=-0.66),
            TimeseriesPoint(month="2024-02", ndvi=0.73, ndwi=-0.67),
            TimeseriesPoint(month="2024-03", ndvi=0.74, ndwi=-0.69),
            TimeseriesPoint(month="2024-04", ndvi=0.75, ndwi=-0.70),
            TimeseriesPoint(month="2024-05", ndvi=0.76, ndwi=-0.70),
            TimeseriesPoint(month="2024-06", ndvi=0.78, ndwi=-0.68),
            TimeseriesPoint(month="2024-07", ndvi=0.80, ndwi=-0.64),
            TimeseriesPoint(month="2024-08", ndvi=0.81, ndwi=-0.62),
            TimeseriesPoint(month="2024-09", ndvi=0.80, ndwi=-0.63),
            TimeseriesPoint(month="2024-10", ndvi=0.79, ndwi=-0.65),
            TimeseriesPoint(month="2024-11", ndvi=0.77, ndwi=-0.68),
            TimeseriesPoint(month="2024-12", ndvi=0.76, ndwi=-0.69),
        ],
        summary=SummaryMetrics(
            green_cover_percent=76.8,
            water_bodies_percent=3.1,
            built_up_area_ha=0.0,
            environmental_score=82,
        ),
        buildup=BuildupResult(),
        alerts=[
            Alert(
                level="medium",
                type="water",
                title="Low Surface Water Signal",
                message="NDWI is negative across the panchayat average; inspect known streams and ponds after monsoon.",
                metric=-0.689,
            )
        ],
        metadata={"data_status": "Run gee/fetch_change.py to replace sample data."},
    )


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    data = _sample_data().model_dump(mode="json")
    data.update(raw)

    if "tile_url" in raw:
        data.setdefault("tiles", {})
        data["tiles"]["ndvi_change"] = {
            "url": raw["tile_url"],
            "attribution": "Google Earth Engine / Sentinel-2 SR Harmonized",
            "min": -0.5,
            "max": 0.5,
            "palette": ["#d73027", "#fc8d59", "#fee08b", "#d9ef8b", "#1a9850"],
        }

    if "ndvi" in raw or "ndwi" in raw:
        data["indices"] = {
            "ndvi": raw.get("ndvi", data["indices"]["ndvi"]),
            "ndwi": raw.get("ndwi", data["indices"]["ndwi"]),
        }

    return data


def load_data() -> ApiData:
    if not DATA_FILE.exists():
        return _sample_data()

    global _DATA_CACHE
    mtime_ns = DATA_FILE.stat().st_mtime_ns
    if _DATA_CACHE and _DATA_CACHE[0] == mtime_ns:
        return _DATA_CACHE[1]

    with DATA_FILE.open("r", encoding="utf-8") as file:
        raw = json.load(file)

    data = ApiData.model_validate(_normalize(raw))
    _DATA_CACHE = (mtime_ns, data)
    return data


def refresh_data_cache() -> None:
    global _DATA_CACHE
    _DATA_CACHE = None


def load_boundary() -> dict[str, Any]:
    with BOUNDARY_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)
