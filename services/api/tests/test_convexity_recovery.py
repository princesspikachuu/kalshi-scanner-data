"""Behavioral checks for actual fee-adjusted cash recovery, not quote touches."""
from decimal import Decimal as D
import json
import unittest
from unittest.mock import Mock
from services.paper_demo.shadow.core import Engine, FeePolicy, ConvexityStrategy, StrategyFleet
from services.paper_demo.shadow.profit_recovery import execution_report
from services.paper_demo.shadow.state import encode,restore

T='KXBTC15M-test'

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.e=Engine(Mock(),cash='100',toxic_fill_probability=0)
        self.e.advance(1000)
        self.e.add_market(dict(ticker=T,close=1900),FeePolicy())
        self.e.wallet.fill(T,'yes','buy',D(100),D('.10'),D(0),1,'lot',acquired_at=1000)
        self.s=ConvexityStrategy(self.e,require_spot_warmup=False)
        self.s.enabled=False  # Pausing entries does not disable inventory management.
        self.book('.40','100',1000.2)

    def book(self,price,quantity,now):
        self.e.advance(now)
        b=self.e.books[T]
        b.levels={'yes':{D(price):D(quantity)},'no':{D('.59'):D(100)}}
        b.used={'yes':{},'no':{}}
        b.valid=True;b.at=now

    def exits(self):
        return [o for o in self.e.orders.values() if o.action=='sell']

    def test_cost_and_fees_recovered_once_while_preserving_upside(self):
        self.s.step();o=self.exits()[0]
        self.assertEqual(o.quantity,27)
        self.assertEqual(o.price,D('.40'))
        self.assertEqual(o.purpose,'partial_profit')
        self.e.advance(1000.35)
        lot=self.e.wallet.lots[0]
        self.assertEqual(lot.quantity,73)
        self.assertEqual(lot.recovery_proceeds,D('10.3464'))
        self.assertGreaterEqual(lot.recovery_proceeds,lot.recovery_cost)
        self.book('.50','100',1001);self.s.step()
        self.assertEqual(len(self.exits()),1)
        report=execution_report(self.e,T)
        self.assertEqual(report['profit_contracts'],'27')
        self.assertEqual(report['profit_net_proceeds'],'10.3464')

    def test_partial_arrival_fill_retries_only_unrecovered_cash(self):
        self.s.step();o=self.exits()[0]
        self.book('.40','10',1000.3)
        self.e.advance(1000.35)
        self.assertEqual(o.remaining,17)
        self.assertEqual(o.status,'ioc_cancelled')
        self.assertEqual(self.e.wallet.lots[0].recovery_proceeds,D('3.8320'))
        self.book('.40','100',1001);self.s.step()
        retry=self.exits()[-1]
        self.assertEqual(retry.quantity,17)
        self.e.advance(1001.15)
        self.assertEqual(self.e.wallet.lots[0].quantity,73)
        self.assertEqual(self.e.wallet.stat(T).partial_iocs,1)
        self.assertEqual(self.e.wallet.stat(T).ioc_unfilled,17)

    def test_pending_exit_prevents_duplicate_recovery_orders(self):
        self.s.step();self.s.step()
        self.assertEqual(len(self.exits()),1)

    def test_arrival_below_profit_limit_does_not_sell(self):
        self.s.step();self.book('.35','100',1000.3);self.e.advance(1000.35)
        self.assertEqual(self.e.wallet.lots[0].quantity,100)
        self.assertEqual(self.e.wallet.lots[0].recovery_proceeds,0)
        self.assertEqual(self.e.wallet.stat(T).ioc_unfilled,27)

    def test_thin_depth_neither_arms_nor_triggers_profit_exit(self):
        self.book('.41','1',1000.3);self.s.step()
        self.assertFalse(self.e.wallet.lots[0].is_armed)
        self.assertEqual(self.exits(),[])
        self.book('.41','100',1000.4);self.s.step()
        self.assertTrue(self.e.wallet.lots[0].is_armed)
        self.assertEqual(len(self.exits()),1)

    def test_protective_exit_takes_priority(self):
        self.e.wallet.lots[0].is_armed=True
        self.book('.30','100',1000.3);self.s.step()
        o=self.exits()[0]
        self.assertEqual(o.quantity,100)
        self.assertEqual(o.price,D('.01'))
        self.assertNotEqual(o.purpose,'partial_profit')

    def test_last_contract_is_retained(self):
        self.e.wallet.lots[0].quantity=D(1)
        self.e.wallet.lots[0].recovery_cost=D('.10')
        self.s.step();self.assertEqual(self.exits(),[])

    def test_profit_exit_cannot_arrive_after_freeze(self):
        self.book('.40','100',1780.95);self.s.step()
        o=self.exits()[0];self.e.advance(1781.11)
        self.assertEqual(o.status,'cancelled')
        self.assertEqual(self.e.wallet.lots[0].recovery_proceeds,0)
        self.s.step();self.assertEqual(len(self.exits()),1)

    def test_pre_entry_book_cannot_trigger_profit_exit(self):
        self.e.books[T].at=1000
        self.s.step();self.assertEqual(self.exits(),[])

    def test_entry_fees_are_included_in_recovery_goal(self):
        self.e.wallet.lots[0].recovery_cost=D('10.63')
        self.s.step();self.assertEqual(self.exits()[0].quantity,28)

    def test_recovery_progress_survives_checkpoint(self):
        self.s.step();self.e.advance(1000.35)
        profiles=[dict(series='KXBTC15M',name='BTC',contracts=100)]
        fleet=StrategyFleet(self.e,profiles)
        data=json.loads(json.dumps(encode(self.e,fleet),default=str))
        restored=Engine(Mock());f=StrategyFleet(restored,profiles);restore(restored,f,data)
        self.assertEqual(restored.wallet.lots[0].recovery_proceeds,D('10.3464'))
        self.assertEqual(restored.wallet.lots[0].recovery_cost,10)
        self.assertEqual(restored.wallet.stat(T).profit_contracts,27)

    def test_legacy_checkpoint_does_not_invent_recovery_or_metrics(self):
        profiles=[dict(series='KXBTC15M',name='BTC',contracts=100)]
        self.e.wallet.stat(T)
        data=json.loads(json.dumps(encode(self.e,StrategyFleet(self.e,profiles)),default=str))
        for lot in data['wallet']['lots']:
            lot.pop('recovery_cost');lot.pop('recovery_proceeds')
        for stat in data['wallet']['stats'].values():
            for key in ('maker_requested','maker_filled','taker_requested','ioc_unfilled','profit_contracts',
                    'profit_proceeds','execution_orders','rejected_orders','ioc_attempts','partial_iocs','execution_measured'):
                stat.pop(key)
        restored=Engine(Mock());restore(restored,StrategyFleet(restored,profiles),data)
        self.assertEqual(restored.wallet.lots[0].recovery_cost,0)
        self.assertIsNone(execution_report(restored,T)['maker_fill_rate'])
        self.assertFalse(execution_report(restored,T)['measured'])

    def test_offsetting_buy_reduces_remaining_recovery_target(self):
        self.e.wallet.fill(T,'no','buy',D(20),D('.1'),D(0),1,'offset')
        self.assertEqual(self.e.wallet.lots[0].recovery_cost,8)
        self.assertEqual(self.e.wallet.lots[0].quantity,80)

if __name__=='__main__':unittest.main()
