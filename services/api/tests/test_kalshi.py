"""Stub HTTP transport: no network, account credentials or trading."""
import json
import unittest
from unittest.mock import patch

import httpx

from services.research.inventory import Scope, ProviderFailure
from services.research.kalshi import KalshiInventory, MAX_RESPONSE, retry_after

RECENT = Scope('KXBTC15M', 'recent', '2026-10-25', 'transport-test')
HISTORICAL = Scope('KXBTC15M', 'historical', None, 'transport-test')
MARKET = {'ticker': 'KXBTC15M-TEST', 'event_ticker': 'KXBTC15M-EVENT',
          'close_time': '2026-10-25T12:00:00Z', 'yes_bid_dollars': '0.8800',
          'result': 'yes', 'future_field': {'preserve': True}}
PAYLOAD = {'markets': [MARKET], 'cursor': 'opaque+/=&token'}


class Chunks(httpx.SyncByteStream):
    def __init__(self, chunks, callback=lambda: None):
        self.chunks, self.callback, self.closed, self.reads = chunks, callback, False, 0
    def __iter__(self):
        for chunk in self.chunks:
            self.reads += 1
            self.callback()
            if isinstance(chunk, Exception): raise chunk
            yield chunk
    def close(self): self.closed = True


def reply(status=200, payload=PAYLOAD, raw=None, headers=None, stream=None):
    raw = json.dumps(payload).encode() if raw is None else raw
    return httpx.Response(status, headers={'Content-Type': 'application/json', **(headers or {})},
                          stream=stream if stream is not None else Chunks([raw]))


class KalshiTests(unittest.TestCase):
    def provider(self, handler, **kwargs):
        provider = KalshiInventory(transport=httpx.MockTransport(handler), **kwargs)
        self.addCleanup(provider.close)
        return provider

    def failure(self, provider, code='provider_invalid', retry=False):
        with self.assertRaises(ProviderFailure) as caught: provider.fetch(RECENT, '', 10)
        self.assertEqual((caught.exception.code, caught.exception.retry), (code, retry))
        return caught.exception

    def test_only_fixed_get_listing_routes_query_encoding_and_original_prices(self):
        calls = []
        provider = self.provider(lambda r: (calls.append(r) or reply()))
        self.assertEqual(provider.fetch(RECENT, 'opaque+/=&token', 4).payload, PAYLOAD)
        provider.fetch(HISTORICAL, '', 4)
        for r in calls:
            self.assertEqual(r.method, 'GET')
            self.assertEqual((r.url.scheme,r.url.host), ('https','external-api.kalshi.com'))
            self.assertEqual(r.headers['accept-encoding'], 'identity')
            self.assertFalse({'authorization','cookie','proxy-authorization'} & set(r.headers))
            self.assertEqual(r.extensions['timeout']['read'], 4)
        self.assertEqual(calls[0].url.path, '/trade-api/v2/markets')
        self.assertEqual(calls[0].url.params['cursor'], 'opaque+/=&token')
        self.assertIn('min_close_ts', calls[0].url.params)
        self.assertEqual(calls[1].url.path, '/trade-api/v2/historical/markets')
        self.assertNotIn('min_close_ts', calls[1].url.params)
        self.assertNotIn('status', calls[0].url.params)  # preserve inventory, filter later

    def test_jar_cookies_and_environment_credentials_are_not_sent(self):
        calls = []
        provider = self.provider(lambda r: (calls.append(r) or reply(headers={'set-cookie':'session=do-not-forward; Path=/'})))
        provider.client.cookies.set('existing', 'do-not-forward', domain='external-api.kalshi.com')
        with patch.dict('os.environ', {'HTTP_PROXY':'http://invalid.test:9', 'NETRC':'/no/such/netrc'}):
            provider.fetch(RECENT,'',10); provider.fetch(RECENT,'',10)
        self.assertEqual(len(calls),2)
        self.assertTrue(all('cookie' not in r.headers and 'authorization' not in r.headers for r in calls))
        self.assertFalse(provider.client.trust_env)

    def test_redirects_auth_errors_and_404_never_become_empty_or_followed(self):
        for status in (301,302,307,308,400,401,403,404,409,418):
            calls = []
            stream = Chunks([b'sensitive raw diagnostic'])
            provider = self.provider(lambda r: (calls.append(r) or reply(status, headers={'location':'https://other.test/private'},stream=stream)))
            self.failure(provider)
            self.assertEqual(len(calls), 1)
            self.assertEqual(stream.reads,0)
            self.assertTrue(stream.closed)

    def test_rate_limit_has_single_attempt_and_safe_retry_after(self):
        calls = []
        stream = Chunks([b'sensitive diagnostic'])
        p = self.provider(lambda r: (calls.append(r) or reply(429, headers={'retry-after':'17'},stream=stream)))
        error = self.failure(p,'provider_rate_limit',True)
        self.assertEqual(error.delay,17)
        self.assertNotIn('sensitive',str(error))
        self.assertEqual(len(calls),1)
        self.assertEqual(stream.reads,0)
        self.assertTrue(stream.closed)

    def test_rate_limit_without_server_retry_time_starts_at_one_second(self):
        for headers in ({},{'retry-after':'invalid'}):
            error=self.failure(self.provider(lambda _:reply(429,headers=headers)),'provider_rate_limit',True)
            self.assertEqual((error.delay,error.cooldown),(1,1))
        error=self.failure(self.provider(lambda _:reply(503)),'provider_unavailable',True)
        self.assertEqual(error.delay,30)

    def test_server_failures_retry_and_no_response_body_is_exposed(self):
        for status in (408,500,502,503,504):
            p = self.provider(lambda _: reply(status,headers={'retry-after':'23'}))
            self.assertEqual(self.failure(p,'provider_unavailable',True).delay,23)

    def test_retry_after_seconds_dates_and_bounds(self):
        now = 1793059200  # 2026-10-27 00:00:00 UTC
        cases = [('15',15),('0',1),('99999999',99999999),('Tue, 27 Oct 2026 00:01:00 GMT',60),
                 ('Mon, 26 Oct 2026 23:00:00 GMT',1),('bogus',30),('-1',30),('0.5',30),
                 (None,30),('x'*129,30)]
        for value, expected in cases: self.assertEqual(retry_after(value,now),expected)

    def test_timeout_and_network_errors_have_safe_codes_and_no_internal_retry(self):
        for kind, code in [(httpx.ReadTimeout,'provider_timeout'),(httpx.ConnectError,'provider_unavailable'),
                            (httpx.RemoteProtocolError,'provider_unavailable')]:
            calls = []
            def fail(r):
                calls.append(r)
                raise kind('private url/cursor diagnostic',request=r)
            self.failure(self.provider(fail),code,True)
            self.assertEqual(len(calls),1)

    def test_invalid_json_schema_duplicate_nonfinite_depth_and_surrogates_fail_whole_page(self):
        bad = [b'not json', b'\xff', b'[]', b'{"markets":[],"cursor":"","cursor":"next"}',
               b'{"markets":[],"cursor":"","bad":NaN}', b'{"markets":[],"cursor":"","bad":1e999}',
               b'{"markets":[],"cursor":"","bad":"\\ud800"}',
               json.dumps({'markets':[]}).encode(), json.dumps({'markets':{},'cursor':''}).encode(),
               json.dumps({'markets':[],'cursor':False}).encode(),
               json.dumps({'markets':[{}],'cursor':''}).encode(),
               json.dumps({'markets':[{**MARKET,'close_time':'2026-10-25T12:00:00'}],'cursor':''}).encode(),
               b'{"markets":[],"cursor":"","deep":' + b'['*70 + b'0' + b']'*70 + b'}',
               json.dumps({'markets':[MARKET]*1001,'cursor':''}).encode()]
        for raw in bad:
            with self.subTest(raw=raw[:80]): self.failure(self.provider(lambda _: reply(raw=raw)))

    def test_empty_list_and_null_cursor_are_successful_evidence(self):
        payload = {'markets':[], 'cursor':None}
        self.assertEqual(self.provider(lambda _:reply(payload=payload)).fetch(RECENT,'',10).payload,payload)

    def test_compression_content_type_and_invalid_lengths_fail_before_reading(self):
        for headers in ({'content-encoding':'gzip'},{'content-type':'text/html'},
                        {'content-length':str(MAX_RESPONSE+1)}, {'content-length':'-1'},
                        {'content-length':'1,2'}):
            stream = Chunks([b'never read'])
            self.failure(self.provider(lambda _: reply(headers=headers,stream=stream)))
            self.assertEqual(stream.reads,0)
            self.assertTrue(stream.closed)

    def test_streamed_size_limit_and_truncation_close_response(self):
        stream = Chunks([b' '*32,b' '*33,b'never read'])
        with patch('services.research.kalshi.MAX_RESPONSE',64):
            self.failure(self.provider(lambda _:reply(stream=stream)))
        self.assertEqual(stream.reads,2)
        self.assertTrue(stream.closed)
        stream = Chunks([b'{}'])
        self.failure(self.provider(lambda _:reply(headers={'content-length':'3'},stream=stream)))
        self.assertTrue(stream.closed)

    def test_stream_deadline_and_read_timeout_close_response(self):
        now = [0.0]
        stream = Chunks([b'{',b'never read'],callback=lambda:now.__setitem__(0,11))
        self.failure(self.provider(lambda _:reply(stream=stream),clock=lambda:now[0]),'provider_timeout',True)
        self.assertEqual(stream.reads,1)
        self.assertTrue(stream.closed)
        stream = Chunks([httpx.ReadTimeout('private detail')])
        self.failure(self.provider(lambda _:reply(stream=stream)),'provider_timeout',True)
        self.assertTrue(stream.closed)

    def test_bad_scope_cursor_and_timeout_fail_before_any_request(self):
        calls = []
        p = self.provider(lambda r:(calls.append(r) or reply()))
        for timeout in (True,0,-1,11,float('nan'),float('inf')):
            with self.assertRaises(ValueError): p.fetch(RECENT,'',timeout)
        with self.assertRaises(ValueError): p.fetch('https://other.test','',10)
        with self.assertRaises(ValueError): p.fetch(RECENT,'x'*4097,10)
        self.assertEqual(calls,[])

    def test_long_retry_after_keeps_full_cooldown_and_bounded_queue_retry(self):
        p = self.provider(lambda _: reply(429,headers={'retry-after':'7200'}))
        error = self.failure(p,'provider_rate_limit',True)
        self.assertEqual(error.delay,3600)
        self.assertEqual(error.cooldown,7200)
