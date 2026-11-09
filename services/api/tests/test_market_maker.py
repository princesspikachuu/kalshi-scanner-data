"""Execution, isolation, bounded discovery and recovery for maker/scalper upgrades."""
import asyncio,json,math,time,unittest
from decimal import Decimal as D
from unittest.mock import Mock,AsyncMock,patch
from services.api.tests.test_strategy_folders import QuietAudit,market,ready_suite
T='KXBTC15M-test'
from datetime import datetime,timezone
def iso(at):return datetime.fromtimestamp(at,timezone.utc).isoformat()
from services.paper_demo.shadow.core import Engine,FeePolicy
from services.paper_demo.shadow.scalper import ScalperEngine,VolatilityScalper
from services.paper_demo.shadow.market_maker import MarketMaker,MM_FOLDERS,profiles,category,schedule_times,maker_once,initialize_market_maker
from services.paper_demo.shadow.execution import committed,size,depth_quote,choose
from services.paper_demo.shadow.microstructure import MarketTape
from services.paper_demo.shadow.accounting import snapshot

class MakerTests(unittest.TestCase):
    def bot(self,side='yes',config=None):
        e=ScalperEngine(QuietAudit(),cash='1000',latency_ms=150,toxic_fill_probability=0,seed=1);e.advance(200)
        profile=dict(next(profiles()),revision=1,config=dict(next(profiles())['config'],**(dict(max_price=.5) if side=='no' and config is None else config or {})))
        market(e,T,yes='.42' if side=='yes' else '.52',no='.52' if side=='yes' else '.42',close=200000)
        e.markets[T].update(market_maker=True,market_category='politics',bot_id=profile['id'],discovered_at=200)
        b=MarketMaker(e,profile)
        for at in range(200,225,6):
            e.books[T].at=at;e.advance(at);b.step(T)
        return e,b,profile
    def print_fill(self,e,o,ident,quantity=None):
        e.books[T].at=e.now+.2;e.advance(e.now+.2)
        yes_price=o.price if o.side=='yes' else 1-o.price
        taker=o.side if o.action=='sell' else ('no' if o.side=='yes' else 'yes')
        e.trade(T,dict(trade_id=ident,taker_side=taker,yes_price_dollars=str(yes_price),count_fp=str(o.ahead+(quantity or o.remaining)),ts_ms=e.now*1000))
    def test_market_maker_warms_after_three_fresh_samples(self):
        e=ScalperEngine(QuietAudit(),cash='1000',latency_ms=150,toxic_fill_probability=0,seed=1);e.advance(200)
        p=dict(next(profiles()),revision=1)
        market(e,T,yes='.42',no='.52',close=200000)
        e.markets[T].update(market_maker=True,market_category='politics',bot_id=p['id'],discovered_at=200)
        b=MarketMaker(e,p)
        for at in (200,206):
            e.books[T].at=at;e.advance(at);b.step(T)
        self.assertFalse(e.orders);self.assertIn('/3 price samples',b.last_reason)
        e.books[T].at=212;e.advance(212);b.step(T)
        self.assertTrue(e.orders)

    def test_category_filters_exclude_short_crypto_weather_and_sports_games(self):
        cases=[('Politics','Presidential nomination','politics'),('Economics','Next Fed decision','economics'),('Sports','World Cup champion','sports_futures'),('Entertainment','Academy Awards','entertainment'),('Sports','Lakers game winner',None),('Financials','Bitcoin target',None),('Weather','Daily temperature',None),('Economics','Hourly GDP',None),('Other','Something',None)]
        for primary,title,want in cases:self.assertEqual(category(dict(category=primary,title=title)),want)
    def test_maker_round_trip_uses_covered_ask_and_real_prints_on_both_sides(self):
        for side in ('yes','no'):
            e,b,p=self.bot(side);o=next(iter(e.orders.values()));self.assertTrue(o.maker);self.assertEqual(o.side,side)
            before=e.available();self.assertLess(before,1000);self.assertFalse(e.wallet.lots)
            self.print_fill(e,o,'entry');e.books[T].at=e.now+.2;e.advance(e.now+.2);b.step(T)
            sell=next(o for o in e.orders.values() if o.action=='sell');self.assertEqual(sell.side,side);self.assertEqual(sell.reserved,0)
            self.print_fill(e,sell,'exit');self.assertFalse(e.wallet.lots)
            self.assertEqual(b.research['totals']['completed'],1);self.assertGreater(e.wallet.cash,1000)
            self.assertAlmostEqual(float(e.wallet.cash-1000),b.research['totals']['net'])
            self.assertEqual(snapshot(e,[p],e.now)['portfolio']['total_pnl'],str(e.wallet.cash-1000))
    def test_no_touch_fills_and_duplicate_print_does_not_double_fill(self):
        e,b,p=self.bot();o=next(iter(e.orders.values()));e.books[T].at=e.now+.2;e.advance(e.now+.2)
        self.assertFalse(e.wallet.lots)
        print=dict(trade_id='once',taker_side='no',yes_price_dollars=str(o.price),count_fp=str(o.ahead+1),ts_ms=e.now*1000)
        e.trade(T,print);e.trade(T,print);self.assertEqual(e.wallet.inventory(T,'yes'),1)
    def test_partial_maker_sale_keeps_cash_reservation_zero_and_inventory_covered(self):
        e,b,p=self.bot();self.print_fill(e,next(iter(e.orders.values())),'entry');e.books[T].at=e.now+.2;e.advance(e.now+.2);b.step(T)
        sell=next(o for o in e.orders.values() if o.action=='sell');self.print_fill(e,sell,'partial',2)
        self.assertEqual(sell.remaining,3);self.assertEqual(sell.reserved,0);self.assertEqual(e.wallet.inventory(T,'yes'),3)
        with self.assertRaises(ValueError):e.place(T,'yes','sell',D(1),D('.6'),maker=True)
    def test_ordinary_engine_still_rejects_maker_sales(self):
        e=Engine(QuietAudit());e.advance(200);market(e)
        with self.assertRaises(ValueError):e.place(T,'yes','sell',D(1),D('.6'),maker=True)
    def test_cancel_keeps_capital_reserved_until_ack_and_releases_it(self):
        e,b,p=self.bot();o=next(iter(e.orders.values()));reserved=o.reserved;e.cancel(o.id)
        self.assertEqual(e.available(),D(1000)-reserved)
        e.books[T].at=e.now+.2;e.advance(e.now+.2);self.assertEqual(e.available(),1000)
        self.assertEqual(committed(e),0)
    def test_event_and_market_pause_prevent_new_entries_and_preserve_exit_management(self):
        for field in ('paused_markets','scheduled_events'):
            e,b,p=self.bot();o=next(iter(e.orders.values()))
            if field=='paused_markets':p[field]=[T]
            else:e.markets[T][field]=[e.now]
            b.step(T);e.books[T].at=e.now+.2;e.advance(e.now+.2);b.step(T)
            self.assertTrue(e.markets[T]['maker_entry_blocked']);self.assertEqual(o.status,'cancelled')
            self.assertFalse(any(o.status in ('pending','resting') for o in e.orders.values()))
    def test_finite_trade_timestamps_and_block_trades_never_fill(self):
        e,b,p=self.bot();o=next(iter(e.orders.values()));e.books[T].at=e.now+.2;e.advance(e.now+.2)
        for at,block in ((float('nan'),False),(e.now*1000,True)):
            e.trade(T,dict(trade_id=str(at),taker_side='no',yes_price_dollars=str(o.price),count_fp='1000',ts_ms=at,is_block_trade=block))
            self.assertFalse(e.wallet.lots)
    def test_sizing_accounts_for_market_event_category_and_unfilled_orders(self):
        e,b,p=self.bot();f=b.features(T,'yes');c=dict(b.config,market_exposure=.001)
        self.assertEqual(size(e,T,100,D('.44'),f,c),0)
        self.assertGreater(committed(e),0)
        self.assertLess(committed(e),D(1000)*D(str(b.config['portfolio_exposure'])))
    def test_depth_quote_accounts_for_slippage_partial_liquidity_and_fees(self):
        e,b,p=self.bot();e.books[T].levels['yes']={D('.42'):D(2),D('.40'):D(3)}
        q=depth_quote(e,T,'yes','sell',D(10),D('.40'))
        self.assertEqual(q['quantity'],5);self.assertEqual(q['gross'],D('2.04'));self.assertGreater(q['fees'],0)
    def test_fee_policy_rounds_per_fill_and_charges_applicable_maker_multiplier(self):
        f=FeePolicy(D(1),D(1));self.assertEqual(f.charge(D(5),D('.5'),False),D('.0875'));self.assertEqual(f.charge(D(5),D('.5'),True),D('.0219'))
        self.assertEqual(FeePolicy(D(1),D(0)).charge(D(5),D('.5'),True),0)
        self.assertGreater(sum(f.charge(D(1),D('.5'),True) for _ in range(5)),f.charge(D(5),D('.5'),True))
    def test_shared_features_are_bounded_and_computed_once_per_frame(self):
        e,b,p=self.bot();tape=MarketTape()
        for at in range(300,1300,2):
            tape.sample(T,e.books[T],at);tape.sample(T,e.books[T],at)
            tape.trade(T,dict(trade_id=str(at),taker_side='yes',yes_price_dollars='.5',count_fp='1',ts_ms=at*1000),at)
        self.assertEqual(tape.calculations,500);self.assertLessEqual(len(tape.state(T)['prices']),60);self.assertLessEqual(len(tape.state(T)['trades']),256)
        tape.prune(set());self.assertFalse(tape.markets)
    def test_gap_cancels_vulnerable_quotes_and_clears_features(self):
        e,b,p=self.bot();self.assertTrue(e.tape.markets);e.data_gap(T,'sequence gap')
        self.assertFalse(e.books[T].valid);self.assertNotIn(T,e.tape.markets)
        self.assertTrue(any(row[2]=='cancel' for row in e.pending))
    def test_schedules_require_explicit_event_link_and_use_published_dates_only(self):
        self.assertEqual(schedule_times([dict(start_date='2026-11-10T00:00:00Z',related_event_tickers=['OTHER'])],'E'),[])
        self.assertEqual(len(schedule_times([dict(start_date='2026-11-10T00:00:00Z',related_event_tickers=['E'])],'E')),1)
    def test_independent_wallets_restart_recovery_and_covered_sell_display(self):
        rows=[dict(parameters=dict(p,revision=1),progress=dict(desired='running')) for p in profiles()]
        host=Mock();host.audit=QuietAudit();host.verified_fees.schedule.return_value=('quadratic',1)
        suite=ready_suite(host,rows);e,b,p=self.bot()
        suite.handle('maker_market',dict(market=e.markets[T],taker_multiplier='1',maker_multiplier='0'),200)
        e1,f,_=suite.portfolios[MM_FOLDERS[0]];e2,_,_=suite.portfolios[MM_FOLDERS[1]]
        self.assertIs(e1.tape,e2.tape);self.assertIsNot(e1.wallet,e2.wallet)
        book=e1.books[T];book.levels={'yes':{D('.42'):D(100)},'no':{D('.52'):D(100)}};book.valid=True;book.at=200
        e1.wallet.fill(T,'yes','buy',D(5),D('.42'),D(0),1,'entry')
        i=e1.place(T,'yes','sell',D(5),D('.47'),maker=True,purpose='scalper_maker_profit_exit')
        shown=suite.snapshot(200)[MM_FOLDERS[0]]['accounting']['orders'][0]
        self.assertEqual((shown['side'],shown['action'],shown['price']),('yes','sell','0.47'))
        restored=ready_suite(host,rows,json.loads(json.dumps(suite.state(),default=str)))
        self.assertEqual(restored.portfolios[MM_FOLDERS[0]][0].wallet.inventory(T,'yes'),5)
        self.assertEqual(restored.portfolios[MM_FOLDERS[1]][0].wallet.inventory(T,'yes'),0)
        self.assertFalse(restored.portfolios[MM_FOLDERS[0]][0].books[T].valid)
    def test_install_does_not_touch_preexisting_data(self):
        store=Mock();store.get.return_value=True;guard=Mock();initialize_market_maker(store,guard);guard.assert_not_called();store.pool.connection.assert_not_called()

class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_verifies_trade_count_not_volume_and_bounds_reads(self):
        now=time.time();raw=dict(ticker='POL-X',event_ticker='POL',open_time=iso(now-86400),close_time=iso(now+172800),status='active',yes_bid_dollars='.42',no_bid_dollars='.52',volume_24h_fp='1000')
        p=dict(next(profiles()),revision=1);suite=Mock();suite.portfolios={};suite.enabled_profiles.return_value=[p];suite.monitoring_snapshot.return_value=dict(admitting=True);suite.feed_markets.return_value={};suite.search_capacity.return_value=True
        host=Mock();host.experiments=suite;host.put=AsyncMock();host.fee_policy=AsyncMock(return_value=FeePolicy())
        def call(method,path,params=None):
            if path=='/incentive_programs':return dict(incentive_programs=[])
            if path=='/events':return dict(events=[dict(category='Politics',title='Election',series_ticker='POL',markets=[raw])])
            if path=='/markets/trades':return dict(trades=[dict(created_time=iso(now-100),yes_price_dollars='.45')]*29)
            raise AssertionError(path)
        host.verified_data.call.side_effect=call
        # Mock dynamically creates attributes, use explicit initialized state.
        suite.maker_discovery=dict(cursor='',candidates={},reads=0,next_at=0,incentive_at=0,incentives={},settlement_at={},rejected={})
        await maker_once(host)
        host.put.assert_not_called();self.assertEqual(host.verified_data.call.call_count,3)
        event_call=next(c for c in host.verified_data.call.call_args_list if c.args[1]=='/events')
        self.assertEqual(event_call.args[2]['limit'],50)
        self.assertEqual(suite.maker_discovery['candidates']['POL-X']['reason'],'insufficient_executed_trade_frequency')
        await maker_once(host);self.assertEqual(host.verified_data.call.call_count,3)
    async def test_eligible_market_admission_and_incentives_are_metadata_only(self):
        now=time.time();raw=dict(ticker='POL-X',event_ticker='POL',open_time=iso(now-86400),close_time=iso(now+172800),status='active',yes_bid_dollars='.42',no_bid_dollars='.52',volume_24h_fp='1000')
        suite=Mock();suite.portfolios={};suite.enabled_profiles.return_value=[dict(next(profiles()),revision=1)];suite.monitoring_snapshot.return_value=dict(admitting=True);suite.feed_markets.return_value={};suite.search_capacity.return_value=True
        suite.maker_discovery=dict(cursor='',candidates={},reads=0,next_at=0,incentive_at=0,incentives={},settlement_at={},rejected={})
        host=Mock();host.experiments=suite;host.put=AsyncMock();host.fee_policy=AsyncMock(return_value=FeePolicy())
        responses={'/incentive_programs':dict(incentive_programs=[dict(incentive_type='liquidity',market_ticker='POL-X',start_date=iso(now-100),end_date=iso(now+100),id='program',period_reward=100)]),'/events':dict(events=[dict(category='Politics',title='Election',series_ticker='POL',markets=[raw])]),'/markets/trades':dict(trades=[dict(created_time=iso(now-100),yes_price_dollars='.45')]*30),'/markets/POL-X/orderbook':dict(orderbook_fp=dict(yes_dollars=[['.42','100']],no_dollars=[['.52','100']]))}
        host.verified_data.call.side_effect=lambda method,path,params=None:responses[path]
        await maker_once(host);self.assertEqual(host.verified_data.call.call_count,4)
        args=host.put.call_args.args;self.assertEqual(args[0],'maker_market');m=args[1]['market'];self.assertEqual(m['trades_24h'],30);self.assertEqual(m['incentives'][0]['id'],'program');self.assertNotIn('incentive_profit',m)
        self.assertEqual(m['maker_idle_seconds'],900);self.assertAlmostEqual(m['maker_last_trade_at'],now-100,places=5)
        self.assertEqual(suite.maker_discovery['candidates']['POL-X']['reason'],'awaiting_shared_admission')

class ResearchWindowTests(unittest.TestCase):
    def test_minute_baselines_produce_deltas_and_signed_pnl(self):
        from services.paper_demo.shadow.bot_performance import research_delta
        old=dict(completed=2,wins=1,round_net=-.4,net=-.4,maker_submitted=5,maker_entry_orders_filled=2,rejections=dict(depth=3))
        new=dict(completed=4,wins=3,round_net=.2,net=.2,holding_seconds=40,fill_events=4,fill_seconds=8,maker_submitted=8,maker_entry_orders_filled=4,rejections=dict(depth=5))
        r=research_delta(new,old);self.assertEqual(r['completed'],2);self.assertEqual(r['win_rate'],100);self.assertAlmostEqual(r['average_net'],.3);self.assertEqual(r['rejections'],dict(depth=2));self.assertAlmostEqual(r['maker_fill_rate'],2/3)
    def test_executable_value_uses_depth_and_exit_fees_without_selling(self):
        e=ScalperEngine(QuietAudit());e.advance(200);market(e,yes='.5',no='.4');e.books[T].levels['yes']={D('.5'):D(2),D('.4'):D(3)}
        e.wallet.fill(T,'yes','buy',D(5),D('.3'),D(0),1,'entry')
        q=depth_quote(e,T,'yes','sell',D(5),D(0));money=snapshot(e,[],200)
        self.assertEqual(D(money['positions'][0]['value']),q['gross']-q['fees']);self.assertEqual(money['positions'][0]['valuation_source'],'executable_depth_net_fees');self.assertEqual(e.wallet.inventory(T,'yes'),5)

from services.api.tests import test_demo_postgres as db_fixture
@unittest.skipUnless(db_fixture.URL,'Disposable PostgreSQL is required')
class MakerPostgresTests(unittest.TestCase):
    setUp=db_fixture.DemoPostgres.setUp
    tearDown=db_fixture.DemoPostgres.tearDown
    @classmethod
    def setUpClass(cls):db_fixture.DemoPostgres.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):db_fixture.DemoPostgres.tearDownClass.__func__(cls)
    def test_additive_install_config_category_market_controls_and_history_preservation(self):
        from services.paper_demo.shadow.scalper_install import initialize_scalper,initialize_scalper_upgrade,scalper_profiles
        self.demo.put('shadow/installed',dict(real_orders_enabled=False))
        self.demo.put('shadow/checkpoint',dict(preserve='historical checkpoint'))
        initialize_scalper(self.demo,lambda:None);initialize_scalper_upgrade(self.demo,lambda:None);initialize_market_maker(self.demo,lambda:None)
        initialize_scalper_upgrade(self.demo,lambda:None);initialize_market_maker(self.demo,lambda:None)
        self.assertEqual(self.demo.get('shadow/checkpoint')['progress'],dict(preserve='historical checkpoint'))
        rows=self.demo.rows('shadow/bot/',800);self.assertEqual(sum(r['parameters'].get('strategy')=='market_maker' for r in rows),8)
        self.assertEqual(sum(r['parameters'].get('strategy')=='volatility_scalper' for r in rows),5*len(scalper_profiles()))
        ident='market_maker_politics'
        response=self.client.post('/demo/shadow/bots/'+ident,json=dict(revision=1,config=dict(min_spread=.02,max_hold=7200)))
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['revision'],2)
        response=self.client.post('/demo/shadow/bots/'+ident,json=dict(revision=2,market_ticker='POL-X',market_desired='paused'))
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(self.demo.get('shadow/bot/'+ident)['parameters']['paused_markets'],['POL-X'])
        response=self.client.post('/demo/shadow/bulk',json=dict(action='pause',folder_id='market_maker',category='politics'))
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.demo.get('shadow/bot/'+ident)['progress']['desired'],'paused')
        self.assertEqual(self.demo.get('shadow/bot/market_maker_economics')['progress']['desired'],'running')
        response=self.client.post('/demo/shadow/bots/'+ident,json=dict(revision=2,config=dict(live_enabled=1)))
        self.assertEqual(response.status_code,422)

class SchedulingTests(unittest.TestCase):
    def test_scalper_clock_skips_empty_profiles_but_visits_held_market_owner(self):
        from services.paper_demo.shadow.experiments import ExperimentFleet
        from services.paper_demo.shadow.sequential import PairModel
        from services.api.tests.test_strategy_folders import profile
        ps=[dict(profile(series='SERIES'+str(i),id='s'+str(i),strategy='volatility_scalper'),folder_id='scalper_momentum') for i in range(50)]
        e=ScalperEngine(QuietAudit());e.advance(200);f=ExperimentFleet(e,ps,PairModel())
        market(e,'SERIES0-test')
        for b in f.bots.values():b.step=Mock()
        f.step();self.assertEqual(f.bots['SERIES0'].step.call_count,1)
        self.assertTrue(all(not b.step.called for s,b in f.bots.items() if s!='SERIES0'))
    def test_each_mode_has_independent_causal_signal(self):
        from services.api.tests.test_scalper import p
        e=ScalperEngine(QuietAudit())
        f=dict(bid=.45,spread=.02,sigma=.02,resistance=.6,support=.4,displacement=.04,last_change=.01,previous_change=-.06,trend=.025,mean=.44,trade_pressure=.1,acceleration=.005,depth_withdrawal=.3)
        for folder in ('volatility_scalper','scalper_grid','scalper_momentum','scalper_dislocation'):
            b=VolatilityScalper(e,p(folder));features=dict(f)
            if folder=='scalper_grid':features['bid']=.405
            self.assertTrue(b.decision(features)[0],folder)
        momentum=VolatilityScalper(e,p('scalper_momentum'))
        self.assertFalse(momentum.decision(dict(f,bid=.9,mean=.4))[0])


class HorizonTests(unittest.TestCase):
    def test_remaining_time_bands_distinguish_fast_and_long_market_research(self):
        from services.paper_demo.shadow.scalper import horizon
        self.assertEqual(horizon(600),'5–10m');self.assertEqual(horizon(800),'10–15m');self.assertEqual(horizon(7200),'1–6h');self.assertEqual(horizon(172800),'1–7d');self.assertEqual(horizon(40*86400),'30d+')


class LongRunningResourceTests(unittest.TestCase):
    def test_trade_deduplication_retains_only_live_timestamp_window(self):
        e=ScalperEngine(QuietAudit());e.advance(200);market(e)
        for i in range(5000):
            e.now=200+i*.001;e.books[T].at=e.now
            e.trade(T,dict(trade_id=str(i),taker_side='yes',yes_price_dollars='.51',count_fp='1',ts_ms=e.now*1000))
        self.assertLess(len(e.trade_ids),3010);self.assertLess(len(e._print_times),3010)
        self.assertLessEqual(len(e.tape.state(T)['trades']),256)
    def test_flat_parked_maker_probes_are_retired_without_erasing_research(self):
        rows=[dict(parameters=dict(p,revision=1),progress=dict(desired='running')) for p in profiles()]
        from services.api.tests.test_strategy_folders import profile
        rows.append(dict(parameters=profile('ALL','set_scanner','complete_set'),progress=dict(desired='running')))
        host=Mock();host.audit=QuietAudit();host.verified_fees.schedule.return_value=('quadratic',1);suite=ready_suite(host,rows)
        suite.handle('maker_market',dict(market=dict(ticker='POL-X',market_maker=True,market_category='politics',open=100,close=200000,discovered_at=200),taker_multiplier='1',maker_multiplier='0'),200)
        first=suite.portfolios[MM_FOLDERS[0]][1].bots['MM_POLITICS'];first.research['totals']['completed']=7
        suite.park_candidate('POL-X',suite.feed_markets()['POL-X'],500)
        for folder in MM_FOLDERS:suite.portfolios[folder][0].advance(700)
        suite.maintain()
        self.assertTrue(all('POL-X' not in suite.portfolios[folder][0].markets for folder in MM_FOLDERS))
        self.assertEqual(first.research['totals']['completed'],7)
        self.assertEqual(suite.snapshot(700)[MM_FOLDERS[0]]['bots']['market_maker_politics']['completed'],7)


class MakerVariantSelectionTests(unittest.TestCase):
    def test_discovery_sees_every_experimental_configuration_without_duplicate_streams(self):
        rows=[dict(parameters=dict(p,revision=1),progress=dict(desired='running')) for p in profiles()]
        host=Mock();host.audit=QuietAudit();suite=ready_suite(host,rows)
        choices=suite.enabled_profiles('market_maker')
        self.assertEqual(len(choices),8);self.assertEqual(len({p['series'] for p in choices}),4)
        self.assertEqual({p['config']['min_spread'] for p in choices},{.02,.03})
