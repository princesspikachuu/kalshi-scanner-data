import unittest
from services.paper_demo.shadow.performance import change,record_balances,folder_performance,history_key
from services.api.tests import test_strategy_folders as existing
from services.api.tests import test_demo_postgres as fixture

class Returns(unittest.TestCase):
    def test_refill_is_excluded_from_profit(self):
        self.assertEqual(change(dict(equity='1120',deposits='1100'),dict(equity='1010',deposits='1000')),'10')
    def test_missing_valuation_never_becomes_zero(self):
        self.assertIsNone(change(dict(equity=None,deposits='1000'),dict(equity='1000',deposits='1000')))
        self.assertIsNone(change(dict(equity='1000',deposits='1000'),dict(equity=None,deposits='1000')))

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
        folder_performance(self.pool,end,15600)
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
        current=self.folders('998');folder_performance(self.pool,current,15720)
        fav=next(f for f in current if f['id']=='favorites')
        self.assertEqual(fav['performance']['1H']['pnl'],'-2')
        self.assertTrue(fav['performance']['1H']['partial'])
        self.assertEqual(fav['performance']['1H']['since'],15660)
        self.assertEqual(self.demo.get('shadow/balance-origin/favorites/new-session')['progress']['equity'],'1000')
    def test_bounded_retention_and_unknown_equity(self):
        self.seed();folders=self.folders();self.record(folders,60)
        self.record(folders,36*86400)
        self.assertIsNone(self.demo.get(history_key(60)[5:]))
        for f in folders:f['accounting']['portfolio']['equity']=None
        self.record(folders,36*86400+60)
        folder_performance(self.pool,folders,36*86400+60)
        self.assertTrue(all(f['performance']['1H']['pnl'] is None for f in folders))
