"""Bounded public market inventory reads. No account credentials or trade routes."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import re
import time

import httpx

from .inventory import ProviderFailure, ProviderPage, Scope, valid_cursor

BASE = 'https://external-api.kalshi.com/trade-api/v2'
MAX_RESPONSE = 8 * 1024 * 1024


def retry_after(value, now):
    """Shared cooldown: bounded 1..2**40 seconds, 30-second fallback."""
    if not isinstance(value, str) or len(value) > 128:
        return 30
    value = value.strip()
    try:
        if value.isascii() and value.isdigit():
            delay = int(value)
        else:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None: return 30
            delay = math.ceil(stamp.timestamp() - now)
        return max(1, min(2**40, delay))
    except (ValueError, OverflowError, TypeError):
        return 30


def invalid():
    return ProviderFailure('provider_invalid', retry=False)


def pairs(items):
    result = {}
    for key, value in items:
        key.encode('utf-8')
        if key in result: raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def constant(_): raise ValueError('Nonfinite JSON number')


def parse_json(body):
    """Fail the whole page on malformed evidence; never drop rows silently."""
    try:
        value = json.loads(body.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
        stack = [(value, 0)]
        while stack:
            item, depth = stack.pop()
            if depth > 64 or (isinstance(item, float) and not math.isfinite(item)):
                raise ValueError('Invalid JSON value')
            if isinstance(item, dict): stack.extend((v, depth+1) for v in item.values())
            elif isinstance(item, list): stack.extend((v, depth+1) for v in item)
            elif isinstance(item, str): item.encode('utf-8')  # reject unpaired surrogates
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise invalid() from None


def parse_inventory(body):
    try:
        value = parse_json(body)
        if not isinstance(value, dict) or not isinstance(value.get('markets'), list) or 'cursor' not in value:
            raise ValueError('Invalid market page')
        valid_cursor('' if value['cursor'] is None else value['cursor'])
        if len(value['markets']) > 1000: raise ValueError('Too many markets')
        for market in value['markets']:
            if not isinstance(market, dict): raise ValueError('Invalid market')
            for field in ('ticker', 'event_ticker'):
                text = market.get(field)
                if not isinstance(text, str) or not 1 <= len(text) <= 256 or any(ord(c) < 32 for c in text):
                    raise ValueError('Invalid market identity')
            closed = market.get('close_time')
            if not isinstance(closed, str): raise ValueError('Invalid close time')
            stamp = datetime.fromisoformat(closed.replace('Z', '+00:00'))
            if stamp.tzinfo is None: raise ValueError('Missing close timezone')
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise invalid() from None


class KalshiInventory:
    """Owned HTTPX client with no ambient credentials/proxies/cookies or redirects.

    Optional transport injection is for deterministic tests. Production transport
    has zero internal retries. A runner, scheduler and hosted connections are not
    created by this class. Use a context manager or close it explicitly.
    """
    def __init__(self, *, transport=None, clock=time.monotonic, wall_clock=time.time):
        self.clock, self.wall_clock = clock, wall_clock
        limits = httpx.Limits(max_connections=8, max_keepalive_connections=4)
        self.client = httpx.Client(
            transport=transport if transport is not None else httpx.HTTPTransport(retries=0, trust_env=False, limits=limits),
            trust_env=False, follow_redirects=False, timeout=10,
            limits=limits)

    def close(self): self.client.close()
    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    def fetch(self, scope, cursor, timeout_seconds):
        if type(scope) is not Scope:
            raise ValueError('Expected validated inventory scope')
        path, args = scope.request(cursor)
        return self._read(path, args, timeout_seconds, parse_inventory)

    def _read(self, path, args, timeout_seconds, parser, *, allow_missing=False):
        allowed = (path in ('/markets','/historical/markets','/markets/trades','/historical/trades','/markets/candlesticks')
            or re.fullmatch(r'/historical/markets/[A-Za-z0-9_.-]{1,256}/candlesticks',path)
            or re.fullmatch(r'/series/[A-Z0-9_-]{1,64}/markets/[A-Za-z0-9_.-]{1,256}/candlesticks',path))
        if not allowed: raise ValueError('Unsupported public read route')
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 10):
            raise ValueError('Invalid provider request timeout')
        deadline = self.clock()+timeout_seconds
        # Build a Request directly: Client.build_request would merge its cookie
        # jar into later requests. No authorization, cookies or caller URLs here.
        request = httpx.Request('GET', BASE+path, params=args,
            headers={'Accept': 'application/json', 'Accept-Encoding': 'identity',
                     'User-Agent': 'PocketAnalyticsResearch/2'},
            extensions={'timeout': httpx.Timeout(timeout_seconds).as_dict()})
        response = None
        try:
            response = self.client.send(request, stream=True, follow_redirects=False)
            if self.clock() >= deadline: raise ProviderFailure('provider_timeout')
            if response.status_code == 429:
                cooldown = retry_after(response.headers.get('retry-after'), self.wall_clock())
                raise ProviderFailure('provider_rate_limit', delay=min(3600,cooldown), cooldown=cooldown)
            if response.status_code in (408, 500, 502, 503, 504):
                cooldown = retry_after(response.headers.get('retry-after'), self.wall_clock())
                # Honor server-requested service backoff across workers as well.
                raise ProviderFailure('provider_unavailable', delay=min(3600,cooldown), cooldown=cooldown)
            if response.status_code == 404 and allow_missing:
                return ProviderPage({'http_status':404}, 'unavailable')
            if response.status_code != 200:
                # A listing 404 is not proof of an unavailable/empty series.
                # Redirects/auth failures and unsupported statuses are terminal.
                raise invalid()
            if response.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
                raise invalid()
            if response.headers.get('content-encoding', 'identity').strip().lower() != 'identity':
                raise invalid()  # no automatic decompression of an untrusted body
            raw_length = response.headers.get('content-length')
            length = None
            if raw_length is not None:
                if not raw_length.isascii() or not raw_length.isdigit() or len(raw_length) > 12:
                    raise invalid()
                length = int(raw_length)
                if length > MAX_RESPONSE: raise invalid()
            body = bytearray()
            # Do not request a large coalesced chunk: check elapsed time on each
            # raw transport chunk, including slowly arriving partial responses.
            for chunk in response.iter_raw():
                if self.clock() >= deadline: raise ProviderFailure('provider_timeout')
                if len(body)+len(chunk) > MAX_RESPONSE: raise invalid()
                body.extend(chunk)
            if length is not None and len(body) != length: raise invalid()
            if self.clock() >= deadline: raise ProviderFailure('provider_timeout')
            payload = parser(bytes(body))
            if self.clock() >= deadline: raise ProviderFailure('provider_timeout')
            return ProviderPage(payload)
        except httpx.TimeoutException:
            raise ProviderFailure('provider_timeout') from None
        except httpx.HTTPError:
            raise ProviderFailure('provider_unavailable') from None
        finally:
            if response is not None: response.close()
