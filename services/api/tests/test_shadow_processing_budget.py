"""Bound work per feed event without skipping delayed execution safety checks."""
import unittest
from decimal import Decimal as D
from unittest.mock import Mock,patch
from services.demo.exchange import ExchangeFailure
from services.paper_demo.shadow.core import Engine,FeePolicy,StrategyFleet
from services.paper_demo.shadow.host import HostedRun,processing_batch_budget
from services.paper_demo.read_budget import ReadBudget

class BurstBatchBudgetTests(unittest.TestCase):
    def test_batch_budget_expands_only_under_backlog(self):
        self.assertEqual(processing_batch_budget(0),(128,.020))
        self.assertEqual(processing_batch_budget(128),(128,.020))
        self.assertEqual(processing_batch_budget(129),(768,.100))
        self.assertEqual(processing_batch_budget(2001),(1536,.200))
        self.assertEqual(processing_batch_budget(10001),(2048,.260))
        self.assertLess(processing_batch_budget(20000)[1],.300)

class ProcessingBudgetTests(unittest.TestCase):
    def fixture(self):
        run=object.__new__(HostedRun);run.engine=Engine(Mock());run.engine.advance(1000)
        run.verified_fees=Mock();run.verified_fees.schedule.return_value=('quadratic',1)
        for i in range(28):
            ticker='S'+str(i)+'-test'
            run.engine.add_market(dict(ticker=ticker,close=1900),FeePolicy())
            book=run.engine.books[ticker];book.valid=True;book.at=1000
            book.levels={'yes':{D('.10'):D(100)},'no':{D('.80'):D(100)}}
        return run

    def test_unrelated_lifecycle_burst_has_no_per_bot_fee_or_strategy_fanout(self):
        run=self.fixture()
        fleet=StrategyFleet(run.engine,[dict(series='S'+str(i),name='Bot '+str(i),contracts=1) for i in range(28)])
        for bot in fleet.bots.values():bot.step=Mock(wraps=bot.step)
        for i in range(1000):
            payload=dict(type='market_lifecycle_v2',msg=dict(market_ticker='UNRELATED-'+str(i),event_type='created'))
            run.engine.handle('kalshi',run.prepare_fees('kalshi',payload,1000.1),1000.1)
        run.verified_fees.schedule.assert_not_called()
        for bot in fleet.bots.values():bot.step.assert_not_called()
        self.assertEqual(run.engine.orders,{})

    def test_due_order_checks_its_own_fees_even_on_another_markets_event(self):
        run=self.fixture();engine=run.engine
        ident=engine.place('S0-test','yes','buy',D(1),D('.1'))
        def schedule(ticker,now):
            if ticker=='S0-test':raise ExchangeFailure('paper_fee_schedule_stale')
            return 'quadratic',1
        run.verified_fees.schedule.side_effect=schedule
        payload=dict(type='ticker',msg=dict(market_ticker='S1-test'))
        engine.handle('kalshi',run.prepare_fees('kalshi',payload,1000.2),1000.2)
        self.assertEqual(engine.orders[ident].status,'rejected')
        self.assertEqual(engine.wallet.cash,50)
        self.assertTrue(engine.books['S1-test'].valid)
        self.assertEqual({call.args[0] for call in run.verified_fees.schedule.call_args_list},{'S0-test','S1-test'})

    def test_single_market_event_evaluates_only_its_owner(self):
        run=self.fixture();engine=run.engine
        fleet=StrategyFleet(engine,[dict(series='S'+str(i),name='Bot '+str(i),contracts=1) for i in range(28)])
        for bot in fleet.bots.values():
            bot.require_spot=False;bot.step=Mock(wraps=bot.step)
        payload=dict(type='ticker',msg=dict(market_ticker='S1-test'))
        engine.handle('kalshi',run.prepare_fees('kalshi',payload,1000.1),1000.1)
        self.assertTrue(engine.orders)
        self.assertEqual({o.ticker for o in engine.orders.values()},{'S1-test'})
        self.assertEqual(sum(b.step.call_count for b in fleet.bots.values()),1)
        engine.handle('clock',run.prepare_fees('clock',{},1000.11),1000.11)
        self.assertEqual(len({o.ticker for o in engine.orders.values()}),28)

class ReadBudgetTests(unittest.TestCase):
    def test_shared_cooldown_blocks_reads_until_explicit_window_expires(self):
        budget=ReadBudget();clock=[100.]
        with patch('services.paper_demo.read_budget.time.monotonic',side_effect=lambda:clock[0]),patch('services.paper_demo.read_budget.time.sleep',side_effect=lambda n:clock.__setitem__(0,clock[0]+n)):
            budget.wait();budget.wait()
            self.assertAlmostEqual(clock[0],100.2)
            budget.reject()
            with self.assertRaises(ExchangeFailure):budget.wait()
            clock[0]+=30
            budget.wait()
