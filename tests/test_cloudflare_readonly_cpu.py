"""Offline safety/contract tests for the public-log-only MT-017 bridge."""
import io
import json
import os
import unittest
from unittest import mock
from datetime import datetime, timezone

from scripts import cloudflare_readonly_cpu as audit


class CloudflareCpuReadonlyTests(unittest.TestCase):
    def test_aggregates_cpu_microseconds_to_milliseconds(self):
        data = {
            "total": [{
                "sum": {"requests": 120, "errors": 3},
                "quantiles": {"cpuTimeP50": 2000, "cpuTimeP95": 9100, "cpuTimeP99": 12000},
            }],
            "exceeded": [{"sum": {"requests": 2}}],
        }
        result = audit.summarize_worker("pocket-analytics-staging", data)
        self.assertEqual(result["requests"], 120)
        self.assertEqual(result["errors"], 3)
        self.assertEqual(result["exceeded_cpu"], 2)
        self.assertEqual(result["cpu_ms_p95"], 9.1)
        self.assertEqual(result["cpu_ms_p99"], 12.0)
        self.assertNotIn("accountTag", result)
        self.assertNotIn("Authorization", result)

    def test_no_rows_are_unknown_not_zero(self):
        self.assertEqual(
            audit.summarize_worker("kalshi-pocket-analytics", {"total": [], "exceeded": []}),
            {"worker": "kalshi-pocket-analytics", "state": "no_analytics_rows"},
        )

    def test_missing_exceeded_dataset_fails_closed(self):
        with self.assertRaises(audit.AnalyticsUnavailable):
            audit.summarize_worker("x", {
                "total": [{"sum": {"requests": 5, "errors": 1}, "quantiles": {}}],
            })

    def test_incident_and_recent_windows_are_utc(self):
        now = datetime(2026, 11, 22, 3, 0, tzinfo=timezone.utc)
        self.assertEqual(audit.select_window("nov_09_2026", now), (
            "2026-11-09T00:00:00Z", "2026-11-10T00:00:00Z",
        ))
        self.assertEqual(audit.select_window("last_24h", now), (
            "2026-11-21T02:58:00Z", "2026-11-22T02:58:00Z",
        ))

    def test_query_uses_only_read_analytics_endpoint(self):
        self.assertEqual(audit.GRAPHQL_URL, "https://api.cloudflare.com/client/v4/graphql")
        self.assertIn('status: "exceededCpu"', audit.GRAPHQL_QUERY)
        self.assertNotIn("mutation", audit.GRAPHQL_QUERY.lower())

    def test_missing_credentials_does_not_access_network(self):
        with mock.patch.dict(os.environ, {
            "CLOUDFLARE_OBSERVABILITY_TOKEN": "",
            "CLOUDFLARE_ACCOUNT_ID": "",
        }):
            with mock.patch.object(audit.urllib.request, "urlopen") as urlopen:
                with mock.patch("sys.argv", ["cloudflare_readonly_cpu.py"]):
                    with mock.patch("sys.stderr", new_callable=io.StringIO) as output:
                        self.assertEqual(audit.main(), 2)
                urlopen.assert_not_called()
                self.assertNotIn("Bearer", output.getvalue())

    def test_auth_errors_do_not_dump_api_body_or_token(self):
        response = {"errors": [{"message": "private account and token details"}]}
        encoded = json.dumps(response).encode("utf-8")
        with mock.patch.object(audit.urllib.request, "urlopen") as opener:
            opener.return_value.__enter__.return_value = io.BytesIO(encoded)
            with self.assertRaisesRegex(audit.AnalyticsUnavailable, "verify Account Analytics Read"):
                audit.read_analytics("secret-account", "secret-token", "a-worker",
                                     "2026-11-09T00:00:00Z", "2026-11-10T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
