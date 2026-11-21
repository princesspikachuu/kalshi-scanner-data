"""Maker improves stationary books and reprices against its desired quote, not the raw bid."""
import unittest
from decimal import Decimal as D
from services.api.tests import test_market_maker as fixture
from services.paper_demo.shadow.execution import passive_entry_price
from services.paper_demo.shadow.market_maker import quote_diagnostics
T=fixture.T

class CompetitiveMakerQuoteTests(unittest.TestCase):
    def test_maker_improves_yes_and_no_without_waiting_for_a_live_trade(self):
        for side in ('yes','no'):
            e,b,_=fixture.MakerTests().bot(side);o=next(iter(e.orders.values()))
            self.assertEqual(o.side,side);self.assertEqual(o.price,D('.43'))
            self.assertFalse(e.wallet.lots);self.assertLess(o.price,e.books[T].ask(side))
    def test_competitive_reprice_uses_inside_quote_even_without_recent_trade(self):
        e,b,p=fixture.MakerTests().bot();o=next(iter(e.orders.values()))
        self.assertEqual(o.price,D('.43'))
        p['folder_id']='maker_competitive';b.refresh_config()
        self.assertTrue(b.config['competitive_inside'])
        e.books[T].at=300;e.advance(300);b.step(T)
        self.assertTrue(any(item[2]=='cancel' for item in e.pending))
        self.assertEqual(b.attempts[T]['replace_reason'],'quote_moved')

    def test_stationary_competitive_quote_does_not_cancel_itself_after_thirty_seconds(self):
        e,b,_=fixture.MakerTests().bot();b.config['reprice_ticks']=1;o=next(iter(e.orders.values()))
        e.books[T].at=e.now+.2;e.advance(e.now+.2)
        e.books[T].at=300;e.advance(300);b.step(T)
        self.assertEqual(o.status,'resting');self.assertEqual(len(e.orders),1)
        self.assertFalse(any(p[2]=='cancel' for p in e.pending))
        e.books[T].levels['yes']={D('.43'):D(100)}
        e.books[T].at=340;e.advance(340);b.step(T)
        self.assertTrue(any(p[2]=='cancel' for p in e.pending))
    def test_scalper_passive_price_rule_is_unchanged_and_maker_never_crosses(self):
        quiet=dict(trade_count=0,last_change=0);base=dict(adaptive=True,approach='mean_reversion')
        self.assertEqual(passive_entry_price({},D('.42'),D('.48'),quiet,base),D('.42'))
        self.assertEqual(passive_entry_price({},D('.42'),D('.48'),quiet,dict(base,approach='market_maker')),D('.43'))
        self.assertEqual(passive_entry_price({},D('.42'),D('.48'),quiet,dict(base,approach='market_maker',competitive_inside=True)),D('.47'))
        self.assertEqual(passive_entry_price({},D('.42'),D('.43'),quiet,dict(base,approach='market_maker',competitive_inside=True)),D('.42'))
    def test_quote_diagnostics_distinguish_non_executable_prints_and_real_partial_fill(self):
        e,b,_=fixture.MakerTests().bot();o=next(iter(e.orders.values()))
        e.books[T].at=e.now+.2;e.advance(e.now+.2)
        def trade(ident,price,q):
            e.trade(T,dict(trade_id=ident,taker_side='no',yes_price_dollars=price,count_fp=q,ts_ms=e.now*1000))
        trade('above','.44','1');r=quote_diagnostics(e,e.now)[0]
        self.assertEqual((r['recent_trade_count'],r['recent_executable_trade_count']),(1,0))
        self.assertFalse(e.wallet.lots)
        volume=o.ahead+D('.25')
        trade('matching','.43',str(volume));r=quote_diagnostics(e,e.now)[0]
        self.assertEqual(r['recent_executable_trade_count'],1);self.assertAlmostEqual(r['recent_executable_volume'],float(volume))
        self.assertEqual(e.wallet.inventory(T,'yes'),D('.25'));self.assertEqual(o.remaining,D('4.75'))
