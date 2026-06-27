from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .app.data_store import load_boundary, load_data, refresh_data_cache

app = FastAPI(
    title="GramaDrishti API",
    description="Python backend for panchayat-level satellite intelligence.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/indices")
def get_indices() -> dict[str, object]:
    data = load_data()
    return {
        "panchayat": data.panchayat,
        "generated_at": data.generated_at,
        "source": data.source,
        "indices": data.indices.model_dump(),
    }


@app.get("/api/tiles")
def get_tiles() -> dict[str, object]:
    data = load_data()
    return {
        "panchayat": data.panchayat,
        "generated_at": data.generated_at,
        "tiles": {name: layer.model_dump(mode="json") for name, layer in data.tiles.items()},
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
def get_report() -> dict[str, object]:
    data = load_data()
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
