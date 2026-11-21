import unittest
from contextlib import contextmanager
from decimal import Decimal
from services.api.demo_pairs import completed_pairs

class PairResults(unittest.TestCase):
    def test_weighted_sell_prices_fees_and_cursor_keep_exact_parent_records(self):
        rows=[dict(id=str(i),parameters=dict(price=3,client_id=str(i)),progress=dict(fees=1,closed_at=100),finished_at=100,
            contracts=Decimal('10'),proceeds=Decimal('78'),fees=Decimal('2'),sell_count=2) for i in range(51)]
        class Connection:
            def execute(self,sql,args):self.args=args;return self
            def fetchall(self):return rows
        connection=Connection()
        class Pool:
            @contextmanager
            def connection(self):yield connection
        page=completed_pairs(Pool(),before='cursor',bot='bot',ticker='market')
        self.assertEqual(tuple(connection.args),('cursor','cursor','bot','bot','market','market'))
        self.assertEqual(len(page['items']),50);self.assertEqual(page['next_before'],'49')
        pair=page['items'][0]
        self.assertEqual(pair['sell_price'],7.8);self.assertEqual(pair['estimated_net_cents'],45)
        self.assertEqual(pair['fees'],3);self.assertEqual(pair['sell_count'],2)
