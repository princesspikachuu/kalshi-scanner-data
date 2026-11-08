"""Flat experiments reuse verified data; active orders retain causal independent books."""
import unittest
from decimal import Decimal as D
from unittest.mock import Mock
from services.api.tests.test_strategy_folders import QuietAudit,ready_suite,profile
from services.paper_demo.shadow.scalper import SCALPER_FOLDERS
T='KXBTC15M-test'
class FlatExperimentFeedTests(unittest.TestCase):
    def suite(self):
        rows=[dict(parameters=dict(profile(id=f+'_btc',strategy='volatility_scalper'),folder_id=f,contracts=5),progress=dict(desired='running')) for f in SCALPER_FOLDERS]
        h=Mock();h.audit=QuietAudit();h.verified_fees.schedule.return_value=('quadratic',1)
        s=ready_suite(h,rows)
        s.handle('market',dict(market=dict(ticker=T,open=100,close=1000),taker_multiplier='1',maker_multiplier='0'),200)
        return s
    def book(self,s,at,seq,yes='.45',no='.50',q='100'):
        s.handle('kalshi',dict(type='orderbook_snapshot',sid=1,seq=seq,msg=dict(market_ticker=T,yes_dollars_fp=[[yes,q]],no_dollars_fp=[[no,q]])),at)
    def delta(self,s,at,seq,side,price,quantity):
        s.handle('kalshi',dict(type='orderbook_delta',sid=1,seq=seq,msg=dict(market_ticker=T,side=side,price_dollars=price,delta_fp=quantity)),at)
    def test_flat_books_are_detached_and_identical_at_the_entry_clock(self):
        s=self.suite();self.book(s,200.1,1);e=s.portfolios['scalper_momentum'][0];p=s.portfolios['volatility_scalper'][0]
        self.assertEqual(e.coalesced_inputs,1);self.assertFalse(e.books[T].valid)
        s.handle('clock',{},202)
        self.assertEqual(e.books[T].levels,p.books[T].levels);self.assertIsNot(e.books[T].levels['yes'],p.books[T].levels['yes'])
        self.delta(s,202.1,2,'yes','.45','2')
        self.assertEqual(e.books[T].levels['yes'][D('.45')],100)
        self.assertEqual(p.books[T].levels['yes'][D('.45')],102)
        s.handle('clock',{},204);self.assertEqual(e.books[T].levels['yes'][D('.45')],102)
        self.assertFalse(e.wallet.lots);self.assertEqual(e.wallet.cash,1000)
    def test_delayed_ioc_uses_prior_book_not_the_next_primary_snapshot(self):
        s=self.suite();self.book(s,200.1,1);s.handle('clock',{},202)
        e=s.portfolios['scalper_momentum'][0];ident=e.place(T,'yes','buy',D(5),D('.52'),maker=False)
        self.book(s,202.2,2,yes='.05',no='.10')
        self.assertEqual(e.wallet.inventory(T,'yes'),5);self.assertEqual(e.wallet.lots[0].price,D('.50'))
        self.assertEqual(e.orders[ident].status,'filled')
        self.assertEqual(e.books[T].bid('yes'),D('.05'))
    def test_partial_ioc_uses_available_prior_liquidity_and_preserves_fees(self):
        s=self.suite();self.book(s,200.1,1,q='2');s.handle('clock',{},202)
        e=s.portfolios['scalper_dislocation'][0];ident=e.place(T,'yes','buy',D(5),D('.52'),maker=False)
        self.book(s,202.2,2,yes='.05',no='.10',q='100')
        self.assertEqual(e.wallet.inventory(T,'yes'),2);self.assertEqual(e.orders[ident].remaining,3)
        self.assertGreater(e.wallet.stat(T).fees_paid,0)
    def test_active_resting_order_is_never_coalesced(self):
        s=self.suite();self.book(s,200.1,1);s.handle('clock',{},202)
        e=s.portfolios['scalper_momentum'][0];e.place(T,'yes','buy',D(2),D('.44'),maker=True)
        before=e.coalesced_inputs;self.delta(s,202.2,2,'yes','.45','2')
        self.assertEqual(e.coalesced_inputs,before);self.assertEqual(e.books[T].levels['yes'][D('.45')],102)
    def test_gap_fails_closed_until_the_verified_replacement_snapshot(self):
        s=self.suite();self.book(s,200.1,1);s.handle('clock',{},202)
        self.delta(s,202.1,3,'yes','.45','2')
        e=s.portfolios['scalper_dislocation'][0];self.assertFalse(e.books[T].valid);self.assertFalse(e.wallet.lots)
        self.book(s,202.2,4);s.handle('clock',{},204);self.assertTrue(e.books[T].valid)
    def test_portfolio_depth_overlays_are_not_copied_between_experiments(self):
        s=self.suite();self.book(s,200.1,1);s.handle('clock',{},202)
        e=s.portfolios['scalper_momentum'][0];p=s.portfolios['volatility_scalper'][0]
        e.books[T].used['no'][D('.50')]=D(3);p.books[T].used['no'][D('.50')]=D(77)
        self.delta(s,202.1,2,'yes','.45','2');s.handle('clock',{},204)
        self.assertEqual(e.books[T].used['no'][D('.50')],3)
        self.assertEqual(p.books[T].used['no'][D('.50')],77)
        self.delta(s,204.1,3,'no','.50','-100');s.handle('clock',{},206)
        self.assertNotIn(D('.50'),e.books[T].used['no'])
    def test_other_existing_experiments_keep_processing_every_book_frame(self):
        s=self.suite();self.book(s,200.1,1);self.delta(s,200.2,2,'yes','.45','2')
        for f in ('volatility_scalper','scalper_fixed','scalper_grid'):
            self.assertEqual(s.portfolios[f][0].books[T].levels['yes'][D('.45')],102)
            self.assertFalse(hasattr(s.portfolios[f][0],'coalesced_inputs'))
