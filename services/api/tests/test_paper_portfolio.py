import unittest
from services.paper.portfolio import replay_portfolio,proposed_bid
from datetime import datetime,timezone

BASE=1792886400

def iso(t):return datetime.fromtimestamp(t,timezone.utc).isoformat()
def candle(t,bid=80,ask=90):return dict(end_period_ts=t,yes_bid={'close':str(bid/100)},yes_ask={'close':str(ask/100)})
def trade(t,price=89,volume=1,**kwargs):return dict(created_time=iso(t),yes_price_dollars=str(price/100),no_price_dollars=str((100-price)/100),taker_outcome_side='no',count_fp=str(volume),**kwargs)
def source(asset='btc',ticker='a',event='game-a',bars=None,trades=None,close=BASE+300):
    c=dict(ticker=ticker,event_ticker=event,series='KXBTC15M',close_time=iso(close),result='yes')
    records=[dict(ticker=ticker,resource='candles',record=b) for b in (bars or [candle(BASE)])]
    records += [dict(ticker=ticker,resource='trades',record=t) for t in (trades or [])]
    return asset,{'candidates':[c]},records

def strategy(**kwargs):
    s=dict(asset='btc',entry_minute_min=3,entry_minute_max=5,min_price=90,max_price=99,below_ask_cents=1,maximum_bid_cents=None,contracts=5,balance_percent=10,loss_trigger_cents=None,statistical_yield_percent=5)
    s.update(kwargs);return s

class PortfolioTests(unittest.TestCase):
    def run_replay(self,sources,strategies=None,cash=10000,model='estimated'):
        return replay_portfolio(sources,strategies or [strategy()],cash,model)
    def test_optional_cap_overrides_distance(self):
        self.assertEqual(proposed_bid(96,strategy(below_ask_cents=2)),94)
        self.assertEqual(proposed_bid(96,strategy(below_ask_cents=2,maximum_bid_cents=90)),90)
    def test_ask_band_and_time_gate_not_proposed_bid(self):
        self.assertEqual(self.run_replay([source(bars=[candle(BASE,70,89)])])['orders_placed'],0)
        self.assertEqual(self.run_replay([source(bars=[candle(BASE+121)])])['orders_placed'],0)
        r=self.run_replay([source()], [strategy(maximum_bid_cents=70)])
        self.assertEqual(r['orders_placed'],1);self.assertEqual(r['trades'][0]['bid_cents'],70)
    def test_orders_fill_after_entry_window_then_expire_only_unfilled_remainder(self):
        r=self.run_replay([source(trades=[trade(BASE+200,volume=2)])])
        self.assertEqual(r['filled_contracts'],2);self.assertEqual(r['expired_orders'],1)
        expired=next(e for e in r['trades'] if e['kind']=='cancel')
        self.assertEqual(expired['time'],BASE+300);self.assertEqual(expired['contracts'],3)
        self.assertEqual(r['ending_cash_cents'],10020)
    def test_estimated_allows_at_bid_but_conservative_requires_through(self):
        src=source(trades=[trade(BASE+3,volume=2)])
        self.assertEqual(self.run_replay([src])['filled_contracts'],2)
        self.assertEqual(self.run_replay([src],model='conservative')['filled_contracts'],0)
        self.assertEqual(self.run_replay([source(trades=[trade(BASE+3,88,2)])],model='conservative')['filled_contracts'],2)
    def test_single_trade_volume_is_not_reused_by_multiple_bids(self):
        r=self.run_replay([source(trades=[trade(BASE+3,volume=3)])],[strategy(),strategy()],cash=100000)
        self.assertEqual(r['filled_contracts'],3)
    def test_multiple_bids_and_related_markets_share_event_cap(self):
        a=source(ticker='a',event='one-game');b=source(ticker='b',event='one-game')
        # Different source cohorts are combined; two strategies each request 5.
        r=self.run_replay([a,b],[strategy(),strategy()])
        self.assertLessEqual(r['peak_event_exposure_percent'],10)
        self.assertEqual(sum(e['contracts'] for e in r['trades'] if e['kind']=='bid'),11)
    def test_separate_games_can_each_reserve_ten_percent(self):
        r=self.run_replay([source(ticker='a'),source(ticker='b',event='game-b')],[strategy(contracts=100)])
        self.assertEqual(r['orders_placed'],2);self.assertLessEqual(r['peak_event_exposure_percent'],10)
    def test_stop_sells_at_observed_bid_below_trigger_without_floor(self):
        r=self.run_replay([source(bars=[candle(BASE),candle(BASE+60,50,60)],trades=[trade(BASE+3,volume=2)])],[strategy(loss_trigger_cents=70)])
        sale=next(e for e in r['trades'] if e['kind']=='loss_prevention_sale')
        self.assertEqual(sale['sale_cents'],50);self.assertEqual(r['loss_prevention_sales'],1)
        self.assertEqual(r['ending_cash_cents'],9918)
    def test_no_quote_after_fill_does_not_invent_stop_sale(self):
        r=self.run_replay([source(trades=[trade(BASE+3,volume=2)])],[strategy(loss_trigger_cents=50)])
        self.assertEqual(r['loss_prevention_sales'],0)
    def test_higher_yield_sports_reclaims_lower_yield_unfilled_funds(self):
        sources=[source(ticker=f'crypto{i}',event=f'crypto{i}',trades=[trade(BASE+200,volume=10)]) for i in range(10)]
        sources.append(source('sports',ticker='sport',event='match',bars=[candle(BASE+60)],trades=[trade(BASE+100,volume=10)]))
        # The sport starts one minute later; initial ten orders use 99% cash.
        r=self.run_replay(sources,[strategy(contracts=100),strategy(asset='sports',statistical_yield_percent=20,contracts=100)])
        self.assertGreater(r['priority_cancellations'],0)
        self.assertTrue(any(e['kind']=='fill' and e['ticker']=='sport' for e in r['trades']))
        self.assertGreaterEqual(r['ending_cash_cents'],0)
    def test_newest_source_replaces_duplicate_market_instead_of_double_filling(self):
        r=self.run_replay([source(trades=[trade(BASE+3,volume=10)]),source(trades=[])])
        self.assertEqual(r['filled_contracts'],0)
    def test_trade_at_period_end_cannot_fill_expired_bid(self):
        r=self.run_replay([source(trades=[trade(BASE+300,volume=10)])])
        self.assertEqual(r['filled_contracts'],0);self.assertEqual(r['ending_cash_cents'],10000)
