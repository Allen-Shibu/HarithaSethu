"""
gee/fetch_buildup_sar.py

High-confidence new construction detection using Sentinel-1 SAR + Sentinel-2 NDVI fusion.

Physics:
  - New buildings create a "double-bounce" between their walls and the ground,
    which sharply increases Sentinel-1 VV backscatter.
  - Construction also clears vegetation, causing Sentinel-2 NDVI to decrease.
  - Requiring BOTH signals to agree eliminates most false positives
    (e.g. seasonal flooding raises VV but not NDVI; cloud shadows drop NDVI but not VV).

Outputs:
  - tile_url: GEE tile overlay (orange-red pixels = new construction)
  - vv_change_tile_url: VV change raster for debugging
  - new_built_area_ha: total area of detected new construction
  - clusters: list of {lat, lon, area_m2} for the largest change patches
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import ee

ROOT_DIR = Path(__file__).resolve().parents[1]
BOUNDARY_FILE = ROOT_DIR / "Chakkittapara Grama Panchayat - Boundaries.geojson"
OUTPUT_FILE = ROOT_DIR / "data" / "buildup_sar.json"
PROJECT = "n8n-workflows-473615"

# ── Tunable thresholds ─────────────────────────────────────────────────────────
VV_CHANGE_THRESHOLD_DB = 2.0   # dB: VV increase above this → likely new structure
NDVI_CHANGE_THRESHOLD = -0.10  # NDVI drop below this → vegetation removed
SPECKLE_RADIUS_M = 50          # metres: focal-mean filter radius for SAR speckle
MIN_PATCH_AREA_M2 = 200        # m²: ignore patches smaller than ~2 pixels (noise)
MAX_CLUSTERS = 12              # max building-cluster centroids to return
# ──────────────────────────────────────────────────────────────────────────────


def load_panchayat_geometry() -> ee.Geometry:
    with BOUNDARY_FILE.open("r", encoding="utf-8") as f:
        geojson = json.load(f)
    polygon = next(
        feature["geometry"]
        for feature in geojson["features"]
        if feature["geometry"]["type"] in {"Polygon", "MultiPolygon"}
    )
    return ee.Geometry(polygon)


def sar_composite(panchayat: ee.Geometry, start: str, end: str) -> ee.Image:
    """
    Mean Sentinel-1 IW VV+VH composite clipped to the panchayat,
    with a focal-mean speckle filter applied before returning.
    """
    collection = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterBounds(panchayat)
        .filterDate(start, end)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
        .select(["VV", "VH"])
    )
    count = int(collection.size().getInfo())
    print(f"  SAR [{start} → {end}]: {count} scenes")

    composite = collection.mean().clip(panchayat)
    # Focal mean reduces speckle (multiplicative noise inherent in SAR)
    return composite.focal_mean(radius=SPECKLE_RADIUS_M, units="meters")


def ndvi_composite(panchayat: ee.Geometry, start: str, end: str) -> ee.Image:
    """
    Cloud-masked Sentinel-2 SR median composite, returning only the NDVI band.
    Falls back to a looser cloud threshold if few images are available.
    """
    def mask_clouds(image: ee.Image) -> ee.Image:
        qa = image.select("QA60")
        cloud_mask = qa.bitwiseAnd(1 << 10).eq(0)
        cirrus_mask = qa.bitwiseAnd(1 << 11).eq(0)
        return image.updateMask(cloud_mask.And(cirrus_mask))

    for cloud_pct in (20, 40, 70):
        col = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(panchayat)
            .filterDate(start, end)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud_pct))
            .map(mask_clouds)
        )
        count = int(col.size().getInfo())
        print(f"  S2 NDVI [{start} → {end}] cloud<{cloud_pct}%: {count} scenes")
        if count > 0:
            composite = col.median().clip(panchayat)
            return composite.normalizedDifference(["B8", "B4"]).rename("ndvi")

    raise RuntimeError(f"No Sentinel-2 imagery for {start} → {end}")


def tile_url(image: ee.Image, vis_params: dict[str, Any]) -> str:
    return image.getMapId(vis_params)["tile_fetcher"].url_format


def detect_new_construction(
    panchayat: ee.Geometry,
    before_start: str,
    before_end: str,
    after_start: str,
    after_end: str,
) -> dict[str, Any]:
    """
    Core fusion pipeline:

      1. SAR: compute VV change (after − before). Increase > threshold → hard structure.
      2. NDVI: compute NDVI change. Decrease > threshold → vegetation loss.
      3. Fuse: require BOTH signals to fire (AND).
      4. Morphological clean-up: erode then dilate to remove single-pixel speckle.
      5. Vectorise change patches → extract centroids of the largest clusters.
    """
    print("\n── Sentinel-1 composites ──")
    sar_before = sar_composite(panchayat, before_start, before_end)
    sar_after  = sar_composite(panchayat, after_start, after_end)

    # VV change in dB (the images are already in dB from GEE's S1_GRD)
    vv_change = sar_after.select("VV").subtract(sar_before.select("VV")).rename("vv_change")
    sar_signal = vv_change.gt(VV_CHANGE_THRESHOLD_DB)

    print("\n── Sentinel-2 NDVI composites ──")
    ndvi_before = ndvi_composite(panchayat, before_start, before_end)
    ndvi_after  = ndvi_composite(panchayat, after_start, after_end)

    ndvi_change = ndvi_after.subtract(ndvi_before).rename("ndvi_change")
    ndvi_signal = ndvi_change.lt(NDVI_CHANGE_THRESHOLD)

    print("\n── Fusion & clean-up ──")
    # Require both SAR increase AND NDVI decrease
    fused = sar_signal.And(ndvi_signal).rename("new_construction")

    # Morphological opening: removes isolated pixels (speckle) while preserving clusters
    cleaned = (
        fused
        .focal_min(radius=10, units="meters")   # erosion: shrink small blobs away
        .focal_max(radius=10, units="meters")   # dilation: restore surviving blobs
        .selfMask()
        .rename("new_construction")
    )

    # ── Tile URLs ──────────────────────────────────────────────────────────────
    construction_tile = tile_url(cleaned, {
        "min": 0, "max": 1,
        "palette": ["FF4500"],   # orange-red
    })
    vv_change_tile = tile_url(vv_change, {
        "min": -5, "max": 5,
        "palette": ["#2166ac", "#d1e5f0", "#f7f7f7", "#fddbc7", "#d6604d"],
    })

    # ── Area ──────────────────────────────────────────────────────────────────
    area_result = (
        cleaned
        .multiply(ee.Image.pixelArea())
        .reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=panchayat,
            scale=10,
            maxPixels=1_000_000_000,
        )
        .getInfo()
    )
    area_ha = round((area_result.get("new_construction") or 0) / 10_000, 2)
    print(f"  New construction area: {area_ha} ha")

    # ── Cluster centroids ──────────────────────────────────────────────────────
    clusters: list[dict[str, Any]] = []
    try:
        vectors = cleaned.reduceToVectors(
            geometry=panchayat,
            scale=10,
            geometryType="polygon",
            maxPixels=1_000_000_000,
            bestEffort=True,
        )

        def add_area(feature: ee.Feature) -> ee.Feature:
            return feature.set("area_m2", feature.geometry().area(10))

        vectors_with_area = vectors.map(add_area)

        significant = vectors_with_area.filter(
            ee.Filter.gt("area_m2", MIN_PATCH_AREA_M2)
        )
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

            clusters.append({
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "area_m2": round(props.get("area_m2", 0), 1),
            })

        print(f"  Clusters (≥{MIN_PATCH_AREA_M2} m²): {len(clusters)}")

    except Exception as exc:
        print(f"  Warning — centroid extraction failed: {exc}")

    return {
        "method": "sentinel1_sar_ndvi_fusion",
        "tile_url": construction_tile,
        "vv_change_tile_url": vv_change_tile,
        "new_built_area_ha": area_ha,
        "cluster_count": len(clusters),
        "clusters": clusters,
        "thresholds": {
            "vv_change_db": VV_CHANGE_THRESHOLD_DB,
            "ndvi_change": NDVI_CHANGE_THRESHOLD,
            "speckle_filter_radius_m": SPECKLE_RADIUS_M,
        },
        "periods": {
            "before": {"start": before_start, "end": before_end},
            "after":  {"start": after_start,  "end": after_end},
        },
    }


def main() -> None:
    ee.Initialize(project=PROJECT)

    panchayat = load_panchayat_geometry()

    result = detect_new_construction(
        panchayat,
        before_start="2023-12-01",
        before_end="2024-02-28",
        after_start="2024-03-01",
        after_end="2024-05-01",
    )

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"\n✅  Wrote {OUTPUT_FILE}")
    print(f"   Area:     {result['new_built_area_ha']} ha")
    print(f"   Clusters: {result['cluster_count']}")
    for i, c in enumerate(result["clusters"], 1):
        print(f"   [{i}] lat={c['lat']}, lon={c['lon']}, area={c['area_m2']} m²")


if __name__ == "__main__":
    main()
