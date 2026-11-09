import unittest
from types import SimpleNamespace
from decimal import Decimal as D
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

    def test_timestamp_metadata_is_bounded_with_evidence(self):
        cells={}
        for i in range(505):
            observe(cells,'one',str(i),1,observed_at=i)
        self.assertEqual(len(cells['one']['events']),500)
        self.assertEqual(len(cells['one']['event_times']),500)
        self.assertNotIn('0',cells['one']['event_times'])
        self.assertEqual(cells['one']['event_times']['504'],504.0)


if __name__=='__main__':unittest.main()
