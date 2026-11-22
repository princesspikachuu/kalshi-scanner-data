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
        self.assertIn("$datetimeStart: Time!", audit.GRAPHQL_QUERY)
        self.assertIn("$datetimeEnd: Time!", audit.GRAPHQL_QUERY)
        self.assertIn("$datetimeStart: Time!", audit.GRAPHQL_QUERY_MINIMAL)
        self.assertIn("$datetimeStart: string!", audit.GRAPHQL_QUERY_MINIMAL_STRING)
        self.assertNotIn("mutation", audit.GRAPHQL_QUERY.lower())
        self.assertNotIn("mutation", audit.GRAPHQL_QUERY_MINIMAL.lower())

    def test_http_400_retries_minimal_query_and_marks_unknown_cpu_error_count(self):
        sample = {
            "total": [{"sum": {"requests": 30, "errors": 2},
                       "quantiles": {"cpuTimeP50": 1500, "cpuTimeP99": 9900}}],
        }
        with mock.patch.object(audit, "_read_analytics_query",
                               side_effect=[audit.AnalyticsUnavailable(
                                   "Cloudflare GraphQL HTTP 400 (query validation)"
                               ), sample]) as request:
            result = audit.read_analytics("private-account", "private-token", "worker",
                                          "2026-11-21T00:00:00Z", "2026-11-22T00:00:00Z")
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[0].args[-1], audit.GRAPHQL_QUERY)
        self.assertEqual(request.call_args_list[1].args[-1], audit.GRAPHQL_QUERY_MINIMAL)
        item = audit.summarize_worker("worker", result)
        self.assertEqual(item["state"], "estimated_analytics_partial")
        self.assertIsNone(item["exceeded_cpu"])
        self.assertIsNone(item["cpu_ms_p95"])
        self.assertEqual(item["requests"], 30)
        self.assertEqual(item["cpu_ms_p99"], 9.9)

    def test_http_400_can_fallback_to_legacy_string_scalar(self):
        sample = {
            "total": [{"sum": {"requests": 1, "errors": 0},
                       "quantiles": {"cpuTimeP50": 1200, "cpuTimeP99": 1200}}],
        }
        with mock.patch.object(audit, "_read_analytics_query",
                               side_effect=[audit.AnalyticsUnavailable(
                                   "Cloudflare GraphQL HTTP 400 (query validation)"
                               ), audit.AnalyticsUnavailable(
                                   "Cloudflare GraphQL HTTP 400 (query validation)"
                               ), sample]) as request:
            result = audit.read_analytics("a", "b", "worker", "start", "end")
        self.assertEqual(request.call_count, 3)
        self.assertEqual(request.call_args_list[-1].args[-1], audit.GRAPHQL_QUERY_MINIMAL_STRING)
        self.assertIsNone(audit.summarize_worker("worker", result)["exceeded_cpu"])

    def test_no_retry_on_auth_error(self):
        with mock.patch.object(audit, "_read_analytics_query",
                               side_effect=audit.AnalyticsUnavailable(
                                   "Cloudflare Analytics returned HTTP 403")) as request:
            with self.assertRaisesRegex(audit.AnalyticsUnavailable, "HTTP 403"):
                audit.read_analytics("a", "b", "worker", "start", "end")
        self.assertEqual(request.call_count, 1)

    def test_http_400_body_and_token_not_in_error(self):
        import urllib.error
        from io import BytesIO
        secret = "secret-token-please-do-not-log"
        response = BytesIO(b'{"errors":[{"message":"secret-token-please-do-not-log"}]}')
        def throw_bad_query(_request, timeout):
            raise urllib.error.HTTPError(audit.GRAPHQL_URL, 400, "bad query",
                                         hdrs={}, fp=response)
        with mock.patch.object(audit.urllib.request, "urlopen", side_effect=throw_bad_query):
            with self.assertRaisesRegex(audit.AnalyticsUnavailable, "HTTP 400") as raised:
                audit._read_analytics_query("private-account", secret, "worker",
                                            "start", "end", audit.GRAPHQL_QUERY)
        self.assertNotIn(secret, str(raised.exception))
        self.assertNotIn("private-account", str(raised.exception))

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
