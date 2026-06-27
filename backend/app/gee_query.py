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

from .models import Alert, ApiData, BuildupCluster, BuildupResult, IndexValues, SummaryMetrics, TileLayer, CompareResponse, CompareStats, MetricChange

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
            masked = collection.map(mask_s2_clouds).median().clip(panchayat)
            raw = collection.median().clip(panchayat)
            return masked.unmask(raw)
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
    ndbi = image.normalizedDifference(["B11", "B8"]).rename("ndbi")
    return image.addBands([ndvi, ndwi, ndbi])


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
    url_before = tile_url(before.select(["B4", "B3", "B2"]), {"min": 0, "max": 2500})
    url_after = tile_url(after.select(["B4", "B3", "B2"]), {"min": 0, "max": 2500})
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


def compare_periods(month_a: str, month_b: str) -> CompareResponse:
    init_ee()
    panchayat = load_panchayat_geometry()
    
    # Get total area in ha
    total_area_ha = panchayat.area(10).getInfo() / 10000

    a_start, a_end = get_month_range(month_a)
    b_start, b_end = get_month_range(month_b)

    # 1. Monthly S2 composites
    before_raw = sentinel_composite(panchayat, a_start, a_end)
    after_raw = sentinel_composite(panchayat, b_start, b_end)

    before = add_indices(before_raw)
    after = add_indices(after_raw)

    # 2. Difference layers
    change = after.select("ndvi").subtract(before.select("ndvi")).rename("ndvi_change")
    water_change = after.select("ndwi").subtract(before.select("ndwi")).rename("ndwi_change")
    ndbi_change = after.select("ndbi").subtract(before.select("ndbi")).rename("ndbi_change")

    # 3. Built-up expansion detection
    # Transition: ndbi after > -0.1 and ndbi change > 0.15 and ndvi change < -0.10
    built_up_expansion = (
        after.select("ndbi").gt(-0.1)
        .And(ndbi_change.gt(0.15))
        .And(change.lt(-0.10))
    )
    cleaned_expansion = (
        built_up_expansion.focal_min(radius=10, units="meters")
        .focal_max(radius=10, units="meters")
        .selfMask()
        .rename("built_up_expansion")
    )

    # 4. Mean statistics (single call)
    mean_image = ee.Image.cat([
        before.select("ndvi").rename("ndvi_before"),
        before.select("ndwi").rename("ndwi_before"),
        before.select("ndbi").rename("ndbi_before"),
        after.select("ndvi").rename("ndvi_after"),
        after.select("ndwi").rename("ndwi_after"),
        after.select("ndbi").rename("ndbi_after")
    ])
    mean_stats = mean_image.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=panchayat,
        scale=30,
        maxPixels=1_000_000_000,
    ).getInfo()

    # 5. Area statistics (single call)
    area_image = ee.Image.cat([
        before.select("ndvi").gt(0.4).multiply(ee.Image.pixelArea()).rename("green_cover_before"),
        after.select("ndvi").gt(0.4).multiply(ee.Image.pixelArea()).rename("green_cover_after"),
        before.select("ndwi").gt(0.0).multiply(ee.Image.pixelArea()).rename("water_bodies_before"),
        after.select("ndwi").gt(0.0).multiply(ee.Image.pixelArea()).rename("water_bodies_after"),
        change.lt(-0.1).multiply(ee.Image.pixelArea()).rename("veg_loss"),
        water_change.lt(-0.1).multiply(ee.Image.pixelArea()).rename("water_loss"),
        water_change.gt(0.1).multiply(ee.Image.pixelArea()).rename("water_gain"),
        cleaned_expansion.multiply(ee.Image.pixelArea()).rename("built_up_expansion"),
        before.select("ndbi").gt(-0.1).multiply(ee.Image.pixelArea()).rename("built_up_before"),
        after.select("ndbi").gt(-0.1).multiply(ee.Image.pixelArea()).rename("built_up_after")
    ])
    area_stats = area_image.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=panchayat,
        scale=30,
        maxPixels=1_000_000_000,
    ).getInfo()

    # Donut NDVI change statistics
    high_increase_mask = change.gt(0.25)
    mod_increase_mask = change.gt(0.1).And(change.lte(0.25))
    no_change_mask = change.gte(-0.1).And(change.lt(0.1))
    mod_decrease_mask = change.gte(-0.25).And(change.lt(-0.1))
    high_decrease_mask = change.lt(-0.25)

    donut_image = ee.Image.cat([
        high_increase_mask.rename("high_inc"),
        mod_increase_mask.rename("mod_inc"),
        no_change_mask.rename("no_chg"),
        mod_decrease_mask.rename("mod_dec"),
        high_decrease_mask.rename("high_dec")
    ]).multiply(ee.Image.pixelArea())

    donut_stats = donut_image.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=panchayat,
        scale=30,
        maxPixels=1_000_000_000,
    ).getInfo()

    donut_total = sum(donut_stats.values()) or 1.0
    donut_pct = {k: round((v / donut_total) * 100, 1) for k, v in donut_stats.items()}

    # Extract dynamic stats values
    ndvi_before_avg = round(mean_stats.get("ndvi_before") or 0.0, 3)
    ndvi_after_avg = round(mean_stats.get("ndvi_after") or 0.0, 3)
    ndwi_before_avg = round(mean_stats.get("ndwi_before") or 0.0, 3)
    ndwi_after_avg = round(mean_stats.get("ndwi_after") or 0.0, 3)
    ndbi_before_avg = round(mean_stats.get("ndbi_before") or 0.0, 3)
    ndbi_after_avg = round(mean_stats.get("ndbi_after") or 0.0, 3)

    green_before_pct = round(((area_stats.get("green_cover_before") or 0.0) / 10000) / total_area_ha * 100, 1)
    green_after_pct = round(((area_stats.get("green_cover_after") or 0.0) / 10000) / total_area_ha * 100, 1)
    green_change_pct = round(green_after_pct - green_before_pct, 1)

    water_before_pct = round(((area_stats.get("water_bodies_before") or 0.0) / 10000) / total_area_ha * 100, 1)
    water_after_pct = round(((area_stats.get("water_bodies_after") or 0.0) / 10000) / total_area_ha * 100, 1)
    water_change_pct = round(water_after_pct - water_before_pct, 1)

    built_before_pct = round(((area_stats.get("built_up_before") or 0.0) / 10000) / total_area_ha * 100, 1)
    built_after_pct = round(((area_stats.get("built_up_after") or 0.0) / 10000) / total_area_ha * 100, 1)
    built_change_pct = round(built_after_pct - built_before_pct, 1)

    veg_loss_ha = round((area_stats.get("veg_loss") or 0.0) / 10000, 2)
    water_loss_ha = round((area_stats.get("water_loss") or 0.0) / 10000, 2)
    water_gain_ha = round((area_stats.get("water_gain") or 0.0) / 10000, 2)
    water_change_ha = round(water_gain_ha - water_loss_ha, 2)
    built_up_expansion_ha = round((area_stats.get("built_up_expansion") or 0.0) / 10000, 2)
    total_built_up_area_ha = round((area_stats.get("built_up_after") or 0.0) / 10000, 2)

    # 6. Clickable Change Polygons (GeoJSON extraction)
    # Define vector filters
    features = []
    
    # Built-up expansion polygons
    try:
        vectors_buildup = cleaned_expansion.reduceToVectors(
            geometry=panchayat,
            scale=30,
            geometryType="polygon",
            maxPixels=1_000_000_000,
            bestEffort=True
        )
        buildup_features = vectors_buildup.map(lambda f: f.set("area_m2", f.geometry().area(10))).filter(ee.Filter.gt("area_m2", 200)).limit(10).getInfo()
        for i, f in enumerate(buildup_features.get("features", [])):
            area_m2 = f["properties"].get("area_m2", 0)
            area_ha = round(area_m2 / 10000, 2)
            coords = f["geometry"]["coordinates"]
            geom_type = f["geometry"]["type"]
            features.append({
                "type": "Feature",
                "geometry": {"type": geom_type, "coordinates": coords},
                "properties": {
                    "location": f"Zone B-{i+1} - Construction Site",
                    "change_type": "Built-up Expansion",
                    "estimated_area_ha": area_ha,
                    "confidence": 0.85,
                    "before_val": "Vegetated / Open Land",
                    "after_val": "New Developed Surface"
                }
            })
    except Exception as e:
        logger.warning(f"Error vectorizing buildup expansion: {e}")

    # Significant vegetation loss polygons
    try:
        vectors_veg = change.lt(-0.25).selfMask().reduceToVectors(
            geometry=panchayat,
            scale=30,
            geometryType="polygon",
            maxPixels=1_000_000_000,
            bestEffort=True
        )
        veg_features = vectors_veg.map(lambda f: f.set("area_m2", f.geometry().area(10))).filter(ee.Filter.gt("area_m2", 500)).limit(10).getInfo()
        for i, f in enumerate(veg_features.get("features", [])):
            area_m2 = f["properties"].get("area_m2", 0)
            area_ha = round(area_m2 / 10000, 2)
            coords = f["geometry"]["coordinates"]
            geom_type = f["geometry"]["type"]
            features.append({
                "type": "Feature",
                "geometry": {"type": geom_type, "coordinates": coords},
                "properties": {
                    "location": f"Zone V-{i+1} - Vegetation Clearing",
                    "change_type": "Vegetation Loss",
                    "estimated_area_ha": area_ha,
                    "confidence": 0.89,
                    "before_val": "Healthy Forest / Canopy",
                    "after_val": "Cleared / Low Density Vegetation"
                }
            })
    except Exception as e:
        logger.warning(f"Error vectorizing vegetation loss: {e}")

    # 7. Environmental Score Calculation
    score = 100 - (veg_loss_ha * 0.4) - (built_up_expansion_ha * 2.5) - (water_loss_ha * 1.5)
    score = min(100, max(10, int(score)))

    # 8. Tile URLs
    url_before = tile_url(before.select(["B4", "B3", "B2"]), {"min": 0, "max": 2500})
    url_after = tile_url(after.select(["B4", "B3", "B2"]), {"min": 0, "max": 2500})
    url_ndvi = tile_url(change, {"min": -0.5, "max": 0.5, "palette": CHANGE_PALETTE})
    url_ndwi = tile_url(water_change, {"min": -0.5, "max": 0.5, "palette": ["#d73027", "#fc8d59", "#fee08b", "#d9ef8b", "#4575b4"]})
    url_ndbi = tile_url(ndbi_change, {"min": -0.5, "max": 0.5, "palette": ["#4575b4", "#fee08b", "#fc8d59", "#d73027"]})
    url_buildup = tile_url(cleaned_expansion, {"min": 0, "max": 1, "palette": ["#FF3333"]})

    # 9. Dynamic Report and Recommendation
    rec = "Panchayat environment is stable. Continue periodic monitoring."
    if veg_loss_ha > 5:
        rec = "Inspect highlighted regions with significant vegetation loss."
    elif built_up_expansion_ha > 2:
        rec = "Investigate rapid built-up expansion zones for encroachment."
    
    report_text = (
        f"Green Cover: {green_change_pct:+.1f}%\n"
        f"Water Bodies: {water_change_pct:+.1f}%\n"
        f"Built-up Expansion: {built_change_pct:+.1f}%\n"
        f"Environmental Score: {score}/100\n"
        f"Recommendation: {rec}"
    )

    # 10. Dynamic Alerts
    alerts = []
    if veg_loss_ha > 5:
        alerts.append(Alert(
            level="high",
            type="vegetation",
            title="High Vegetation Loss",
            message=f"Significant clearing detected. Area: {veg_loss_ha:.2f} ha"
        ))
    if water_loss_ha > 2:
        alerts.append(Alert(
            level="high",
            type="water",
            title="Water Body Shrinking",
            message=f"Significant surface water contraction detected. Area: {water_loss_ha:.2f} ha"
        ))
    if built_up_expansion_ha > 0.5:
        alerts.append(Alert(
            level="medium",
            type="buildup",
            title="New Built-up Expansion",
            message=f"New developed/barren surfaces identified. Area: {built_up_expansion_ha:.2f} ha"
        ))

    return CompareResponse(
        monthA=month_a,
        monthB=month_b,
        generated_at=datetime.now(UTC).isoformat(),
        tiles={
            "before": url_before,
            "after": url_after,
            "ndvi_change": url_ndvi,
            "ndwi_change": url_ndwi,
            "ndbi_change": url_ndbi,
            "new_construction": url_buildup
        },
        stats=CompareStats(
            green_cover=MetricChange(
                before=green_before_pct,
                after=green_after_pct,
                change=green_change_pct,
                avg_before=ndvi_before_avg,
                avg_after=ndvi_after_avg
            ),
            water=MetricChange(
                before=water_before_pct,
                after=water_after_pct,
                change=water_change_pct,
                avg_before=ndwi_before_avg,
                avg_after=ndwi_after_avg
            ),
            built_up=MetricChange(
                before=built_before_pct,
                after=built_after_pct,
                change=built_change_pct,
                avg_before=ndbi_before_avg,
                avg_after=ndbi_after_avg
            ),
            environmental_score=score,
            vegetation_loss_area_ha=veg_loss_ha,
            water_change_area_ha=water_change_ha,
            built_up_expansion_area_ha=built_up_expansion_ha,
            total_built_up_area_ha=total_built_up_area_ha,
            panchayat_area_ha=round(total_area_ha, 1),
            donut_ndvi_change=donut_pct
        ),
        polygons={
            "type": "FeatureCollection",
            "features": features
        },
        report={
            "text": report_text,
            "recommendation": rec
        },
        alerts=alerts
    )
