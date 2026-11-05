import unittest
from decimal import Decimal as D
from unittest.mock import Mock,patch
from services.api.tests.test_demo_cycles import worker,entry,NOW
from services.demo.market_activity import external_book_ready
from services.demo.cycles import eligible
from services.demo.runtime import quote

class MarketActivityTests(unittest.TestCase):
    def worker(self,volume=10):
        w=worker();w.started_at=NOW-120;w.bots[0]['config']['require_active_market']=True
        w.quotes['t'].update(market_volume=volume,open=NOW-100)
        w.books.books['t']={'yes':{D('.50'):D('10')},'no':{D('.40'):D('10')}}
        return w
    def test_own_buys_and_complemented_sells_do_not_create_external_liquidity(self):
        book={'yes':{D('.03'):D(10)},'no':{D('.40'):D(10)}}
        buys=[entry(price=3,remaining=10),entry(client_id='other',kind='exit',side='yes',price=60,remaining=10)]
        self.assertFalse(external_book_ready(book,buys,'t'))
        book['yes'][D('.03')]+=1;book['no'][D('.40')]+=1
        self.assertTrue(external_book_ready(book,buys,'t'))
    def test_verified_external_book_and_reported_volume_allow_entries(self):
        w=self.worker();w.refresh_market_activity(NOW)
        self.assertTrue(w.quotes['t']['market_activity_ready']);self.assertIsNone(w.inactive_bot(w.bots[0]))
        self.assertTrue(eligible(w.bots[0]['config'],w.bots[0]['config']['squares'][0],w.quotes['t'],NOW))
    def test_zero_trade_market_after_opening_minute_is_flagged_and_releases_waiting_buys(self):
        w=self.worker(volume=0);w.refresh_market_activity(NOW)
        self.assertIsNotNone(w.inactive_bot(w.bots[0]));self.assertFalse(w.quotes['t']['market_activity_ready'])
        w.orders=[entry(remaining=10,filled=2)];w.cancel=Mock()
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        w.cancel.assert_called_once();w.submit.assert_not_called();self.assertEqual(w.orders[0]['filled'],2)
    def test_opening_grace_does_not_delay_bids_until_first_trade(self):
        w=self.worker(volume=0);w.quotes['t']['open']=NOW-1;w.refresh_market_activity(NOW)
        self.assertTrue(w.quotes['t']['market_activity_ready'])
    def test_future_round_is_not_an_active_market_and_missing_market_gets_periodic_probe(self):
        w=self.worker();w.quotes['t'].update(open=NOW+10);w.refresh_market_activity(NOW)
        self.assertIsNotNone(w.inactive_bot(w.bots[0]));self.assertEqual(w.market_probe_at['KXBTC15M'],NOW+60)
        w.quotes={};w.refresh_market_activity(NOW+30);self.assertEqual(w.market_probe_at['KXBTC15M'],NOW+60)
        w.refresh_market_activity(NOW+61)
        # Expiry permits discovery to run, rather than resetting cooldown forever.
        self.assertLess(w.market_probe_at['KXBTC15M'],NOW+61)
    def test_activity_automatically_recovers_after_next_probe(self):
        w=self.worker(volume=0);w.refresh_market_activity(NOW)
        w.quotes['t'].update(market_volume=20,at=NOW+61);w.refresh_market_activity(NOW+61)
        self.assertIsNone(w.inactive_bot(w.bots[0]));self.assertTrue(w.quotes['t']['market_activity_ready'])
    def test_stale_or_disconnected_feed_does_not_prove_market_inactive(self):
        w=self.worker(volume=0);w.quotes['t']['at']=NOW-10;w.refresh_market_activity(NOW)
        self.assertIsNone(w.inactive_bot(w.bots[0]))
    def test_prelisted_fifteen_minute_contract_uses_round_open_not_listing_time(self):
        from datetime import datetime,timezone
        stamp=lambda n:datetime.fromtimestamp(n,timezone.utc).isoformat()
        _,q=quote(dict(ticker='KXGOLD15M-test',series_ticker='KXGOLD15M',yes_bid_dollars='.03',yes_ask_dollars='.97',
            open_time=stamp(NOW-36000),close_time=stamp(NOW+1800),volume_fp='0',status='active'),NOW)
        self.assertEqual(q['open'],NOW+900);self.assertEqual(q['listed_open'],NOW-36000)
