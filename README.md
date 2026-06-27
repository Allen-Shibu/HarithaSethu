# GramaDrishti

Python backend for gram panchayat-level satellite intelligence.

## Run the API

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

The API runs at `http://127.0.0.1:8000`.

## Test the Backend

```bash
python -m unittest discover -v
```

## Endpoints

- `GET /health`
- `GET /api/indices`
- `GET /api/tiles`
- `GET /api/timeseries`
- `GET /api/report`
- `GET /api/boundary`

## Run the Frontend

In a second terminal:

```bash
python3.12 -m http.server 5173 --directory frontend
```

Open `http://127.0.0.1:5173`.

## Generate Earth Engine Data

Authenticate Google Earth Engine first, then run:

```bash
python gee/fetch_change.py
```

That writes `data/output.json`, which the API reads automatically. Until the file exists, the API serves sample values matching the current project context
