import unittest
from decimal import Decimal as D
from services.paper_demo.shadow.performance import change,record_balances,folder_performance,history_key,equity_bounds,equity_estimate,period_change
from services.api.tests import test_strategy_folders as existing
from services.api.tests import test_demo_postgres as fixture

class Returns(unittest.TestCase):
    def test_refill_is_excluded_from_profit(self):
        self.assertEqual(change(dict(equity='1120',deposits='1100'),dict(equity='1010',deposits='1000')),'10')
    def test_missing_valuation_never_becomes_zero(self):
        self.assertIsNone(change(dict(equity=None,deposits='1000'),dict(equity='1000',deposits='1000')))
        self.assertIsNone(change(dict(equity='1000',deposits='1000'),dict(equity=None,deposits='1000')))
    def test_period_pnl_keeps_known_prices_and_bounds_only_unpriced_contracts(self):
        current=dict(equity=None,cash='970',deposits='1000',active_contracts='30',pending_contracts='20',realized_pnl='4')
        positions=[dict(quantity='10',value='8'),dict(quantity='20',value=None),dict(quantity='20',value=None)]
        self.assertEqual(equity_bounds(current,positions),(D('978'),D('1018')))
        result=period_change(current,dict(equity='1000',deposits='1000',realized_pnl='1'),positions)
        self.assertEqual((result['pnl_low'],result['pnl_high']),('-22','18'))
        self.assertIsNone(result['pnl']);self.assertTrue(result['unpriced']);self.assertEqual(result['realized_pnl'],'3')
    def test_bounds_on_both_snapshots_exclude_added_funds(self):
        a=dict(equity=None,equity_low='1015',equity_high='1025',deposits='1005')
        b=dict(equity=None,equity_low='1000',equity_high='1010',deposits='1000')
        result=period_change(a,b);self.assertEqual((result['pnl_low'],result['pnl_high']),('0','20'))
        self.assertIsNone(equity_bounds(dict(equity=None,cash='900',deposits='1000')))
    def test_historical_missing_quotes_use_saved_marks_or_cost_basis_not_range_midpoint(self):
        baseline=dict(equity=None,equity_low='900',equity_high='1100',equity_estimate='990',deposits='1000',realized_pnl='-5')
        result=period_change(dict(equity='1005',deposits='1000',realized_pnl='0'),baseline)
        self.assertEqual(result['pnl'],'15')
        del baseline['equity_estimate']
        self.assertEqual(equity_estimate(baseline),D('995'))
        self.assertEqual(period_change(dict(equity='1005',deposits='1000'),baseline)['pnl'],'10')
    def test_current_estimate_uses_lot_prices_for_missing_quotes_and_preserves_known_marks(self):
        row=dict(equity=None,cash='90',position_cost='10',active_contracts='20',deposits='100',realized_pnl='0')
        positions=[dict(quantity='10',value='7',cost='5'),dict(quantity='10',value=None,price='.4',cost='5')]
        self.assertEqual(equity_estimate(row,positions),D('101'))
        self.assertEqual(D(period_change(row,dict(equity='100',deposits='100'),positions)['pnl']),D('1'))

    def test_exact_period_returns_remain_exact(self):
        result=period_change(dict(equity='1120',deposits='1100'),dict(equity='1010',deposits='1000'))
        self.assertEqual(result['pnl'],'10');self.assertFalse(result['unpriced'])

@unittest.skipUnless(fixture.URL,'Disposable PostgreSQL required')
class PerformancePostgres(unittest.TestCase):
    setUp=existing.FolderPostgres.setUp;tearDown=existing.FolderPostgres.tearDown;seed=existing.FolderPostgres.seed
    @classmethod
    def setUpClass(cls):existing.FolderPostgres.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):existing.FolderPostgres.tearDownClass.__func__(cls)
    def folders(self,equity='1000',deposits='1000'):
        return [dict(r['parameters'],**r['progress'],accounting=dict(portfolio=dict(equity=equity,cash=equity,deposits=deposits,total_pnl=str(int(equity)-int(deposits))))) for r in self.demo.rows('shadow/folder/',10)]
    def record(self,folders,at):record_balances(self.demo,{f['id']:f['accounting'] for f in folders},at)
    def test_minute_history_refills_reset_isolation_and_missing_older_history(self):
        self.seed();start=self.folders('1010');self.record(start,12000)
        end=self.folders('1120','1100');self.record(end,15600)
        folder_performance(self.demo.pool,end,15600)
        for f in end:
            self.assertEqual(f['performance']['1H']['pnl'],'10')
            self.assertFalse(f['performance']['1H']['partial'])
            self.assertEqual(f['performance']['24H']['pnl'],'10')
            self.assertTrue(f['performance']['24H']['partial'])
            self.assertEqual(f['performance']['all']['pnl'],'20')
        # A reset cuts off only that folder's old session, rather than showing
        # a $120 loss from returning its wallet to $1,000.
        row=self.demo.get('shadow/folder/favorites')
        self.demo.put('shadow/folder/favorites',dict(row['progress'],session='new-session',reset_at=15630))
        fresh=self.folders('1000');self.record(fresh,15660)
        current=self.folders('998');folder_performance(self.demo.pool,current,15720)
        fav=next(f for f in current if f['id']=='favorites')
        self.assertEqual(fav['performance']['1H']['pnl'],'-2')
        self.assertTrue(fav['performance']['1H']['partial'])
        self.assertEqual(fav['performance']['1H']['since'],15660)
        self.assertEqual(self.demo.get('shadow/balance-origin/favorites/new-session')['progress']['equity'],'1000')
    def test_denied_cleanup_rolls_back_only_savepoint_and_keeps_snapshots(self):
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import patch
        self.seed();folders=self.folders()
        self.record(folders,60)
        actual_pool=self.demo.pool
        class DeniedCleanupConnection:
            def __init__(self,c):self.c=c
            def transaction(self):return self.c.transaction()
            def execute(self,sql,args=None):
                if sql.startswith('DELETE '):
                    # A real PostgreSQL error aborts this subtransaction. The
                    # savepoint must recover it without losing earlier inserts.
                    return self.c.execute("DO $$ BEGIN RAISE insufficient_privilege; END $$")
                return self.c.execute(sql,args)
        @contextmanager
        def connection():
            with actual_pool.connection() as c:yield DeniedCleanupConnection(c)
        store=SimpleNamespace(rows=self.demo.rows,pool=SimpleNamespace(connection=connection))
        with patch('builtins.print') as log:
            record_balances(store,{f['id']:f['accounting'] for f in folders},36*86400)
        self.assertIsNotNone(self.demo.get(history_key(60)[5:]))
        saved=self.demo.get(history_key(36*86400)[5:])
        self.assertEqual(saved['progress']['folders']['favorites']['equity'],'1000')
        self.assertTrue(any('paper_balance_retention_deferred' in str(call) for call in log.call_args_list))
        self.assertTrue(any('paper_folder_balances_sampled' in str(call) for call in log.call_args_list))
    def test_bounded_retention_and_unknown_equity(self):
        self.seed();folders=self.folders();self.record(folders,60)
        self.record(folders,36*86400)
        self.assertIsNone(self.demo.get(history_key(60)[5:]))
        for f in folders:f['accounting']['portfolio']['equity']=None
        self.record(folders,36*86400+60)
        folder_performance(self.demo.pool,folders,36*86400+60)
        self.assertTrue(all(f['performance']['1H']['pnl'] is None for f in folders))
    def test_unpriced_favorites_period_uses_saved_bounds_and_preserves_session(self):
        self.seed();folders=self.folders()
        for f in folders:
            f['accounting']['portfolio'].update(equity=None,cash='970',active_contracts='50',pending_contracts='0',realized_pnl='0')
            f['accounting']['positions']=[dict(quantity='50',value=None)]
        before={f['id']:f['session'] for f in folders};self.record(folders,12000)
        # A legacy, unpriced minute sample did not record sufficient position
        # information. Use the new bounded origin with honest shorter coverage.
        from services.paper_demo.shadow.storage import put
        with self.demo.pool.connection() as c:
            put(c,history_key(11900),{},dict(at=11900,folders={f['id']:dict(session=f['session'],equity=None,cash='970',deposits='1000') for f in folders}))
        for f in folders:f['accounting']['portfolio'].update(cash='975',realized_pnl='5')
        folder_performance(self.demo.pool,folders,15500)
        for f in folders:
            p=f['performance']['1H'];self.assertEqual((p['pnl_low'],p['pnl_high']),('-45','55'))
            self.assertEqual(p['realized_pnl'],'5');self.assertFalse(p['missing_history']);self.assertTrue(p['partial'])
            self.assertEqual(f['session'],before[f['id']])
        self.assertEqual(len(self.demo.rows('shadow/balance-range-origin/',10)),4)
