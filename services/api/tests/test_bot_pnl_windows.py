import unittest
from decimal import Decimal as D
from services.paper_demo.shadow.bot_performance import pack,unpack,sample,bot_performance,record_bot_balances,key
from services.api.tests import test_demo_postgres as pg
from services.api.tests import test_strategy_folders as fixture

class BotSamples(unittest.TestCase):
    def test_snapshot_compression_round_trips_expanded_workspace(self):
        data={str(i):dict(session='test',equity='0',realized_pnl='0',deposits='0') for i in range(254)}
        encoded=pack(data);self.assertEqual(unpack(encoded),data);self.assertLess(len(encoded),3000)
    def test_pnl_does_not_assign_folder_cash_to_a_bot(self):
        row=dict(realized_pnl='3',position_cost='10',active_contracts='20',pending_contracts='0',total_pnl=None)
        result=sample(row,[dict(quantity='5',value='4'),dict(quantity='15',value=None)],'s')
        self.assertEqual((result['equity_low'],result['equity_high']),('-3','12'))
        self.assertEqual(result['realized_pnl'],'3');self.assertEqual(result['deposits'],'0')
    def test_missing_account_is_not_zero_profit(self):
        self.assertIsNone(sample({},[],'s'))

@unittest.skipUnless(pg.URL,'Disposable PostgreSQL required')
class BotWindows(unittest.TestCase):
    setUp=fixture.FolderPostgres.setUp;tearDown=fixture.FolderPostgres.tearDown
    @classmethod
    def setUpClass(cls):fixture.FolderPostgres.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):fixture.FolderPostgres.tearDownClass.__func__(cls)
    def run_sample(self,at,pnl,realized='0',session='s'):
        folders=[dict(id='favorites',session=session,accounting=dict(positions=[]))]
        bots=[dict(id='fav_test',folder_id='favorites',account=dict(total_pnl=pnl,realized_pnl=realized,
            position_cost='0',active_contracts='0',pending_contracts='0'))]
        bot_performance(self.demo.pool,bots,folders,at);return bots[0]['performance']
    def test_windows_use_observed_differences_and_reset_boundaries(self):
        self.run_sample(12000,'10','5')
        self.run_sample(12060,'12','6')
        result=self.run_sample(15660,'20','9')
        self.assertEqual(result['1H']['pnl'],'8');self.assertEqual(result['1H']['realized_pnl'],'3')
        self.assertFalse(result['1H']['partial']);self.assertTrue(result['24H']['partial'])
        self.assertEqual(result['all']['pnl'],'20')
        fresh=self.run_sample(15720,'-1','-1','new-session')
        self.assertEqual(fresh['1H']['pnl'],'0');self.assertTrue(fresh['1H']['partial'])
        self.assertEqual(fresh['all']['pnl'],'-1')
    def test_old_cutoff_with_a_gap_is_not_presented_as_full_window(self):
        self.run_sample(12000,'10')
        result=self.run_sample(20000,'20')
        self.assertTrue(result['1H']['missing_history']);self.assertIsNone(result['1H']['pnl'])
    def test_worker_records_history_without_dashboard_and_combines_archived_realized_pnl(self):
        self.demo.put('shadow/folder/convexity',dict(session='worker-session'),parameters=dict(id='convexity'))
        self.demo.put('shadow/report/old',dict(bot_id='bot',ticker='OLD',net_realized_pnl='7',at=100))
        account=dict(bots={'bot':dict(unrealized_pnl='0',position_cost='0',active_contracts='0',pending_contracts='0')},
            current_cycles={'LIVE':dict(bot_id='bot',net_realized_pnl='2')})
        record_bot_balances(self.demo,dict(convexity=account),{},12000)
        row=self.demo.get(key(12000)[5:]);saved=unpack(row['progress']['snapshot'])
        self.assertEqual(saved['bots']['bot']['realized_pnl'],'9')
        self.assertEqual(saved['bots']['bot']['equity'],'9')
