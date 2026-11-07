"""Execution, evidence and persistence checks for the paper-only comparison."""
import json,unittest
from decimal import Decimal as D
from unittest.mock import Mock
from services.api.tests.test_strategy_folders import QuietAudit,market,profile
from services.api.tests import test_strategy_folders as fixture
from services.paper_demo.shadow.core import Engine,FeePolicy
from services.paper_demo.shadow.sequential import SequentialStrategy,PairModel
from services.paper_demo.shadow.sequential_adaptive import AdaptiveSequentialStrategy,AdaptivePairModel
from services.paper_demo.shadow.sequential_comparison import initialize_comparison,SEQUENTIAL_FOLDERS
from services.paper_demo.shadow.experiments import ExperimentSuite

T='KXBTC15M-test'

class ExecutionTests(unittest.TestCase):
    def setup_pair(self,variant='flexible',quantity='2',depth='100',multiplier='1'):
        e=Engine(QuietAudit(),cash='1000',latency_ms=150,toxic_fill_probability=0);e.advance(200)
        market(e,yes='.52',no='.49',qty=depth)
        e.fees[T]=FeePolicy(D(multiplier),D(0))
        cls=AdaptiveSequentialStrategy if variant=='adaptive' else SequentialStrategy
        b=cls(e,dict(profile(),variant=variant),AdaptivePairModel() if variant=='adaptive' else PairModel())
        e.fill_callback=b.on_fill
        q=D(quantity);e.wallet.fill(T,'yes','buy',q,D('.45'),D(0),1,'first')
        b.attempts[T]=dict(ticker=T,key='x',first=True,first_side='yes',first_quantity=quantity,first_cost=str(q*D('.45')),
            yes='.45',no='.45',quantity=quantity,baseline='0',started_at=200,completion_deadline=970,loss_budget='5')
        return e,b
    def test_flexible_completes_above_original_bid_with_actual_fees(self):
        e,b=self.setup_pair();b.step()
        order=next(iter(e.orders.values()))
        self.assertFalse(order.maker);self.assertGreater(order.price,D('.45'))
        e.advance(201);e.books[T].at=201;b.step()
        self.assertFalse(e.wallet.lots);self.assertTrue(b.attempts[T]['completed'])
        self.assertGreaterEqual(e.wallet.cash-D(1000),D('.04'))
        self.assertEqual(b.trial['completed'],1)
    def test_baseline_keeps_original_second_bid(self):
        e,b=self.setup_pair('baseline');b.step()
        order=next(iter(e.orders.values()));self.assertTrue(order.maker);self.assertEqual(order.price,D('.45'))
    def test_fees_or_insufficient_full_depth_prevent_taker_completion(self):
        for kwargs in (dict(multiplier='10'),dict(depth='1')):
            with self.subTest(kwargs=kwargs):
                e,b=self.setup_pair(**kwargs);b.step();self.assertTrue(all(o.maker for o in e.orders.values()))
    def test_cancellation_acknowledgement_prevents_duplicate_hedges(self):
        e,b=self.setup_pair();e.place(T,'no','buy',D(2),D('.45'),expiry=970)
        e.advance(201);e.books[T].at=201;b.step()
        self.assertEqual(len(e.orders),1)
        e.advance(202);e.books[T].at=202;b.step()
        self.assertEqual(sum(o.status in ('pending','resting') for o in e.orders.values()),1)
        self.assertEqual(sum(not o.maker for o in e.orders.values()),1)
    def test_price_jump_after_submission_cannot_buy_beyond_profit_limit(self):
        e,b=self.setup_pair();b.step();limit=next(iter(e.orders.values())).price
        e.books[T].levels={'yes':{D('.29'):D(100)},'no':{D('.70'):D(100)}}
        e.advance(201)
        self.assertEqual(e.wallet.inventory(T,'yes'),D(2));self.assertEqual(e.wallet.inventory(T,'no'),0)
        self.assertLess(limit,D('.71'))
    def test_partial_ioc_remains_open_and_never_claims_full_completion(self):
        e,b=self.setup_pair();b.step()
        e.books[T].levels={'yes':{D('.52'):D(1)},'no':{D('.49'):D(100)}}
        e.advance(201);e.books[T].at=201;b.step()
        self.assertEqual(e.wallet.inventory(T,'yes'),1);self.assertFalse(b.attempts[T].get('recorded'))
    def test_adaptive_candidates_follow_asymmetric_book(self):
        e,b=self.setup_pair('adaptive');e.books[T].levels={'yes':{D('.70'):D(100)},'no':{D('.29'):D(100)}}
        self.assertIn((65,24),b.candidates(e.books[T]))
        self.assertTrue(all(yp!=np for yp,np in b.candidates(e.books[T])))
        self.assertLess(b.deadline(e.markets[T],200,.1),b.deadline(e.markets[T],200,0))
    def test_no_tiny_sample_promotion_or_invented_continuation_probability(self):
        m=AdaptivePairModel();key='entry|15m|1|quiet|2|2|BTC'
        for _ in range(20):m.observe(key,True,True,.1)
        self.assertIsNone(m.estimate(key)['lower_net'])
        self.assertIsNone(m.state_estimate('state|15m|1|yes|0|1|0|0')['completion_probability'])
    def test_pooled_observations_and_adverse_outcomes_reduce_estimates(self):
        m=AdaptivePairModel();key='entry|15m|1|quiet|2|2|BTC';other=key.rsplit('|',1)[0]+'|ETH'
        for _ in range(100):m.observe(key,True,False,-.45)
        self.assertEqual(m.estimate(other)['samples'],100);self.assertLess(m.estimate(other)['lower_net'],0)
        state='state|15m|1|yes|1|1|0|0'
        for _ in range(100):m.observe_state(state,False,.1)
        estimate=m.state_estimate(state)
        self.assertLess(estimate['completion_probability'],.02);self.assertLess(estimate['recovery_upper'],.4)
    def test_observing_same_continuation_state_repeatedly_is_one_training_sample(self):
        e,b=self.setup_pair('adaptive');a=b.attempts[T]
        for _ in range(40):b.continuation(T,e.wallet.lots,a)
        self.assertEqual(len(a['continuation_states']),1)
        e.wallet.fill(T,'yes','sell',D(2),D('.52'),D(0),1,'exit');a['failed']=True;b.finish(T)
        key=next(iter(a['continuation_states']));self.assertEqual(b.model.state_estimate(key)['samples'],1)
    def test_gap_results_count_financially_but_do_not_train_adaptive_model(self):
        e,b=self.setup_pair('adaptive');a=b.attempts[T];b.continuation(T,e.wallet.lots,a)
        e.wallet.fill(T,'yes','sell',D(2),D('.20'),D(0),1,'exit');a['failed']=True;e.wallet.stat(T).valid=False;b.finish(T)
        self.assertAlmostEqual(b.trial['unmatched_losses'],.5);self.assertFalse(b.model.cells)

class ComparisonSuiteTests(unittest.TestCase):
    def suite(self):
        rows=[dict(parameters=dict(profile(id=folder),folder_id=folder,variant=folder.removeprefix('sequential_'),comparison_started_at=100),progress=dict(desired='running')) for folder in SEQUENTIAL_FOLDERS]
        rows.append(dict(parameters=profile('ALL','set_scanner','complete_set'),progress=dict(desired='running')))
        host=Mock();host.audit=QuietAudit();host.verified_fees.schedule.return_value=('quadratic',1)
        return ExperimentSuite(host,rows),host,rows
    def test_shared_feed_and_restart_keep_three_wallets_and_models_isolated(self):
        suite,host,rows=self.suite()
        suite.handle('market',dict(market=dict(ticker=T,open=100,close=1000),taker_multiplier='1',maker_multiplier='0'),200)
        for folder in SEQUENTIAL_FOLDERS:self.assertIn(T,suite.portfolios[folder][0].markets)
        suite.portfolios['sequential_flexible'][0].wallet.cash=D(999)
        suite.portfolios['sequential_adaptive'][1].bots['KXBTC15M'].trial['unmatched_losses']=.5
        restored=ExperimentSuite(host,rows,json.loads(json.dumps(suite.state(),default=str)))
        self.assertEqual(restored.portfolios['sequential'][0].wallet.cash,1000)
        self.assertEqual(restored.portfolios['sequential_flexible'][0].wallet.cash,999)
        self.assertEqual(restored.portfolios['sequential_adaptive'][1].bots['KXBTC15M'].trial['unmatched_losses'],.5)
    def test_flexible_inherits_baseline_learning_once_without_sharing_mutable_model(self):
        suite,host,rows=self.suite();suite.models['sequential'].observe('existing',True,True,.1)
        previous=json.loads(json.dumps(suite.state(),default=str));previous.pop('sequential_flexible')
        restored=ExperimentSuite(host,rows,previous)
        self.assertEqual(restored.models['sequential_flexible'].estimate('existing')['samples'],1)
        restored.models['sequential_flexible'].observe('existing',True,False,-.4)
        self.assertEqual(restored.models['sequential'].estimate('existing')['samples'],1)
    def test_comparison_excludes_earlier_baseline_attempts_and_handles_unpriced_positions(self):
        suite,_,_=self.suite();e,f,_=suite.portfolios['sequential'];e.now=200;market(e)
        b=f.bots['KXBTC15M'];b.attempts[T]=dict(ticker=T,started_at=50,baseline='0')
        e.wallet.fill(T,'yes','buy',D(1),D('.45'),D(0),1,'old')
        self.assertEqual(suite.snapshot(200)['sequential']['comparison']['net_pnl'],0)
        b.attempts[T]['started_at']=200;e.books[T].valid=False
        result=suite.snapshot(200)['sequential']['comparison'];self.assertIsNone(result['net_pnl']);self.assertTrue(result['drawdown_incomplete'])

@unittest.skipUnless(fixture.fixture.URL,'Disposable PostgreSQL required')
class ComparisonMigration(unittest.TestCase):
    setUp=fixture.FolderPostgres.setUp;tearDown=fixture.FolderPostgres.tearDown;seed=fixture.FolderPostgres.seed
    @classmethod
    def setUpClass(cls):fixture.FolderPostgres.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):fixture.FolderPostgres.tearDownClass.__func__(cls)
    def test_migration_is_idempotent_preserves_baseline_and_supports_controls(self):
        self.seed();before=self.demo.get('shadow/folder/sequential')['progress']
        initialize_comparison(self.demo,lambda:None);initialize_comparison(self.demo,lambda:None)
        self.assertEqual(self.demo.get('shadow/folder/sequential')['progress'],before)
        self.assertEqual(len(self.demo.rows('shadow/bot/',400)),141)
        data=self.client.get('/demo/shadow/workspace').json();self.assertEqual(len(data['folders']),6);self.assertEqual(len(data['bots']),141)
        for folder in SEQUENTIAL_FOLDERS:
            self.assertEqual(self.client.post('/demo/shadow/bulk',json=dict(action='pause',folder_id=folder)).status_code,200)
            self.assertEqual(self.client.post('/demo/shadow/folders/'+folder+'/reset',json=dict(request_id='comparison-reset-'+folder)).status_code,200)
