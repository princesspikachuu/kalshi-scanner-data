"""Causal execution and accounting acceptance for the isolated scalper portfolios."""
import json
import unittest
from decimal import Decimal as D
from unittest.mock import Mock
from services.api.tests.test_strategy_folders import QuietAudit,market,profile,ready_suite
from services.paper_demo.shadow.core import Engine,FeePolicy
from services.paper_demo.shadow.scalper import VolatilityScalper,ScalperEngine,SCALPER_FOLDERS,CONFIGS
from services.paper_demo.shadow.scalper_install import initialize_scalper,scalper_profiles
from services.paper_demo.shadow.experiments import ExperimentSuite
from services.paper_demo.shadow.accounting import snapshot

T='KXBTC15M-test'

def p(folder='scalper_fixed'):
    return dict(profile(id=folder+'_btc',strategy='volatility_scalper'),folder_id=folder,contracts=5,market_category='crypto',underlying='BTC')

class ScalperTests(unittest.TestCase):
    def setup_bot(self,folder='scalper_fixed',cls=ScalperEngine):
        e=cls(QuietAudit(),cash='1000',latency_ms=150,toxic_fill_probability=0,seed=17)
        e.advance(200);market(e)
        e.markets[T]['bot_id']=p(folder)['id']
        b=VolatilityScalper(e,p(folder))
        return e,b
    def tick(self,e,b,at,price):
        e.books[T].at=at;e.books[T].valid=True;e.books[T].snapshot_at=at
        e.advance(at)
        e.books[T].levels={'yes':{D(str(price)):D(100)},'no':{1-D(str(price))-D('.02'):D(100)}}
        b.step(T)
    def warm(self,e,b,mirror=False):
        for i,price in enumerate((.60,.55,.50,.45,.46)):
            self.tick(e,b,200+2*i,1-price if mirror else price)
    def fill_entry(self,e,b,quantity=5):
        order=next(o for o in e.orders.values() if o.action=='buy')
        e.books[T].at=208.2;e.advance(208.2)
        if order.maker:
            # A true public aggressive print, including queue ahead.
            e.trade(T,dict(trade_id='entry',taker_side='no' if order.side=='yes' else 'yes',yes_price_dollars=str(order.price if order.side=='yes' else 1-order.price),count_fp=str(order.ahead+D(quantity)),ts_ms=208200))
        return order
    def test_warmup_reversal_submits_and_no_quote_touch_fill(self):
        e,b=self.setup_bot();self.warm(e,b)
        self.assertEqual(len(e.orders),1)
        order=next(iter(e.orders.values()));self.assertTrue(order.maker)
        e.books[T].at=208.2;e.advance(208.2)
        self.assertEqual(order.status,'resting');self.assertFalse(e.wallet.lots)
        self.assertGreater(order.ahead,D(100))
    def test_yes_and_no_are_evaluated_independently_without_stacked_exposure(self):
        for mirror in (False,True):
            e,b=self.setup_bot();self.warm(e,b,mirror)
            order=self.fill_entry(e,b)
            self.assertEqual(order.side,'no' if mirror else 'yes')
            self.tick(e,b,210,.50)
            self.assertFalse(any(o.purpose=='scalper_entry' and o.id!=order.id for o in e.orders.values()))
    def test_real_print_partial_fill_cancels_remaining_before_exiting(self):
        e,b=self.setup_bot();self.warm(e,b);order=self.fill_entry(e,b,2)
        self.assertEqual(e.wallet.inventory(T,'yes'),2)
        self.assertEqual(order.remaining,3)
        self.assertTrue(any(item[2]=='cancel' for item in e.pending))
        self.tick(e,b,209,.60)
        self.assertEqual(order.status,'cancelled')
        self.assertTrue(any(o.purpose=='scalper_maker_profit_exit' for o in e.orders.values()))
    def test_full_round_trip_reconciles_cash_fees_and_repeated_cycle(self):
        e,b=self.setup_bot('volatility_scalper');self.warm(e,b);self.fill_entry(e,b)
        self.tick(e,b,210,.60)
        e.books[T].at=210.2;e.advance(210.2)
        self.assertTrue(b.attempts[T].get('partial_taken'))
        self.tick(e,b,212,.64)
        e.books[T].at=212.2;e.advance(212.2)
        self.assertFalse(e.wallet.lots)
        self.assertEqual(b.research['totals']['completed'],1)
        money=snapshot(e,[p()],e.now)['portfolio']
        self.assertEqual(D(money['realized_pnl']),e.wallet.stat(T).gross-e.wallet.stat(T).realized_fees)
        self.assertAlmostEqual(float(e.wallet.cash-1000),b.research['totals']['net'])
        for i,price in enumerate((.60,.55,.50,.45,.46)):
            self.tick(e,b,330+2*i,price)
        self.assertEqual(sum(o.action=='buy' for o in e.orders.values()),2)
    def test_mixed_taker_has_fees_and_disappearing_depth_does_not_fill(self):
        e,b=self.setup_bot('volatility_scalper');self.warm(e,b)
        o=next(iter(e.orders.values()));self.assertFalse(o.maker)
        e.books[T].levels={'yes':{},'no':{}}
        e.books[T].at=208.2;e.advance(208.2)
        self.assertFalse(e.wallet.lots);self.assertEqual(o.status,'ioc_cancelled')
    def test_taker_partial_depth_does_not_create_fictitious_full_fill(self):
        e,b=self.setup_bot('volatility_scalper');self.warm(e,b)
        o=next(iter(e.orders.values()))
        e.books[T].levels['no'][D('.52')]=D(1)
        e.books[T].at=208.2;e.advance(208.2)
        self.assertEqual(e.wallet.inventory(T,'yes'),1)
        self.assertEqual(o.remaining,4)
        self.assertGreater(e.wallet.stat(T).fees_paid,0)
    def test_stop_and_near_close_exit_bypass_minimum_hold(self):
        for near_close in (False,True):
            e,b=self.setup_bot();self.warm(e,b);self.fill_entry(e,b)
            self.tick(e,b,950 if near_close else 209,.30)
            self.assertTrue(any(o.action=='sell' for o in e.orders.values()))
            self.assertIn(b.attempts[T]['exit_reason'],('time_liquidation','stop_loss'))
    def test_failed_liquidation_and_settlement_are_explicit_and_count_losses(self):
        e,b=self.setup_bot();self.warm(e,b);self.fill_entry(e,b)
        e.books[T].valid=False;e.advance(990);b.step(T)
        self.assertTrue(any(kind=='SCALPER_LIQUIDATION_BLOCKED' for kind,_ in e.audit.events))
        e.wallet.settle(T,D(0));e.markets[T].update(paid=True,yes_payout_confirmed='0');b.step(T)
        self.assertEqual(b.research['totals']['settlement_carryovers'],1)
        self.assertLess(b.research['totals']['net'],0)
        self.assertEqual(b.research['totals']['completed'],0)
    def test_missing_ask_does_not_crash_held_position_management(self):
        e,b=self.setup_bot();self.warm(e,b);self.fill_entry(e,b)
        e.books[T].levels['no'].clear()
        e.books[T].at=209;e.advance(209);b.step(T)
        self.assertTrue(e.wallet.lots)
        self.assertTrue(any(o.purpose=='scalper_maker_profit_exit' for o in e.orders.values()))

    def test_maker_profit_exit_nets_existing_lot_without_opposite_exposure(self):
        e,b=self.setup_bot();self.warm(e,b);self.fill_entry(e,b)
        self.tick(e,b,209,.48)
        exit_order=next(o for o in e.orders.values() if o.purpose=='scalper_maker_profit_exit')
        e.books[T].at=209.2;e.advance(209.2)
        self.assertEqual(exit_order.status,'resting')
        e.trade(T,dict(trade_id='exit',taker_side='yes',yes_price_dollars=str(1-exit_order.price),count_fp=str(exit_order.ahead+5),ts_ms=209200))
        self.assertFalse(e.wallet.lots)
        self.assertEqual(b.research['totals']['completed'],1)
        self.assertGreater(b.research['totals']['net'],0)
        self.assertEqual(b.research['totals']['entry_fills'],1)
        self.assertEqual(b.research['totals']['exit_fills'],1)
    def test_history_is_causal_and_bounded_and_does_not_trade_on_future_rebound(self):
        e,b=self.setup_bot()
        for i,price in enumerate((.60,.55,.50,.45)):
            self.tick(e,b,200+2*i,price)
            self.assertFalse(e.orders)
        self.tick(e,b,208,.46);self.assertEqual(len(e.orders),1)
        self.assertTrue(all(at<=e.now for at,_ in b.history[T]))
    def test_resource_backlog_prevents_entries_without_disabling_protective_exits(self):
        e,b=self.setup_bot();b.resource_paused=True;self.warm(e,b)
        self.assertFalse(e.orders)
        self.assertIn('worker_processing_backlog',b.research['totals']['rejections'])
        b.resource_paused=False;self.tick(e,b,210,.47);self.assertTrue(e.orders)
    def test_pause_prevents_new_entries_but_still_exits_held_inventory(self):
        e,b=self.setup_bot();self.warm(e,b);self.fill_entry(e,b);b.enabled=False
        self.tick(e,b,210,.30)
        self.assertTrue(any(o.action=='sell' for o in e.orders.values()))
    def test_portfolio_state_survives_restart_without_reusing_old_history(self):
        rows=[dict(parameters=p(folder),progress=dict(desired='running')) for folder in SCALPER_FOLDERS]
        rows.append(dict(parameters=profile('ALL','set_scanner','complete_set'),progress=dict(desired='running')))
        host=Mock();host.audit=QuietAudit();host.verified_fees.schedule.return_value=('quadratic',1)
        suite=ready_suite(host,rows)
        suite.handle('market',dict(market=dict(ticker=T,open=100,close=1000),taker_multiplier='1',maker_multiplier='0'),200)
        for folder in SCALPER_FOLDERS:self.assertIn(T,suite.portfolios[folder][0].markets)
        e,f,_=suite.portfolios['scalper_fixed'];b=f.bots['KXBTC15M'];self.warm(e,b);self.fill_entry(e,b)
        b.research['totals']['completed']=7
        prior=json.loads(json.dumps(suite.state(),default=str))
        rebuilt=ready_suite(host,rows,prior)
        re,rf,_=rebuilt.portfolios['scalper_fixed'];rb=rf.bots['KXBTC15M']
        self.assertEqual(rb.research['totals']['completed'],7)
        self.assertEqual(re.wallet.inventory(T,'yes'),5)
        self.assertFalse(rb.history)
        self.assertFalse(rb.attempts[T]['verified'])
        self.assertEqual(rebuilt.portfolios['volatility_scalper'][0].wallet.cash,1000)
    def test_config_and_market_split_match_across_variants_without_learning(self):
        e,b=self.setup_bot();self.warm(e,b)
        config=b.config.copy();before=b.metadata(T)
        b.research['totals']['completed']=10000
        self.assertEqual(config,b.config)
        self.assertIn(before['split'],('training','validation'))
        self.assertTrue(all(not p.get('live_enabled') for p in scalper_profiles()))
    def test_entry_observations_align_to_clock_frames_and_exits_stay_event_driven(self):
        e,b=self.setup_bot()
        def book(at,seq,price):
            e.handle('kalshi',dict(type='orderbook_snapshot',sid=1,seq=seq,msg=dict(market_ticker=T,yes_dollars_fp=[[str(price),'100']],no_dollars_fp=[[str(1-D(str(price))-D('.02')),'100']])),at)
        book(201,1,.6)
        self.assertFalse(b.history)
        e.handle('clock',{},202)
        self.assertEqual(len(b.history[T]),1)
        book(202.1,2,.5);e.handle('clock',{},202.2)
        self.assertEqual(len(b.history[T]),1)
        e.handle('clock',{},204)
        self.assertEqual(len(b.history[T]),2)
        # A held position's stop reacts to the next book event, not its frame.
        e,b=self.setup_bot();self.warm(e,b);self.fill_entry(e,b)
        book(209,1,.20)
        self.assertTrue(any(o.action=='sell' for o in e.orders.values()))

    def test_opportunity_batch_preserves_every_variant_and_existing_events(self):
        from services.paper_demo.shadow.storage import HostedAudit
        from services.paper_demo.shadow.core import StrategyFleet
        audit=HostedAudit(Mock(),lambda:None);audit.engine=Engine(audit);audit.fleet=StrategyFleet(audit.engine,[])
        records=[(200,'EXPERIMENT',dict(folder_id=folder,experiment_kind='SCALPER_OPPORTUNITY',ticker=T,side=side,reason='no_signal',details=json.dumps(dict(value=folder+side)))) for folder in SCALPER_FOLDERS for side in ('yes','no')]
        records.append((200,'UNCHANGED',dict(ticker=T,reason='prior strategy')))
        batch,commands,events=audit.prepare(records)
        self.assertEqual(len(batch),3)
        self.assertEqual(len(events[0]['decisions']),6)
        self.assertEqual(events[1]['event'],'UNCHANGED')
        self.assertEqual({d['folder_id'] for d in events[0]['decisions']},set(SCALPER_FOLDERS))

    def test_installation_is_idempotent_and_never_updates_existing_rows(self):
        store=Mock();store.get.return_value={'installed':True};guard=Mock()
        initialize_scalper(store,guard)
        guard.assert_not_called();store.pool.connection.assert_not_called()
    def test_momentum_and_fees_reject_unexecutable_candidates(self):
        e,b=self.setup_bot();self.warm(e,b)
        reasons=b.research['totals']['rejections']
        self.assertIn('no_reversal_or_range_signal',reasons)
        f=b.features(T,'yes');f.update(trend=-.50,last_change=-.05,displacement=.10)
        self.assertTrue(b.decision(f)[1])

from services.api.tests import test_demo_postgres as db_fixture
@unittest.skipUnless(db_fixture.URL,'Disposable PostgreSQL is required')
class ScalperPostgresTests(unittest.TestCase):
    setUp=db_fixture.DemoPostgres.setUp
    tearDown=db_fixture.DemoPostgres.tearDown
    @classmethod
    def setUpClass(cls):db_fixture.DemoPostgres.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):db_fixture.DemoPostgres.tearDownClass.__func__(cls)
    def test_additive_install_controls_and_durable_research_snapshot(self):
        from services.paper_demo.shadow.storage import HostedAudit,put
        from services.paper_demo.shadow.core import StrategyFleet
        self.demo.put('shadow/installed',dict(real_orders_enabled=False))
        self.demo.put('shadow/bot/existing',dict(desired='paused'),parameters=dict(id='existing',revision=7,contracts=19,series='OLD',name='Prior bot'))
        self.demo.put('shadow/checkpoint',dict(preserve='old-checkpoint'))
        initialize_scalper(self.demo,lambda:None)
        initialize_scalper(self.demo,lambda:None)
        self.assertEqual(self.demo.get('shadow/bot/existing')['parameters']['revision'],7)
        self.assertEqual(self.demo.get('shadow/checkpoint')['progress'],dict(preserve='old-checkpoint'))
        rows=self.demo.rows('shadow/bot/',800)
        new=[r for r in rows if r['parameters'].get('strategy')=='volatility_scalper']
        self.assertEqual(len(new),3*len(scalper_profiles()))
        for folder in SCALPER_FOLDERS:
            response=self.client.post('/demo/shadow/bulk',json=dict(action='pause',folder_id=folder))
            self.assertEqual(response.status_code,200)
            self.assertTrue(all(r['progress']['desired']=='paused' for r in self.demo.rows('shadow/bot/',800) if r['parameters'].get('folder_id')==folder))
        self.assertEqual(self.demo.get('shadow/bot/existing')['progress']['desired'],'paused')
        host=Mock();host.audit=HostedAudit(self.demo,lambda:None)
        host.audit.engine=Engine(host.audit,cash='1000');host.audit.fleet=StrategyFleet(host.audit.engine,[])
        suite=ready_suite(host,rows);host.audit.experiments=suite
        bot=suite.portfolios['volatility_scalper'][1].bots['KXBTC15M']
        bot.research['totals']['completed']=23
        host.audit.checkpoint()
        checkpoint=self.demo.get('shadow/checkpoint')['progress']
        rebuilt=ready_suite(host,rows,checkpoint['experiments'])
        self.assertEqual(rebuilt.portfolios['volatility_scalper'][1].bots['KXBTC15M'].research['totals']['completed'],23)
        self.assertFalse(checkpoint['experiments']['volatility_scalper']['engine']['wallet']['lots'])
