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
  $accountTag: string,
  $datetimeStart: string,
  $datetimeEnd: string,
  $scriptName: string
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


def read_analytics(account: str, token: str, worker: str, start: str, end: str) -> dict:
    payload = {
        "query": GRAPHQL_QUERY,
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
        # Do not print response body, URI, token, or raw provider exception.
        raise AnalyticsUnavailable("Cloudflare Analytics returned HTTP " + str(exc.code)) from None
    except (urllib.error.URLError, TimeoutError):
        raise AnalyticsUnavailable("Cloudflare Analytics network request unavailable") from None
    except (ValueError, UnicodeDecodeError):
        raise AnalyticsUnavailable("Cloudflare Analytics returned invalid JSON") from None

    if not isinstance(result, dict) or result.get("errors"):
        raise AnalyticsUnavailable(
            "Cloudflare GraphQL query failed; verify Account Analytics Read permission and dataset access"
        )
    accounts = ((result.get("data") or {}).get("viewer") or {}).get("accounts")
    if not isinstance(accounts, list) or len(accounts) != 1:
        raise AnalyticsUnavailable("No readable Cloudflare analytics account returned")
    return accounts[0]


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
    if not isinstance(exceeded, list):
        raise AnalyticsUnavailable("Missing Cloudflare exceededCpu result")
    cpu_failures = (exceeded[0].get("sum") or {}).get("requests") if exceeded else 0
    if not isinstance(cpu_failures, (int, float)):
        raise AnalyticsUnavailable("Invalid exceededCpu counter")

    return {
        "worker": worker,
        "state": "estimated_analytics",
        "requests": int(requests),
        "errors": int(errors),
        "exceeded_cpu": int(cpu_failures),
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
