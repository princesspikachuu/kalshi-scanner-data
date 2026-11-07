import contextlib
from decimal import Decimal as D
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from services.paper_demo.shadow.core import Audit, Book, ConvexityStrategy, Engine, FeePolicy, Lot, Wallet, phase_at


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.audit = Audit(self.temp.name)
        self.e = Engine(self.audit, cash='100', toxic_fill_probability=0)
        self.e.advance(1000)
        self.e.add_market(dict(ticker='KXBTC15M-test', close=1900, open=1000), FeePolicy())
        self.snapshot()

    def tearDown(self):
        self.audit.close()
        self.temp.cleanup()

    def snapshot(self, yes=None, no=None, at=1000, seq=1):
        self.e.handle('kalshi', dict(type='orderbook_snapshot', sid=1, seq=seq,
            sending_ts_ms=at*1000, msg=dict(market_ticker='KXBTC15M-test',
                yes_dollars_fp=yes if yes is not None else [['.10','100']],
                no_dollars_fp=no if no is not None else [['.80','100']])), at)

    def trade(self, price='.10', qty='100', at=1000.2, ident='a', taker='no'):
        self.e.handle('kalshi', dict(type='trade',msg=dict(market_ticker='KXBTC15M-test',
            trade_id=ident,yes_price_dollars=price,count_fp=qty,taker_side=taker,ts_ms=at*1000)),at)

    def maker(self, qty='10', price='.10'):
        ident = self.e.place('KXBTC15M-test','yes','buy',D(qty),D(price))
        self.e.advance(1000.15)
        return self.e.orders[ident]

    def test_latency_and_back_of_queue(self):
        ident = self.e.place('KXBTC15M-test','yes','buy',D(10),D('.10'))
        self.e.advance(1000.149)
        self.assertEqual(self.e.orders[ident].status,'pending')
        self.e.advance(1000.15)
        self.assertEqual(self.e.orders[ident].ahead,D(100))

    def test_touch_does_not_fill(self):
        order=self.maker()
        self.snapshot(at=1000.2,seq=2)
        self.assertEqual(order.remaining,10)
        self.assertEqual(self.e.wallet.cash,100)

    def test_exact_queue_exhaustion_requires_extra_volume_for_own_fill(self):
        order=self.maker()
        self.trade(qty='100')
        self.assertEqual(order.ahead,0)
        self.assertEqual(order.remaining,10)
        self.trade(qty='4',at=1000.3,ident='b')
        self.assertEqual(order.remaining,6)
        self.assertEqual(self.e.wallet.inventory(order.ticker,'yes'),4)

    def test_visible_cancellation_does_not_advance_queue(self):
        order=self.maker()
        self.e.handle('kalshi',dict(type='orderbook_delta',sid=1,seq=2,sending_ts_ms=1000200,
            msg=dict(market_ticker=order.ticker,side='yes',price_dollars='.10',delta_fp='-90')),1000.2)
        self.assertEqual(order.ahead,100)

    def test_wrong_aggressor_does_not_fill_bid(self):
        order=self.maker()
        self.trade(qty='200',taker='yes')
        self.assertEqual(order.remaining,10)

    def test_print_before_arrival_does_not_fill(self):
        order=self.maker()
        self.e.handle('kalshi',dict(type='trade',msg=dict(market_ticker=order.ticker,
            trade_id='old',yes_price_dollars='.10',count_fp='1000',taker_side='no',ts_ms=1000100)),1000.2)
        self.assertEqual(order.remaining,10)

    def test_trade_through_is_volume_bounded(self):
        order=self.maker()
        self.trade(price='.09',qty='3')
        self.assertEqual(order.remaining,7)
        self.assertEqual(self.e.wallet.inventory(order.ticker,'yes'),3)

    def test_duplicate_print_does_not_double_count(self):
        order=self.maker()
        self.trade(qty='103')
        self.trade(qty='103',at=1000.3)
        self.assertEqual(order.remaining,7)

    def test_multiple_virtual_orders_share_print_volume(self):
        a=self.maker()
        b_id=self.e.place(a.ticker,'yes','buy',D(10),D('.10'))
        self.e.advance(1000.3)
        self.trade(qty='115',at=1000.4)
        b=self.e.orders[b_id]
        self.assertEqual(a.remaining,0)
        self.assertEqual(b.remaining,5)
        self.assertEqual(self.e.wallet.inventory(a.ticker,'yes'),15)

    def test_higher_order_fill_does_not_also_advance_lower_queue(self):
        high=self.maker()
        lower_id=self.e.place(high.ticker,'yes','buy',D(10),D('.09'))
        self.e.books[high.ticker].levels['yes'][D('.09')]=D(100)
        self.e.advance(1000.3)
        self.trade(price='.09',qty='10',at=1000.4)
        self.assertEqual(high.remaining,0)
        self.assertEqual(self.e.orders[lower_id].ahead,100)
        self.assertEqual(self.e.orders[lower_id].remaining,10)

    def test_cancel_latency_allows_fill_before_ack(self):
        order=self.maker()
        self.e.cancel(order.id)
        self.trade(qty='105',at=1000.2)
        self.assertEqual(order.remaining,5)
        self.e.advance(1000.3)
        self.assertEqual(order.status,'cancelled')

    def test_post_only_rechecked_at_delayed_arrival(self):
        ident=self.e.place('KXBTC15M-test','yes','buy',D(10),D('.10'))
        self.snapshot(yes=[['.04','100']],no=[['.95','100']],at=1000.1,seq=2)
        self.e.advance(1000.15)
        self.assertEqual(self.e.orders[ident].status,'rejected')

    def test_maker_reserves_cash(self):
        self.e.place('KXBTC15M-test','yes','buy',D(900),D('.10'))
        second=self.e.place('KXBTC15M-test','yes','buy',D(200),D('.10'))
        self.assertEqual(self.e.orders[second].status,'rejected')
        self.assertEqual(self.e.available(),10)

    def test_taker_sweeps_layers_and_fees(self):
        self.e.wallet.fill('KXBTC15M-test','yes','buy',D(100),D('.1'),D(0),1,'lot')
        self.snapshot(yes=[['.50','10'],['.49','40'],['.48','50']], no=[['.49','100']])
        ident=self.e.place('KXBTC15M-test','yes','sell',D(100),D('.01'),maker=False)
        self.e.advance(1000.15)
        # 10*.50 + 40*.49 + 50*.48 = 48.60. Per-layer fees, not fee at VWAP.
        fee=sum((FeePolicy().charge(D(q),D(p)) for p,q in [('.50','10'),('.49','40'),('.48','50')]),D(0))
        self.assertEqual(self.e.wallet.cash,D('90')+D('48.60')-fee)
        self.assertEqual(self.e.orders[ident].remaining,0)
        self.assertEqual(self.e.wallet.stat('KXBTC15M-test').taker_slippage,D('1.40'))

    def test_taker_uses_arrival_book_not_trigger_book(self):
        self.e.wallet.fill('KXBTC15M-test','yes','buy',D(10),D('.1'),D(0),1,'lot')
        self.snapshot(yes=[['.50','10']],no=[['.49','100']])
        ident=self.e.place('KXBTC15M-test','yes','sell',D(10),D('.01'),maker=False)
        self.snapshot(yes=[['.40','10']],no=[['.59','100']],at=1000.1,seq=2)
        self.e.advance(1000.15)
        self.assertEqual(self.e.orders[ident].remaining,0)
        self.assertEqual(self.e.wallet.stat('KXBTC15M-test').taker_slippage,1)
        self.assertEqual(self.e.wallet.cash,D('102.8320'))

    def test_ioc_partial_never_invents_depth(self):
        self.e.wallet.fill('KXBTC15M-test','yes','buy',D(100),D('.1'),D(0),1,'lot')
        self.snapshot(yes=[['.50','10']], no=[['.49','100']])
        ident=self.e.place('KXBTC15M-test','yes','sell',D(100),D('.01'),maker=False)
        self.e.advance(1000.15)
        self.assertEqual(self.e.orders[ident].remaining,90)
        self.assertEqual(self.e.orders[ident].status,'ioc_cancelled')
        self.assertEqual(self.e.wallet.inventory('KXBTC15M-test','yes'),90)

    def test_same_depth_not_reused_by_second_ioc(self):
        self.e.wallet.fill('KXBTC15M-test','yes','buy',D(100),D('.1'),D(0),1,'lot')
        self.snapshot(yes=[['.50','10']], no=[['.49','100']])
        a=self.e.place('KXBTC15M-test','yes','sell',D(10),D('.01'),maker=False)
        b=self.e.place('KXBTC15M-test','yes','sell',D(10),D('.01'),maker=False)
        self.e.advance(1000.15)
        self.assertEqual(self.e.orders[a].remaining,0)
        self.assertEqual(self.e.orders[b].remaining,10)

    def test_snapshot_does_not_give_same_consumed_depth_back(self):
        self.e.wallet.fill('KXBTC15M-test','yes','buy',D(100),D('.1'),D(0),1,'lot')
        self.snapshot(yes=[['.50','10']],no=[['.49','100']])
        self.e.place('KXBTC15M-test','yes','sell',D(10),D('.01'),maker=False)
        self.e.advance(1000.15)
        self.snapshot(yes=[['.50','10']],no=[['.49','100']],at=1000.2,seq=2)
        second=self.e.place('KXBTC15M-test','yes','sell',D(10),D('.01'),maker=False)
        self.e.advance(1000.35)
        self.assertEqual(self.e.orders[second].remaining,10)

    def test_refill_logged_and_excluded_from_pnl(self):
        self.e.refill(D(50))
        self.assertEqual(self.e.wallet.cash,150)
        self.assertEqual(self.e.wallet.stat('KXBTC15M-test').gross,0)
        self.assertIn('REFILL',(Path(self.temp.name)/'events.csv').read_text())

    def test_invalid_print_never_changes_wallet(self):
        order=self.maker()
        with self.assertRaises(ValueError):
            self.trade(qty='-1')
        self.assertEqual(self.e.wallet.cash,100)
        self.assertEqual(order.remaining,10)

    def test_toxic_stress_is_flagged_and_volume_limited(self):
        order=self.maker()
        self.e.toxic_probability=1
        self.e.spot.toxic_until['yes']=1010
        self.e.spot.episode=1
        self.trade(qty='3')
        self.assertEqual(order.remaining,7)
        self.assertEqual(self.e.wallet.stat(order.ticker).stress_fills,3)

    def test_book_gap_invalidates_cycle(self):
        self.e.handle('kalshi',dict(type='orderbook_delta',sid=1,seq=3,sending_ts_ms=1000200,
            msg=dict(market_ticker='KXBTC15M-test',side='yes',price_dollars='.10',delta_fp='1')),1000.2)
        self.assertFalse(self.e.books['KXBTC15M-test'].valid)
        self.assertFalse(self.e.wallet.stat('KXBTC15M-test').valid)

    def test_stale_book_rejects_taker(self):
        self.e.advance(1004)
        ident=self.e.place('KXBTC15M-test','yes','sell',D(1),D('.01'),maker=False)
        self.e.advance(1004.15)
        self.assertEqual(self.e.orders[ident].status,'rejected')

    def test_settlement_requires_explicit_ws(self):
        with self.assertRaises(ValueError):
            self.e.handle('settlement',dict(ticker='KXBTC15M-test',yes_payout='1'),1001)

    def test_settlement_payout_and_report(self):
        self.e.wallet.fill('KXBTC15M-test','yes','buy',D(10),D('.10'),D(0),1,'lot')
        with contextlib.redirect_stdout(io.StringIO()):
            self.e.handle('kalshi',dict(type='market_lifecycle_v2',msg=dict(
                market_ticker='KXBTC15M-test',event_type='settled')),1901)
        with contextlib.redirect_stdout(io.StringIO()):
            self.e.handle('settlement',dict(ticker='KXBTC15M-test',yes_payout='1'),1901.1)
            report=self.e.report('KXBTC15M-test',True)
        self.assertEqual(self.e.wallet.cash,109)
        self.assertEqual(D(report['net_realized_pnl']),9)
        self.assertEqual(D(report['win_rate']),100)

    def test_strategy_phase_one_and_phase_two(self):
        strategy=ConvexityStrategy(self.e,1,require_spot_warmup=False)
        strategy.step()
        self.assertEqual(len(self.e.orders),2)
        self.assertTrue(all(o.price==D('.10') for o in self.e.orders.values()))
        self.e.handle('clock',{},1601)
        self.snapshot(at=1601,seq=2)
        phase_two=[o for o in self.e.orders.values() if o.phase==2]
        # Clock gap marks cycle invalid rather than trading on invented intermediate history.
        self.assertFalse(self.e.wallet.stat('KXBTC15M-test').valid)
        self.assertEqual(phase_two,[])

    def test_arming_rollover_and_freeze(self):
        strategy=ConvexityStrategy(self.e,1,require_spot_warmup=False)
        self.e.wallet.lots=[Lot('lot','KXBTC15M-test','yes',D(1),D('.1'),D(0),1,True)]
        self.e.advance(1601)
        self.snapshot(yes=[['.44','20']],no=[['.55','10']],at=1601,seq=2)
        self.assertTrue(self.e.wallet.lots[0].is_armed)
        self.assertTrue(self.e.wallet.lots[0].exit_requested)
        self.e.advance(1781)
        for o in self.e.orders.values():
            if not o.maker:
                self.assertFalse(strategy.exit_allowed(o))

    def test_pre_entry_quote_cannot_arm_a_new_fill(self):
        self.snapshot(yes=[['.45','100']],no=[['.4','100']],at=1000,seq=2)
        strategy=ConvexityStrategy(self.e,1,require_spot_warmup=False)
        strategy.step();self.e.advance(1000.15)
        self.trade(price='.09',qty='1',at=1000.2)
        lot=self.e.wallet.lots[0]
        self.assertEqual(lot.acquired_at,1000.2);self.assertFalse(lot.is_armed)
        self.snapshot(yes=[['.2','100']],no=[['.7','100']],at=1000.3,seq=3)
        self.assertFalse(lot.exit_requested)
        self.assertFalse(any(not o.maker for o in self.e.orders.values()))
        self.snapshot(yes=[['.41','100']],no=[['.5','100']],at=1000.4,seq=4)
        self.assertTrue(lot.is_armed)
        self.snapshot(yes=[['.3','100']],no=[['.6','100']],at=1000.5,seq=5)
        self.assertTrue(lot.exit_requested)
        self.assertTrue(any(not o.maker and o.status=='pending' for o in self.e.orders.values()))


class AccountingTests(unittest.TestCase):
    def test_fee_count_and_rounding(self):
        self.assertEqual(FeePolicy().charge(D(100),D('.5')),D('1.7500'))
        self.assertEqual(FeePolicy().charge(D(1),D('.01')),D('.0007'))
        self.assertEqual(FeePolicy().charge(D(100),D('.1'),True),0)

    def test_fees_not_at_vwap(self):
        f=FeePolicy()
        actual=f.charge(D(50),D('.1'))+f.charge(D(50),D('.9'))
        self.assertNotEqual(actual,f.charge(D(100),D('.5')))

    def test_fee_metadata_unsupported_fails(self):
        with self.assertRaises(ValueError):
            FeePolicy.from_series(dict(fee_type='flat',fee_multiplier=1))
        self.assertEqual(FeePolicy.from_series(dict(fee_type='quadratic',fee_multiplier=2)).taker_multiplier,2)

    def test_complete_set_netting(self):
        w=Wallet(D(50))
        w.fill('T','yes','buy',D(100),D('.1'),D(0),1,'a')
        w.fill('T','no','buy',D(100),D('.1'),D(0),1,'b')
        self.assertEqual(w.cash,130)
        self.assertEqual(w.lots,[])
        self.assertEqual(w.stat('T').gross,80)

    def test_deposit_is_not_profit(self):
        w=Wallet(D(50))
        self.assertEqual(w.stat('T').gross,0)

    def test_clock_boundaries(self):
        self.assertEqual(phase_at(1900,1600.99),1)
        self.assertEqual(phase_at(1900,1601),2)
        self.assertEqual(phase_at(1900,1781),3)

    def test_spot_math_detects_directional_two_sigma_and_safety_valve(self):
        from services.paper_demo.shadow.core import Spot
        spot=Spot()
        for second in range(60):
            spot.add(100+second%2,1000+second,1000+second)
        self.assertTrue(spot.ready(1059))
        no_until=spot.toxic_until['no']
        spot.add(90,1060,1060)
        self.assertTrue(spot.spike)
        self.assertGreater(spot.toxic_until['yes'],1060)
        self.assertEqual(spot.toxic_until['no'],no_until)

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            note=Path(root)/'events.csv'
            note.write_text('keep me')
            with self.assertRaises(ValueError):
                Audit(root)
            self.assertEqual(note.read_text(),'keep me')

    def test_network_client_rejects_account_routes(self):
        from services.paper_demo.shadow.runner import ProductionData
        client=ProductionData()
        for path in ('/portfolio/orders','/portfolio/balance','https://evil.example','/markets/../portfolio'):
            with self.assertRaises(ValueError):
                client.get(path)


class ReplayTests(unittest.TestCase):
    def test_same_tape_same_seed_identical_executions_and_known_pnl(self):
        from types import SimpleNamespace
        from services.api.tests.shadow_example import generate
        from services.paper_demo.shadow.runner import replay
        with tempfile.TemporaryDirectory() as root:
            tape=Path(root)/'synthetic.jsonl'
            generate(tape)
            for name in ('a','b'):
                args=SimpleNamespace(capture=str(tape),output=str(Path(root)/name),
                                     latency_ms=None,seed=None,toxic_probability=None)
                with contextlib.redirect_stdout(io.StringIO()):
                    replay(args)
            self.assertEqual((Path(root)/'a/events.csv').read_bytes(),
                             (Path(root)/'b/events.csv').read_bytes())
            reports=(Path(root)/'a/reports.jsonl').read_text().splitlines()
            report=json.loads(reports[-1])
            # Cost recovery splits the old full stop into two IOC fills, each
            # charged and rounded separately. Identical tapes remain deterministic.
            self.assertEqual(D(report['net_realized_pnl']),D('29.3066'))
            self.assertTrue(report['final'])
            self.assertTrue(report['data_valid'])

    def test_no_network_needed_for_replay(self):
        from types import SimpleNamespace
        from services.api.tests.shadow_example import generate
        from services.paper_demo.shadow.runner import replay
        with tempfile.TemporaryDirectory() as root:
            tape=Path(root)/'tape.jsonl'
            generate(tape)
            with patch('requests.Session',side_effect=AssertionError('network forbidden')):
                with contextlib.redirect_stdout(io.StringIO()):
                    replay(SimpleNamespace(capture=str(tape),output=str(Path(root)/'run'),
                                           latency_ms=None,seed=None,toxic_probability=None))



class FleetTests(unittest.TestCase):
    setUp=SimulationTests.setUp
    tearDown=SimulationTests.tearDown
    snapshot=SimulationTests.snapshot
    trade=SimulationTests.trade
    def test_registry_has_28_distinct_paused_profiles(self):
        profiles=json.loads(Path(__import__('services.paper_demo.shadow.core',fromlist=['x']).__file__).with_name('market_profiles.json').read_text())
        self.assertEqual(len(profiles),28)
        self.assertEqual(len({p['series'] for p in profiles}),28)
        self.assertTrue(all(not p['live_enabled'] for p in profiles))

    def test_fill_locks_only_its_own_market_instance(self):
        from services.paper_demo.shadow.core import StrategyFleet
        profiles=json.loads(Path(__import__('services.paper_demo.shadow.core',fromlist=['x']).__file__).with_name('market_profiles.json').read_text())[:2]
        fleet=StrategyFleet(self.e,profiles)
        for bot in fleet.bots.values():bot.require_spot=False
        self.e.add_market(dict(ticker='KXETH15M-test',close=1900,open=1000),FeePolicy())
        self.e.handle('kalshi',dict(type='orderbook_snapshot',sid=2,seq=1,sending_ts_ms=1000000,
            msg=dict(market_ticker='KXETH15M-test',yes_dollars_fp=[['.1','100']],
                     no_dollars_fp=[['.8','100']])),1000)
        fleet.step()
        self.assertEqual(len(self.e.orders),4)
        self.e.advance(1000.15)
        self.trade(qty='105',at=1000.2)
        self.assertIn(('KXBTC15M-test',1),fleet.bots['KXBTC15M'].locked)
        self.assertEqual(fleet.bots['KXETH15M'].locked,set())
        eth=[o for o in self.e.orders.values() if o.ticker=='KXETH15M-test']
        self.assertTrue(all(o.remaining==100 for o in eth))


if __name__=='__main__':
    unittest.main()
