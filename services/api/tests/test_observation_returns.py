import unittest
from decimal import Decimal as D
from services.paper_demo.shadow.observation_returns import merge, summarize

class ReturnTests(unittest.TestCase):
    def test_equal_event_weight_and_merge_correlated_partial_fills(self):
        values={}
        merge(values,{'small':dict(cost='1',net='1'),'large':dict(cost='100',net='-10')})
        self.assertEqual(D(summarize(values)['average_return_pct']),45)
        merge(values,{'small':dict(cost='9',net='-1')})
        self.assertEqual(D(summarize(values)['average_return_pct']),-5)
        self.assertEqual(summarize(values)['return_observations'],2)

    def test_missing_attribution_is_unavailable(self):
        self.assertIsNone(summarize({})['average_return_pct'])
