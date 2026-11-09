import unittest
from decimal import Decimal as D
from services.paper_demo.shadow.favorite_entries import entry_key,observe
from services.paper_demo.shadow.favorite_timing import cell
from services.paper_demo.shadow.favorite_statistics import select,statistics_quote,aggregate,statistics_matrix,price_bucket,PRICE_BUCKETS,select_groups
from services.paper_demo.shadow.statistics_favorites import StatisticsFavoritesStrategy
from services.api.tests.test_strategy_folders import QuietAudit,market,profile
from services.paper_demo.shadow.core import Engine

def add_events(cells,series,count,wins,price='.80',h='10–15m',market_type='15m_price',side='yes'):
    key=entry_key(series,side,D(price),600)
    cell(cells,key,dict(key=key,series=series,market_type=market_type,side=side,price=price,horizon=h,clock='market_close'))
    for i in range(count):observe(cells,key,f'{series}-{i}',int(i<wins))
    return key

class StatisticsEvidence(unittest.TestCase):
    def test_sparse_cell_probes_even_with_no_settled_history(self):
        e=Engine(QuietAudit(),cash='1000');e.advance(200)
        market(e,'KXBTCD-test',yes='.79',no='.19',close=1000)
        p=dict(profile(series='KXBTCD',strategy='favorites_statistics'),
               statistics_active_learning=True,statistics_exploration_contracts=2)
        q,decision=statistics_quote(e,p,D(10),'KXBTCD-test','yes',{})
        self.assertIsNotNone(q)
        self.assertEqual(q['mode'],'statistics_exploration')
        self.assertEqual(q['quantity'],D(2))
        self.assertEqual(decision['reason'],'exploration_missing_cell')
        self.assertEqual(decision['exact_samples'],0)
        self.assertNotIn('trade',decision['decision_type'])
        self.assertTrue(decision['provisional_not_validated'])

    def test_exploration_caps_total_open_risk_and_does_not_claim_edge(self):
        e=Engine(QuietAudit(),cash='1000');e.advance(200)
        market(e,'KXBTCD-a',yes='.79',no='.19',close=1000)
        p=dict(profile(series='KXBTCD',strategy='favorites_statistics'),
               statistics_active_learning=True,statistics_exploration_contracts=2,
               statistics_exploration_portfolio_fraction='.001')
        q,decision=statistics_quote(e,p,D(10),'KXBTCD-a','yes',{})
        self.assertIsNone(q)
        self.assertEqual(decision['reason'],'exploration_budget_exhausted')
        self.assertEqual(decision['decision_type'],'exploration')

    def test_mature_unprofitable_cell_does_not_explore(self):
        e=Engine(QuietAudit(),cash='1000');e.advance(200)
        market(e,'KXBTCD-test',yes='.79',no='.19',close=1000)
        cells={};add_events(cells,'KXBTCD',30,10)
        p=dict(profile(series='KXBTCD',strategy='favorites_statistics'),
               statistics_active_learning=True,statistics_min_samples=20)
        q,decision=statistics_quote(e,p,D(10),'KXBTCD-test','yes',cells)
        self.assertIsNone(q)
        self.assertEqual(decision['exact_samples'],30)
        self.assertIn(decision['reason'],('confidence_lower_bound_below_threshold','evidence_below_threshold'))

    def test_statistical_bot_uses_scarce_side_instead_of_highest_bid(self):
        e=Engine(QuietAudit(),cash='1000');e.advance(200)
        market(e,'KXBTCD-test',yes='.79',no='.19',close=1000)
        cells={};add_events(cells,'KXBTCD',30,26,price='.80',side='yes')
        p=dict(profile(series='KXBTCD',strategy='favorites_statistics'),
               statistics_active_learning=True)
        b=StatisticsFavoritesStrategy(e,p)
        b.set_statistics_source(lambda:cells)
        self.assertEqual(b.choose_entry_side('KXBTCD-test',[(D('.79'),'yes'),(D('.19'),'no')]),'yes')
        # Both sides are considered, but only a maker price in range can win.

    def test_own_and_collector_results_count_one_event_once(self):
        a={};b={}
        add_events(a,'KXBTCD',3,3)
        add_events(b,'KXBTCD',3,3)
        p=dict(profile(series='KXBTCD',strategy='favorites_statistics'),
               statistics_active_learning=True)
        result=select_groups(aggregate([a,b]),p,dict(close=1000),'yes',D('.80'),600,1)
        self.assertEqual(result['samples'],3)

    def test_price_buckets_cover_range_without_crossing_five_cent_boundaries(self):
        self.assertEqual(price_bucket(D('.70')),'70-74')
        self.assertEqual(price_bucket(D('.74')),'70-74')
        self.assertEqual(price_bucket(D('.75')),'75-79')
        self.assertEqual(price_bucket(D('.90')),'90-94')
        self.assertEqual(price_bucket(D('.95')),'95-95')
        self.assertEqual(PRICE_BUCKETS,('70-74','75-79','80-84','85-89','90-94','95-95'))

    def test_matrix_preserves_exact_category_and_time_samples_and_shows_fallback(self):
        cells={}
        add_events(cells,'KXBTCD',3,3)
        add_events(cells,'KXETHD',30,29,price='.82')
        add_events(cells,'KXWEATHER',30,30,market_type='weather_daily')
        p=dict(profile(series='KXBTCD',strategy='favorites_statistics'),statistics_min_samples=20)
        matrices=statistics_matrix(aggregate(cells),p)
        kinds={m['market_type'] for m in matrices}
        self.assertEqual(kinds,{'15m_price','weather_daily'})
        crypto=next(m for m in matrices if m['market_type']=='15m_price')
        sparse=next(x for x in crypto['cells'] if x['price_bucket']=='80-84' and x['horizon']=='10–15m')
        self.assertEqual(sparse['samples'],33)
        self.assertEqual(sparse['fallback_level'],'market_type_price_time')
        thin=next(x for x in crypto['cells'] if x['price_bucket']=='80-84' and x['horizon']=='5–10m')
        self.assertEqual(thin['samples'],0)
        self.assertEqual(thin['eligibility'],'insufficient_samples')
        weather=next(m for m in matrices if m['market_type']=='weather_daily')
        populated=next(x for x in weather['cells'] if x['price_bucket']=='80-84' and x['horizon']=='10–15m')
        self.assertEqual(populated['samples'],30)

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
