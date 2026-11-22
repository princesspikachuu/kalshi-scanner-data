"""Issue #333: active regular Favorites 15m discovery is independent of paused Convexity.

Exercises the actual ForwardRun scanner and ExperimentSuite market routing with
fake public venue reads. Does not reach Kalshi accounts, orders, or live workers.
"""
import time
import unittest
from datetime import datetime, timezone
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from services.api.tests.test_strategy_scope import ScopeTests
from services.api.tests.test_strategy_folders import QuietAudit, profile
from services.paper_demo.shadow.core import Engine, FeePolicy, StrategyFleet
from services.paper_demo.shadow.runner import ForwardRun
from services.paper_demo.shadow.schedules import EASTERN


def iso(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat()


class FavoritesIndependent15mDiscovery(unittest.IsolatedAsyncioTestCase):
    def fixture(self, *, active=True, legacy_active=False, now=2000000000):
        suite, rows=ScopeTests().suite()
        for row in rows:
            p=row['parameters']
            is_fav=p.get('folder_id')=='favorites' and p['series']=='KXBTC15M'
            row['progress']['desired']='running' if active and is_fav else 'paused'
            if is_fav:p['contracts']=1
        suite.control(rows)
        run=object.__new__(ForwardRun)
        run.suspend_idle_feeds=True
        run.engine=Engine(QuietAudit(),cash='1000')
        legacy=profile('KXBTC15M','legacy_btc','convexity')
        run.profiles=[legacy]
        run.strategy=StrategyFleet(run.engine,[legacy])
        run.strategy.bots['KXBTC15M'].enabled=legacy_active
        run.experiments=suite
        suite.host=run
        run.selected={}
        run.settlement_observed=AsyncMock(return_value=False)
        run.legacy_ticker_needed=Mock(return_value=False)
        t='KXBTC15M-26NOV21-TEST'
        listed=dict(ticker=t,event_ticker='BTC-EVENT',status='active',
                    open_time=iso(now-30),close_time=iso(now+750))
        run.api=SimpleNamespace(fetch=AsyncMock(return_value={'markets':[listed]}))
        run.market_metadata=AsyncMock(return_value=(
            {'fee_type':'linear','fee_multiplier':0}, FeePolicy(D(1),D(0))))
        run.verified_fees=Mock()
        run.verified_fees.zero_maker_fees_until.return_value=True
        run.verified_fees.schedule.return_value=('linear',D(1))
        async def enqueue(source,payload):
            # Mirror the serialized hosted consumer: legacy engine receives the
            # public market but only the enabled Favorites portfolio can trade.
            run.engine.handle(source,payload,now)
            suite.handle(source,payload,now)
        run.put=AsyncMock(side_effect=enqueue)
        return run,suite,rows,listed,now

    async def test_paused_legacy_running_favorites_receives_market_and_fresh_book(self):
        run,suite,rows,listed,now=self.fixture()
        self.assertFalse(run.strategy.bots['KXBTC15M'].enabled)
        self.assertTrue(suite.portfolios['favorites'][1].bots['KXBTC15M'].enabled)
        self.assertTrue(run.legacy_discovery_required('KXBTC15M'))
        with patch('services.paper_demo.shadow.runner.time.time',return_value=now):
            await run.discover_once()
        t=listed['ticker']
        self.assertEqual(run.selected,{'KXBTC15M':t})
        self.assertIn(t,suite.portfolios['favorites'][0].markets)
        self.assertNotIn(t,suite.portfolios['sequential'][0].markets)
        self.assertIn(t,run.subscription_tickers(now))
        e=suite.portfolios['favorites'][0]
        self.assertFalse(e.books[t].valid,'the new public listing is not an order book')
        self.assertFalse(e.orders)
        self.assertFalse(run.engine.orders,'paused legacy fleet cannot submit')
        before_cash=e.wallet.cash
        suite.handle('kalshi',dict(type='orderbook_snapshot',sid=1,seq=1,msg=dict(
            market_ticker=t,yes_dollars_fp=[['.79','100']],
            no_dollars_fp=[['.19','100']])),now+1)
        self.assertTrue(e.orders,'a fresh verified snapshot enables the Favorites paper bid')
        self.assertTrue(all(o.maker and o.action=='buy' and o.quantity==D(1) for o in e.orders.values()))
        self.assertEqual(e.wallet.cash,before_cash,'submission does not spend simulated cash until fill')
        self.assertFalse(run.engine.orders)
        self.assertFalse(run.strategy.bots['KXBTC15M'].enabled)

    async def test_both_paused_skip_discovery_reads_and_clear_dormant_wake(self):
        run,suite,rows,listed,now=self.fixture(active=False)
        suite.discovery_wakes['fifteen:KXBTC15M']=now+300
        self.assertFalse(run.legacy_discovery_required('KXBTC15M'))
        with patch('services.paper_demo.shadow.runner.time.time',return_value=now):
            await run.discover_once()
        run.api.fetch.assert_not_awaited()
        run.put.assert_not_awaited()
        self.assertNotIn('fifteen:KXBTC15M',suite.discovery_wakes)

    async def test_statistics_only_cannot_reactivate_regular_favorites_15m_reads(self):
        run,suite,rows,listed,now=self.fixture(active=False)
        stats=suite.portfolios['favorites_statistics'][1]
        stats.bots['KXBTC15M']=SimpleNamespace(enabled=True,
            profile=dict(strategy='favorites_statistics',series='KXBTC15M'))
        self.assertFalse(run.favorites_fifteen_discovery_enabled('KXBTC15M'))
        self.assertFalse(run.legacy_discovery_required('KXBTC15M'))
        with patch('services.paper_demo.shadow.runner.time.time',return_value=now):
            await run.discover_once()
        run.api.fetch.assert_not_awaited()
        run.put.assert_not_awaited()

    async def test_legacy_only_and_standalone_behavior_remains_unchanged(self):
        run,suite,rows,listed,now=self.fixture(active=False,legacy_active=True)
        self.assertTrue(run.legacy_discovery_required('KXBTC15M'))
        with patch('services.paper_demo.shadow.runner.time.time',return_value=now):
            await run.discover_once()
        self.assertEqual(run.selected['KXBTC15M'],listed['ticker'])
        self.assertNotIn(listed['ticker'],suite.portfolios['favorites'][0].markets)
        self.assertTrue(run.strategy.bots['KXBTC15M'].enabled)
        run.suspend_idle_feeds=False
        run.strategy.bots['KXBTC15M'].enabled=False
        self.assertTrue(run.legacy_discovery_required('KXBTC15M'))

    async def test_rss_capacity_and_unverified_fees_never_admit_favorite_market(self):
        run,suite,_,listed,now=self.fixture()
        suite.extra_capacity=Mock(return_value=False)
        with patch('services.paper_demo.shadow.runner.time.time',return_value=now):
            await run.discover_once()
        run.api.fetch.assert_awaited()
        suite.extra_capacity.assert_called_once_with([listed['ticker']],now)
        run.market_metadata.assert_not_awaited()
        run.put.assert_not_awaited()
        self.assertNotIn('KXBTC15M',run.selected)
        self.assertEqual(run.discovery_retry_at['KXBTC15M'],now+5)
        # Once admission is healthy, current venue fees must still be verified.
        suite.extra_capacity.return_value=True
        run.verified_fees.zero_maker_fees_until.return_value=False
        with patch('services.paper_demo.shadow.runner.time.time',return_value=now+6):
            await run.discover_once()
        run.market_metadata.assert_awaited_once()
        run.put.assert_not_awaited()
        self.assertEqual(run.discovery_retry_at['KXBTC15M'],now+66)

    async def test_expired_unexposed_legacy_selection_does_not_block_next_roll(self):
        run,suite,_,listed,now=self.fixture()
        previous='KXBTC15M-26NOV21-OLD'
        run.engine.add_market(dict(ticker=previous,event_ticker='OLD',
                                   open=now-900,close=now-1),FeePolicy())
        run.selected={'KXBTC15M':previous}
        with patch('services.paper_demo.shadow.runner.time.time',return_value=now):
            await run.discover_once()
        self.assertIn(previous,run.engine.markets,'do not delete historical legacy market')
        self.assertEqual(run.selected['KXBTC15M'],listed['ticker'])
        self.assertIn(listed['ticker'],suite.portfolios['favorites'][0].markets)

    async def test_expired_legacy_with_risk_keeps_settlement_gate(self):
        run,suite,_,listed,now=self.fixture()
        previous='KXBTC15M-26NOV21-HELD'
        run.engine.add_market(dict(ticker=previous,event_ticker='OLD',
                                   open=now-900,close=now-1),FeePolicy())
        run.selected={'KXBTC15M':previous}
        run.legacy_ticker_needed.return_value=True
        with patch('services.paper_demo.shadow.runner.time.time',return_value=now):
            await run.discover_once()
        run.settlement_observed.assert_awaited_once_with(previous)
        self.assertEqual(run.selected['KXBTC15M'],previous)
        self.assertIn(previous,run.engine.markets)
        run.put.assert_not_awaited()

    async def test_cash_index_weekend_remains_asleep_until_local_session(self):
        run,suite,_,_,now=self.fixture()
        series='KXINX15M'
        run.profiles=[profile(series,'legacy_index','convexity')]
        run.strategy=StrategyFleet(run.engine,run.profiles)
        run.strategy.bots[series].enabled=False
        bot=SimpleNamespace(enabled=True,profile=dict(series=series,strategy='favorites',retired=False))
        suite.portfolios['favorites'][1].bots[series]=bot
        on_weekend=datetime(2026,11,7,12,tzinfo=EASTERN).timestamp()
        expected=datetime(2026,11,9,9,29,tzinfo=EASTERN).timestamp()
        with patch('services.paper_demo.shadow.runner.time.time',return_value=on_weekend):
            await run.discover_once()
        run.api.fetch.assert_not_awaited()
        run.put.assert_not_awaited()
        self.assertEqual(suite.discovery_wakes['fifteen:'+series],expected)
        self.assertEqual(run.discovery_retry_at[series],expected)


if __name__=='__main__':
    unittest.main()
