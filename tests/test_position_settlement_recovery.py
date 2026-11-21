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
