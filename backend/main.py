from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .app.data_store import load_boundary, load_data, refresh_data_cache
from .app.gee_query import compute_monthly_comparison
from .app.models import ApiData

app = FastAPI(
    title="GramaDrishti API",
    description="Python backend for gram panchayat-level satellite intelligence.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

CACHE_DIR = Path(__file__).resolve().parent / "data" / "cache"


def get_data_for_period(before: str | None = None, after: str | None = None) -> ApiData:
    if not before or not after:
        return load_data()

    try:
        datetime.strptime(before, "%Y-%m")
        datetime.strptime(after, "%Y-%m")
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Use YYYY-MM (e.g. 2024-05)"
        )

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{before}_{after}.json"

    if cache_file.exists():
        try:
            with cache_file.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            return ApiData.model_validate(raw)
        except Exception:
            # If cache file is corrupt, delete and recompute
            try:
                cache_file.unlink()
            except OSError:
                pass

    # Compute on the fly
    try:
        data = compute_monthly_comparison(before, after)
        with cache_file.open("w", encoding="utf-8") as f:
            json.dump(data.model_dump(mode="json"), f, indent=2)
        return data
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Google Earth Engine computation failed: {str(e)}"
        )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/indices")
def get_indices(before: str | None = None, after: str | None = None) -> dict[str, object]:
    data = get_data_for_period(before, after)
    return {
        "panchayat": data.panchayat,
        "generated_at": data.generated_at,
        "source": data.source,
        "indices": data.indices.model_dump(),
    }


@app.get("/api/tiles")
def get_tiles(before: str | None = None, after: str | None = None) -> dict[str, object]:
    data = get_data_for_period(before, after)
    return {
        "panchayat": data.panchayat,
        "generated_at": data.generated_at,
        "tiles": {name: layer.model_dump(mode="json") for name, layer in data.tiles.items()},
    }


@app.get("/api/buildup")
def get_buildup(before: str | None = None, after: str | None = None) -> dict[str, object]:
    """SAR + NDVI fusion building-change detection results."""
    data = get_data_for_period(before, after)
    return {
        "panchayat": data.panchayat,
        "generated_at": data.generated_at,
        "buildup": data.buildup.model_dump(mode="json"),
    }


@app.get("/api/timeseries")
def get_timeseries() -> dict[str, object]:
    data = load_data()
    return {
        "panchayat": data.panchayat,
        "generated_at": data.generated_at,
        "timeseries": [point.model_dump() for point in data.timeseries],
    }


@app.get("/api/report")
def get_report(before: str | None = None, after: str | None = None) -> dict[str, object]:
    data = get_data_for_period(before, after)
    return {
        "panchayat": data.panchayat,
        "district": data.district,
        "state": data.state,
        "generated_at": data.generated_at,
        "source": data.source,
        "indices": data.indices.model_dump(),
        "summary": data.summary.model_dump(),
        "alerts": [alert.model_dump() for alert in data.alerts],
        "metadata": data.metadata,
    }


@app.get("/api/boundary")
def get_boundary() -> dict[str, object]:
    try:
        return load_boundary()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Boundary GeoJSON not found") from exc


@app.post("/api/refresh")
def refresh() -> dict[str, str]:
    refresh_data_cache()
    return {"status": "refreshed"}
