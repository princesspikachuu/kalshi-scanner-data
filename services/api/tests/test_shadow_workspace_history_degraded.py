"""Current Favorites research remains available through historical SQL timeouts."""
import json
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Response, Request
from psycopg.errors import QueryCanceled

import services.api.shadow as shadow


class HistoryDelayedWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.old_retry=shadow.SHADOW_HISTORY_RETRY_AFTER
        shadow.SHADOW_HISTORY_RETRY_AFTER=0
        self.addCleanup(setattr,shadow,'SHADOW_HISTORY_RETRY_AFTER',self.old_retry)

        self.worker_money=dict(
            schema='paper-v1',at=1000,
            portfolio=dict(cash='1000',realized_pnl='5',total_pnl='7'),
            bots={'conv':dict(realized_pnl='5',unrealized_pnl='2',total_pnl='7')},
            current_cycles={})
        self.fav_account=dict(at=1000,portfolio=dict(
            cash='999',realized_pnl='1',total_pnl='1'),positions=[],bots={})
        self.fav_metrics=dict(gross_profit='1',fees='0',net_realized_pnl='1',
            win_rate='100',cycles=1,excluded_cycles=0,
            attempts=1,completed=1,entry_timing=[dict(
                series='KXBTC15M',market_type='15m_price',clock='market_close',
                price='.80',horizon='5–10m',events=1,event_wins=1,
                contracts='1',cost='.80',return_sum='.25',return_observations=1)])
        self.status=dict(at=1000,accounting=self.worker_money,positions=[],
            orders=[],experiments={'favorites':dict(
                accounting=self.fav_account,bots={'fav':self.fav_metrics})})
        self.store=MagicMock()
        def get(key):
            return {'shadow/installed':dict(progress=dict(enabled=True)),
                    'shadow/status':dict(progress=self.status),
                    'health':dict(progress=dict(state='ready',message='Ready'))}.get(key)
        self.store.get.side_effect=get
        folder=lambda ident,order:dict(parameters=dict(
            id=ident,session='s',order=order,name=ident),progress={})
        self.store.indexed_control_rows.side_effect=lambda prefix,limit:(
            [folder('convexity',0),folder('favorites',1)]
            if prefix=='shadow/folder/' else [])
        self.pool=MagicMock()
        self.conn=self.pool.connection.return_value.__enter__.return_value
        self.conn.execute.side_effect=QueryCanceled('canceling statement due to statement timeout')
        self.profiles=[
            dict(parameters=dict(id='conv',name='Convexity',strategy='convexity',
                folder_id='convexity',revision=1),progress=dict(desired='paused')),
            dict(parameters=dict(id='fav',name='Bitcoin',strategy='favorites',
                folder_id='favorites',series='KXBTC15M',asset='crypto',revision=1),
                progress=dict(desired='running'))]
        self.app=FastAPI()
        patches=[
            patch.object(shadow,'DemoStore',return_value=self.store),
            patch.object(shadow,'load_bots',return_value=self.profiles),
            patch.object(shadow,'folder_performance'),
            patch.object(shadow,'bot_performance'),
        ]
        self.mocks=[p.start() for p in patches]
        for p in patches:self.addCleanup(p.stop)
        shadow.install_shadow(self.app,lambda request:None,None,self.pool)
        self.endpoint=next(r.endpoint for r in self.app.routes
            if getattr(r,'path','')=='/demo/shadow/workspace')

    def workspace(self):
        request=Request(dict(type='http',method='GET',
            path='/demo/shadow/workspace',query_string=b'',headers=[],
            scheme='https',server=('test',443)))
        response=self.endpoint(request,Response())
        return json.loads(response.body)

    def test_history_timeout_keeps_current_buckets_and_real_accounting(self):
        result=self.workspace()
        self.assertTrue(result['historical_metrics_delayed'])
        self.assertEqual(result['contract'],'demo-v1')
        self.assertTrue(result['installed'])
        self.assertEqual(result['accounting']['portfolio']['cash'],'1000')
        self.assertNotIn('quality',result['accounting'])
        conv=next(x for x in result['bots'] if x['id']=='conv')
        self.assertEqual(conv['account']['realized_pnl'],'5')
        self.assertEqual(conv['account']['total_pnl'],'7')
        self.assertIsNone(conv['financial_metrics']['all']['net_realized_pnl'])
        self.assertIsNone(conv['metrics']['all']['cycles'])
        favorite=next(f for f in result['folders'] if f['id']=='favorites')
        self.assertEqual(favorite['accounting']['portfolio']['cash'],'999')
        research=favorite['collector_timed_summary']['rows']['crypto-15m']
        self.assertEqual(int(research[0]['events']),1)
        fav_bot=next(x for x in result['bots'] if x['id']=='fav')
        self.assertEqual(fav_bot['experiment']['completed'],1)
        self.assertEqual(self.conn.execute.call_count,1)
        self.mocks[2].assert_not_called()
        self.mocks[3].assert_not_called()

    def test_repeated_polling_during_cooldown_does_not_query_history(self):
        first=self.workspace()
        second=self.workspace()
        self.assertTrue(first['historical_metrics_delayed'])
        self.assertTrue(second['historical_metrics_delayed'])
        self.assertEqual(self.conn.execute.call_count,1)
        self.assertEqual(int(second['folders'][1]['collector_timed_summary']['rows']['crypto-15m'][0]['events']),1)

    def test_cooldown_expires_and_history_reads_are_retried(self):
        self.workspace()
        shadow.SHADOW_HISTORY_RETRY_AFTER=0
        self.workspace()
        self.assertEqual(self.conn.execute.call_count,2)


if __name__=='__main__':
    unittest.main()
