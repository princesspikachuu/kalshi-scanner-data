import unittest
from decimal import Decimal as D
from unittest.mock import patch
from services.api.tests import test_favorite_entry_timing as timing_fixture
from services.paper_demo.shadow.favorite_timing import rows,METRICS
from services.api.tests import test_strategy_scope as scope_fixture
from services.api.tests.test_strategy_folders import market

class HoldOnlyTests(unittest.TestCase):
    def test_deep_loss_never_builds_exit_model_or_submits_sell_and_rejects_old_exit(self):
        e,b,book,o=timing_fixture.EntryTiming().setup_bot(close=1000)
        b.hold_only=True
        e.fill(o,D(10),o.price,'TEST')
        book.levels={'yes':{D('.20'):D(100)},'no':{D('.79'):D(100)}}
        sell=e.place(o.ticker,'yes','sell',D(10),D('.01'),maker=False)
        with patch('services.paper_demo.shadow.favorites.assess',side_effect=AssertionError('exit model ran')):
            b.step();e.advance(202);b.step()
        self.assertEqual(e.orders[sell].status,'cancelled')
        self.assertEqual(sum(l.quantity for l in e.wallet.lots),10)
        self.assertEqual(len([o for o in e.orders.values() if o.action=='sell']),1)

    def test_known_outcome_uses_hold_return_even_after_prior_partial_exit(self):
        for exited in (False,True):
            e,b,book,o=timing_fixture.EntryTiming().setup_bot(close=1000)
            e.fill(o,D(10),o.price,'TEST')
            if exited:
                sell=e.place(o.ticker,'yes','sell',D(4),D('.01'),maker=False)
                e.advance(202)
            b.hold_only=True
            timing_fixture.EntryTiming().settle(e,b,1001)
            result=rows(b.exit_evidence.cells,hold_only=True)[0]
            self.assertEqual(result['return_observations'],1)
            self.assertEqual(D(result['average_return_pct']),D(100)/9)
            if exited:self.assertNotEqual(D(result['net']),D(1))

    def test_historical_known_outcomes_ignore_exits_and_unknown_outcomes_are_omitted(self):
        key='legacy'
        metric=dict(key=key,series='KXBTCD',side='yes',price='.8',horizon='5–10m',
            contracts='10',closed='10',resolved='10',winners='10',unverified='0',
            cost='8.1',closed_cost='8.1',net='1.9',dollar_hours='0',holding_seconds='0')
        cells={key:dict(events={'one':1}),METRICS+key:metric}
        self.assertEqual(rows(cells,hold_only=True)[0]['return_observations'],1)
        metric['net']='-1'
        self.assertEqual(rows(cells,hold_only=True)[0]['return_observations'],1)
        self.assertEqual(D(rows(cells,hold_only=True)[0]['average_return_pct']),100*D('1.9')/D('8.1'))
        cells[key]['events']['two']=1
        self.assertEqual(rows(cells,hold_only=True)[0]['estimated_return_observations'],2)
        cells[key]['events']={}
        self.assertEqual(rows(cells,hold_only=True)[0]['return_observations'],0)

    def test_known_losing_outcome_after_exit_has_minus_100_percent_hold_return(self):
        e,b,book,o=timing_fixture.EntryTiming().setup_bot(close=1000)
        e.fill(o,D(10),o.price,'TEST')
        sell=e.place(o.ticker,'yes','sell',D(4),D('.01'),maker=False)
        e.advance(202)
        b.hold_only=True
        e.settled.add(o.ticker);e.markets[o.ticker]['yes_payout_confirmed']='0'
        e.handle('settlement',dict(ticker=o.ticker,yes_payout='0'),1001);b.step()
        result=rows(b.exit_evidence.cells,hold_only=True)[0]
        self.assertEqual(result['return_observations'],1)
        self.assertEqual(D(result['average_return_pct']),-100)
        self.assertNotEqual(D(result['net']),-D(result['cost']))

    def test_hold_research_retains_entry_fees_but_ignores_exit_fees_and_keeps_ledger(self):
        e,b,book,o=timing_fixture.EntryTiming().setup_bot(close=1000,fees=True)
        e.fill(o,D(10),o.price,'TEST')
        e.place(o.ticker,'yes','sell',D(4),D('.01'),maker=False);e.advance(202)
        b.hold_only=True
        timing_fixture.EntryTiming().settle(e,b,1001)
        cash=e.wallet.cash
        result=rows(b.exit_evidence.cells,hold_only=True)[0]
        self.assertEqual(D(result['average_return_pct']),100*(D(10)-D(result['cost']))/D(result['cost']))
        self.assertNotEqual(D(result['net']),D(10)-D(result['cost']))
        rows(b.exit_evidence.cells,hold_only=True)
        self.assertEqual(e.wallet.cash,cash)

    def test_expired_depth_is_released_without_changing_position_or_financial_state(self):
        suite,_=scope_fixture.ScopeTests().suite();engine=suite.portfolios['favorites'][0]
        ticker='KXBTC15M-memory';market(engine,ticker,close=250);engine.now=300
        engine.wallet.fill(ticker,'yes','buy',D(2),D('.8'),D('.1'),200,'original')
        cash=engine.wallet.cash;lots=list(engine.wallet.lots)
        self.assertTrue(engine.books[ticker].levels['yes'])
        suite.maintain()
        self.assertFalse(engine.books[ticker].levels['yes'])
        self.assertEqual(engine.wallet.cash,cash);self.assertEqual(engine.wallet.lots,lots)
        self.assertIn(ticker,engine.markets)

    def test_paused_statistics_freezes_display_and_releases_index_until_resumed(self):
        from services.api.tests import test_strategy_folders as folder_fixture
        from services.paper_demo.shadow.statistics_favorites import StatisticsFavoritesStrategy
        suite,source_rows=scope_fixture.ScopeTests().suite()
        p=folder_fixture.profile(series='KXBTCD',id='stat-test',strategy='favorites_statistics')
        p['folder_id']='favorites_statistics'
        suite=folder_fixture.ready_suite(suite.host,source_rows+[dict(parameters=p,progress=dict(desired='paused'))])
        bot=suite.portfolios['favorites_statistics'][1].bots['KXBTCD']
        self.assertIsInstance(bot,StatisticsFavoritesStrategy)
        with patch.object(bot,'statistics_snapshot',return_value=dict(matrix=[],evidence_refreshed_at=200)) as calculate:
            suite.shared_statistics_cache['groups']={'large-index':{'events':{}}}
            first=suite.snapshot(200)['favorites_statistics']['statistics']
            second=suite.snapshot(201)['favorites_statistics']['statistics']
            self.assertIs(first,second);self.assertEqual(calculate.call_count,1)
            self.assertFalse(suite.shared_statistics_cache['groups'])
            bot.enabled=True;suite.snapshot(202)
            self.assertEqual(calculate.call_count,2)

    def test_expired_untraded_markets_retire_without_inventing_settlement_or_dropping_filled_trials(self):
        from services.api.tests import test_strategy_folders as folder_fixture
        suite,_=scope_fixture.ScopeTests().suite();engine,fleet,_=suite.portfolios['favorites']
        for name in ('untraded','funded','working'):
            ticker='KXBTC15M-'+name;market(engine,ticker,close=250)
            engine.markets[ticker].update(bot_id=fleet.owner(ticker).profile['id'],discovered_at=200)
        engine.now=200
        engine.wallet.fill('KXBTC15M-funded','yes','buy',D(1),D('.8'),D(0),201,'fill')
        # Model a previously closed fill still waiting for its authoritative outcome.
        engine.wallet.fill('KXBTC15M-funded','yes','sell',D(1),D('.7'),D(0),202,'exit')
        order=engine.place('KXBTC15M-working','yes','buy',D(1),D('.8'),maker=True)
        engine.now=300;cash=engine.wallet.cash
        suite.maintain()
        self.assertNotIn('KXBTC15M-untraded',engine.markets)
        self.assertIn('KXBTC15M-funded',engine.markets)
        self.assertIn('KXBTC15M-working',engine.markets)
        self.assertEqual(engine.wallet.cash,cash)
        self.assertFalse(engine.markets['KXBTC15M-funded'].get('paid',False))
        self.assertIn(order,engine.orders)
