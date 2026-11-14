"""Default quote policy upgrades are versioned, idempotent and financially non-destructive."""
import unittest
from unittest.mock import Mock
from services.api.tests import test_demo_postgres as fixture
from services.paper_demo.shadow.maker_quote_policy import initialize_quote_policy
from services.paper_demo.shadow.market_maker import initialize_market_maker
from services.paper_demo.shadow.storage import put

class QuoteUpgradeUnitTests(unittest.TestCase):
    def test_completed_upgrade_does_not_write_or_touch_existing_state(self):
        store=Mock();store.get.return_value={'progress':{'done':True}};guard=Mock()
        initialize_quote_policy(store,guard);guard.assert_not_called();store.pool.connection.assert_not_called()

@unittest.skipUnless(fixture.URL,'Disposable PostgreSQL is required')
class QuoteUpgradePostgresTests(unittest.TestCase):
    setUp=fixture.DemoPostgres.setUp
    tearDown=fixture.DemoPostgres.tearDown
    @classmethod
    def setUpClass(cls):fixture.DemoPostgres.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):fixture.DemoPostgres.tearDownClass.__func__(cls)
    def test_upgrade_preserves_wallet_history_pauses_and_custom_values(self):
        initialize_market_maker(self.demo,lambda:None)
        with self.demo.pool.connection() as c:
            put(c,'demo/shadow/checkpoint',{},dict(wallet=dict(cash='1000.0166'),preserve='history'))
            rows=self.demo.rows('shadow/bot/',800)
            for i,row in enumerate(rows):
                p=row['parameters'];p=dict(p,revision=3,version='maker-1',contracts=19,
                    config=dict(p['config'],order_ttl=60 if i==0 else 300,exit_ttl=60 if i==0 else 120),paused_markets=['PAUSED'])
                put(c,'demo/shadow/bot/'+p['id'],p,dict(desired='paused'))
        initialize_quote_policy(self.demo,lambda:None)
        rows=self.demo.rows('shadow/bot/',800)
        for row in rows:
            p=row['parameters'];self.assertEqual(p['contracts'],19);self.assertEqual(p['paused_markets'],['PAUSED'])
            self.assertEqual(row['progress']['desired'],'paused')
            if p['config']['order_ttl']==60:self.assertEqual((p['revision'],p['config']['exit_ttl']),(3,60))
            else:
                self.assertEqual((p['revision'],p['config']['order_ttl'],p['config']['exit_ttl']),(4,1800,900))
                self.assertEqual(self.demo.get('shadow/version/'+p['id']+'/3')['progress']['config']['order_ttl'],300)
        self.assertEqual(self.demo.get('shadow/checkpoint')['progress'],dict(wallet=dict(cash='1000.0166'),preserve='history'))
        before=[r['parameters'] for r in rows];initialize_quote_policy(self.demo,lambda:None)
        self.assertEqual([r['parameters'] for r in self.demo.rows('shadow/bot/',800)],before)
