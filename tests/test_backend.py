from __future__ import annotations

import unittest

from backend.app.data_store import _normalize
from backend.main import get_boundary, get_indices, get_report, get_tiles, get_timeseries, health


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
