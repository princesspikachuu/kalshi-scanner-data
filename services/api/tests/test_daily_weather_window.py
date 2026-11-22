import unittest
from datetime import datetime,timezone
from decimal import Decimal as D
from services.paper_demo.shadow.weather_window import entry_allowed,daily_day_end,observation_end
from services.paper_demo.shadow.favorites import FavoritesStrategy
from services.paper_demo.shadow.accounting import snapshot
from services.api.tests import test_strategy_folders as fixture
from services.paper_demo.shadow.weather import weather_profiles

def at(text):return datetime.fromisoformat(text.replace('Z','+00:00')).timestamp()

def ny():return dict(ticker='KXHIGHNY-26NOV20-T65',event_ticker='KXHIGHNY-26NOV20',
                     weather_category='weather_daily',open=at('2026-11-20T15:00Z'),close=at('2026-11-21T06:00Z'))

class DailyWindowTests(unittest.TestCase):
    def test_full_local_day_uses_city_midnight_not_later_api_close(self):
        m=ny();end=at('2026-11-21T05:00Z')
        self.assertEqual(daily_day_end(m),end)
        for now,allowed in ((at('2026-11-20T04:59Z'),False),(at('2026-11-20T05:00Z'),True),(end-7201,True),(end-61,True),(end-60,False),(end+25*60,False)):
            self.assertEqual(entry_allowed(m,now),allowed)
    def test_new_days_markets_trade_after_own_local_midnight(self):
        for ticker in ('KXHIGHNY-26NOV21-T60','KXHIGHLAX-26NOV21-T70','KXHIGHAUS-26NOV21-T80'):
            m=dict(ticker=ticker,event_ticker=ticker.rsplit('-',1)[0],weather_category='weather_daily',close=at('2026-11-22T10:00Z'))
            self.assertEqual(entry_allowed(m,at('2026-11-21T08:25Z')),
                             True)
    def test_iana_timezone_handles_summer_trading_day_and_earlier_venue_close(self):
        m=dict(ny(),ticker='KXHIGHNY-26JUN15-T80',event_ticker='KXHIGHNY-26JUN15',close=at('2026-06-16T05:00Z'))
        self.assertEqual(daily_day_end(m),at('2026-06-16T04:00Z'))
        self.assertTrue(entry_allowed(m,at('2026-06-16T02:00Z')))
        m['close']=at('2026-06-16T03:00Z')
        self.assertFalse(entry_allowed(m,at('2026-06-16T03:00Z')))
    def test_unknown_city_date_or_wrong_event_fails_closed(self):
        for change in (dict(ticker='UNKNOWN-26NOV20-T60'),dict(event_ticker='OTHER-26NOV20'),dict(event_ticker='KXHIGHNY-26NOV99')):
            self.assertFalse(entry_allowed(dict(ny(),**change),at('2026-11-21T04:00Z')))
    def bot(self):
        e=fixture.Engine(fixture.QuietAudit());e.advance(at('2026-11-21T04:00Z'))
        p=dict(next(p for p in weather_profiles() if p['series']=='KXHIGHNY'),revision=1)
        b=FavoritesStrategy(e,p);e.strategy=b;e.fill_callback=b.on_fill
        m=ny();e.add_market(m,fixture.FeePolicy())
        book=e.books[m['ticker']];book.levels={'yes':{D('.79'):D(100)},'no':{D('.19'):D(100)}};book.valid=True;book.at=e.now
        return e,b,m
    def test_delayed_and_resting_bids_cannot_fill_after_the_local_cutoff(self):
        for resting in (False,True):
            e,b,m=self.bot();b.step();o=next(iter(e.orders.values()))
            o.status='resting' if resting else 'pending'
            e.now=at('2026-11-21T05:25Z');e.books[o.ticker].at=e.now
            before=e.wallet.cash
            if resting:e.fill(o,D(10),o.price,'TEST')
            else:e.arrive(o)
            self.assertEqual(o.status,'cancelled');self.assertEqual(e.wallet.cash,before);self.assertFalse(e.wallet.lots)
    def test_ended_day_is_pending_without_inferred_win_or_cash_credit(self):
        e,b,m=self.bot();e.wallet.fill(m['ticker'],'yes','buy',D(2),D('.8'),D(0),e.now,'historical')
        before=e.wallet.cash;now=at('2026-11-21T05:25Z')
        value=snapshot(e,[b.profile],now)
        self.assertEqual(value['positions'][0]['state'],'pending')
        self.assertEqual(value['portfolio']['pending_payout_state'],'estimated')
        self.assertEqual(e.wallet.cash,before);self.assertNotIn('yes_payout_confirmed',m)
        self.assertEqual(observation_end(m),at('2026-11-21T05:00Z'))
