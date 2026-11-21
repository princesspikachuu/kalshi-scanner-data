import json
import unittest
from decimal import Decimal as D
from types import SimpleNamespace as S
from unittest.mock import patch
from services.paper_demo.shadow.settlement_recovery import recover_once

class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    def host(self, results):
        engine=S(markets={t:dict(close=10,paid=False) for t in results},
                 wallet=S(lots=[S(ticker=t,quantity=D(10)) for t in results]))
        calls=[];queued=[]
        def call(method,path):
            t=path.split('/')[-1];calls.append(t)
            result=results[t]
            if isinstance(result,Exception):raise result
            return dict(market=result)
        async def put(source,payload):queued.append((source,payload))
        return S(experiments=S(portfolios={'favorites':(engine,None,None)}),
                 verified_data=S(call=call),put=put),calls,queued

    async def test_orphaned_15m_positions_queue_confirmations_without_mutating_wallet(self):
        host,calls,queued=self.host({'BTC15M':dict(ticker='BTC15M',status='finalized',result='yes')})
        with patch('services.paper_demo.shadow.settlement_recovery.time.time',return_value=100):
            await recover_once(host);await recover_once(host)
        self.assertEqual(calls,['BTC15M'])
        self.assertEqual(queued,[('experiment_settlement',dict(ticker='BTC15M',status='finalized',result='yes'))])
        self.assertEqual(host.experiments.portfolios['favorites'][0].wallet.lots[0].quantity,D(10))

    async def test_bad_or_unresolved_result_and_failed_lookup_do_not_starve_later_positions(self):
        results={str(i):dict(ticker=str(i),status='closed',result='') for i in range(7)}
        results['0']=RuntimeError('unavailable')
        results['1']=dict(ticker='WRONG',status='settled',result='yes')
        results['6']=dict(ticker='6',status='settled',result='no')
        host,calls,queued=self.host(results)
        with patch('services.paper_demo.shadow.settlement_recovery.time.time',return_value=100):
            await recover_once(host);self.assertEqual(len(calls),4)
            await recover_once(host)
        self.assertEqual(len(calls),7)
        self.assertEqual([p['ticker'] for _,p in queued],['6'])

    async def test_poll_health_distinguishes_venue_delay_missing_result_and_errors(self):
        results=dict(
            a=dict(ticker='a',status='closed',result=''),
            b=dict(ticker='b',status='finalized',result=''),
            c=dict(ticker='WRONG',status='settled',result='yes'),
            d=RuntimeError('temporary outage'),
        )
        host,calls,queued=self.host(results)
        with patch('services.paper_demo.shadow.settlement_recovery.time.time',return_value=1000), patch('builtins.print') as output:
            await recover_once(host)
        records=[json.loads(call.args[0]) for call in output.call_args_list]
        summary=next(row for row in records if row['event']=='paper_position_settlement_poll_health')
        self.assertEqual(summary['held_markets'],4)
        self.assertEqual(summary['rest_calls'],4)
        self.assertEqual(summary['poll_outcomes'],dict(venue_not_final=1,
            finalized_missing_result=1,ticker_mismatch=1,lookup_error=1))
        self.assertEqual(len(summary['oldest_unresolved']),3)
        self.assertEqual(summary['oldest_expired_seconds'],990)
        self.assertEqual(sum(summary['age_groups'].values()),4)
        self.assertEqual(queued,[])
        self.assertEqual(len(calls),4)
        self.assertTrue(all(row.quantity==D(10) for row in host.experiments.portfolios['favorites'][0].wallet.lots))
        self.assertFalse(summary['real_orders_enabled'])
        self.assertEqual(host.position_settlement_poll_telemetry['per_ticker']['b']['last_venue_status'],
                         'finalized')

    async def test_poll_summary_is_rate_limited_and_prunes_consumed_positions(self):
        results=dict(a=dict(ticker='a',status='closed',result=''),
                     b=dict(ticker='b',status='settled',result='yes'))
        host,calls,queued=self.host(results)
        with patch('builtins.print') as output:
            with patch('services.paper_demo.shadow.settlement_recovery.time.time',return_value=100):
                await recover_once(host)
            with patch('services.paper_demo.shadow.settlement_recovery.time.time',return_value=120):
                await recover_once(host)
            # The serialized consumer, not the polling task, removes a paid lot.
            host.experiments.portfolios['favorites'][0].wallet.lots=[
                row for row in host.experiments.portfolios['favorites'][0].wallet.lots if row.ticker!='b']
            with patch('services.paper_demo.shadow.settlement_recovery.time.time',return_value=161):
                await recover_once(host)
        records=[json.loads(call.args[0]) for call in output.call_args_list]
        summaries=[row for row in records if row['event']=='paper_position_settlement_poll_health']
        self.assertEqual(len(summaries),2)
        self.assertEqual(summaries[0]['rest_calls'],2)
        self.assertEqual(summaries[0]['poll_outcomes'],dict(venue_not_final=1,confirmed_queued=1))
        self.assertEqual(summaries[1]['rest_calls'],1)
        self.assertEqual(summaries[1]['poll_outcomes'],dict(venue_not_final=1))
        self.assertEqual([x['ticker'] for x in summaries[1]['oldest_unresolved']],['a'])
        self.assertEqual(calls,['a','b','a'])
        self.assertEqual(len(queued),1)
        self.assertNotIn('b',host.position_settlement_poll_telemetry['per_ticker'])
        self.assertNotIn('b',host.position_settlement_checks)

    async def test_bounded_oldest_unresolved_samples_and_untrusted_status_label(self):
        results={str(i):dict(ticker=str(i),status='untrusted-secret-marker',result='')
                 for i in range(7)}
        host,calls,queued=self.host(results)
        with patch('services.paper_demo.shadow.settlement_recovery.time.time',return_value=10000), patch('builtins.print') as output:
            await recover_once(host)
        summary=next(json.loads(call.args[0]) for call in output.call_args_list
                     if json.loads(call.args[0])['event']=='paper_position_settlement_poll_health')
        self.assertEqual(summary['held_markets'],7)
        self.assertEqual(summary['rest_calls'],4)
        self.assertEqual(summary['poll_outcomes'],dict(venue_not_final=4))
        self.assertEqual(len(summary['oldest_unresolved']),3)
        self.assertEqual(summary['age_groups']['over_120m'],7)
        self.assertNotIn('untrusted-secret-marker',json.dumps(summary))
        self.assertEqual(len(calls),4)
        self.assertFalse(queued)

    async def test_actual_consumer_pays_held_experiment_once_after_legacy_rollover(self):
        from services.api.tests.test_strategy_scope import ScopeTests
        from services.api.tests.test_strategy_folders import market
        suite,_=ScopeTests().suite()
        engine=suite.portfolios['favorites'][0]
        ticker='KXBTC15M-orphan'
        market(engine,ticker,close=250)
        engine.wallet.fill(ticker,'yes','buy',D(10),D('.8'),D('.1'),201,'fill')
        before=engine.wallet.cash
        host=S(experiments=suite,verified_data=S(call=lambda *args:dict(
            market=dict(ticker=ticker,status='finalized',result='yes'))))
        async def consume(source,payload):suite.handle(source,payload,300)
        host.put=consume
        with patch('services.paper_demo.shadow.settlement_recovery.time.time',return_value=300):
            await recover_once(host);await recover_once(host)
        self.assertEqual(engine.wallet.cash,before+D(10))
        self.assertFalse(engine.wallet.lots)
        self.assertTrue(engine.markets[ticker]['paid'])
        suite.handle('experiment_settlement',dict(ticker=ticker,status='finalized',result='yes'),301)
        self.assertEqual(engine.wallet.cash,before+D(10))

    async def test_released_cash_can_fund_hourly_finance_maker_entry(self):
        from services.api.tests import test_strategy_scope as scope_fixture
        from services.api.tests import test_strategy_folders as folder_fixture
        suite,_=scope_fixture.ScopeTests().suite();engine,fleet,_=suite.portfolios['favorites']
        orphan='KXBTC15M-old';folder_fixture.market(engine,orphan,close=250)
        engine.wallet.fill(orphan,'yes','buy',D(10),D('.8'),D(0),200,'historical')
        engine.wallet.cash=D('.4742')
        ticker='KXUSDCADAH-finance'
        suite.handle('hourly_market',dict(market=dict(ticker=ticker,event_ticker='FINANCE',
            series_ticker='KXUSDCADAH',open=100,close=2000,hourly_price=True,discovered_at=300),
            taker_multiplier='1',maker_multiplier='0'),300)
        book=dict(type='orderbook_snapshot',sid=7,seq=1,msg=dict(market_ticker=ticker,
            yes_dollars_fp=[['.81','100']],no_dollars_fp=[['.17','100']]))
        suite.handle('kalshi',book,301)
        self.assertFalse([o for o in engine.orders.values() if o.ticker==ticker])
        host=S(experiments=suite,verified_data=S(call=lambda *args:dict(
            market=dict(ticker=orphan,status='settled',result='yes'))))
        async def consume(source,payload):suite.handle(source,payload,302)
        host.put=consume
        with patch('services.paper_demo.shadow.settlement_recovery.time.time',return_value=302):
            await recover_once(host)
        engine.books[ticker].at=305
        suite.handle('clock',{},305)
        orders=[o for o in engine.orders.values() if o.ticker==ticker and o.action=='buy']
        self.assertTrue(orders);self.assertTrue(all(o.maker for o in orders))
        self.assertTrue(all(o.quantity>=1 for o in orders))
