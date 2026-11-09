import unittest
from decimal import Decimal as D
from services.paper_demo.shadow.favorite_entries import entry_key,observe
from services.paper_demo.shadow.favorite_timing import cell
from services.paper_demo.shadow.favorite_statistics import select,statistics_quote
from services.paper_demo.shadow.statistics_favorites import StatisticsFavoritesStrategy
from services.api.tests.test_strategy_folders import QuietAudit,market,profile
from services.paper_demo.shadow.core import Engine

def add_events(cells,series,count,wins,price='.80',h='10–15m',market_type='15m_price',side='yes'):
    key=entry_key(series,side,D(price),600)
    cell(cells,key,dict(key=key,series=series,market_type=market_type,side=side,price=price,horizon=h,clock='market_close'))
    for i in range(count):observe(cells,key,f'{series}-{i}',int(i<wins))
    return key

class StatisticsEvidence(unittest.TestCase):
    def test_sparse_exact_group_falls_back_to_pooled_market_type_segment(self):
        cells={}
        add_events(cells,'KXBTCD',6,6);add_events(cells,'KXETHD',8,8)
        p=profile(series='KXBTCD',strategy='favorites_statistics')
        result=select(cells,p,dict(close=1000), 'yes',D('.80'),600,min_samples=10)
        self.assertEqual(result['level'],'market_type_price_time_side')
        self.assertEqual(result['samples'],14)

    def test_tiny_groups_are_not_treated_as_authoritative(self):
        cells={};add_events(cells,'KXBTCD',3,3)
        p=profile(series='KXBTCD',strategy='favorites_statistics')
        result=select(cells,p,dict(close=1000),'yes',D('.80'),600,min_samples=10)
        self.assertEqual(result['reason'],'insufficient_samples')
        self.assertEqual(result['samples'],3)

    def test_new_settled_observations_can_change_future_decision(self):
        e=Engine(QuietAudit(),cash='1000');e.advance(200)
        market(e,'KXBTCD-test',yes='.79',no='.19',close=1000)
        p=dict(profile(series='KXBTCD',strategy='favorites_statistics'),statistics_min_samples=10,
               statistics_min_probability_edge='.01',statistics_min_expected_roi='.01',statistics_slippage_buffer='0')
        cells={};add_events(cells,'KXBTCD',10,9)
        q,first=statistics_quote(e,p,D(10),'KXBTCD-test','yes',cells)
        self.assertIsNone(q)
        key=entry_key('KXBTCD','yes',D('.80'),600)
        for i in range(10,40):observe(cells,key,f'KXBTCD-{i}',1)
        q,second=statistics_quote(e,p,D(10),'KXBTCD-test','yes',cells)
        self.assertIsNotNone(q);self.assertEqual(second['reason'],'trade')
        self.assertGreater(second['samples'],first['samples'])

    def test_strategy_reads_collector_evidence_without_own_history_copy(self):
        e=Engine(QuietAudit(),cash='1000');e.advance(200)
        market(e,'KXBTCD-test',yes='.79',no='.19',close=1000)
        p=dict(profile(series='KXBTCD',strategy='favorites_statistics'),statistics_min_samples=10,
               statistics_min_probability_edge='.01',statistics_min_expected_roi='.01',statistics_slippage_buffer='0')
        cells={};add_events(cells,'KXBTCD',40,39)
        b=StatisticsFavoritesStrategy(e,p);b.set_statistics_source(lambda:cells);e.strategy=b;e.fill_callback=b.on_fill
        b.step()
        self.assertTrue(e.orders)
        self.assertEqual(next(iter(e.orders.values())).maker,True)
        self.assertEqual(b.attempts['KXBTCD-test']['entry_policy'],'favorites-statistics-v1')
        self.assertFalse(b.exit_evidence.cells)

if __name__=='__main__':unittest.main()
