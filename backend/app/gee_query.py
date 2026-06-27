"""
backend/app/gee_query.py

On-the-fly GEE computation for arbitrary month selections.
This module executes the same Sentinel-1/Sentinel-2 fusion logic
as the offline GEE scripts but exposes it dynamically for the API.
"""
from __future__ import annotations

import calendar
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ee

from .models import Alert, ApiData, BuildupCluster, BuildupResult, IndexValues, SummaryMetrics, TileLayer

logger = logging.getLogger("gee_query")

ROOT_DIR = Path(__file__).resolve().parents[2]
BOUNDARY_FILE = ROOT_DIR / "Chakkittapara Grama Panchayat - Boundaries.geojson"
PROJECT = "n8n-workflows-473615"
CHANGE_PALETTE = ["#d73027", "#fc8d59", "#fee08b", "#d9ef8b", "#1a9850"]

# SAR thresholds
VV_CHANGE_THRESHOLD_DB = 2.0
NDVI_CHANGE_THRESHOLD = -0.10
SPECKLE_RADIUS_M = 50
MIN_PATCH_AREA_M2 = 200
MAX_CLUSTERS = 12


def init_ee() -> None:
    try:
        ee.Initialize(project=PROJECT)
    except Exception as e:
        logger.warning(f"EE initialization warning: {e}")


def get_month_range(month_str: str) -> tuple[str, str]:
    """Converts '2024-05' to ('2024-05-01', '2024-05-31')"""
    dt = datetime.strptime(month_str, "%Y-%m")
    last_day = calendar.monthrange(dt.year, dt.month)[1]
    return f"{month_str}-01", f"{month_str}-{last_day:02d}"


def load_panchayat_geometry() -> ee.Geometry:
    with BOUNDARY_FILE.open("r", encoding="utf-8") as f:
        geojson = json.load(f)
    polygon = next(
        feature["geometry"]
        for feature in geojson["features"]
        if feature["geometry"]["type"] in {"Polygon", "MultiPolygon"}
    )
    return ee.Geometry(polygon)


def mask_s2_clouds(image: ee.Image) -> ee.Image:
    qa = image.select("QA60")
    cloud_mask = qa.bitwiseAnd(1 << 10).eq(0)
    cirrus_mask = qa.bitwiseAnd(1 << 11).eq(0)
    return image.updateMask(cloud_mask.And(cirrus_mask))


def sentinel_composite(
    panchayat: ee.Geometry,
    start: str,
    end: str,
) -> ee.Image:
    # Try different cloud thresholds to get at least one image
    for threshold in [20, 40, 70, 100]:
        collection = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(panchayat)
            .filterDate(start, end)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", threshold))
        )
        if int(collection.size().getInfo()) > 0:
            return collection.map(mask_s2_clouds).median().clip(panchayat)
    raise RuntimeError(f"No Sentinel-2 imagery available between {start} and {end}")


def sar_composite(panchayat: ee.Geometry, start: str, end: str) -> ee.Image:
    collection = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterBounds(panchayat)
        .filterDate(start, end)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
        .select(["VV", "VH"])
    )
    if int(collection.size().getInfo()) == 0:
        raise RuntimeError(f"No Sentinel-1 SAR imagery available between {start} and {end}")
    return collection.mean().clip(panchayat).focal_mean(radius=SPECKLE_RADIUS_M, units="meters")


def add_indices(image: ee.Image) -> ee.Image:
    ndvi = image.normalizedDifference(["B8", "B4"]).rename("ndvi")
    ndwi = image.normalizedDifference(["B3", "B8"]).rename("ndwi")
    return image.addBands([ndvi, ndwi])


def mean_indices(image: ee.Image, panchayat: ee.Geometry) -> dict[str, float]:
    result = (
        image.select(["ndvi", "ndwi"])
        .reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=panchayat,
            scale=10,
            maxPixels=1_000_000_000,
        )
        .getInfo()
    )
    return {"ndvi": round(result["ndvi"] or 0.0, 3), "ndwi": round(result["ndwi"] or 0.0, 3)}


def tile_url(image: ee.Image, vis_params: dict[str, Any]) -> str:
    map_id = image.getMapId(vis_params)
    return map_id["tile_fetcher"].url_format


def compute_monthly_comparison(before_month: str, after_month: str) -> ApiData:
    init_ee()
    panchayat = load_panchayat_geometry()

    before_start, before_end = get_month_range(before_month)
    after_start, after_end = get_month_range(after_month)

    # 1. Optical composites
    before_raw = sentinel_composite(panchayat, before_start, before_end)
    after_raw = sentinel_composite(panchayat, after_start, after_end)

    before = add_indices(before_raw)
    after = add_indices(after_raw)

    # 2. SAR composites
    sar_before = sar_composite(panchayat, before_start, before_end)
    sar_after = sar_composite(panchayat, after_start, after_end)

    # 3. Difference calculations
    change = after.select("ndvi").subtract(before.select("ndvi")).rename("ndvi_change")

    # 4. Built-up detection (SAR + NDVI Fusion)
    vv_change = sar_after.select("VV").subtract(sar_before.select("VV"))
    sar_signal = vv_change.gt(VV_CHANGE_THRESHOLD_DB)
    ndvi_signal = change.lt(NDVI_CHANGE_THRESHOLD)

    fused = sar_signal.And(ndvi_signal)
    cleaned = (
        fused.focal_min(radius=10, units="meters")
        .focal_max(radius=10, units="meters")
        .selfMask()
        .rename("new_construction")
    )

    # 5. Tile URLs
    url_before = tile_url(before.select(["B8", "B4", "B3"]), {"min": 0, "max": 3000})
    url_after = tile_url(after.select(["B8", "B4", "B3"]), {"min": 0, "max": 3000})
    url_change = tile_url(change, {"min": -0.5, "max": 0.5, "palette": CHANGE_PALETTE})
    url_buildup = tile_url(cleaned, {"min": 0, "max": 1, "palette": ["#FF4500"]})

    # 6. Area Calculation
    area_result = (
        cleaned.multiply(ee.Image.pixelArea())
        .reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=panchayat,
            scale=10,
            maxPixels=1_000_000_000,
        )
        .getInfo()
    )
    area_ha = round((area_result.get("new_construction") or 0) / 10_000, 2)

    # 7. Cluster Centroids
    clusters: list[BuildupCluster] = []
    try:
        vectors = cleaned.reduceToVectors(
            geometry=panchayat,
            scale=10,
            geometryType="polygon",
            maxPixels=1_000_000_000,
            bestEffort=True,
        )

        def add_area(f: ee.Feature) -> ee.Feature:
            return f.set("area_m2", f.geometry().area(10))

        vectors_with_area = vectors.map(add_area)
        significant = vectors_with_area.filter(ee.Filter.gt("area_m2", MIN_PATCH_AREA_M2))
        top = significant.sort("area_m2", False).limit(MAX_CLUSTERS)

        for feat in top.getInfo().get("features", []):
            geom = feat["geometry"]
            props = feat.get("properties", {})
            if geom["type"] == "Polygon":
                ring = geom["coordinates"][0]
                lon = sum(c[0] for c in ring) / len(ring)
                lat = sum(c[1] for c in ring) / len(ring)
            elif geom["type"] == "Point":
                lon, lat = geom["coordinates"]
            else:
                continue

            clusters.append(
                BuildupCluster(
                    lat=round(lat, 6),
                    lon=round(lon, 6),
                    area_m2=round(props.get("area_m2", 0.0), 1),
                )
            )
    except Exception as exc:
        logger.warning(f"Failed to extract clusters: {exc}")

    # 8. Indices and Score
    indices_after = mean_indices(after, panchayat)
    score = min(100, max(0, round((indices_after["ndvi"] * 85) + 18)))

    # Alerts
    alerts = []
    if indices_after["ndvi"] < 0.6:
        alerts.append(
            Alert(
                level="high",
                type="vegetation",
                title="Low Vegetation Density",
                message=f"Panchayat NDVI is {indices_after['ndvi']:.3f}, indicating significant vegetation loss.",
                metric=indices_after["ndvi"],
            )
        )
    if area_ha > 1.0:
        alerts.append(
            Alert(
                level="medium",
                type="buildup",
                title="Significant Construction Detected",
                message=f"Detected {area_ha:.2f} ha of new built-up area between {before_month} and {after_month}.",
                metric=area_ha,
            )
        )

    return ApiData(
        panchayat="Chakkittapara Grama Panchayat",
        district="Kozhikode",
        state="Kerala",
        generated_at=datetime.now(UTC).isoformat(),
        source="google_earth_engine_dynamic",
        indices=IndexValues(ndvi=indices_after["ndvi"], ndwi=indices_after["ndwi"]),
        tiles={
            "true_color_before": TileLayer(
                url=url_before,
                attribution="Google Earth Engine / Sentinel-2 SR Harmonized",
            ),
            "true_color_after": TileLayer(
                url=url_after,
                attribution="Google Earth Engine / Sentinel-2 SR Harmonized",
            ),
            "ndvi_change": TileLayer(
                url=url_change,
                attribution="Google Earth Engine / Sentinel-2 SR Harmonized",
                min=-0.5,
                max=0.5,
                palette=CHANGE_PALETTE,
            ),
            "new_construction": TileLayer(
                url=url_buildup,
                attribution="Google Earth Engine / Sentinel-1 SAR + Sentinel-2 NDVI",
            ),
        },
        summary=SummaryMetrics(
            green_cover_percent=round(indices_after["ndvi"] * 100, 1),
            water_bodies_percent=round(max(indices_after["ndwi"], 0.0) * 100, 1),
            built_up_area_ha=area_ha,
            environmental_score=score,
        ),
        buildup=BuildupResult(
            method="sentinel1_sar_ndvi_fusion",
            tile_url=url_buildup,
            new_built_area_ha=area_ha,
            cluster_count=len(clusters),
            clusters=clusters,
            thresholds={
                "vv_change_db": VV_CHANGE_THRESHOLD_DB,
                "ndvi_change": NDVI_CHANGE_THRESHOLD,
            },
            periods={
                "before": {"start": before_start, "end": before_end},
                "after": {"start": after_start, "end": after_end},
            },
        ),
        alerts=alerts,
        metadata={
            "before_month": before_month,
            "after_month": after_month,
            "sensor": "Sentinel-1 SAR / Sentinel-2 SR",
        },
    )
