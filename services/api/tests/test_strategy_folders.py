"""Trading invariants: no touch fills, conditional learning, covered sets and reset isolation."""
import json,tempfile,unittest,time,threading
from pathlib import Path
from decimal import Decimal as D
from unittest.mock import Mock
from services.paper_demo.shadow.core import Engine,FeePolicy,Wallet,Lot
from services.paper_demo.shadow.sequential import SequentialStrategy,PairModel
from services.paper_demo.shadow.complete_set import CompleteSetStrategy
from services.paper_demo.shadow.experiments import ExperimentSuite
from services.paper_demo.shadow.folders import initialize_folders,FOLDERS
from services.api.tests import test_demo_postgres as fixture

class QuietAudit:
    def __init__(self):self.path=Path(tempfile.mkdtemp());self.events=[]
    def log(self,now,kind,wallet,**fields):self.events.append((kind,fields))

def profile(series='KXBTC15M',id='seq_btc',strategy='sequential'):
    return dict(series=series,id=id,name=id,contracts=10,revision=1,folder_id=strategy,strategy=strategy)

def market(e,t='KXBTC15M-test',yes='.49',no='.49',close=1000,qty='100'):
    e.add_market(dict(ticker=t,close=close,open=100,event_ticker='TEST',bot_id='seq_btc'),FeePolicy())
    b=e.books[t];b.levels={'yes':{D(yes):D(qty)},'no':{D(no):D(qty)}};b.valid=True;b.at=e.now
    return b

class StrategyTests(unittest.TestCase):
    def engine(self):return Engine(QuietAudit(),cash='1000',latency_ms=150,toxic_fill_probability=0)
    def test_fresh_model_does_not_invent_probabilities(self):
        self.assertIsNone(PairModel().estimate('unseen')['completion_probability'])
    def test_completion_probability_is_conditional_on_first_fill(self):
        m=PairModel()
        for _ in range(80):m.observe('x',False,False,0)
        for _ in range(20):m.observe('x',True,True,.1)
        p=m.estimate('x')
        self.assertLess(p['first_probability'],.22)
        self.assertGreater(p['completion_probability'],.95)
    def test_losses_on_failed_pairs_reduce_score(self):
        m=PairModel()
        for _ in range(8):m.observe('x',True,True,.1)
        for _ in range(2):m.observe('x',True,False,-.45)
        self.assertLess(m.estimate('x')['expected_net'],0)
    def test_only_touching_a_price_never_fills_an_order(self):
        e=self.engine();e.advance(200);market(e)
        i=e.place('KXBTC15M-test','yes','buy',D(1),D('.45'))
        e.advance(201)
        self.assertEqual(e.orders[i].status,'resting');self.assertFalse(e.wallet.lots)
    def test_complementary_fills_realize_ten_cents_and_net_inventory(self):
        w=Wallet(D(1000));w.fill('T','yes','buy',D(10),D('.45'),D(0),1,'a')
        w.fill('T','no','buy',D(10),D('.45'),D(0),1,'b')
        self.assertEqual(w.cash,D(1001));self.assertFalse(w.lots)
        self.assertEqual(w.stat('T').gross,D(1))
    def test_partial_complement_only_closes_matching_quantity(self):
        w=Wallet(D(1000));w.fill('T','yes','buy',D(10),D('.45'),D(0),1,'a')
        w.fill('T','no','buy',D(3),D('.45'),D(0),1,'b')
        self.assertEqual(w.inventory('T','yes'),D(7));self.assertEqual(w.stat('T').gross,D('.3'))
    def test_paper_exploration_is_labeled_and_limited_to_one_contract(self):
        e=self.engine();e.advance(200);market(e)
        b=SequentialStrategy(e,profile(),PairModel());b.step();e.now=221;e.books['KXBTC15M-test'].at=221;b.step()
        a=b.attempts['KXBTC15M-test'];self.assertEqual(a['mode'],'paper_exploration');self.assertEqual(a['quantity'],'1')
        self.assertIsNone(a['estimate']['completion_probability'])
    def test_first_fill_cancels_extra_entries_but_preserves_hedge_intent(self):
        e=self.engine();e.advance(200);market(e)
        b=SequentialStrategy(e,profile(),PairModel());b.step();e.now=221;e.books['KXBTC15M-test'].at=221;b.step();e.advance(222)
        o=next(iter(e.orders.values()));e.fill(o,D(1),o.price,'TEST')
        self.assertTrue(b.attempts[o.ticker]['first']);self.assertTrue(e.pending)
        e.advance(223);e.books[o.ticker].at=223;b.step()
        hedge=[o for o in e.orders.values() if o.status=='pending']
        self.assertEqual(len(hedge),1);self.assertEqual(hedge[0].side,'no')
    def test_no_false_complete_set_from_unverified_exclusivity(self):
        e=self.engine();b=CompleteSetStrategy(e,profile('ALL','set_scanner','complete_set'))
        self.assertFalse(b.register(dict(event_ticker='TEST',mutually_exclusive=False),[dict(ticker='A',event_ticker='TEST'),dict(ticker='B',event_ticker='TEST')]))
        self.assertFalse(b.register(dict(event_ticker='TEST',mutually_exclusive=True),[dict(ticker='A',event_ticker='TEST'),dict(ticker='B',event_ticker='OTHER')]))
    def test_no_basket_covers_even_an_unlisted_outcome(self):
        payouts=[sum(0 if winner==i else 1 for i in range(3)) for winner in (0,1,2,None)]
        self.assertEqual(min(payouts),2)
    def test_complete_set_uses_takers_with_latency_not_instant_profit(self):
        e=self.engine();e.advance(200)
        for t in ('A','B'):market(e,t,yes='.60',no='.39')
        b=CompleteSetStrategy(e,profile('ALL','set_scanner','complete_set'))
        b.register(dict(event_ticker='TEST',mutually_exclusive=True),[dict(ticker=t,event_ticker='TEST') for t in ('A','B')]);b.step()
        self.assertEqual(len(e.orders),2);self.assertTrue(all(not o.maker for o in e.orders.values()))
        self.assertEqual(e.wallet.cash,D(1000));self.assertFalse(e.wallet.lots)
        e.advance(201);b.step()
        self.assertTrue(b.attempts['TEST']['complete']);self.assertEqual(len(e.wallet.lots),2)
        self.assertEqual(e.wallet.stat('A').gross,0)
    def test_fees_can_eliminate_apparent_set_profit(self):
        e=self.engine();e.advance(200)
        for t in ('A','B'):market(e,t,yes='.51',no='.48')
        b=CompleteSetStrategy(e,profile('ALL','set_scanner','complete_set'))
        b.register(dict(event_ticker='TEST',mutually_exclusive=True),[dict(ticker=t,event_ticker='TEST') for t in ('A','B')]);b.step()
        self.assertFalse(e.orders)
    def test_disappearing_second_leg_is_not_called_completed(self):
        e=self.engine();e.advance(200)
        for t in ('A','B'):market(e,t,yes='.60',no='.39')
        b=CompleteSetStrategy(e,profile('ALL','set_scanner','complete_set'))
        b.register(dict(event_ticker='TEST',mutually_exclusive=True),[dict(ticker=t,event_ticker='TEST') for t in ('A','B')]);b.step()
        e.books['B'].levels={'yes':{},'no':{}};e.advance(201);b.step()
        self.assertFalse(b.attempts['TEST']['complete'])
        self.assertTrue(any(k=='SET_INCOMPLETE' for k,f in e.audit.events))

class FavoriteTests(unittest.TestCase):
    def test_only_high_price_passive_entries_are_submitted(self):
        from services.paper_demo.shadow.favorites import FavoritesStrategy
        e=Engine(QuietAudit(),cash='1000');e.advance(200)
        b=FavoritesStrategy(e,profile(series='KXBTCD',strategy='favorites'))
        market(e,'KXBTCD-test',yes='.79',no='.19');b.step()
        order=next(iter(e.orders.values()))
        self.assertTrue(order.maker);self.assertEqual(order.side,'yes');self.assertEqual(order.price,D('.80'))
        self.assertTrue(b.exit_allowed(order))
    def test_middle_price_and_last_minute_are_not_favorite_entries(self):
        from services.paper_demo.shadow.favorites import FavoritesStrategy
        e=Engine(QuietAudit(),cash='1000');e.advance(200)
        b=FavoritesStrategy(e,profile(series='KXBTCD',strategy='favorites'));market(e,'KXBTCD-test');b.step();self.assertFalse(e.orders)
        e.now=950;e.books['KXBTCD-test'].at=950;e.books['KXBTCD-test'].levels={'yes':{D('.79'):D(10)},'no':{D('.19'):D(10)}}
        b.step();self.assertFalse(e.orders)

@unittest.skipUnless(fixture.URL,'Disposable PostgreSQL required')
class FolderPostgres(unittest.TestCase):
    setUp=fixture.DemoPostgres.setUp;tearDown=fixture.DemoPostgres.tearDown
    @classmethod
    def setUpClass(cls):fixture.DemoPostgres.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):fixture.DemoPostgres.tearDownClass.__func__(cls)
    def seed(self):
        from services.paper_demo.shadow.migrate import initialize
        initialize(self.demo,lambda:None);initialize_folders(self.demo,lambda:None)
    def test_migration_pauses_originals_and_is_idempotent(self):
        self.seed();initialize_folders(self.demo,lambda:None)
        rows=self.demo.rows('shadow/bot/',100)
        self.assertEqual(len(rows),85)
        old=[r for r in rows if r['parameters']['folder_id']=='convexity']
        self.assertEqual(len(old),28);self.assertTrue(all(r['progress']['desired']=='paused' for r in old))
        self.assertEqual(len(self.demo.rows('shadow/folder/',10)),4)
    def test_folder_control_does_not_resume_other_strategies(self):
        self.seed();r=self.client.post('/demo/shadow/bulk',json=dict(action='pause',folder_id='sequential'))
        self.assertEqual(r.status_code,200)
        rows=self.demo.rows('shadow/bot/',100)
        self.assertTrue(all(r['progress']['desired']=='paused' for r in rows if r['parameters']['folder_id']=='sequential'))
        self.assertEqual(self.demo.get('shadow/bot/set_scanner')['progress']['desired'],'running')
    def test_reset_request_is_idempotent_and_keeps_other_folders(self):
        self.seed();body=dict(request_id='test-reset-request-unique')
        for _ in range(2):self.assertEqual(self.client.post('/demo/shadow/folders/sequential/reset',json=body).status_code,200)
        self.assertEqual(len(self.demo.rows('shadow/command/',100)),1)
        self.assertEqual(self.client.post('/demo/shadow/folders/complete_set/reset',json=body).status_code,409)
    def test_workspace_returns_strategy_folders_without_losing_legacy_bots(self):
        self.seed();r=self.client.get('/demo/shadow/workspace');self.assertEqual(r.status_code,200)
        data=r.json();self.assertEqual(len(data['bots']),85);self.assertEqual(len(data['folders']),4)
        self.assertFalse(data['real_orders_enabled'])

    def test_worker_reset_archives_and_checkpoints_one_session_atomically(self):
        from services.paper_demo.shadow.host import HostedRun
        from services.paper_demo.shadow.storage import HostedAudit
        from services.paper_demo.shadow.core import StrategyFleet
        from services.paper_demo.shadow.migrate import profiles
        self.seed();w=HostedRun.__new__(HostedRun);w.store=self.demo
        w.audit=HostedAudit(self.demo,lambda:None);w.engine=Engine(w.audit,cash='1000')
        w.strategy=StrategyFleet(w.engine,profiles());w.audit.engine=w.engine;w.audit.fleet=w.strategy
        w.experiments=ExperimentSuite(w,self.demo.rows('shadow/bot/',100));w.audit.experiments=w.experiments
        e=w.experiments.portfolios['sequential'][0];e.now=200;market(e)
        e.wallet.fill('KXBTC15M-test','yes','buy',D(1),D('.45'),D(0),1,'before-reset')
        other=w.experiments.portfolios['favorites'][0];other.wallet.cash=D(990)
        session=self.demo.get('shadow/folder/sequential')['progress']['session']
        request_id='worker-reset-idempotent-123'
        self.client.post('/demo/shadow/folders/sequential/reset',json=dict(request_id=request_id))
        w.audit.command_key='demo/shadow/command/'+request_id
        w.reset_folder('sequential')
        archived=self.demo.get('shadow/session/sequential/'+session)
        self.assertEqual(archived['progress']['engine']['wallet']['cash'],'999.55')
        checkpoint=self.demo.get('shadow/checkpoint')['progress']['experiments']
        self.assertEqual(checkpoint['sequential']['engine']['wallet']['cash'],'1000')
        self.assertFalse(checkpoint['sequential']['engine']['wallet']['lots'])
        self.assertEqual(checkpoint['favorites']['engine']['wallet']['cash'],'990')
        self.assertTrue(self.demo.get('shadow/command/'+request_id)['progress']['done'])
        self.client.post('/demo/shadow/folders/sequential/reset',json=dict(request_id=request_id))
        self.assertTrue(self.demo.get('shadow/command/'+request_id)['progress']['done'])
        self.assertEqual(self.client.get('/demo/shadow/sessions').status_code,200)

class SuiteTests(unittest.TestCase):
    def suite(self):
        rows=[dict(parameters=profile(strategy='sequential'),progress=dict(desired='running')),
              dict(parameters=profile(id='fav_btc',strategy='favorites'),progress=dict(desired='running')),
              dict(parameters=profile('ALL','set_scanner','complete_set'),progress=dict(desired='running'))]
        host=Mock();host.audit=QuietAudit();host.verified_fees.schedule.return_value=('quadratic',1)
        return ExperimentSuite(host,rows),rows
    def test_all_new_portfolios_start_with_independent_thousand(self):
        suite,rows=self.suite()
        for e,f,ps in suite.portfolios.values():self.assertEqual(e.wallet.cash,D(1000))
        e=suite.portfolios['sequential'][0];e.wallet.cash-=D(5)
        self.assertEqual(suite.portfolios['favorites'][0].wallet.cash,D(1000))
    def test_reset_clears_one_account_and_preserves_other_inventory_and_cash(self):
        suite,rows=self.suite();seq=suite.portfolios['sequential'][0];fav=suite.portfolios['favorites'][0]
        market(seq);market(fav)
        seq.wallet.fill('KXBTC15M-test','yes','buy',D(1),D('.45'),D(0),1,'old')
        fav.wallet.fill('KXBTC15M-test','yes','buy',D(1),D('.8'),D(0),1,'other')
        previous=json.loads(json.dumps(suite.state()['sequential'],default=str))
        suite.reset('sequential')
        self.assertEqual(seq.wallet.cash,D(1000));self.assertFalse(seq.wallet.lots)
        self.assertEqual(fav.wallet.cash,D('999.2'));self.assertEqual(len(fav.wallet.lots),1)
        self.assertEqual(previous['engine']['wallet']['lots'][0]['quantity'],'1')
        self.assertIn('KXBTC15M-test',suite.portfolios['sequential'][1].halted)
    def test_checkpoint_restores_inventory_models_and_cancels_uncertain_orders(self):
        suite,rows=self.suite();e=suite.portfolios['sequential'][0];e.now=200;market(e)
        e.wallet.fill('KXBTC15M-test','yes','buy',D(1),D('.45'),D(0),1,'old')
        suite.models['sequential'].observe('x',True,False,-.45)
        e.place('KXBTC15M-test','no','buy',D(1),D('.45'))
        state=json.loads(json.dumps(suite.state(),default=str))
        restored=ExperimentSuite(suite.host,rows,state)
        new=restored.portfolios['sequential'][0]
        self.assertEqual(new.wallet.cash,e.wallet.cash);self.assertEqual(len(new.wallet.lots),1)
        self.assertTrue(all(o.status=='cancelled' for o in new.orders.values()))
        self.assertEqual(restored.models['sequential'].estimate('x')['samples'],1)
    def test_shared_market_events_create_independent_bot_ownership(self):
        suite,rows=self.suite()
        payload=dict(market=dict(ticker='KXBTC15M-test',close=1000,open=100,event_ticker='TEST'),taker_multiplier='1',maker_multiplier='0')
        suite.handle('market',payload,200)
        self.assertEqual(suite.portfolios['sequential'][0].markets['KXBTC15M-test']['bot_id'],'seq_btc')
        self.assertEqual(suite.portfolios['favorites'][0].markets['KXBTC15M-test']['bot_id'],'fav_btc')
        result=suite.snapshot(200)
        self.assertEqual(result['sequential']['accounting']['portfolio']['total_pnl'],'0')

class RiskTests(unittest.TestCase):
    def test_no_cold_start_continuation_probability_is_invented(self):
        from services.paper_demo.shadow.risk import ExitEvidence
        self.assertIsNone(ExitEvidence().estimate('x')['upper'])
    def test_missing_depth_is_unknown_not_a_zero_dollar_sale(self):
        from services.paper_demo.shadow.risk import liquidation
        e=Engine(QuietAudit());e.now=200;market(e,qty='1')
        self.assertIsNone(liquidation(e,'KXBTC15M-test','yes',D(10)))
    def test_loss_budget_compares_net_liquidation_and_entry_fees(self):
        from services.paper_demo.shadow.risk import ExitEvidence,assess
        e=Engine(QuietAudit(),cash='1000');e.now=200;market(e,yes='.30',no='.69')
        e.wallet.fill('KXBTC15M-test','yes','buy',D(10),D('.9'),D('.1'),1,'a')
        a=dict(quantity='10',loss_budget='5')
        reason=assess(e,'KXBTC15M-test',e.wallet.lots,a,ExitEvidence())
        self.assertIn('loss budget',reason)
    def test_evidence_exit_requires_sale_to_beat_upper_continuation(self):
        from services.paper_demo.shadow.risk import ExitEvidence,assess
        e=Engine(QuietAudit(),cash='1000');e.now=200;market(e,yes='.80',no='.19')
        e.wallet.fill('KXBTC15M-test','yes','buy',D(1),D('.85'),D(0),1,'a')
        model=ExitEvidence();key=model.key('KXBTC15M',D('.8'),800)
        for _ in range(500):model.observe(key,.3)
        reason=assess(e,'KXBTC15M-test',e.wallet.lots,dict(quantity='1',loss_budget='5'),model)
        self.assertIn('continuation',reason)
    def test_partial_fills_receive_proportional_loss_budget(self):
        from services.paper_demo.shadow.risk import ExitEvidence,assess
        e=Engine(QuietAudit(),cash='1000');e.now=200;market(e,yes='.30',no='.69')
        e.wallet.fill('KXBTC15M-test','yes','buy',D(1),D('.9'),D(0),1,'a')
        reason=assess(e,'KXBTC15M-test',e.wallet.lots,dict(quantity='10',loss_budget='5'),ExitEvidence())
        self.assertIn('loss budget',reason)
    def test_settlement_without_completing_pair_is_a_failure_even_if_it_wins(self):
        e=Engine(QuietAudit(),cash='1000');e.now=200;market(e)
        b=SequentialStrategy(e,profile(),PairModel());b.attempts['KXBTC15M-test']=dict(first=True,recorded=False,key='x',quantity='1',baseline='0',first_quantity='1',first_cost='.45')
        e.wallet.fill('KXBTC15M-test','yes','buy',D(1),D('.45'),D(0),1,'a')
        e.wallet.settle('KXBTC15M-test',D(1));e.markets['KXBTC15M-test']['paid']=True
        b.step();self.assertFalse(b.attempts['KXBTC15M-test']['completed'])
        self.assertEqual(b.model.cells['x']['completed'],0)

class PortfolioRetirementTests(SuiteTests):
    def test_retirement_preserves_realized_totals_and_frees_hot_execution_state(self):
        suite,rows=self.suite();e,f,ps=suite.portfolios['sequential'];e.now=200;market(e)
        e.wallet.fill('KXBTC15M-test','yes','buy',D(1),D('.45'),D(0),1,'a')
        e.wallet.fill('KXBTC15M-test','no','buy',D(1),D('.45'),D(0),1,'b')
        e.markets['KXBTC15M-test']['paid']=True
        before=suite.snapshot(200)['sequential']['bots']['seq_btc']['net_realized_pnl']
        suite.maintain()
        self.assertFalse(e.markets);self.assertEqual(suite.snapshot(201)['sequential']['bots']['seq_btc']['net_realized_pnl'],before)
        self.assertEqual(suite.snapshot(201)['sequential']['accounting']['portfolio']['realized_pnl'],before)

class CompleteRetirementTests(SuiteTests):
    def test_completed_basket_retires_as_a_group_without_breaking_remaining_legs(self):
        suite,rows=self.suite();e,f,ps=suite.portfolios['complete_set'];e.now=200
        b=next(iter(f.bots.values()))
        for t in ('A','B'):
            market(e,t,yes='.60',no='.39');e.markets[t]['bot_id']='set_scanner'
            e.wallet.fill(t,'no','buy',D(1),D('.4'),D(0),1,t)
        b.groups['TEST']=['A','B'];b.attempts['TEST']=dict(tickers=['A','B'],quantity='1',orders=[],complete=True,checked=True,finished=False)
        e.wallet.settle('A',D(1));e.markets['A']['paid']=True
        suite.maintain();self.assertEqual(len(e.markets),2)
        e.wallet.settle('B',D(0));e.markets['B']['paid']=True
        suite.maintain();self.assertFalse(e.markets);self.assertFalse(b.groups)
        self.assertEqual(suite.snapshot(201)['complete_set']['bots']['set_scanner']['net_realized_pnl'],'0.2')

class SequentialTimingTests(unittest.TestCase):
    def test_high_frequency_ticks_do_not_prevent_twenty_second_warmup(self):
        e=Engine(QuietAudit(),cash='1000');e.now=200;market(e)
        b=SequentialStrategy(e,profile(),PairModel())
        for i in range(451):
            e.now=200+i*.05;e.books['KXBTC15M-test'].at=e.now;b.step()
        self.assertIn('KXBTC15M-test',b.attempts)
    def test_marketable_profitable_hedge_uses_taker_with_fees(self):
        e=Engine(QuietAudit(),cash='1000');e.now=200;market(e,yes='.60',no='.39')
        b=SequentialStrategy(e,profile(),PairModel())
        e.wallet.fill('KXBTC15M-test','yes','buy',D(1),D('.45'),D(0),1,'entry')
        b.attempts['KXBTC15M-test']=dict(first=True,recorded=False,yes='.45',no='.45',quantity='1',loss_budget='5',completion_deadline=970,entry_deadline=260)
        b.step();o=next(iter(e.orders.values()))
        self.assertEqual(o.action,'buy');self.assertEqual(o.side,'no');self.assertFalse(o.maker)
        self.assertEqual(o.price,D('.40'))
