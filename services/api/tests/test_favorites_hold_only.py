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

    def test_held_settlement_records_return_but_prior_partial_exit_is_excluded(self):
        for exited in (False,True):
            e,b,book,o=timing_fixture.EntryTiming().setup_bot(close=1000)
            e.fill(o,D(10),o.price,'TEST')
            if exited:
                sell=e.place(o.ticker,'yes','sell',D(4),D('.01'),maker=False)
                e.advance(202)
            b.hold_only=True
            timing_fixture.EntryTiming().settle(e,b,1001)
            result=rows(b.exit_evidence.cells,hold_only=True)[0]
            self.assertEqual(result['return_observations'],0 if exited else 1)
            if not exited:self.assertEqual(D(result['average_return_pct']),D(100)/9)

    def test_historical_singleton_hold_result_is_reconstructed_but_exit_altered_row_is_not(self):
        key='legacy'
        metric=dict(key=key,series='KXBTCD',side='yes',price='.8',horizon='5–10m',
            contracts='10',closed='10',resolved='10',winners='10',unverified='0',
            cost='8.1',closed_cost='8.1',net='1.9',dollar_hours='0',holding_seconds='0')
        cells={key:dict(events={'one':1}),METRICS+key:metric}
        self.assertEqual(rows(cells,hold_only=True)[0]['return_observations'],1)
        metric['net']='-1'
        self.assertEqual(rows(cells,hold_only=True)[0]['return_observations'],0)
        metric['net']='1.9';cells[key]['events']['two']=1
        self.assertEqual(rows(cells,hold_only=True)[0]['return_observations'],0)

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
