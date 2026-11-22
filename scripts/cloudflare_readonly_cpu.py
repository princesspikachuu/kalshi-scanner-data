#!/usr/bin/env python3
"""MT-017 read-only Cloudflare Workers CPU diagnostics.

Only queries the Cloudflare GraphQL Analytics API. Prints aggregate metrics
safe for GitHub Actions logs; never prints tokens, account IDs, raw Cloudflare
responses, request URLs, request headers, IPs, paths, or invocation traces.

IMPORTANT: This repository is PUBLIC. Even aggregate Actions output is public.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import re
import sys
import urllib.error
import urllib.request

GRAPHQL_URL = "https://api.cloudflare.com/client/v4/graphql"
DEFAULT_WORKERS = ("pocket-analytics-staging", "kalshi-pocket-analytics")

# Cloudflare's workersInvocationsAdaptive aggregate fields are documented at
# https://developers.cloudflare.com/analytics/graphql-api/tutorials/querying-workers-metrics/
# Both total and exceededCpu are aggregate queries; no event payload is fetched.
GRAPHQL_QUERY = """
query WorkerCpuAudit(
  $accountTag: string!,
  $datetimeStart: Time!,
  $datetimeEnd: Time!,
  $scriptName: string!
) {
  viewer {
    accounts(filter: { accountTag: $accountTag }) {
      total: workersInvocationsAdaptive(
        limit: 1,
        filter: {
          scriptName: $scriptName,
          datetime_geq: $datetimeStart,
          datetime_leq: $datetimeEnd
        }
      ) {
        sum { requests errors }
        quantiles { cpuTimeP50 cpuTimeP95 cpuTimeP99 }
      }
      exceeded: workersInvocationsAdaptive(
        limit: 1,
        filter: {
          scriptName: $scriptName,
          status: "exceededCpu",
          datetime_geq: $datetimeStart,
          datetime_leq: $datetimeEnd
        }
      ) {
        sum { requests }
      }
    }
  }
}
"""

# Cloudflare versions may not expose every optional field/filter. If the
# full read-only query gets a schema HTTP 400, try the smaller official
# Workers metrics shape, never turning an unknown exceededCpu count into zero.
GRAPHQL_QUERY_MINIMAL = """
query WorkerCpuAuditBasic(
  $accountTag: string!,
  $datetimeStart: Time!,
  $datetimeEnd: Time!,
  $scriptName: string!
) {
  viewer {
    accounts(filter: { accountTag: $accountTag }) {
      total: workersInvocationsAdaptive(
        limit: 1,
        filter: {
          scriptName: $scriptName,
          datetime_geq: $datetimeStart,
          datetime_leq: $datetimeEnd
        }
      ) {
        sum { requests errors }
        quantiles { cpuTimeP50 cpuTimeP99 }
      }
    }
  }
}
"""

# An older public Cloudflare tutorial declares time variables with the
# provider-specific "string" scalar; newer examples use Time. This is the
# last compatibility probe if the strict Time query fails validation.
GRAPHQL_QUERY_MINIMAL_STRING = (GRAPHQL_QUERY_MINIMAL
    .replace("Time!", "string")
    .replace("string!", "string"))

# Zero-data, no-PII read-only probes. The first checks the token endpoint, the
# second checks that this token may see this account, and the third checks the
# Workers aggregate dataset. Only fixed result labels are ever printed.
GRAPHQL_PREFLIGHT_VIEWER = "query MT017Viewer { viewer { budget } }"
GRAPHQL_PREFLIGHT_ACCOUNT = """
query MT017Account($accountTag: string) {
  viewer {
    accounts(filter: { accountTag: $accountTag }) { __typename }
  }
}
"""



class AnalyticsUnavailable(RuntimeError):
    """Signals missing/invalid data without exposing private API details."""


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def select_window(period: str, now: datetime) -> tuple[str, str]:
    if period == "nov_09_2026":
        return "2026-11-09T00:00:00Z", "2026-11-10T00:00:00Z"
    if period != "last_24h":
        raise ValueError("Unsupported audit window")
    # Leave a two-minute buffer for provider aggregation lag.
    end = now.astimezone(timezone.utc) - timedelta(minutes=2)
    start = end - timedelta(hours=24)
    return format_utc(start), format_utc(end)


def _error_category(errors: object) -> str:
    """Classify provider errors against a CLOSED vocabulary for public logs.

    Never echo raw error messages, paths, extension values, or account fields.
    """
    if not isinstance(errors, list):
        return "unknown"
    words = " ".join(
        str(item.get("message", "")).lower()[:2000]
        for item in errors if isinstance(item, dict)
    )
    if any(term in words for term in (
        "cannot request data older than", "query time range is too large",
        "time range exceeds", "maximum time range",
    )):
        return "window_not_supported"
    if any(term in words for term in ("unknown field", "cannot query field", "unknown argument")):
        return "unsupported_field"
    if any(term in words for term in ("unknown type", "expected type", "variable", "validation")):
        return "schema_or_variable_type"
    if any(term in words for term in (
        "error parsing args", "syntax", "query contains error",
        "query contains errors", "invalid graphql query",
        "scalar fields must have no selections",
        "object field must have selections", "failed to parse query",
    )):
        return "query_parse_failure"
    if any(term in words for term in (
        "authentication error", "invalid api token", "invalid token",
        "token revoked", "token expired", "invalid credentials",
        "missing authentication",
    )):
        return "token_authentication_error"
    if any(term in words for term in (
        "permission denied", "permission missing",
        "token does not have access", "not authorized for",
    )):
        return "account_access_denied"
    if any(term in words for term in ("not authorized", "unauthorized", "not permitted", "access denied")):
        return "account_access_denied"
    if any(term in words for term in ("rate limit", "budget depleted")):
        return "rate_limited"
    if "dataset" in words and any(x in words for x in ("not found", "not allowed", "unavailable")):
        return "dataset_unavailable"
    return "unclassified"


def _provider_error_category(response: object) -> str:
    """Classify REST/GraphQL errors using only fixed labels (never error text).

    Cloudflare can return HTTP 400 for invalid Authorization headers, not just
    bad GraphQL syntax. Inspect known nested numeric codes without logging raw
    response bodies, identifiers, token material, or new arbitrary codes.
    """
    if not isinstance(response, dict):
        return "unclassified"
    errors = response.get("errors")
    if not isinstance(errors, list):
        return "unclassified"
    codes: set[int] = set()
    for error in errors[:8]:
        if not isinstance(error, dict):
            continue
        items = [error]
        chain = error.get("error_chain")
        if isinstance(chain, list):
            items.extend(item for item in chain[:8] if isinstance(item, dict))
        for item in items:
            code = item.get("code")
            if type(code) is int:
                codes.add(code)
    if codes.intersection({6003, 6102, 6103, 6111}):
        return "malformed_auth_header"
    if codes.intersection({9106, 10000, 10001}):
        return "token_rejected"
    return _error_category(errors)


def _safe_token_input_issue(token: str) -> str | None:
    """Recognize clear copy/paste mistakes, emitting labels only.

    Never require a fixed token length: Cloudflare supports older unprefixed
    API tokens as well as newer scannable cfut_/cfat_ tokens.
    """
    if token != token.strip():
        return "outer_whitespace"
    if len(token) >= 2 and token[0] in ("'", '"') and token[-1] == token[0]:
        return "quoted_token"
    if token.lower().startswith((
        "bearer ", "authorization:", "token=", "cf_api_token=",
        "cloudflare_api_token=", "cloudflare_observability_token=",
    )):
        return "copied_header_or_assignment"
    if token.lower().startswith("cfk_"):
        return "global_api_key_not_api_token"
    if token[:1] in ("{", "[", "<"):
        return "copied_non_token_content"
    if re.fullmatch(r"[A-Fa-f0-9]{32}", token):
        return "identifier_instead_of_token"
    if any(ord(ch) <= 32 or ord(ch) == 127 for ch in token):
        return "embedded_whitespace_or_control"
    return None


def _post_graphql(token: str, query: str, variables: dict) -> dict:
    """POST only to the fixed read-only GraphQL endpoint; sanitize all errors."""
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=json.dumps({"query": " ".join(query.split()), "variables": variables}).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        # A GitHub Actions runner in this PUBLIC repo may receive messages
        # including private IDs. Read for classification, never echo content.
        try:
            response = json.loads(exc.read(16384))
            if isinstance(response, dict):
                category = _provider_error_category(response)
                if category == "unclassified":
                    provider_errors = response.get("errors")
                    if not isinstance(provider_errors, list):
                        brief = response.get("message") or response.get("error")
                        category = _error_category(
                            [{"message": brief}] if isinstance(brief, str) else []
                        )
            else:
                category = "unexpected_json_shape"
        except (ValueError, UnicodeDecodeError, OSError):
            category = "non_json_or_unreadable"
        # Even provider error objects and HTTP reason phrases remain private.
        code = exc.code if exc.code in (400, 401, 403, 429, 500, 503) else 0
        raise AnalyticsUnavailable("Cloudflare GraphQL HTTP " + str(code)
                                   + " (" + category + ")") from None
    except (urllib.error.URLError, TimeoutError):
        raise AnalyticsUnavailable("Cloudflare Analytics network request unavailable") from None
    except (ValueError, UnicodeDecodeError):
        raise AnalyticsUnavailable("Cloudflare Analytics returned invalid JSON") from None

    if not isinstance(result, dict):
        raise AnalyticsUnavailable("Cloudflare GraphQL invalid response")
    if result.get("errors"):
        raise AnalyticsUnavailable("Cloudflare GraphQL response error ("
                                   + _error_category(result.get("errors")) + ")")
    return result


def _read_analytics_query(account: str, token: str, worker: str,
                          start: str, end: str, query: str) -> dict:
    result = _post_graphql(token, query, {
        "accountTag": account,
        "datetimeStart": start,
        "datetimeEnd": end,
        "scriptName": worker,
    })
    accounts = ((result.get("data") or {}).get("viewer") or {}).get("accounts")
    if not isinstance(accounts, list) or len(accounts) != 1:
        raise AnalyticsUnavailable("No readable Cloudflare analytics account returned")
    return accounts[0]


def safe_verify_token(account: str, token: str) -> dict:
    """Check Cloudflare's documented user/account read-only token endpoints.

    Return fixed status and optional HTTP code only; never token ID, account
    ID, expiry, raw response, headers, or request URL to PUBLIC logs.
    """
    if re.fullmatch(r"[0-9a-fA-F]{32}", account) is None:
        return {"status": "invalid_account_id_shape"}
    paths = (
        ("user", "https://api.cloudflare.com/client/v4/user/tokens/verify"),
        ("account", "https://api.cloudflare.com/client/v4/accounts/"
         + account + "/tokens/verify"),
    )
    for kind, url in paths:
        request = urllib.request.Request(
            url, method="GET", headers={
                "Authorization": "Bearer " + token, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                obj = json.load(response)
        except urllib.error.HTTPError as exc:
            # Only fixed error classes, never the raw response, reach logs.
            try:
                category = _provider_error_category(json.loads(exc.read(16384)))
            except (ValueError, UnicodeDecodeError, OSError):
                category = "unclassified"
            # The user endpoint may reject account-owned API tokens.
            if kind == "user" and exc.code in (400, 401, 403, 404):
                continue
            return {"status": "http_error",
                    "code": exc.code if exc.code in (400, 401, 403, 404, 429) else 0,
                    "category": category}
        except (urllib.error.URLError, TimeoutError, ValueError, UnicodeDecodeError):
            return {"status": "unavailable"}
        if not isinstance(obj, dict):
            return {"status": "unexpected_response"}
        result = obj.get("result")
        status = result.get("status") if isinstance(result, dict) else None
        if obj.get("success") is True and status in ("active", "disabled", "expired"):
            return {"status": status, "token_kind": kind}
        if kind == "user":
            continue
        return {"status": "not_verified"}
    return {"status": "not_verified"}


def safe_preflight(account: str, token: str, worker: str, start: str, end: str) -> dict:
    """Read-only connection checks. Returned values use fixed safe labels."""
    if re.fullmatch(r"[0-9a-fA-F]{32}", account) is None:
        return {"stage": "account_id", "result": "not_32_hex_characters"}

    probes = (
        ("viewer", GRAPHQL_PREFLIGHT_VIEWER, {}),
        ("account", GRAPHQL_PREFLIGHT_ACCOUNT, {"accountTag": account}),
        ("dataset", GRAPHQL_QUERY_MINIMAL_STRING, {
            "accountTag": account, "datetimeStart": start,
            "datetimeEnd": end, "scriptName": worker,
        }),
    )
    for stage, query, vars_ in probes:
        try:
            response = _post_graphql(token, query, vars_)
        except AnalyticsUnavailable as exc:
            # _post_graphql errors are sanitized before reaching this handler.
            return {"stage": stage, "result": "failed",
                    "category": str(exc)}
        if stage == "viewer" and not isinstance((response.get("data") or {}).get("viewer"), dict):
            return {"stage": stage, "result": "no_viewer"}
        if stage in ("account", "dataset"):
            accounts = ((response.get("data") or {}).get("viewer") or {}).get("accounts")
            if not isinstance(accounts, list) or len(accounts) != 1:
                return {"stage": stage, "result": "account_not_readable"}
    return {"stage": "dataset", "result": "valid"}



def read_analytics(account: str, token: str, worker: str, start: str, end: str) -> dict:
    """Prefer the complete query, then documented read-only compat shapes."""
    options = (GRAPHQL_QUERY, GRAPHQL_QUERY_MINIMAL, GRAPHQL_QUERY_MINIMAL_STRING)
    for idx, query in enumerate(options):
        try:
            result = _read_analytics_query(account, token, worker, start, end, query)
        except AnalyticsUnavailable as exc:
            if "HTTP 400" in str(exc) and idx < len(options) - 1:
                continue
            raise
        if idx:
            # Explicitly distinguish unsupported breakdown from zero errors.
            result = dict(result)
            result["exceeded"] = None
            result["_partial_analytics"] = True
        return result
    raise AnalyticsUnavailable("Cloudflare GraphQL schema not supported")

def optional_ms(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnalyticsUnavailable("Cloudflare CPU percentile had invalid type")
    return round(float(value) / 1000, 3)


def summarize_worker(worker: str, account: dict) -> dict:
    total = account.get("total")
    if not isinstance(total, list):
        raise AnalyticsUnavailable("Missing Cloudflare total invocation data")
    if not total:
        # No rows is not proof of zero requests, a healthy Worker, or no CPU errors.
        return {"worker": worker, "state": "no_analytics_rows"}
    source = total[0]
    sums = source.get("sum") or {}
    quantiles = source.get("quantiles") or {}
    requests, errors = sums.get("requests"), sums.get("errors")
    if not isinstance(requests, (int, float)) or not isinstance(errors, (int, float)):
        raise AnalyticsUnavailable("Incomplete invocation counters")

    exceeded = account.get("exceeded")
    if account.get("_partial_analytics"):
        cpu_failures = None
    elif not isinstance(exceeded, list):
        raise AnalyticsUnavailable("Missing Cloudflare exceededCpu result")
    else:
        cpu_failures = (exceeded[0].get("sum") or {}).get("requests") if exceeded else 0
        if isinstance(cpu_failures, bool) or not isinstance(cpu_failures, (int, float)):
            raise AnalyticsUnavailable("Invalid exceededCpu counter")

    return {
        "worker": worker,
        "state": "estimated_analytics_partial" if account.get("_partial_analytics") else "estimated_analytics",
        "requests": int(requests),
        "errors": int(errors),
        "exceeded_cpu": int(cpu_failures) if cpu_failures is not None else None,
        "cpu_ms_p50": optional_ms(quantiles.get("cpuTimeP50")),
        "cpu_ms_p95": optional_ms(quantiles.get("cpuTimeP95")),
        "cpu_ms_p99": optional_ms(quantiles.get("cpuTimeP99")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", choices=("last_24h", "nov_09_2026"), default="last_24h")
    args = parser.parse_args()

    token = os.getenv("CLOUDFLARE_OBSERVABILITY_TOKEN", "")
    account = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
    if not token or not account:
        print("Cloudflare read-only analytics secrets are not configured; no query performed.", file=sys.stderr)
        return 2
    input_issue = _safe_token_input_issue(token)
    if input_issue is not None:
        print("MT017_CREDENTIAL_PREFLIGHT " + json.dumps({"status": input_issue}),
              file=sys.stderr)
        return 2

    start, end = select_window(args.period, datetime.now(timezone.utc))
    try:
        results = [
            summarize_worker(worker, read_analytics(account, token, worker, start, end))
            for worker in DEFAULT_WORKERS
        ]
    except AnalyticsUnavailable as exc:
        print("Cloudflare audit unavailable: " + str(exc), file=sys.stderr)
        # A second blind retry is not useful. Identify the failure boundary
        # with fixed-label probes, NEVER printing provider error objects.
        verification = safe_verify_token(account, token)
        print("MT017_TOKEN_VERIFY " + json.dumps(verification, sort_keys=True),
              file=sys.stderr)
        if verification.get("status") in ("disabled", "expired",
                                          "invalid_account_id_shape"):
            return 1
        diagnostic = safe_preflight(account, token, DEFAULT_WORKERS[0], start, end)
        print("MT017_SAFE_PREFLIGHT " + json.dumps(diagnostic, sort_keys=True),
              file=sys.stderr)
        return 1

    print("MT017_CLOUDFLARE_CPU_SUMMARY " + json.dumps({
        "start_utc": start,
        "end_utc": end,
        "scope": "aggregate_statistics_only",
        "adaptive_sampling": "counts may be sampled estimates",
        "workers": results,
    }, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
