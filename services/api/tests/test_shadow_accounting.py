"""Wallet reconciliation must include gap-cycle money and distinguish cost/value."""
import unittest
from decimal import Decimal as D
from unittest.mock import Mock
from services.paper_demo.shadow.core import Engine,FeePolicy,Lot
from services.paper_demo.shadow.accounting import snapshot

PROFILES=[dict(id='btc',series='KXBTC15M'),dict(id='eth',series='KXETH15M')]

def fixture():
    engine=Engine(Mock(),cash='100');engine.advance(1000)
    for profile,close,bid in ((PROFILES[0],1900,'.2'),(PROFILES[1],999,'.7')):
        ticker=profile['series']+'-test'
        engine.add_market(dict(ticker=ticker,bot_id=profile['id'],bot_revision=1,close=close),FeePolicy())
        engine.wallet.stat(ticker)
        book=engine.books[ticker];book.valid=True;book.at=1000
        book.levels={'yes':{D(bid):D(1000)},'no':{D('.1'):D(1000)}}
    engine.wallet.cash=D(70)
    engine.wallet.lots=[Lot('active','KXBTC15M-test','yes',D(100),D('.1'),D(1),1),
                        Lot('pending','KXETH15M-test','yes',D(10),D('.03'),D(0),2)]
    engine.place('KXBTC15M-test','yes','buy',D(100),D('.1'))
    return engine

class AccountingTests(unittest.TestCase):
    def test_cash_reserves_cost_and_market_value_reconcile(self):
        a=snapshot(fixture(),PROFILES,1000)['portfolio']
        for key,value in dict(cash=70,available_cash=60,unfilled_bids=10,active_cost=11,
                active_value=20,pending_cost='.3',pending_value=7,equity=97,
                realized_pnl='-18.7',unrealized_pnl='15.7',total_pnl=-3).items():
            self.assertEqual(D(a[key]),D(value),key)
        self.assertEqual(D(a['realized_pnl'])+D(a['unrealized_pnl']),D(a['total_pnl']))
        self.assertEqual(a['pending_payout_state'],'estimated')

    def test_refill_and_cancel_release_do_not_create_profit(self):
        e=fixture();before=snapshot(e,PROFILES,1000)['portfolio'];e.refill(D(50))
        e.cancel(next(iter(e.orders)));e.advance(1000.2)
        after=snapshot(e,PROFILES,1000.2)['portfolio']
        self.assertEqual(D(after['total_pnl']),D(before['total_pnl']))
        self.assertEqual(D(after['unfilled_bids']),0)
        self.assertEqual(D(after['available_cash']),120)

    def test_unconfirmed_and_confirmed_pending_payout_are_distinct(self):
        e=fixture();e.markets['KXETH15M-test']['yes_payout_confirmed']='1'
        a=snapshot(e,PROFILES,1000)['portfolio']
        self.assertEqual(a['pending_payout_state'],'confirmed');self.assertEqual(D(a['pending_value']),10)
        e.markets['KXETH15M-test']['yes_payout_confirmed']='0'
        self.assertEqual(D(snapshot(e,PROFILES,1000)['portfolio']['pending_value']),0)

    def test_missing_quote_uses_entry_price_only_when_no_verified_mark_is_saved(self):
        e=fixture();e.books['KXETH15M-test'].valid=False
        a=snapshot(e,PROFILES,1000)
        self.assertEqual(D(a['portfolio']['equity']),D('90.3'))
        self.assertEqual(D(a['portfolio']['pending_value']),D('.3'))
        self.assertEqual(a['positions'][1]['valuation_source'],'entry_price')
        self.assertEqual(a['portfolio']['pending_payout_state'],'estimated')
    def test_missing_quote_retains_last_verified_bid_and_confirms_outcome_when_available(self):
        e=fixture();snapshot(e,PROFILES,1000)
        e.books['KXETH15M-test'].valid=False
        a=snapshot(e,PROFILES,1001)
        self.assertEqual(D(a['portfolio']['pending_value']),D('7'))
        self.assertEqual(a['positions'][1]['valuation_source'],'last_verified_bid')
        e.markets['KXETH15M-test']['yes_payout_confirmed']='0'
        self.assertEqual(D(snapshot(e,PROFILES,1002)['portfolio']['pending_value']),0)

    def test_best_estimate_never_enables_trading_on_an_invalid_book(self):
        e=fixture();snapshot(e,PROFILES,1000)
        book=e.books['KXBTC15M-test'];book.valid=False
        # Corrupt remaining depth is not adopted over the saved verified mark.
        book.levels={'yes':{D('.9'):D(100)},'no':{D('.9'):D(100)}}
        result=snapshot(e,PROFILES,1001)
        self.assertEqual(result['positions'][0]['mark_price'],'0.2')
        self.assertFalse(book.valid)

    def test_open_entry_fees_are_unrealized_until_position_closes(self):
        e=Engine(Mock(),cash='100');e.advance(1000)
        e.add_market(dict(ticker='KXBTC15M-test',bot_id='btc',close=1900),FeePolicy())
        b=e.books['KXBTC15M-test'];b.at=1000;b.valid=True;b.levels={'yes':{D('.5'):D(100)},'no':{D('.4'):D(100)}}
        e.wallet.fill('KXBTC15M-test','yes','buy',D(100),D('.5'),D('1.75'),1,'lot')
        a=snapshot(e,PROFILES,1000)['portfolio']
        self.assertEqual(D(a['realized_pnl']),0);self.assertEqual(D(a['unrealized_pnl']),D('-1.75'))

    def test_closed_markets_move_from_active_cost_to_pending_without_losing_money(self):
        e=fixture();a=snapshot(e,PROFILES,1900)['portfolio']
        self.assertEqual(D(a['active_cost']),0);self.assertEqual(D(a['pending_cost']),D('11.3'))
        self.assertEqual(D(a['pending_contracts']),110)

    def test_partial_fill_moves_only_filled_cost_out_of_reserved_cash(self):
        e=Engine(Mock(),cash='100');e.advance(1000)
        e.add_market(dict(ticker='KXBTC15M-test',bot_id='btc',close=1900),FeePolicy())
        b=e.books['KXBTC15M-test'];b.valid=True;b.at=1000
        b.levels={'yes':{D('.1'):D(100)},'no':{D('.8'):D(100)}}
        e.place('KXBTC15M-test','yes','buy',D(100),D('.1'));e.advance(1000.15)
        e.handle('kalshi',dict(type='trade',msg=dict(market_ticker='KXBTC15M-test',trade_id='partial',
            yes_price_dollars='.1',count_fp='125',taker_side='no',ts_ms=1000200)),1000.2)
        a=snapshot(e,PROFILES,1000.2)['portfolio']
        self.assertEqual(D(a['cash']),D('97.5'));self.assertEqual(D(a['unfilled_bids']),D('7.5'))
        self.assertEqual(D(a['active_cost']),D('2.5'));self.assertEqual(D(a['available_cash']),90)
        self.assertEqual(D(a['total_pnl']),0)
