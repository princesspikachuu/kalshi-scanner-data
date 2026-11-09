"""Own-slot reallocation preserves cancellation latency, capital and inventory races."""
import json,unittest
from decimal import Decimal as D
from services.api.tests import test_maker_activity_lifecycle as fixture
from services.paper_demo.shadow import maker_allocation
from services.paper_demo.shadow.market_maker import MM_FOLDERS

class MakerOpportunityRotationTests(unittest.TestCase):
    def setup(self):
        s,p=fixture.MakerActivityLifecycleTests().suite()
        p['market'].update(maker_ranking=dict(execution_score=1,trades_last_hour=0))
        s.handle('maker_market',p,200)
        for folder in MM_FOLDERS:
            e,f,_=s.portfolios[folder];book=e.books['POL-X'];book.valid=True;book.at=200;book.sid=1;book.seq=1
            book.levels={'yes':{D('.40'):D(100)},'no':{D('.55'):D(100)}}
            for at in range(200,225,6):book.at=at;e.advance(at);f.step('POL-X')
            book.at=224.2;e.advance(224.2);book.at=1000
        s.host.engine.markets={str(i):dict(close=200000) for i in range(31)}
        s.monitoring.limits=lambda now:dict(total=32,entry_candidates=12,per_category=4,admitting=True,level=0)
        new=dict(p,market=dict(p['market'],ticker='POL-HOT',discovered_at=995,maker_last_trade_at=995,
            maker_ranking=dict(execution_score=20,trades_last_hour=30)))
        return s,new
    def test_acknowledged_swap_uses_only_own_existing_slot_and_releases_capital(self):
        s,p=self.setup();self.assertFalse(s.search_capacity('market_maker',1000))
        self.assertTrue(s.can_replace_maker_market(p,1000));s.handle('maker_market',p,1000)
        self.assertIn('POL-X',s.feed_markets());self.assertNotIn('POL-HOT',s.feed_markets())
        for folder in MM_FOLDERS:self.assertLess(s.portfolios[folder][0].available(),1000)
        maker_allocation.finalize(s,1000.05);self.assertNotIn('POL-HOT',s.maker_allocation['credits'])
        for folder in MM_FOLDERS:s.portfolios[folder][0].advance(1000.2)
        maker_allocation.finalize(s,1000.2)
        self.assertNotIn('POL-X',s.feed_markets());self.assertTrue(maker_allocation.credited_capacity(s,'POL-HOT',1000.2))
        self.assertFalse(s.search_capacity('market_maker',1000.2))  # Expansion reserve still applies.
        s.handle('maker_market',p,1000.3)
        self.assertIn('POL-HOT',s.feed_markets());self.assertNotIn('POL-HOT',s.maker_allocation['credits'])
        self.assertEqual(s.monitoring_snapshot(1000.3)['subscribed_markets'],32)
        for folder in MM_FOLDERS:self.assertEqual(s.portfolios[folder][0].available(),1000)
        for folder in MM_FOLDERS:
            self.assertEqual(s.portfolios[folder][1].bots['MM_POLITICS'].research['totals']['canceled'],1)
        self.assertEqual(len(s.host.engine.markets),31)
    def test_partial_fill_during_cancellation_aborts_retirement_and_keeps_inventory(self):
        s,p=self.setup();s.handle('maker_market',p,1000)
        e=s.portfolios[MM_FOLDERS[0]][0];o=next(iter(e.orders.values()));e.advance(1000.05)
        e.trade('POL-X',dict(trade_id='cancel-race',taker_side='no',yes_price_dollars='.41',count_fp=str(o.ahead+1),ts_ms=1000050))
        maker_allocation.finalize(s,1000.06)
        self.assertEqual(e.wallet.inventory('POL-X','yes'),1);self.assertIn('POL-X',s.feed_markets())
        self.assertFalse(s.maker_allocation['pending']);self.assertFalse(s.maker_allocation['credits'])
        self.assertNotIn('maker_replacement_pending',e.markets['POL-X'])
    def test_only_executable_recent_flow_protects_a_resting_slot_from_replacement(self):
        s,p=self.setup();e=s.portfolios[MM_FOLDERS[0]][0]
        e.tape.trade('POL-X',dict(trade_id='nonexec',taker_side='no',yes_price_dollars='.50',count_fp='1',ts_ms=990000),990)
        self.assertTrue(s.can_replace_maker_market(p,1000))
        e.tape.clear('POL-X')
        e.tape.trade('POL-X',dict(trade_id='exec',taker_side='no',yes_price_dollars='.40',count_fp='1',ts_ms=991000),991)
        self.assertFalse(s.can_replace_maker_market(p,1000))

    def test_inventory_shared_ownership_and_stale_candidates_are_not_replaced(self):
        s,p=self.setup();e=s.portfolios[MM_FOLDERS[0]][0]
        e.wallet.fill('POL-X','yes','buy',D(1),D('.41'),D(0),1,'held')
        self.assertFalse(s.can_replace_maker_market(p,1000))
        s,p=self.setup();p['market']['maker_last_trade_at']=600
        self.assertFalse(s.can_replace_maker_market(p,1000))
        s,p=self.setup();p['market']['maker_ranking']['execution_score']=.001
        self.assertFalse(s.can_replace_maker_market(p,1000))
        s,p=self.setup();s.host.engine.markets['POL-X']=dict(close=200000)
        self.assertFalse(s.can_replace_maker_market(p,1000))
    def test_pending_reallocation_survives_recovery_without_freeing_a_live_position(self):
        from services.api.tests.test_strategy_folders import ready_suite
        s,p=self.setup();s.handle('maker_market',p,1000)
        state=json.loads(json.dumps(s.state(),default=str));restored=ready_suite(s.host,s.rows,state)
        self.assertIn('POL-X',restored.maker_allocation['pending'])
        maker_allocation.finalize(restored,1001)
        self.assertNotIn('POL-X',restored.feed_markets());self.assertIn('POL-HOT',restored.maker_allocation['credits'])
    def test_credit_cannot_oversubscribe_after_another_strategy_uses_the_released_slot(self):
        s,p=self.setup();s.handle('maker_market',p,1000)
        for folder in MM_FOLDERS:s.portfolios[folder][0].advance(1000.2)
        maker_allocation.finalize(s,1000.2);s.host.engine.markets['NEW-OTHER']=dict(close=200000)
        self.assertFalse(maker_allocation.credited_capacity(s,'POL-HOT',1000.3))
        s.handle('maker_market',p,1000.3);self.assertNotIn('POL-HOT',s.feed_markets())
    def test_overload_does_not_trigger_opportunity_cancellations(self):
        s,p=self.setup();s.monitoring.limits=lambda now:dict(total=32,entry_candidates=12,per_category=4,admitting=False,level=0)
        self.assertFalse(s.can_replace_maker_market(p,1000));s.handle('maker_market',p,1000)
        self.assertFalse(s.maker_allocation['pending'])
        for folder in MM_FOLDERS:self.assertFalse(any(item[2]=='cancel' for item in s.portfolios[folder][0].pending))
