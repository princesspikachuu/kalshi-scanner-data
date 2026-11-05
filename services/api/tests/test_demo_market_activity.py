import json,unittest
from decimal import Decimal as D
from unittest.mock import Mock,patch
from services.api.tests.test_demo_cycles import worker,entry,NOW
from services.demo.market_activity import external_book_ready
from services.demo.exchange import ExchangeFailure
from services.demo.runtime import quote

class MarketActivityTests(unittest.TestCase):
    def test_demo_trading_pause_blocks_buys_and_skips_market_probes_for_fifteen_minutes(self):
        w=self.worker();w.demo_status_next=0
        w.exchange.call.return_value=dict(trading_active=False,exchange_index_statuses=[dict(exchange_index=2,trading_active=False)])
        w.probe_market_activity(NOW)
        w.exchange.market_activity_call.assert_not_called()
        self.assertFalse(w.market_entry_ready(w.bots[0]['config'],'t'))
        self.assertIn('Demo trading paused',w.inactive_bot(w.bots[0])['reason'])
        self.assertEqual(w.demo_status_next,NOW+900)
        w.exchange.call.reset_mock();w.probe_market_activity(NOW+899);w.exchange.call.assert_not_called()
        w.exchange.call.return_value=dict(trading_active=True)
        w.raw.update(open_time=NOW+800,close_time=NOW+1700)
        w.probe_market_activity(NOW+901)
        self.assertTrue(w.market_entry_ready(w.bots[0]['config'],'t'))

    def test_paused_crypto_shard_overrides_active_global_flag(self):
        w=self.worker();w.quotes['t']['exchange_index']=2
        w.demo_trading_status=dict(trading_active=True,exchange_index_statuses=[dict(exchange_index=2,trading_active=False)])
        w.market_api_activity={'KXBTC15M':dict(at=NOW,tickers=['t'])};w.refresh_market_activity(NOW)
        self.assertFalse(w.market_entry_ready(w.bots[0]['config'],'t'))
        self.assertIn('Demo trading paused',w.inactive_bot(w.bots[0])['reason'])

    def setUp(self):
        self.clock=patch('time.time',return_value=NOW);self.clock.start();self.addCleanup(self.clock.stop)
    def worker(self,volume=10,bid='.50',markets=True,trades=None):
        w=worker();w.bots[0]['config']['require_active_market']=True
        w.demo_trading_status=dict(trading_active=True);w.demo_status_next=NOW+10000
        w.raw=dict(ticker='t',series_ticker='KXBTC15M',status='active',open_time=NOW-100,close_time=NOW+800,
            yes_bid_dollars=bid,yes_ask_dollars='.60',volume_fp=str(volume))
        w.api_markets=markets;w.api_trades=trades or [];w.api_book='.50'
        def call(method,path,params=None):
            if path=='/markets':return dict(markets=[dict(w.raw)] if w.api_markets else [])
            if path.endswith('/orderbook'):return dict(orderbook_fp=dict(yes_dollars=[[w.api_book,'10']],no_dollars=[['.40','10']]))
            if path=='/markets/trades':return dict(trades=w.api_trades)
            raise AssertionError(path)
        w.exchange=Mock(writes=0);w.exchange.market_activity_call.side_effect=call
        w.quotes['t'].update(series='KXBTC15M',open=NOW-100)
        return w
    def test_rest_activity_does_not_depend_on_stream_volume_or_two_sided_book(self):
        w=self.worker();w.quotes['t'].update(market_volume=0,book_ready=False)
        w.probe_market_activity(NOW)
        self.assertTrue(w.market_entry_ready(w.bots[0]['config'],'t'));self.assertIsNone(w.inactive_bot(w.bots[0]))
        self.assertEqual(w.exchange.market_activity_call.call_args.args[:2],('GET','/markets'))
    def test_zero_reported_volume_with_api_price_movement_is_active(self):
        w=self.worker(volume=0);w.probe_market_activity(NOW)
        self.assertIsNone(w.inactive_bot(w.bots[0]));self.assertFalse(w.market_entry_ready(w.bots[0]['config'],'t'))
        w.raw['yes_bid_dollars']='.51';w.probe_market_activity(NOW+2)
        self.assertTrue(w.market_entry_ready(w.bots[0]['config'],'t'))
    def test_rest_orderbook_movement_counts_when_market_metadata_lags(self):
        w=self.worker(volume=0);w.probe_market_activity(NOW)
        w.api_book='.51';w.probe_market_activity(NOW+2)
        self.assertTrue(w.market_entry_ready(w.bots[0]['config'],'t'))
    def test_recent_api_trade_counts_with_zero_volume_and_static_prices(self):
        w=self.worker(volume=0);w.probe_market_activity(NOW)
        w.api_trades=[dict(ticker='t')];w.probe_market_activity(NOW+2)
        self.assertTrue(w.market_entry_ready(w.bots[0]['config'],'t'))
        self.assertEqual(w.exchange.market_activity_call.call_args.kwargs['params']['min_ts'],NOW-100)
    def test_confirmed_quiet_market_gets_no_buy_and_rechecks_only_after_fifteen_minutes(self):
        w=self.worker(volume=0);w.probe_market_activity(NOW);w.probe_market_activity(NOW+6)
        self.assertEqual(w.market_probe_at['KXBTC15M'],NOW+906)
        self.assertIsNotNone(w.inactive_bot(w.bots[0]));w.exchange.market_activity_call.reset_mock()
        w.probe_market_activity(NOW+900);w.exchange.market_activity_call.assert_not_called()
        w.submit_entry_batch=Mock()
        with patch('services.demo.runtime.time.time',return_value=NOW+6):w.trade()
        w.submit.assert_not_called();w.submit_entry_batch.assert_not_called()
    def test_no_current_round_is_confirmed_from_api_even_if_old_stream_quote_exists(self):
        w=self.worker(markets=False);w.probe_market_activity(NOW)
        self.assertEqual(w.market_probe_at['KXBTC15M'],NOW+900)
        w.api_markets=True;w.raw.update(open_time=NOW+800,close_time=NOW+1700);w.probe_market_activity(NOW+901)
        self.assertIsNone(w.inactive_bot(w.bots[0]));self.assertTrue(w.market_entry_ready(w.bots[0]['config'],'t'))
    def test_api_failure_and_incomplete_response_do_not_mark_market_inactive(self):
        for response in (ExchangeFailure('rate_limited'),dict(markets=[],cursor='more'),dict(markets=[{}])):
            w=self.worker();w.exchange.market_activity_call.side_effect=response if isinstance(response,Exception) else None
            if not isinstance(response,Exception):w.exchange.market_activity_call.return_value=response
            w.probe_market_activity(NOW)
            self.assertIsNone(w.inactive_bot(w.bots[0]));self.assertFalse(w.market_entry_ready(w.bots[0]['config'],'t'))
    def test_cooldown_survives_restart_and_legacy_inferred_flags_are_discarded(self):
        w=self.worker(markets=False);w.probe_market_activity(NOW)
        saved=w.store.saved[-1][1];restarted=self.worker();restarted.store.get=Mock(return_value=dict(progress=saved))
        restarted.restore_market_activity();self.assertEqual(restarted.market_probe_at['KXBTC15M'],NOW+900)
        legacy=self.worker();legacy.store.get=Mock(return_value=dict(progress=dict(inactive=saved['inactive'])))
        legacy.restore_market_activity();self.assertEqual(legacy.market_inactive,{})
    def test_known_active_series_probed_before_unknown(self):
        w=self.worker();other=dict(w.bots[0],id='other',config=dict(w.bots[0]['config'],squares=[dict(w.bots[0]['config']['squares'][0],asset='bnb')]))
        w.bots.append(other);w.market_seen_active['KXBTC15M']=NOW-30;w.probe_market_activity(NOW)
        self.assertEqual(w.exchange.market_activity_call.call_args.kwargs['params']['series_ticker'],'KXBTC15M')
    def test_verified_bid_precedes_other_series_checks(self):
        w=self.worker();w.probe_market_activity(NOW);w.store.get=Mock(return_value=None)
        w.load_bots=Mock();w.repair_rejected_entries=Mock();w.stream=Mock();w.discover=Mock();w.probe_market_activity=Mock()
        w.poll_funding=Mock();w.trading_health=Mock();w.health=Mock()
        def submit(intent):w.exchange.writes+=1;w.stop.set()
        w.submit.side_effect=submit
        with patch('services.demo.runtime.time.time',return_value=NOW),patch('services.demo.reset.ResetController'):w.loop()
        w.submit.assert_called_once();w.discover.assert_not_called();w.poll_funding.assert_not_called();w.probe_market_activity.assert_not_called()
    def test_open_notification_does_not_bypass_cooldown(self):
        w=self.worker(markets=False);w.probe_market_activity(NOW);w.subscription={'t'};w.book_sid=1
        messages=[dict(type='market_lifecycle_v2',sid=3,seq=1,msg=dict(event_type='activated',market_ticker='KXBTC15M-NEW'))]
        class Socket:
            def send(self,data):pass
            def recv(self,**kw):
                if not messages:raise TimeoutError
                return json.dumps(messages.pop(0))
        w.socket=Socket()
        with patch('services.demo.runtime.time.time',return_value=NOW+1):w.stream()
        self.assertEqual(w.pending_markets,set());self.assertEqual(w.market_probe_at['KXBTC15M'],NOW+900)
    def test_own_orders_do_not_create_external_liquidity(self):
        book={'yes':{D('.03'):D(10)},'no':{D('.40'):D(10)}}
        orders=[entry(price=3,remaining=10),entry(client_id='other',kind='exit',side='yes',price=60,remaining=10)]
        self.assertFalse(external_book_ready(book,orders,'t'))
    def test_future_round_is_not_running(self):
        w=self.worker();w.raw.update(open_time=NOW+10,close_time=NOW+1800);w.probe_market_activity(NOW)
        self.assertEqual(w.market_probe_at['KXBTC15M'],NOW+900)
