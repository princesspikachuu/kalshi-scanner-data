"""MT-035: pure finance-hourly regular Favorites observation, not a trade gate."""
import unittest
from decimal import Decimal as D
from types import SimpleNamespace

from services.paper_demo.shadow.core import Book
from services.paper_demo.shadow.favorite_finance_health import (
    finance_hourly_funnel_snapshot,
)


class FinanceHourlyFunnelSnapshotTests(unittest.TestCase):
    NOW = 2_000_000_000
    SERIES = 'KXINXU'
    TICKER = 'KXINXU-26NOV23H1000-T1234'

    def fixture(self, cash='1000', yes='.82', no='.13', fee=True,
                fresh=True, enabled=True, parked=False, now=None):
        now = self.NOW if now is None else now
        book = Book()
        book.levels = dict(
            yes={D(yes): D(5)} if yes is not None else {},
            no={D(no): D(5)} if no is not None else {},
        )
        book.valid = bool(fresh)
        book.at = now if fresh else now-300
        book.snapshot_at = now if fresh else 0
        ticker = self.TICKER
        market = dict(close=now+1800, paid=False, hourly_price=True,
                      entry_parked=parked)
        bot = SimpleNamespace(enabled=enabled, attempts={})
        fleet = SimpleNamespace(bots={self.SERIES: bot})
        profiles = [dict(series=self.SERIES, strategy='favorites', asset='hourly')]
        engine = SimpleNamespace(
            markets={ticker: market}, books={ticker: book}, orders={},
            book_fresh=lambda t: book.valid and book.at >= now-60,
            zero_maker_entry_allowed=lambda t: fee,
            available=lambda: D(cash),
        )
        suite = SimpleNamespace(
            portfolios={'favorites': (engine, fleet, profiles)},
            hourly_coverage={self.SERIES: dict(at=now-15,
                active_markets=1, eligible_markets=1,
                reason='Active qualifying market')},
        )
        return suite, engine, bot

    def check(self, **options):
        suite,engine,bot=self.fixture(**options)
        value=finance_hourly_funnel_snapshot(suite,self.NOW)
        return value,value['by_series'][self.SERIES],suite,engine,bot

    def test_funded_two_sided_quoted_fee_verified_market(self):
        value,row,_,_,_=self.check()
        self.assertEqual(value['configured_series'],1)
        self.assertEqual(value['enabled_series'],1)
        self.assertEqual(value['paper_cash_available'],'1000')
        self.assertEqual(row['admitted_active_markets'],1)
        self.assertEqual(row['fresh_books'],1)
        self.assertEqual(row['fee_verified_admitted_markets'],1)
        self.assertEqual(row['two_sided_books'],1)
        self.assertEqual(row['price_candidate_books'],1)
        self.assertEqual(row['fee_verified_price_books'],1)
        self.assertEqual(row['fundable_price_books'],1)
        self.assertTrue(row['scan_recent'])
        self.assertEqual(row['scan_eligible_last'],1)
        self.assertIn('not_independent_events',value['denominator'])

    def test_cash_shortage_separate_from_eligible_price_and_fee(self):
        value,row,_,engine,_=self.check(cash='.47')
        self.assertEqual(row['price_candidate_books'],1)
        self.assertEqual(row['fee_verified_price_books'],1)
        self.assertEqual(row['fundable_price_books'],0)
        self.assertEqual(engine.available(),D('.47'))

    def test_unverified_maker_fee_still_separately_visible(self):
        _,row,_,_,_=self.check(fee=False)
        self.assertEqual(row['fee_verified_admitted_markets'],0)
        self.assertEqual(row['price_candidate_books'],1)
        self.assertEqual(row['fee_verified_price_books'],0)
        self.assertEqual(row['fundable_price_books'],0)

    def test_stale_or_one_sided_books_are_not_counted_as_valid_quotes(self):
        _,stale,_,_,_=self.check(fresh=False)
        self.assertEqual(stale['fresh_books'],0)
        self.assertEqual(stale['fee_verified_admitted_markets'],1)
        self.assertEqual(stale['two_sided_books'],0)
        _,one_sided,_,_,_=self.check(no=None)
        self.assertEqual(one_sided['fresh_books'],1)
        self.assertEqual(one_sided['two_sided_books'],0)
        self.assertEqual(one_sided['price_candidate_books'],0)

    def test_two_sided_book_with_no_70_cent_candidate(self):
        _,row,_,_,_=self.check(yes='.50',no='.40')
        self.assertEqual(row['two_sided_books'],1)
        self.assertEqual(row['price_candidate_books'],0)

    def test_attempt_side_lock_can_explain_missing_quote(self):
        suite,engine,bot=self.fixture()
        bot.attempts[self.TICKER]=dict(side='no')
        row=finance_hourly_funnel_snapshot(suite,self.NOW)['by_series'][self.SERIES]
        self.assertEqual(row['two_sided_books'],1)
        self.assertEqual(row['price_candidate_books'],0)

    def test_parked_and_disabled_markets_never_appear_as_tradable(self):
        _,parked,_,_,_=self.check(parked=True)
        self.assertEqual(parked['parked_active_markets'],1)
        self.assertEqual(parked['admitted_active_markets'],0)
        value,disabled,_,_,_=self.check(enabled=False)
        self.assertEqual(value['configured_series'],1)
        self.assertEqual(value['enabled_series'],0)
        self.assertEqual(disabled['admitted_active_markets'],0)

    def test_ignores_other_portfolios_and_crypto_hourly_series(self):
        suite,engine,bot=self.fixture()
        # Add a non-finance regular Favorites profile and an unrelated
        # Statistics-Backed portfolio, both of which must be invisible.
        engine.markets['KXBTCD-OTHER']=dict(close=self.NOW+1800,
            paid=False,hourly_price=True)
        suite.portfolios['favorites'][1].bots['KXBTCD']=SimpleNamespace(
            enabled=True,attempts={})
        suite.portfolios['favorites'][2].append(
            dict(series='KXBTCD',strategy='favorites',asset='hourly'))
        suite.portfolios['favorites_statistics']=(
            SimpleNamespace(markets={'KX2YRRATEH-OTHER':{}}),
            SimpleNamespace(bots={}),
            [dict(series='KX2YRRATEH',strategy='favorites_statistics',asset='hourly')])
        value=finance_hourly_funnel_snapshot(suite,self.NOW)
        self.assertEqual(set(value['by_series']),{self.SERIES})

    def test_open_orders_not_contracts_and_no_sensitive_market_ids(self):
        suite,engine,_=self.fixture()
        engine.orders={
            'a':SimpleNamespace(ticker=self.TICKER,action='buy',status='resting',quantity=D(10)),
            'b':SimpleNamespace(ticker=self.TICKER,action='buy',status='pending',quantity=D(1)),
            'c':SimpleNamespace(ticker=self.TICKER,action='sell',status='resting',quantity=D(1)),
        }
        value=finance_hourly_funnel_snapshot(suite,self.NOW)
        self.assertEqual(value['by_series'][self.SERIES]['resting_or_pending_buy_orders'],2)
        self.assertNotIn(self.TICKER,str(value))
        self.assertNotIn('quantity',str(value))
        self.assertEqual(len(engine.orders),3)

    def test_absent_or_stale_scan_has_unknown_coverage_not_zero_listing_proof(self):
        suite,_,_=self.fixture()
        suite.hourly_coverage[self.SERIES]['at']=self.NOW-1000
        row=finance_hourly_funnel_snapshot(suite,self.NOW)['by_series'][self.SERIES]
        self.assertFalse(row['scan_recent'])
        self.assertEqual(row['scan_reason'],'no_recent_scan')
        self.assertIsNone(row['scan_listed_last'])
        self.assertIsNone(row['scan_eligible_last'])

    def test_cash_index_calendar_wake_is_not_a_venue_listing(self):
        suite,engine,_=self.fixture()
        # Saturday Nov 21, 2026 19:13 Pacific. Series has not yet been
        # scanned by a newly started worker; the NYSE calendar is closed.
        now=1_795_317_226
        engine.markets.clear()
        suite.hourly_coverage.clear()
        row=finance_hourly_funnel_snapshot(suite,now)['by_series'][self.SERIES]
        self.assertFalse(row['scan_recent'])
        self.assertEqual(row['scan_state'],'scheduled_cash_index')
        self.assertIsNone(row['scan_last_reason'])
        self.assertIsNone(row['scan_listed_last'])
        self.assertGreater(row['next_scan_hint_seconds'],0)
        self.assertEqual(row['admitted_active_markets'],0)

    def test_stale_scan_vs_explicit_retry_are_different(self):
        suite,_,_=self.fixture()
        suite.hourly_coverage[self.SERIES].update(
            at=self.NOW-200,reason='Last confirmed older scan',
            active_markets=8,eligible_markets=7)
        suite.hourly_retry_at={self.SERIES:self.NOW+3600}
        row=finance_hourly_funnel_snapshot(suite,self.NOW)['by_series'][self.SERIES]
        self.assertFalse(row['scan_recent'])
        self.assertEqual(row['scan_state'],'scheduled_retry')
        self.assertEqual(row['scan_last_age_seconds'],200)
        self.assertEqual(row['scan_last_reason'],'Last confirmed older scan')
        self.assertEqual(row['next_scan_hint_seconds'],3600)
        self.assertIsNone(row['scan_listed_last'])
        self.assertIsNone(row['scan_eligible_last'])
        suite.hourly_retry_at.clear()
        row=finance_hourly_funnel_snapshot(suite,self.NOW)['by_series'][self.SERIES]
        self.assertEqual(row['scan_state'],'stale')
        self.assertIsNone(row['next_scan_hint_seconds'])
        suite.hourly_coverage.clear()
        row=finance_hourly_funnel_snapshot(suite,self.NOW)['by_series'][self.SERIES]
        self.assertEqual(row['scan_state'],'never_scanned')
        self.assertIsNone(row['scan_last_age_seconds'])

    def test_cached_series_frequency_reports_metadata_without_provider_reads(self):
        suite,_,_=self.fixture()
        suite.hourly_metadata={self.SERIES:dict(at=self.NOW-5,frequency='hourly')}
        row=finance_hourly_funnel_snapshot(suite,self.NOW)['by_series'][self.SERIES]
        self.assertEqual(row['verified_series_frequency'],'hourly')
        suite.hourly_metadata[self.SERIES]['frequency']='daily'
        row=finance_hourly_funnel_snapshot(suite,self.NOW)['by_series'][self.SERIES]
        self.assertEqual(row['verified_series_frequency'],'daily')
        self.assertEqual(row['scan_state'],'recent')
        self.assertEqual(suite.hourly_metadata[self.SERIES]['frequency'],'daily')

    def test_future_scan_hints_are_bounded_and_do_not_authorize_listings(self):
        suite,_,_=self.fixture()
        suite.hourly_coverage.clear()
        suite.discovery_wakes={'hourly:'+self.SERIES:self.NOW+180}
        suite.hourly_retry_at={self.SERIES:self.NOW+450}
        row=finance_hourly_funnel_snapshot(suite,self.NOW)['by_series'][self.SERIES]
        self.assertEqual(row['scan_state'],'scheduled_retry')
        self.assertEqual(row['next_scan_hint_seconds'],180)
        self.assertIsNone(row['scan_listed_last'])
        self.assertIsNone(row['scan_eligible_last'])
        suite.discovery_wakes['hourly:'+self.SERIES]=float('inf')
        suite.hourly_retry_at[self.SERIES]=self.NOW+32_000_000
        row=finance_hourly_funnel_snapshot(suite,self.NOW)['by_series'][self.SERIES]
        self.assertEqual(row['scan_state'],'never_scanned')
        self.assertIsNone(row['next_scan_hint_seconds'])

    def test_invalid_scan_timestamp_does_not_crash_read_only_health(self):
        suite,_,_=self.fixture()
        for invalid in (float('-inf'),float('nan'),True):
            suite.hourly_coverage[self.SERIES]['at']=invalid
            row=finance_hourly_funnel_snapshot(suite,self.NOW)['by_series'][self.SERIES]
            self.assertEqual(row['scan_state'],'unknown_scan_time')
            self.assertFalse(row['scan_recent'])
            self.assertIsNone(row['scan_last_age_seconds'])
            self.assertIsNone(row['scan_listed_last'])

    def test_missing_regular_portfolio_fails_to_empty_summary(self):
        value=finance_hourly_funnel_snapshot(SimpleNamespace(portfolios={}),self.NOW)
        self.assertEqual(value['configured_series'],0)
        self.assertEqual(value['by_series'],{})


if __name__=='__main__':
    unittest.main()
