"""Every depth update applies, while irrelevant deltas avoid duplicate strategy work."""
import unittest
from decimal import Decimal as D
from unittest.mock import Mock
from services.api.tests.test_strategy_folders import QuietAudit,market
from services.paper_demo.shadow.core import Engine
from services.paper_demo.shadow.scalper import ScalperEngine
T='KXBTC15M-test'
class MaterialQuoteTests(unittest.TestCase):
    def engine(self,cls=ScalperEngine):
        e=cls(QuietAudit(),cash='1000',latency_ms=150,toxic_fill_probability=0);e.advance(200);market(e)
        e.strategy=Mock()
        e.handle('kalshi',dict(type='orderbook_snapshot',sid=1,seq=1,msg=dict(market_ticker=T,yes_dollars_fp=[['.49','100']],no_dollars_fp=[['.49','100']])),200)
        e.strategy.reset_mock();return e
    def delta(self,e,seq=2,side='yes',price='.49',quantity='1',at=200.1):
        e.handle('kalshi',dict(type='orderbook_delta',sid=1,seq=seq,msg=dict(market_ticker=T,side=side,price_dollars=price,delta_fp=quantity)),at)
    def test_small_quantity_changes_update_book_without_strategy_callback(self):
        e=self.engine();self.delta(e)
        self.assertEqual(e.books[T].levels['yes'][D('.49')],101);self.assertEqual(e.books[T].seq,2)
        e.strategy.step.assert_not_called();self.assertEqual(e.filtered_quote_updates,1)
    def test_deep_level_changes_are_preserved_without_redundant_evaluation(self):
        e=self.engine();self.delta(e,price='.25',quantity='10')
        self.assertEqual(e.books[T].levels['yes'][D('.25')],10);e.strategy.step.assert_not_called()
    def test_bid_price_changes_trigger_immediate_position_evaluation(self):
        e=self.engine();self.delta(e,price='.50',quantity='5')
        e.strategy.step.assert_called_once_with(T);self.assertEqual(e.books[T].bid('yes'),D('.50'))
    def test_large_top_depth_changes_trigger_evaluation(self):
        e=self.engine();self.delta(e,quantity='-25')
        e.strategy.step.assert_called_once_with(T);self.assertEqual(e.books[T].levels['yes'][D('.49')],75)
    def test_pending_ioc_arrival_is_evaluated_even_on_an_unchanged_quote(self):
        e=self.engine();ident=e.place(T,'yes','buy',D(5),D('.52'),maker=False)
        self.delta(e,side='no',at=200.2)
        self.assertEqual(e.wallet.inventory(T,'yes'),5);self.assertEqual(e.orders[ident].status,'filled')
        self.assertGreater(e.wallet.stat(T).fees_paid,0);e.strategy.step.assert_called_once_with(T)
    def test_public_trade_and_clock_are_never_filtered(self):
        e=self.engine()
        e.handle('kalshi',dict(type='trade',sid=2,seq=1,msg=dict(market_ticker=T,trade_id='print',taker_side='yes',yes_price_dollars='.51',count_fp='1',ts_ms=200100)),200.1)
        e.strategy.step.assert_called_once_with(T);e.strategy.reset_mock()
        e.handle('clock',{},200.2);e.strategy.step.assert_called_once_with()
    def test_existing_non_scalper_engine_keeps_original_evaluation_behavior(self):
        e=self.engine(Engine);self.delta(e);e.strategy.step.assert_called_once_with(T)
