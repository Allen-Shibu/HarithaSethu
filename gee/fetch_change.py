from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import ee

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


def fetch_buildup(
    panchayat: ee.Geometry,
    before_start: str,
    before_end: str,
    after_start: str,
    after_end: str,
) -> dict:
    dw_before = (
        ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
        .filterBounds(panchayat)
        .filterDate(before_start, before_end)
        .mode()
    )

    dw_after = (
        ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
        .filterBounds(panchayat)
        .filterDate(after_start, after_end)
        .mode()
    )

    built_before = dw_before.select("label").eq(6)
    built_after = dw_after.select("label").eq(6)

    new_construction = built_after.And(built_before.Not()).selfMask()

    new_construction_url = tile_url(
        new_construction,
        {"min": 0, "max": 1, "palette": ["FF0000"]},
    )

    area = new_construction.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=panchayat,
        scale=10,
        maxPixels=1_000_000_000,
    ).getInfo()

    area_ha = round(area.get("label", 0) / 10000, 2)

    return {
        "tile_url": new_construction_url,
        "new_built_area_ha": area_ha,
    }


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
    buildup = fetch_buildup(
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
                "attribution": "Google Dynamic World / Sentinel-2",
            },
        },
        "summary": {
            "green_cover_percent": round(indices["ndvi"] * 100, 1),
            "water_bodies_percent": round(max(indices["ndwi"], 0) * 100, 1),
            "built_up_percent": buildup["new_built_area_ha"],
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
