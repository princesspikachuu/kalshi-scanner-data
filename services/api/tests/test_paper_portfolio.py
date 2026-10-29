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
    def test_many_events_are_spooled_with_small_sqlite_cache(self):
        from unittest.mock import patch
        import sqlite3
        original_connect=sqlite3.connect
        statements=[]
        class Connection:
            def __init__(self,connection):self.connection=connection
            def execute(self,statement,*args):
                if statement.startswith('PRAGMA'):statements.append(statement)
                return self.connection.execute(statement,*args)
            def __getattr__(self,name):return getattr(self.connection,name)
            def close(self):return self.connection.close()
        with patch('services.paper.portfolio.sqlite3.connect',side_effect=lambda *a,**k:Connection(original_connect(*a,**k))):
            outcome=self.run_replay([source()])
        self.assertIsInstance(outcome['ending_cash_cents'],int)
        self.assertIn('PRAGMA mmap_size=0',statements)
        self.assertIn('PRAGMA cache_size=-1024',statements)

    def test_compressed_paper_source_streams_without_full_json_expansion(self):
        from services.paper.stream import replay_source
        from services.research.datasets import storage_payload
        from services.research.inventory import digest
        import json
        asset,payload,records=source(trades=[trade(BASE+3,volume=2)])
        records=records*2000  # Large enough to force compressed storage.
        raw={**payload,'format':'raw-evidence-dataset-v1',
             'summary':{'resources':['trades','candles']},'records':records}
        canonical=json.dumps(raw,sort_keys=True,separators=(',',':'),allow_nan=False)
        fp=digest(raw)
        compressed=storage_payload(canonical,fp)
        self.assertEqual(compressed.get('storage'),'raw-evidence-gzip-v1')
        result=replay_source(dict(asset=asset,payload=compressed,fingerprint=fp),None)
        self.assertEqual(result[0],'btc')
        self.assertEqual(result[1]['candidates'],payload['candidates'])
        self.assertEqual(list(result[2]),records)
        # Fingerprint checking rejects altered compressed metadata.
        with self.assertRaises(ValueError):
            replay_source(dict(asset=asset,payload={**compressed,'sha256':'0'*64},
                fingerprint=fp),None)

    def test_progress_reports_actual_timeline_denominator(self):
        updates=[]
        r=replay_portfolio([source(bars=[candle(BASE),candle(BASE+60)],
            trades=[trade(BASE+3,volume=2)])],[strategy()],10000,
            on_progress=updates.append)
        self.assertIsInstance(r['profit_loss_cents'],int)
        markers=[v for v in updates if v.get('phase')=='replaying saved markets'
            and 'percent_complete' in v]
        self.assertTrue(markers)
        self.assertEqual(markers[0]['percent_complete'],35)
        self.assertEqual(markers[0]['events_processed'],0)
        self.assertEqual(markers[0]['events_total'],4)
        self.assertTrue(all(0<=x['percent_complete']<=99 for x in markers))

    def test_optional_cap_overrides_distance(self):
        self.assertEqual(proposed_bid(96,strategy(below_ask_cents=2)),94)
        self.assertEqual(proposed_bid(96,strategy(below_ask_cents=2,maximum_bid_cents=90)),90)
        self.assertEqual(proposed_bid(96,strategy(bid_reference='best_bid',bid_adjustment_cents=0),best_bid=87),87)
        self.assertEqual(proposed_bid(96,strategy(bid_reference='best_bid',bid_adjustment_cents=1),best_bid=87),88)
        self.assertEqual(proposed_bid(96,strategy(bid_reference='best_bid',bid_adjustment_cents=-2),best_bid=87),85)
        self.assertEqual(proposed_bid(96,strategy(bid_reference='best_bid',bid_adjustment_cents=1,maximum_bid_cents=82),best_bid=87),82)
        self.assertEqual(proposed_bid(96,strategy(bid_reference='ask',bid_adjustment_cents=-3),best_bid=87),93)
        with self.assertRaises(ValueError):
            proposed_bid(96,strategy(bid_reference='best_bid'),best_bid=87)
    def test_best_bid_basis_uses_same_ask_band_entry_gate(self):
        src=source(bars=[candle(BASE,bid=81,ask=96)])
        r=self.run_replay([src],[strategy(bid_reference='best_bid',bid_adjustment_cents=0,
            min_price=90,max_price=99)])
        self.assertEqual(r['orders_placed'],1)
        bid=next(e for e in r['trades'] if e['kind']=='bid')
        self.assertEqual(bid['bid_cents'],81)
        self.assertEqual(bid['ask_cents'],96)
        self.assertEqual(bid['best_bid_cents'],81)
        self.assertEqual(bid['bid_reference'],'best_bid')
        self.assertEqual(r['reconciliation']['strategies'][0]['bid_reference'],'best_bid')
        too_high=self.run_replay([src],[strategy(bid_reference='best_bid',bid_adjustment_cents=15)])
        self.assertEqual(too_high['orders_placed'],0)
        wrong_ask=self.run_replay([source(bars=[candle(BASE,bid=81,ask=89)])],
            [strategy(bid_reference='best_bid',bid_adjustment_cents=0)])
        self.assertEqual(wrong_ask['orders_placed'],0)
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
        self.assertEqual(r['ending_cash_cents'],10022)
    def test_all_filled_mode_fills_with_no_trades_and_ignores_stops(self):
        src=source(trades=[])
        r=self.run_replay([src],model='all_filled')
        self.assertEqual(r['orders_placed'],1)
        self.assertEqual(r['filled_contracts'],5)
        self.assertEqual(r['expired_orders'],0)
        self.assertEqual(r['reconciliation']['fill_rate_percent'],100)
        self.assertEqual(r['profit_loss_cents'],55)
        self.assertEqual(self.run_replay([src],model='estimated')['filled_contracts'],0)
        stopped=self.run_replay([source(bars=[candle(BASE),candle(BASE+60,50,60)])],
            [strategy(loss_trigger_cents=70)],model='all_filled')
        self.assertEqual(stopped['loss_prevention_sales'],0)
        self.assertEqual(stopped['filled_contracts'],5)

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
        self.assertEqual(r['ending_cash_cents'],9922)
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
    def test_spooled_replay_handles_streamed_large_history_without_event_heap(self):
        count=16000
        asset,payload,_=source()
        def rows():
            for i in range(count):
                # Most quotes can be filtered outside the entry window, but
                # they must still stream through the on-disk timeline.
                yield dict(ticker='a',resource='candles',
                    record=candle(BASE-12000+i))
        updates=[]
        result=replay_portfolio([(asset,payload,rows())],[strategy()],10000,on_progress=updates.append)
        first=next(x for x in updates if x.get('phase')=='replaying saved markets')
        self.assertEqual(first['records_loaded'],count)
        self.assertEqual(first['events_total'],min(count,12300)+1)
        self.assertEqual(result['starting_cash_cents'],10000)
        self.assertEqual(result['ending_cash_cents'],10000)
        self.assertTrue(any(x.get('events_processed',0)>0 for x in updates))

    def test_spooled_replay_preserves_chronological_market_priority(self):
        # Event order at equal timestamps must remain stable in the same
        # per-market order as the previous in-memory heap implementation.
        a=source(ticker='earlier',event='first')
        b=source(ticker='later',event='second')
        result=replay_portfolio([a,b],[strategy(contracts=100)],10000)
        bids=[x for x in result['trades'] if x['kind']=='bid']
        self.assertEqual([x['ticker'] for x in bids],['earlier','later'])

    def test_newest_source_replaces_duplicate_market_instead_of_double_filling(self):
        r=self.run_replay([source(trades=[trade(BASE+3,volume=10)]),source(trades=[])])
        self.assertEqual(r['filled_contracts'],0)
    def test_trade_at_period_end_cannot_fill_expired_bid(self):
        r=self.run_replay([source(trades=[trade(BASE+300,volume=10)])])
        self.assertEqual(r['filled_contracts'],0);self.assertEqual(r['ending_cash_cents'],10000)

    def test_profitable_qualified_orders_can_lose_on_adverse_fill_selection(self):
        selected=strategy(min_price=90,max_price=99)
        # All ten ask-qualified orders would net +50c if filled. But only
        # the losing order has opposing taker volume supporting a maker fill.
        sources=[source(ticker=f'winner-{i}',event=f'winner-event-{i}',
            bars=[candle(BASE,bid=80,ask=90)],trades=[]) for i in range(9)]
        loser_asset,loser_payload,loser_records=source(ticker='loser',event='loser-event',
            bars=[candle(BASE,bid=80,ask=90)],trades=[trade(BASE+3,volume=5)])
        loser_payload['candidates'][0]['result']='no'
        sources.append((loser_asset,loser_payload,loser_records))
        r=self.run_replay(sources,[selected])
        audit=r['reconciliation']
        self.assertEqual(audit['qualified_orders'],10)
        self.assertEqual(audit['qualified_contracts'],50)
        self.assertEqual(audit['filled_contracts'],5)
        self.assertEqual(audit['filled_winners'],0)
        self.assertEqual(audit['all_qualified_filled_pnl_cents'],50)
        self.assertEqual(audit['filled_hold_pnl_cents'],-445)
        self.assertEqual(audit['reconciled_realized_pnl_cents'],-445)
        self.assertEqual(audit['loss_prevention_delta_cents'],0)
        self.assertEqual(audit['strategies'][0]['qualified_win_rate_percent'],90)
        self.assertEqual(audit['strategies'][0]['filled_win_rate_percent'],0)
        self.assertGreater(audit['strategies'][0]['qualified_all_fill_roi_percent'],0)
        self.assertLess(audit['strategies'][0]['filled_hold_roi_percent'],0)

    def test_pay_near_ask_erases_positive_best_bid_edge_even_with_full_fills(self):
        # Same exact opportunities and outcomes, 90% winners at 94c lose;
        # a resting 85c maker price would have positive conditional P/L,
        # but the lower price is NOT assumed to fill at the same rate.
        s=strategy(min_price=95,max_price=99,statistical_yield_percent=5)
        sources=[]
        for i in range(10):
            asset,payload,records=source(ticker=f'spread-{i}',event=f'event-spread-{i}',
                bars=[candle(BASE,bid=85,ask=95)],
                trades=[trade(BASE+3,price=94,volume=5)])
            if i==9:payload['candidates'][0]['result']='no'
            sources.append((asset,payload,records))
        r=self.run_replay(sources,[s]);audit=r['reconciliation'];by=audit['strategies'][0]
        self.assertEqual(audit['filled_contracts'],50)
        self.assertEqual(audit['fill_rate_percent'],100)
        self.assertEqual(audit['all_qualified_filled_pnl_cents'],-200)
        self.assertEqual(audit['same_orders_best_bid_pnl_cents'],250)
        self.assertEqual(audit['entry_price_premium_cents'],450)
        self.assertEqual(audit['filled_entry_price_premium_cents'],450)
        self.assertEqual(by['avg_displayed_spread_cents'],10)
        self.assertEqual(by['avg_entry_premium_over_best_bid_cents'],9)
        self.assertEqual(by['filled_win_rate_percent'],90)
        self.assertEqual(by['filled_break_even_win_rate_percent'],94)

    def test_nearly_all_fills_still_lose_when_win_rate_below_break_even(self):
        # An apparently attractive historical bid-grid strategy has a
        # different ask-qualified cohort. Even with 100% fills and 90%
        # winners, buying at 94c loses because break-even is 94%.
        selected=strategy(min_price=90,max_price=99,statistical_yield_percent=5)
        sources=[]
        for i in range(10):
            asset,payload,records=source(ticker=f'market-{i}',event=f'event-{i}',
                bars=[candle(BASE,bid=93,ask=95)],
                trades=[trade(BASE+3,price=94,volume=5)])
            if i==9:payload['candidates'][0]['result']='no'
            sources.append((asset,payload,records))
        r=self.run_replay(sources,[selected])
        audit=r['reconciliation'];s=audit['strategies'][0]
        self.assertEqual(audit['qualified_contracts'],50)
        self.assertEqual(audit['filled_contracts'],50)
        self.assertEqual(audit['cancelled_unfilled_contracts'],0)
        self.assertEqual(audit['fill_rate_percent'],100)
        self.assertEqual(s['filled_win_rate_percent'],90)
        self.assertEqual(s['filled_break_even_win_rate_percent'],94)
        self.assertEqual(s['reference_bid_grid_roi_percent'],5)
        self.assertLess(r['profit_loss_cents'],0)

    def test_loss_prevention_audit_reconciles_exit_against_holding(self):
        r=self.run_replay([source(bars=[candle(BASE),candle(BASE+60,50,60)],
            trades=[trade(BASE+3,volume=2)])],[strategy(loss_trigger_cents=70)])
        audit=r['reconciliation']
        self.assertEqual(audit['filled_hold_pnl_cents'],22)
        self.assertEqual(audit['reconciled_realized_pnl_cents'],-78)
        self.assertEqual(audit['loss_prevention_delta_cents'],-100)

    def test_activity_reports_identifiable_bids_fills_and_simulated_time(self):
        updates=[]
        r=replay_portfolio([source(trades=[trade(BASE+3,volume=2)])],[strategy()],10000,on_progress=updates.append)
        self.assertTrue(any(u.get('phase')=='loading saved evidence' for u in updates))
        bid=next(e for u in updates for e in u.get('recent_activity',[]) if e['kind']=='bid')
        fill=next(e for u in updates for e in u.get('recent_activity',[]) if e['kind']=='fill')
        self.assertEqual(bid['order_id'],fill['order_id']);self.assertEqual(bid['side'],'yes')
        self.assertEqual(bid['bid_cents'],89);self.assertEqual(fill['remaining'],3)
        self.assertTrue(any(u.get('simulated_time')==BASE+3 for u in updates))
        self.assertTrue(r['recent_activity'])
