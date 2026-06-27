from __future__ import annotations

import json
import unittest

from backend.app.data_store import _normalize
from backend.main import compare, get_boundary, get_indices, get_report, get_tiles, get_timeseries, health


class BackendRouteTests(unittest.TestCase):
    def test_health(self) -> None:
        self.assertEqual(health(), {"status": "ok"})

    def test_indices_response_shape(self) -> None:
        payload = get_indices()

        self.assertEqual(payload["panchayat"], "Chakkittapara Grama Panchayat")
        self.assertIn(payload["source"], {"sample", "google_earth_engine"})
        self.assertIn("ndvi", payload["indices"])
        self.assertIn("ndwi", payload["indices"])

    def test_tiles_response_shape(self) -> None:
        payload = get_tiles()

        self.assertIn("true_color_before", payload["tiles"])
        self.assertIn("true_color_after", payload["tiles"])
        self.assertIn("ndvi_change", payload["tiles"])
        self.assertEqual(
            payload["tiles"]["ndvi_change"]["palette"],
            ["#d73027", "#fc8d59", "#fee08b", "#d9ef8b", "#1a9850"],
        )

    def test_timeseries_has_monthly_points(self) -> None:
        payload = get_timeseries()

        self.assertEqual(len(payload["timeseries"]), 12)
        self.assertEqual(payload["timeseries"][0]["month"], "2024-01")

    def test_report_response_shape(self) -> None:
        payload = get_report()

        self.assertIn("summary", payload)
        self.assertIn("environmental_score", payload["summary"])
        self.assertIn("alerts", payload)

    def test_boundary_loads_geojson(self) -> None:
        payload = get_boundary()

        self.assertEqual(payload["type"], "FeatureCollection")
        self.assertGreaterEqual(len(payload["features"]), 1)

    def test_compare_route_cached(self) -> None:
        from pathlib import Path
        cache_dir = Path(__file__).resolve().parents[1] / "backend" / "data" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "compare_2000-01_2000-02.json"
        
        mock_data = {
            "panchayat": "Chakkittapara Grama Panchayat",
            "monthA": "2000-01",
            "monthB": "2000-02",
            "generated_at": "2026-06-27T19:00:00Z",
            "tiles": {
                "before": "https://url-before",
                "after": "https://url-after",
                "ndvi_change": "https://url-ndvi",
                "ndwi_change": "https://url-ndwi",
                "ndbi_change": "https://url-ndbi",
                "new_construction": "https://url-buildup"
            },
            "stats": {
                "green_cover": {"before": 70.0, "after": 68.0, "change": -2.0, "avg_before": 0.6, "avg_after": 0.5},
                "water": {"before": 3.0, "after": 2.8, "change": -0.2, "avg_before": -0.1, "avg_after": -0.12},
                "built_up": {"before": 10.0, "after": 10.5, "change": 0.5, "avg_before": -0.15, "avg_after": -0.1},
                "environmental_score": 80,
                "vegetation_loss_area_ha": 15.0,
                "water_change_area_ha": -2.0,
                "built_up_expansion_area_ha": 5.0,
                "total_built_up_area_ha": 100.0,
                "panchayat_area_ha": 1000.0,
                "donut_ndvi_change": {
                    "high_inc": 2.0,
                    "mod_inc": 10.0,
                    "no_chg": 70.0,
                    "mod_dec": 15.0,
                    "high_dec": 3.0
                }
            },
            "polygons": {
                "type": "FeatureCollection",
                "features": []
            },
            "report": {
                "text": "Green cover decreased.",
                "recommendation": "Monitor vegetation loss."
            },
            "alerts": []
        }
        
        with cache_file.open("w", encoding="utf-8") as f:
            json.dump(mock_data, f)
            
        try:
            resp = compare("2000-01", "2000-02")
            self.assertEqual(resp.monthA, "2000-01")
            self.assertEqual(resp.monthB, "2000-02")
            self.assertEqual(resp.stats.environmental_score, 80)
            self.assertEqual(resp.tiles["before"], "https://url-before")
        finally:
            if cache_file.exists():
                cache_file.unlink()


class DataNormalizationTests(unittest.TestCase):
    def test_normalizes_legacy_flat_output(self) -> None:
        payload = _normalize(
            {
                "ndvi": 0.55,
                "ndwi": -0.25,
                "tile_url": "https://earthengine.example/tiles/{z}/{x}/{y}",
            }
        )

        self.assertEqual(payload["indices"], {"ndvi": 0.55, "ndwi": -0.25})
        self.assertEqual(
            payload["tiles"]["ndvi_change"]["url"],
            "https://earthengine.example/tiles/{z}/{x}/{y}",
        )


if __name__ == "__main__":
    unittest.main()
