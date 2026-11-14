"""Restore original 15-minute favorites without replacing wallets or bot IDs."""
import unittest
from decimal import Decimal as D
from services.api.tests import test_strategy_folders as fixture
from services.api.tests import test_demo_postgres as pg
from services.paper_demo.shadow.scope import initialize_scope,initialize_restored_favorites
from services.paper_demo.shadow.weather import initialize_weather
from services.paper_demo.shadow.sports import initialize_sports
from services.paper_demo.shadow.core import Engine
from services.paper_demo.shadow.favorites import FavoritesStrategy

class RestoreBehavior(unittest.TestCase):
    def test_unretired_fifteen_minute_favorite_can_place_configured_size(self):
        e=Engine(fixture.QuietAudit(),cash='1000');e.advance(200)
        b=FavoritesStrategy(e,fixture.profile(strategy='favorites'))
        fixture.market(e,'KXBTC15M-current',yes='.79',no='.19')
        b.step();o=next(iter(e.orders.values()))
        self.assertTrue(o.maker);self.assertEqual(o.quantity,D(10));self.assertEqual(o.price,D('.80'))

    def test_join_existing_legacy_feed_keeps_wallets_and_waits_for_snapshot(self):
        suite,_=fixture.SuiteTests().suite();legacy=Engine(fixture.QuietAudit());legacy.advance(200)
        t='KXBTC15M-current';fixture.market(legacy,t,yes='.79',no='.19');suite.host.engine=legacy
        e,f,_=suite.portfolios['favorites'];e.wallet.cash=D('987.65')
        suite.share_legacy_markets(200);suite.share_legacy_markets(200)
        self.assertEqual(e.wallet.cash,D('987.65'));self.assertEqual(len(e.markets),1)
        self.assertEqual(e.markets[t]['bot_id'],'fav_btc');self.assertFalse(e.books[t].valid)
        self.assertNotIn(t,suite.extra)
        f.step();self.assertFalse(e.orders)
        suite.handle('kalshi',dict(type='orderbook_snapshot',sid=1,seq=1,msg=dict(market_ticker=t,
            yes_dollars_fp=[['.79','100']],no_dollars_fp=[['.19','100']])),201)
        self.assertTrue(e.orders);self.assertEqual(next(iter(e.orders.values())).quantity,D(10))

@unittest.skipUnless(pg.URL,'Disposable PostgreSQL required')
class RestoreMigration(unittest.TestCase):
    setUp=fixture.FolderPostgres.setUp;tearDown=fixture.FolderPostgres.tearDown;seed=fixture.FolderPostgres.seed
    @classmethod
    def setUpClass(cls):fixture.FolderPostgres.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):fixture.FolderPostgres.tearDownClass.__func__(cls)
    def prepare(self):
        self.seed();initialize_weather(self.demo,lambda:None);initialize_sports(self.demo,lambda:None);initialize_scope(self.demo,lambda:None)
    def test_restore_is_idempotent_and_preserves_identity_settings_and_wallet_checkpoint(self):
        self.prepare();before=self.demo.rows('shadow/bot/',500)
        retired=[r for r in before if r['parameters'].get('retired')]
        self.demo.put('shadow/checkpoint',dict(wallet=dict(cash='876.54'),history='retained'))
        initialize_restored_favorites(self.demo,lambda:None);initialize_restored_favorites(self.demo,lambda:None)
        self.assertEqual(len(self.demo.rows('shadow/bot/',500)),len(before))
        self.assertEqual(self.demo.get('shadow/checkpoint')['progress']['wallet']['cash'],'876.54')
        for old in retired:
            p=old['parameters'];new=self.demo.get('shadow/bot/'+p['id'])
            for key in ('id','key','contracts','revision'):self.assertEqual(new['parameters'][key],p[key])
            self.assertFalse(new['parameters']['retired']);self.assertEqual(new['progress']['desired'],'running')
        p=retired[0]['parameters']
        self.assertEqual(self.client.post('/demo/shadow/bots/'+p['id'],json=dict(revision=p['revision'],desired='running')).status_code,200)
    def test_existing_folder_pause_is_preserved_and_later_pause_is_not_undone(self):
        self.prepare();self.client.post('/demo/shadow/bulk',json=dict(action='pause',folder_id='favorites'))
        initialize_restored_favorites(self.demo,lambda:None)
        restored=[r for r in self.demo.rows('shadow/bot/',500) if r['parameters'].get('folder_id')=='favorites']
        self.assertTrue(all(r['progress']['desired']=='paused' for r in restored))
        self.assertFalse(any(r['parameters'].get('retired') for r in restored))
        initialize_restored_favorites(self.demo,lambda:None)
        self.assertTrue(all(self.demo.get('shadow/bot/'+r['parameters']['id'])['progress']['desired']=='paused' for r in restored))
