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
        self.assertIn("$datetimeStart: string", audit.GRAPHQL_QUERY_MINIMAL_STRING)
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

    def test_safe_preflight_checks_three_read_only_boundaries(self):
        valid = "a" * 32
        sequence = [
            {"data": {"viewer": {"__typename": "Viewer"}}},
            {"data": {"viewer": {"accounts": [{"__typename": "Account"}]}}},
            {"data": {"viewer": {"accounts": [{"total": []}]}}},
        ]
        with mock.patch.object(audit, "_post_graphql", side_effect=sequence) as client:
            result = audit.safe_preflight(valid, "secret-do-not-log", "some-worker",
                                          "2026-11-21T00:00:00Z", "2026-11-22T00:00:00Z")
        self.assertEqual(result, {"stage": "dataset", "result": "valid"})
        self.assertEqual(client.call_count, 3)
        self.assertEqual(client.call_args_list[0].args[1], audit.GRAPHQL_PREFLIGHT_VIEWER)
        self.assertEqual(client.call_args_list[1].args[1], audit.GRAPHQL_PREFLIGHT_ACCOUNT)
        self.assertEqual(client.call_args_list[2].args[1], audit.GRAPHQL_QUERY_MINIMAL_STRING)

    def test_preflight_invalid_account_id_does_not_call_provider(self):
        with mock.patch.object(audit, "_post_graphql") as client:
            result = audit.safe_preflight("private-account-string", "very-secret-token",
                                          "worker", "start", "end")
        self.assertEqual(result, {
            "stage": "account_id", "result": "not_32_hex_characters",
        })
        client.assert_not_called()
        self.assertNotIn("private-account", str(result))

    def test_preflight_blocks_on_missing_account_permission_without_leaking_details(self):
        account = "b" * 32
        response = {"data": {"viewer": {"__typename": "Viewer"}}}
        with mock.patch.object(audit, "_post_graphql", side_effect=[
            response,
            audit.AnalyticsUnavailable(
                "Cloudflare GraphQL HTTP 403 (account_access_denied)"
            ),
        ]) as client:
            result = audit.safe_preflight(account, "private-token", "worker",
                                          "start", "end")
        self.assertEqual(result["stage"], "account")
        self.assertEqual(result["result"], "failed")
        self.assertEqual(client.call_count, 2)
        self.assertNotIn(account, str(result))
        self.assertNotIn("private-token", str(result))

    def test_provider_400_body_is_classified_without_printing_private_details(self):
        import urllib.error
        from io import BytesIO

        body = json.dumps({"errors": [
            {"message": 'unknown field "private-user-ABC" on dataset'},
            {"message": "Account private-account-ID was invalid"},
        ]}).encode("utf-8")
        def failing_request(_request, timeout):
            raise urllib.error.HTTPError(audit.GRAPHQL_URL, 400, "bad query",
                                         hdrs={}, fp=BytesIO(body))
        with mock.patch.object(audit.urllib.request, "urlopen",
                               side_effect=failing_request):
            with self.assertRaises(audit.AnalyticsUnavailable) as outcome:
                audit._post_graphql("private-token", audit.GRAPHQL_QUERY_MINIMAL_STRING, {})
        self.assertEqual(str(outcome.exception),
                         "Cloudflare GraphQL HTTP 400 (unsupported_field)")
        self.assertNotIn("private-account", str(outcome.exception))
        self.assertNotIn("private-user", str(outcome.exception))
        self.assertNotIn("private-token", str(outcome.exception))

    def test_provider_400_time_window_category_is_constant(self):
        self.assertEqual(audit._error_category([{
            "message": "cannot request data older than 86400s on ACCOUNT_SECRET"
        }]), "window_not_supported")
        self.assertEqual(audit._error_category([{
            "message": "Unknown type Time on ACCOUNT_SECRET"
        }]), "schema_or_variable_type")
        self.assertEqual(audit._error_category([{
            "message": "some unrecognized sensitive issue on TOKEN_SECRET"
        }]), "unclassified")

    def test_preflight_graphql_no_account_is_not_success(self):
        with mock.patch.object(audit, "_post_graphql", side_effect=[
            {"data": {"viewer": {"__typename": "Viewer"}}},
            {"data": {"viewer": {"accounts": []}}},
        ]):
            result = audit.safe_preflight("f" * 32, "private-token", "worker",
                                          "start", "end")
        self.assertEqual(result, {"stage": "account", "result": "account_not_readable"})

    def test_documented_budget_viewer_and_single_line_payload(self):
        self.assertIn("viewer { budget }", audit.GRAPHQL_PREFLIGHT_VIEWER)
        self.assertNotIn("__typename", audit.GRAPHQL_PREFLIGHT_VIEWER)
        response = {"data": {"viewer": {"budget": 100}}}
        with mock.patch.object(audit.urllib.request, "urlopen") as opener:
            opener.return_value.__enter__.return_value = io.BytesIO(
                json.dumps(response).encode("utf-8"))
            out = audit._post_graphql("private-token", audit.GRAPHQL_QUERY_MINIMAL, {})
        self.assertEqual(out, response)
        request = opener.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertNotIn("\n", payload["query"])
        self.assertIn("query WorkerCpuAuditBasic", payload["query"])

    def test_safe_verify_user_token_returns_only_status(self):
        account = "b" * 32
        response = {"success": True, "result": {
            "status": "active", "id": "sensitive-token-id",
            "expires_on": "2030-01-01T00:00:00Z",
        }}
        with mock.patch.object(audit.urllib.request, "urlopen") as opener:
            opener.return_value.__enter__.return_value = io.BytesIO(
                json.dumps(response).encode("utf-8"))
            out = audit.safe_verify_token(account, "private-token")
        self.assertEqual(out, {"status": "active", "token_kind": "user"})
        self.assertEqual(opener.call_count, 1)
        self.assertEqual(opener.call_args.args[0].get_method(), "GET")
        self.assertNotIn("sensitive-token-id", str(out))
        self.assertNotIn(account, str(out))

    def test_safe_verify_can_fall_back_to_account_token(self):
        import urllib.error
        account = "f" * 32
        response = {"success": True, "result": {"status": "active",
                                                 "id": "PRIVATE-ID"}}
        def side_effect(req, timeout):
            if req.full_url.endswith("/user/tokens/verify"):
                raise urllib.error.HTTPError(req.full_url, 403, "PRIVATE ERROR",
                                             hdrs={}, fp=io.BytesIO(b"PRIVATE DATA"))
            return io.BytesIO(json.dumps(response).encode("utf-8"))
        with mock.patch.object(audit.urllib.request, "urlopen",
                               side_effect=side_effect) as opener:
            out = audit.safe_verify_token(account, "PRIVATE TOKEN")
        self.assertEqual(out, {"status": "active", "token_kind": "account"})
        self.assertEqual(opener.call_count, 2)
        self.assertNotIn("PRIVATE", str(out))
        self.assertNotIn(account, str(out))

    def test_safe_verify_fails_closed_without_network_for_invalid_id(self):
        with mock.patch.object(audit.urllib.request, "urlopen") as opener:
            out = audit.safe_verify_token("not-an-account-id", "private-token")
        self.assertEqual(out, {"status": "invalid_account_id_shape"})
        opener.assert_not_called()

    def test_error_categories_include_cloudflare_documented_parse_and_auth(self):
        self.assertEqual(audit._error_category([{
            "message": "query contains error, please review it and retry"
        }]), "query_parse_failure")
        self.assertEqual(audit._error_category([{
            "message": "Authentication error: PRIVATE-ACCOUNT-ID"
        }]), "token_authentication_error")
        self.assertEqual(audit._error_category([{
            "message": "not authorized for PRIVATE-ACCOUNT-ID"
        }]), "account_access_denied")
        self.assertEqual(audit._error_category([{
            "message": "unrecognized PRIVATE TOKEN ERROR"
        }]), "unclassified")

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
            with self.assertRaisesRegex(audit.AnalyticsUnavailable, "response error"):
                audit.read_analytics("secret-account", "secret-token", "a-worker",
                                     "2026-11-09T00:00:00Z", "2026-11-10T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
