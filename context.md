# HarithaSethu / GramaDrishti — Project Context

## What We're Building

A satellite intelligence platform for gram panchayat-level environmental monitoring in Kerala. The target panchayat for the pilot is **Chakkittapara Grama Panchayat, Kozhikode**.

The platform shows local government officials and citizens how their panchayat's environment is changing over time — vegetation loss, water body shrinkage, and built-up area expansion — using real Sentinel-2 satellite imagery.

---

## The Problem

Gram panchayats in Kerala have no affordable, accessible way to monitor environmental changes in their jurisdiction. Deforestation, encroachment, and water body shrinkage happen slowly and go undetected until it's too late. Satellite data exists but is inaccessible to local bodies without technical expertise.

---

## The Solution

GramaDrishti pulls Sentinel-2 imagery from Google Earth Engine, computes environmental indices (NDVI, NDWI), detects change between time periods, and serves it as an interactive map dashboard. Local officials get alerts, reports, and a visual map showing exactly where and how much change has occurred.

---

## Current State

- [x] GEE initialized with project `n8n-workflows-473615`
- [x] NDVI and NDWI values computed for Chakkittapara (NDVI: 0.768, NDWI: -0.689)
- [x] `gee/fetch_change.py` written — computes true-color before/after tiles, NDVI difference raster, NDVI/NDWI indices, and exports to `data/output.json`
- [x] `data/output.json` generated successfully from Google Earth Engine
- [x] Python/FastAPI backend scaffolded
- [x] API endpoints implemented for indices, tiles, timeseries, report, boundary, health, and refresh
- [x] Static frontend scaffolded from `mockup.jpeg`
- [x] Frontend uses Leaflet and consumes the Python API
- [x] Backend tests added with `unittest`
- [ ] Built-up area detection is still placeholder UI/data
- [ ] River/water-body shrinkage detection is still planned

---

## Architecture

```text
GEE Python Scripts
  └── gee/fetch_change.py          # true-color tiles + NDVI/NDWI + NDVI change raster
  └── (planned) gee/fetch_buildup.py
  └── (planned) gee/fetch_river.py

       ↓ writes

data/output.json                   # shared data layer with GEE tile URLs and metrics

       ↓ read by

Python/FastAPI Backend
  └── GET  /health                 # deployment/local health check
  └── GET  /api/indices            # current NDVI, NDWI values
  └── GET  /api/timeseries         # monthly sample NDVI/NDWI series
  └── GET  /api/tiles              # GEE tile URL templates for frontend maps
  └── GET  /api/report             # summary report JSON
  └── GET  /api/boundary           # panchayat boundary GeoJSON
  └── POST /api/refresh            # clears cached data/output.json

       ↓ consumed by

Static Frontend
  └── frontend/index.html          # dashboard layout from mockup.jpeg
  └── frontend/styles.css          # dark operations dashboard styling
  └── frontend/app.js              # API fetch + Leaflet map wiring
  └── Side-by-side comparison      # May/June true-color GEE tile layers
  └── NDVI change panel            # colored GEE change raster overlay
```

---

## File Structure (Current)

```
HarithaSethu/
├── gee/
│   └── fetch_change.py
├── backend/
│   ├── main.py
│   └── app/
│       ├── data_store.py
│       └── models.py
├── data/
│   └── output.json
├── frontend/
    ├── index.html
    ├── styles.css
    └── app.js
├── tests/
│   └── test_backend.py
├── mockup.jpeg
├── requirements.txt
├── README.md
└── Chakkittapara Grama Panchayat - Boundaries.geojson
```

---

## Key Indices

| Index | Formula | What it measures |
|-------|---------|-----------------|
| NDVI  | (B8 - B4) / (B8 + B4) | Vegetation health and density |
| NDWI  | (B3 - B8) / (B3 + B8) | Surface water presence |

**Interpretation:**
- NDVI 0.6–1.0 → dense healthy vegetation
- NDVI 0–0.2 → bare soil / urban
- NDWI > 0 → water body present
- NDWI < 0 → dry land / vegetation

---

## Change Detection Logic

```
NDVI(period_B) - NDVI(period_A) = change raster

Positive → vegetation gained (green on map)
Near zero → no change (yellow)
Negative → vegetation lost (red on map)
```

Color palette used:
- `#d73027` — High Decrease
- `#fc8d59` — Moderate Decrease
- `#fee08b` — No Change
- `#d9ef8b` — Moderate Increase
- `#1a9850` — High Increase

---

## Satellite Data Source

- **Sensor:** Sentinel-2 SR Harmonized (`COPERNICUS/S2_SR_HARMONIZED`)
- **Resolution:** 10m × 10m per pixel
- **Primary cloud filter:** `CLOUDY_PIXEL_PERCENTAGE < 20`
- **Fallback cloud filters:** `< 40`, `< 70`, then broad fallback when exact monthly windows have no imagery
- **Compositing:** `.median()` across the date range to reduce cloud noise
- **Platform:** Google Earth Engine (Python API)
- **True-color bands:** `B4`, `B3`, `B2`
- **NDVI bands:** `B8`, `B4`
- **NDWI bands:** `B3`, `B8`

Current generated composite metadata:
- **Before comparison:** `2024-04-15` to `2024-06-16`, cloud threshold `< 40`, image count `5`
- **After comparison:** `2024-05-15` to `2024-07-16`, cloud threshold `< 40`, image count `2`
- **Current annual indices:** `2024-01-01` to `2024-12-31`, cloud threshold `< 20`, image count `36`

---

## Panchayat Geometry

Real boundary GeoJSON is present:
```
Chakkittapara Grama Panchayat - Boundaries.geojson
```

It is loaded by:
- `gee/fetch_change.py` for Earth Engine geometry
- `GET /api/boundary` for frontend map outline

Approximate active map bounds used by the frontend:
```
[75.792, 11.548, 75.907, 11.681]  # [west, south, east, north]
```

---

## What the Dashboard Shows (per mockup)

1. **Satellite Image** — true color for before and after periods
2. **NDVI Change Detection** — colored diff raster on map
3. **Change Detection — Built-up Expansion** — new construction markers
4. **New Buildings Detected** — image chips of detected structures
5. **Summary (Monthly Change)** — Green Cover %, Water Bodies %, Built-up Area %
6. **Environmental Score** — composite score out of 100
7. **Alerts** — High Vegetation Loss, Water Body Shrinking, New Construction
8. **Yearly Comparison** — June 2023 vs June 2024
9. **NDVI Change (Yearly)** — donut chart breakdown

---

## Implemented API

Base URL during local development:
```
http://127.0.0.1:8000
```

Endpoints:
- `GET /health`
- `GET /api/indices`
- `GET /api/tiles`
- `GET /api/timeseries`
- `GET /api/report`
- `GET /api/boundary`
- `POST /api/refresh`

`/api/tiles` currently returns tile templates for:
- `true_color_before`
- `true_color_after`
- `ndvi_change`

If `data/output.json` is missing, the backend serves sample fallback values so frontend development can continue. Once `data/output.json` exists, it serves the real GEE values and tile URLs.

---

## Frontend State

The frontend is currently a static HTML/CSS/JS dashboard, not React yet.

Run it with:
```
python3.12 -m http.server 5173 --directory frontend
```

Open:
```
http://127.0.0.1:5173
```

Important behavior:
- The three top map panels are Leaflet maps.
- If GEE tile URLs are available, they are loaded over satellite imagery.
- If GEE tile URLs are missing, CSS fallback placeholder visuals appear.
- The layout is based on `mockup.jpeg`.

---

## Backend Commands

Create environment with Python 3.12. Python 3.14 caused `pydantic-core` install/build issues.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Generate GEE output:
```bash
python gee/fetch_change.py
```

Run tests:
```bash
python -m unittest discover -v
```

Current test status:
```text
Ran 7 tests
OK
```

---

## Next Steps

1. Restart or refresh the backend after `data/output.json` changes.
2. Verify the frontend map panels display real GEE tiles instead of fallback gradients.
3. Improve the side-by-side comparison UI with synchronized map movement.
4. Replace sample monthly timeseries with GEE-computed monthly NDVI/NDWI values.
5. Add built-up area detection script and API fields.
6. Add named river/water-body shrinkage detection.
7. Decide whether to keep static frontend or migrate to React/Vite once the dashboard behavior stabilizes.
8. Add screenshot/browser verification for the frontend.

---

## Stack

| Layer | Tech |
|-------|------|
| Satellite data | Google Earth Engine (Python) |
| Backend | Python, FastAPI |
| Frontend | Static HTML/CSS/JS for now; React/Vite still optional |
| Map | Leaflet.js |
| Charts | CSS charts for now; Recharts optional if migrating to React |
| Deployment | Render (backend), Vercel (frontend) |
