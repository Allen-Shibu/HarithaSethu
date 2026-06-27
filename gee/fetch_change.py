from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import ee

# Allow sibling-module import when running as a top-level script
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_buildup_sar import detect_new_construction  # noqa: E402

ROOT_DIR = Path(__file__).resolve().parents[1]
BOUNDARY_FILE = ROOT_DIR / "Chakkittapara Grama Panchayat - Boundaries.geojson"
OUTPUT_FILE = ROOT_DIR / "data" / "output.json"
PROJECT = "n8n-workflows-473615"

CHANGE_PALETTE = ["#d73027", "#fc8d59", "#fee08b", "#d9ef8b", "#1a9850"]
SENTINEL_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"


class EmptyImageCollectionError(RuntimeError):
    pass


def load_panchayat_geometry() -> ee.Geometry:
    with BOUNDARY_FILE.open("r", encoding="utf-8") as file:
        geojson = json.load(file)

    polygon = next(
        feature["geometry"]
        for feature in geojson["features"]
        if feature["geometry"]["type"] in {"Polygon", "MultiPolygon"}
    )
    return ee.Geometry(polygon)


def sentinel_collection(
    panchayat: ee.Geometry,
    start: str,
    end: str,
    cloud_threshold: int,
) -> ee.ImageCollection:
    return (
        ee.ImageCollection(SENTINEL_COLLECTION)
        .filterBounds(panchayat)
        .filterDate(start, end)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud_threshold))
    )


def mask_s2_clouds(image: ee.Image) -> ee.Image:
    qa = image.select("QA60")
    cloud_mask = qa.bitwiseAnd(1 << 10).eq(0)
    cirrus_mask = qa.bitwiseAnd(1 << 11).eq(0)
    return image.updateMask(cloud_mask.And(cirrus_mask))


def sentinel_composite(
    panchayat: ee.Geometry,
    label: str,
    candidates: list[tuple[str, str, int]],
) -> tuple[ee.Image, dict[str, object]]:
    attempts = []

    for start, end, cloud_threshold in candidates:
        collection = sentinel_collection(panchayat, start, end, cloud_threshold)
        count = int(collection.size().getInfo())
        attempts.append(
            {
                "start": start,
                "end": end,
                "cloud_threshold": cloud_threshold,
                "image_count": count,
            }
        )

        if count > 0:
            return collection.map(mask_s2_clouds).median().clip(panchayat), {
                "label": label,
                "start": start,
                "end": end,
                "cloud_threshold": cloud_threshold,
                "image_count": count,
                "attempts": attempts,
            }

    raise EmptyImageCollectionError(
        f"No Sentinel-2 images found for {label}. Attempts: {attempts}"
    )


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
    return {"ndvi": round(result["ndvi"], 3), "ndwi": round(result["ndwi"], 3)}


def tile_url(image: ee.Image, vis_params: dict[str, object]) -> str:
    map_id = image.getMapId(vis_params)
    return map_id["tile_fetcher"].url_format


# Dynamic World fetch_buildup() removed.
# New construction is now detected via SAR + NDVI fusion in fetch_buildup_sar.py.


def build_output() -> dict[str, object]:
    ee.Initialize(project=PROJECT)

    panchayat = load_panchayat_geometry()
    before_raw, before_meta = sentinel_composite(
        panchayat,
        "before",
        [
            ("2023-12-01", "2024-02-28", 20),
            ("2023-11-01", "2024-03-15", 40),
            ("2023-10-01", "2024-03-31", 70),
            ("2023-01-01", "2024-03-31", 100),
        ],
    )
    after_raw, after_meta = sentinel_composite(
        panchayat,
        "after",
        [
            ("2024-03-01", "2024-05-01", 20),
            ("2024-02-01", "2024-05-15", 40),
            ("2024-01-01", "2024-06-01", 70),
            ("2023-06-01", "2024-06-01", 100),
        ],
    )
    current_raw, current_meta = sentinel_composite(
        panchayat,
        "current",
        [
            ("2024-01-01", "2024-05-31", 20),
            ("2023-11-01", "2024-05-31", 40),
            ("2023-06-01", "2024-05-31", 70),
            ("2023-01-01", "2024-05-31", 100),
        ],
    )

    before = add_indices(before_raw)
    after = add_indices(after_raw)
    current = add_indices(current_raw)

    change = after.select("ndvi").subtract(before.select("ndvi")).rename("ndvi_change")
    indices = mean_indices(current, panchayat)

    print("\n── Built-up detection (SAR + NDVI fusion) ──")
    buildup = detect_new_construction(
        panchayat,
        before_start="2023-12-01",
        before_end="2024-02-28",
        after_start="2024-03-01",
        after_end="2024-05-01",
    )

    return {
        "panchayat": "Chakkittapara Grama Panchayat",
        "district": "Kozhikode",
        "state": "Kerala",
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "google_earth_engine",
        "indices": indices,
        "tiles": {
            "true_color_before": {
                "url": tile_url(before.select(["B8", "B4", "B3"]), {"min": 0, "max": 3000}),
                "attribution": "Google Earth Engine / Sentinel-2 SR Harmonized",
                "min": 0,
                "max": 3000,
                "palette": [],
            },
            "true_color_after": {
                "url": tile_url(after.select(["B8", "B4", "B3"]), {"min": 0, "max": 3000}),
                "attribution": "Google Earth Engine / Sentinel-2 SR Harmonized",
                "min": 0,
                "max": 3000,
                "palette": [],
            },
            "ndvi_change": {
                "url": tile_url(
                    change,
                    {
                        "min": -0.5,
                        "max": 0.5,
                        "palette": CHANGE_PALETTE,
                    },
                ),
                "attribution": "Google Earth Engine / Sentinel-2 SR Harmonized",
                "min": -0.5,
                "max": 0.5,
                "palette": CHANGE_PALETTE,
            },
            "new_construction": {
                "url": buildup["tile_url"],
                "attribution": "Google Earth Engine / Sentinel-1 SAR + Sentinel-2 NDVI",
            },
        },
        "buildup": buildup,
        "summary": {
            "green_cover_percent": round(indices["ndvi"] * 100, 1),
            "water_bodies_percent": round(max(indices["ndwi"], 0) * 100, 1),
            "built_up_area_ha": buildup["new_built_area_ha"],
            "environmental_score": min(100, max(0, round((indices["ndvi"] * 85) + 18))),
        },
        "alerts": [],
        "metadata": {
            "sensor": SENTINEL_COLLECTION,
            "before_composite": before_meta,
            "after_composite": after_meta,
            "current_composite": current_meta,
            "resolution_m": 10,
        },
    }


def main() -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    output = build_output()
    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(output, file, indent=2)
    print(f"Wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
