import unittest
from decimal import Decimal as D
from services.paper_demo.shadow.favorite_wide import price_band,summarize_wide

class WideBuckets(unittest.TestCase):
    def row(self,price='.75',horizon='5–10m',event='one',**extra):
        return dict(price=price,horizon=horizon,contracts='10',cost=str(D(price)*10),
                    outcome_events={event:1},return_events={event:dict(cost=str(D(price)*10),net=str(10-D(price)*10))},**extra)
    def summary(self,rows,series='KXBTC15M',asset='crypto'):
        return summarize_wide({'bot':dict(entry_timing=rows)},{'bot':dict(series=series,asset=asset)},lambda p:'category')
    def test_purchase_price_boundaries_are_exact(self):
        for price,band in (('.6999',None),('.70',0),('.7799',0),('.78',1),('.8599',1),('.86',2),('.95',2),('.9501',None)):
            self.assertEqual(price_band(price),band,price)
    def test_15m_legacy_intervals_pool_without_inventing_timestamps_or_double_counting(self):
        result=self.summary([self.row(),self.row('.76')])
        row=result['rows']['category'][0]
        self.assertEqual(row['events'],1);self.assertEqual(row['return_observations'],1)
        self.assertEqual(row['time_slot'],1)
        self.assertEqual(result['coverage']['category']['time_buckets'],['0m–5m','5m–10m','10m–15m'])
        self.assertEqual(D(row['average_return_pct']),D(100)*D('4.9')/D('15.1'))
    def test_hourly_crossing_legacy_time_band_is_excluded_but_exact_entry_is_usable(self):
        excluded=self.summary([self.row(horizon='15–30m')],series='KXBTCD',asset='hourly')
        self.assertFalse(excluded['rows']['category'])
        self.assertEqual(excluded['coverage']['category']['excluded_legacy_observations'],1)
        exact=self.summary([self.row(horizon='15–30m',wide_events={'one':[[1800,'10','7.5']]})],series='KXBTCD',asset='hourly')
        self.assertEqual(exact['rows']['category'][0]['time_slot'],1)
        self.assertEqual(exact['rows']['category'][0]['events'],1)
    def test_exact_time_boundaries_and_maximum_are_classified_once(self):
        rows=[self.row(event=str(t),wide_events={str(t):[[t,'10','7.5']]}) for t in (0,300,600,900)]
        result=self.summary(rows)['rows']['category']
        self.assertEqual([(r['time_slot'],r['events']) for r in result],[(0,1),(1,1),(2,2)])
    def test_sports_and_daily_use_observed_betting_window_not_day_long_market(self):
        for asset in ('sports','weather_daily'):
            row=self.row(time_min=3600,time_max=7200,wide_events={'one':[[3600,'2','1.5'],[4800,'2','1.5'],[7200,'2','1.5']]})
            result=self.summary([row],series='SPORT',asset=asset)
            coverage=result['coverage']['category']
            self.assertEqual((coverage['window_start_seconds'],coverage['window_end_seconds']),(3600,7200))
            self.assertEqual(len(result['rows']['category']),3)
            self.assertEqual({r['events'] for r in result['rows']['category']},{1})
    def test_unknown_observed_range_and_ambiguous_legacy_return_are_not_invented(self):
        result=self.summary([self.row(horizon='>=2h')],asset='weather_daily')
        self.assertFalse(result['rows']['category'])
        row=self.row();row['return_events']={}
        wide=self.summary([row])['rows']['category'][0]
        self.assertEqual(wide['events'],1);self.assertEqual(wide['return_observations'],0)

    def test_detailed_rollup_deduplicates_one_event_across_partial_price_fills(self):
        from services.api.shadow import favorite_collector_timed_totals
        a=self.row();b=self.row('.76')
        for row in (a,b):row.update(events=1,event_win_rate=100,market_type='15m_price',clock='market_close')
        result=favorite_collector_timed_totals({'bot':dict(entry_timing=[a,b])},
                    {'bot':dict(series='KXBTC15M',asset='crypto')})
        row=result['rows']['crypto-15m'][0]
        self.assertEqual(D(row['events']),1);self.assertEqual(D(row['event_wins']),1)
        self.assertEqual(row['return_observations'],1)

    def test_actual_hold_cash_return_is_not_replaced_by_adverse_correlated_outcome(self):
        row=self.row(wide_events={'one':[[400,'10','7.5','2.5']]})
        row['outcome_events']={'one':0}
        result=self.summary([row])['rows']['category'][0]
        self.assertEqual(result['event_wins'],0)
        self.assertEqual(D(result['average_return_pct']),D(100)/3)

    def test_empty_hourly_category_still_shows_its_three_known_time_columns(self):
        result=self.summary([],series='KXUSDCADAH',asset='hourly')
        self.assertEqual(result['rows']['category'],[])
        self.assertEqual(result['coverage']['category']['time_buckets'],['0m–20m','20m–40m','40m–60m'])
