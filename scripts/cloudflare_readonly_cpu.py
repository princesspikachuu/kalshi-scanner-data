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
GRAPHQL_QUERY_MINIMAL_STRING = GRAPHQL_QUERY_MINIMAL.replace("Time!", "string!")


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


def _read_analytics_query(account: str, token: str, worker: str,
                          start: str, end: str, query: str) -> dict:
    """Read one aggregate GraphQL query; never expose provider response text."""
    payload = {
        "query": query,
        "variables": {
            "accountTag": account,
            "datetimeStart": start,
            "datetimeEnd": end,
            "scriptName": worker,
        },
    }
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=json.dumps(payload).encode("utf-8"),
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
        # Do not print body, URL, request headers, account ID or provider
        # exception. HTTP 400 may mean an invalid GraphQL schema selection.
        if exc.code == 400:
            raise AnalyticsUnavailable("Cloudflare GraphQL HTTP 400 (query validation)") from None
        raise AnalyticsUnavailable("Cloudflare Analytics returned HTTP " + str(exc.code)) from None
    except (urllib.error.URLError, TimeoutError):
        raise AnalyticsUnavailable("Cloudflare Analytics network request unavailable") from None
    except (ValueError, UnicodeDecodeError):
        raise AnalyticsUnavailable("Cloudflare Analytics returned invalid JSON") from None

    if not isinstance(result, dict) or result.get("errors"):
        # Same constant regardless of the error body. Logs are PUBLIC.
        raise AnalyticsUnavailable(
            "Cloudflare GraphQL query failed; verify Account Analytics Read permission and dataset access"
        )
    accounts = ((result.get("data") or {}).get("viewer") or {}).get("accounts")
    if not isinstance(accounts, list) or len(accounts) != 1:
        raise AnalyticsUnavailable("No readable Cloudflare analytics account returned")
    return accounts[0]


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

    start, end = select_window(args.period, datetime.now(timezone.utc))
    try:
        results = [
            summarize_worker(worker, read_analytics(account, token, worker, start, end))
            for worker in DEFAULT_WORKERS
        ]
    except AnalyticsUnavailable as exc:
        print("Cloudflare audit unavailable: " + str(exc), file=sys.stderr)
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
