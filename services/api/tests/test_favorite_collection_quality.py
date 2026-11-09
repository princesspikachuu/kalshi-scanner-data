import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from decimal import Decimal as D
from services.paper_demo.shadow.core import Engine,FeePolicy
from services.paper_demo.shadow.host import book_ingest_age_bucket
from services.paper_demo.shadow.runner import ForwardRun
from services.paper_demo.shadow.favorite_entries import observe
from services.paper_demo.shadow.favorite_timing import cell
from services.paper_demo.shadow.favorite_collection_quality import collection_quality


def evidence(cells,key,series,market_type,price,horizon,contracts=5):
    cell(cells,key,dict(key=key,series=series,market_type=market_type,
        side='yes',price=price,horizon=horizon,clock='market_close'))
    cells['timing-metrics|'+key].update(contracts=str(contracts),resolved=str(contracts))


def bot(cells):
    return SimpleNamespace(exit_evidence=SimpleNamespace(cells=cells))


class FavoritesCollectionQualityTests(unittest.TestCase):
    def test_repeat_settlements_and_price_cells_are_not_independent_outcomes(self):
        cells={}
        evidence(cells,'one','AAA','15m_price','.72','5–10m')
        evidence(cells,'two','BBB','15m_price','.77','10–15m')
        observe(cells,'one','EVENT-A',1,observed_at=10000)
        observe(cells,'one','EVENT-A',0,observed_at=10001)
        observe(cells,'two','EVENT-A',1,observed_at=10002)
        observe(cells,'two','EVENT-B',1,observed_at=6500)
        report=collection_quality([bot(cells)],now=10050)
        self.assertEqual(report['unique_verified_outcomes'],2)
        self.assertEqual(report['unique_verified_1h'],2)
        self.assertEqual(report['cohort_contracts'],'10')
        self.assertEqual(report['outcome_cells'],2)
        self.assertEqual(len(report['price_time_cells']),2)
        self.assertEqual(cells['one']['events']['EVENT-A'],0)
        self.assertEqual(cells['one']['event_times']['EVENT-A'],10000)

    def test_legacy_evidence_is_counted_but_does_not_invent_rolling_time(self):
        cells={}
        evidence(cells,'one','AAA','weather_daily','.93','>=2h')
        observe(cells,'one','OLD',1)
        observe(cells,'one','NEW',1,observed_at=9990)
        report=collection_quality([bot(cells)],10000)
        mt=report['by_market_type']['weather_daily']
        self.assertEqual(mt['unique_verified_outcomes'],2)
        self.assertEqual(mt['unique_verified_1h'],1)
        self.assertEqual(mt['unknown_time_outcomes'],1)
        self.assertFalse(mt['rolling_window_complete'])

    def test_price_time_groups_deduplicate_across_bots(self):
        a,b={},{}
        evidence(a,'a','AAA','15m_price','.74','<3m')
        evidence(b,'b','BBB','15m_price','.73','<3m')
        observe(a,'a','SHARED',1,observed_at=100)
        observe(b,'b','SHARED',1,observed_at=100)
        report=collection_quality([bot(a),bot(b)],now=120)
        self.assertEqual(report['unique_verified_outcomes'],1)
        self.assertEqual(report['price_time_cells'][0]['unique_verified_outcomes'],1)

    def test_global_count_does_not_double_count_shared_event_across_market_types(self):
        a,b={},{}
        evidence(a,'a','AA','weather_daily','.83','>=2h')
        evidence(b,'b','BB','15m_price','.81','5–10m')
        observe(a,'a','EVENT-1',1,observed_at=9500)
        observe(b,'b','EVENT-1',0,observed_at=9600)
        report=collection_quality([bot(a),bot(b)],now=10000)
        self.assertEqual(report['unique_verified_outcomes'],1)
        self.assertEqual(report['unique_verified_1h'],1)
        self.assertEqual(sum(v['unique_verified_outcomes'] for v in report['by_market_type'].values()),2)
        self.assertFalse(report['rolling_counts_are_lower_bounds'])

    def test_distinct_categories_contribute_to_global_unique_outcome_totals(self):
        a,b={},{}
        evidence(a,'crypto','AAA','15m_price','.72','5–10m')
        evidence(b,'weather','BBB','weather_daily','.92','>=2h')
        observe(a,'crypto','CRYPTO-A',1,observed_at=9700)
        observe(a,'crypto','CRYPTO-B',0,observed_at=9600)
        observe(b,'weather','WEATHER-C',1,observed_at=9900)
        report=collection_quality([bot(a),bot(b)],now=10000)
        self.assertEqual(report['unique_verified_outcomes'],3)
        self.assertEqual(report['unique_verified_1h'],3)
        self.assertEqual(report['unique_verified_24h'],3)
        self.assertFalse(report['rolling_counts_are_lower_bounds'])
        by_cell={(c['market_type'],c['price_bucket'],c['horizon']):c for c in report['price_time_cells']}
        crypto=by_cell['15m_price','70-74','5–10m']
        weather=by_cell['weather_daily','90-94','>=2h']
        self.assertEqual(crypto['unique_verified_outcomes'],2)
        self.assertEqual(crypto['unique_verified_1h'],2)
        self.assertEqual(weather['unique_verified_24h'],1)
        self.assertTrue(all(c['rolling_window_complete'] for c in by_cell.values()))

    def test_untimed_outcomes_do_not_gain_fabricated_window_membership(self):
        a={}
        evidence(a,'old','OLD','15m_price','.84','10–15m')
        observe(a,'old','OLD-1',1)
        observe(a,'old','NEW-2',1,observed_at=9999)
        report=collection_quality([bot(a)],now=10000)
        self.assertEqual(report['unknown_time_outcomes'],1)
        self.assertTrue(report['rolling_counts_are_lower_bounds'])
        self.assertEqual(report['unique_verified_1h'],1)
        row=report['price_time_cells'][0]
        self.assertEqual(row['unique_verified_outcomes'],2)
        self.assertEqual(row['unknown_time_outcomes'],1)
        self.assertEqual(row['unique_verified_1h'],1)
        self.assertFalse(row['rolling_window_complete'])

    def test_timestamp_metadata_is_bounded_with_evidence(self):
        cells={}
        for i in range(505):
            observe(cells,'one',str(i),1,observed_at=i)
        self.assertEqual(len(cells['one']['events']),500)
        self.assertEqual(len(cells['one']['event_times']),500)
        self.assertNotIn('0',cells['one']['event_times'])
        self.assertEqual(cells['one']['event_times']['504'],504.0)



class FavoritesBookFilterTests(unittest.TestCase):
    def test_unchanged_top_book_deltas_are_applied_without_extra_strategy_evaluation(self):
        engine=Engine(Mock());engine.filter_unchanged_quotes=True
        engine.add_market(dict(ticker='TEST',close=2000),FeePolicy())
        calls=[]
        engine.strategy=SimpleNamespace(step=lambda ticker=None:calls.append(ticker))
        snapshot=dict(type='orderbook_snapshot',sid=3,seq=1,sending_ts_ms=1000000,
            msg=dict(market_ticker='TEST',yes_dollars_fp=[['.70','100']],no_dollars_fp=[['.20','100']]))
        engine.handle('kalshi',snapshot,1000)
        self.assertEqual(calls,['TEST'])
        # All deltas are still applied in order; a below-best price level cannot
        # change a maker quote until clock/time or top-of-book quality changes.
        delta=dict(type='orderbook_delta',sid=3,seq=2,sending_ts_ms=1000500,
            msg=dict(market_ticker='TEST',side='yes',price_dollars='.60',delta_fp='10'))
        engine.handle('kalshi',delta,1000.5)
        self.assertEqual(engine.books['TEST'].levels['yes'][D('.60')],D(10))
        self.assertEqual(calls,['TEST'])
        delta.update(seq=3,sending_ts_ms=1000600,
            msg=dict(market_ticker='TEST',side='yes',price_dollars='.70',delta_fp='5'))
        engine.handle('kalshi',delta,1000.6)
        self.assertEqual(calls,['TEST'])
        # Material depth changes must trigger immediate review.
        delta.update(seq=4,sending_ts_ms=1000700,
            msg=dict(market_ticker='TEST',side='yes',price_dollars='.70',delta_fp='30'))
        engine.handle('kalshi',delta,1000.7)
        self.assertEqual(calls,['TEST','TEST'])
        # The regular clock reevaluates unchanged books and time bands.
        engine.handle('clock',{},1000.8)
        self.assertEqual(calls,['TEST','TEST',None])
        self.assertEqual(engine.sequences[3],4)


class FeedFreshnessMetricsTests(unittest.TestCase):
    def test_book_transport_age_is_separate_from_queue_processing_lag(self):
        now=1000
        self.assertEqual(book_ingest_age_bucket(999800,now),'under_1s')
        self.assertEqual(book_ingest_age_bucket(998000,now),'1_to_3s')
        self.assertEqual(book_ingest_age_bucket(995000,now),'3_to_10s')
        self.assertEqual(book_ingest_age_bucket(980000,now),'over_10s')
        self.assertEqual(book_ingest_age_bucket(None,now),'missing_timestamp')
        self.assertEqual(book_ingest_age_bucket('NaN',now),'invalid_or_future_timestamp')
        self.assertEqual(book_ingest_age_bucket(1002000,now),'invalid_or_future_timestamp')

    def test_simulation_rejection_reasons_are_counted_separately(self):
        fake=SimpleNamespace(engine=SimpleNamespace(books={'TEST':object()},data_gap=Mock()))
        payload=dict(msg=dict(market_ticker='TEST'))
        ForwardRun.reject_input(fake,'kalshi',payload,ValueError('stale book event'))
        ForwardRun.reject_input(fake,'kalshi',payload,ValueError('book sequence gap'))
        self.assertEqual(fake.input_rejections,2)
        self.assertEqual(fake.input_rejection_reasons,
            {'kalshi:stale book event':1,'kalshi:book sequence gap':1})
        self.assertEqual(fake.engine.data_gap.call_count,2)


if __name__=='__main__':unittest.main()
