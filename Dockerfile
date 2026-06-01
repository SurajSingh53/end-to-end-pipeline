import unittest
import os

from fastapi.testclient import TestClient

os.environ["APP_TRANSACTIONS_FILE"] = "inputs/transactions/brigade-bangalore-2026-04-10.csv"
os.environ["APP_VIDEO_DIR"] = "inputs/cctv"
os.environ["APP_EVENT_STORE"] = "artifacts/events.jsonl"
os.environ["APP_SESSION_STORE"] = "artifacts/sessions.json"
os.environ["APP_METRICS_STORE"] = "artifacts/metrics.json"

from src.main import app


class ApiRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_health_endpoints(self) -> None:
        for path in ("/health", "/Health"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body.get("status"), "ok")

    def test_metrics_contract_and_invariants(self) -> None:
        for path in ("/metrics", "/Metrics"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertIn("entries", body)
            self.assertIn("purchasers", body)
            self.assertIn("conversion_rate", body)
            self.assertIn("anomaly_reason_counts", body)
            self.assertIn("vision_edge_case_signals", body)
            self.assertLessEqual(body["purchasers"], body["entries"])

    def test_funnel_contract_and_monotonic(self) -> None:
        for path in ("/funnel", "/Funnel"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertIn("stages", body)
            self.assertIn("is_monotonic_non_increasing", body)
            self.assertTrue(body["is_monotonic_non_increasing"])

    def test_events_sample_schema(self) -> None:
        response = self.client.get("/events/sample?limit=10")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreaterEqual(body.get("count", 0), 1)
        self.assertTrue(len(body.get("events", [])) > 0)

        required_fields = {
            "event_id",
            "event_type",
            "event_time",
            "store_id",
            "session_id",
            "confidence",
            "dedupe_key",
            "reason_code",
            "source",
        }
        first_event = body["events"][0]
        self.assertTrue(required_fields.issubset(first_event.keys()))

    def test_diagnostics_endpoints(self) -> None:
        schema_response = self.client.get("/diagnostics/schema")
        self.assertEqual(schema_response.status_code, 200)
        schema_body = schema_response.json()
        self.assertIn("event_schema", schema_body)

        quality_response = self.client.get("/diagnostics/quality")
        self.assertEqual(quality_response.status_code, 200)
        quality_body = quality_response.json()
        self.assertIn("invariants", quality_body)
        self.assertIn("vision_edge_case_signals", quality_body)
        self.assertIn("anomaly_reason_counts", quality_body)
        self.assertTrue(quality_body["invariants"].get("purchasers_within_entries"))
        self.assertTrue(quality_body["invariants"].get("funnel_monotonic_non_increasing"))


if __name__ == "__main__":
    unittest.main()
