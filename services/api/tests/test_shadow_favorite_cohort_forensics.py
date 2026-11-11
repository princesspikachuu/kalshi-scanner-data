"""Audit-only cohort checks cannot invent completion or financial outcomes."""
import json
import unittest
from copy import deepcopy
from uuid import uuid4

from services.demo.shadow_favorite_cohort_forensics import (
    inspect_original_cohort,inspect_cohort_page,
)
from services.demo.shadow_history_reconcile import HistoryReconciliationError


def cohort():
    identifier=str(uuid4())
    oid=str(uuid4())
    detail=dict(key='entry-v2|KXFAV|yes|80|<3m|market_close',
                at=1794437000.12,price='0.80',quantity='2',
                remaining='2',cost='1.62',remaining_cost='1.62',
                verified=True,order_id=oid)
    return dict(id=identifier,key='demo/shadow/event/'+identifier,
                parameters={},
                progress=dict(event='FAVORITE_ENTRY_COHORT',
                              order_id=oid,quantity='2',price='0.80',
                              fee='0.02',time='1794437000.123456',
                              details=json.dumps(detail)))


class FavoriteCohortForensicsTests(unittest.TestCase):
    def test_exact_fill_validated_without_inferring_outcome(self):
        result=inspect_original_cohort(cohort())
        self.assertTrue(result['source_fill_consistent'])
        self.assertFalse(result['authoritative_settlement_verified'])
        self.assertFalse(result['eligible_for_learning'])
        self.assertFalse(result['realized_pnl_reconciled'])
        self.assertEqual(result['entry_cost_with_fee'],'1.62')
        self.assertEqual(result['quantity'],'2')

    def test_tampered_price_fee_quantity_and_order_fail(self):
        for field,value in (('quantity','4'),('price','0.9'),('fee','0.04'),
                            ('order_id','wrong')):
            e=cohort()
            e['progress'][field]=value
            with self.subTest(field=field):
                with self.assertRaises(HistoryReconciliationError):
                    inspect_original_cohort(e)

    def test_nonfinite_or_negative_cohort_fields_refused(self):
        for field,value in (('quantity','NaN'),('cost','Infinity'),
                            ('price','-0.20'),('remaining','3'),
                            ('remaining_cost','99')):
            e=cohort()
            detail=json.loads(e['progress']['details'])
            detail[field]=value
            e['progress']['details']=json.dumps(detail)
            with self.subTest(field=field):
                with self.assertRaises(HistoryReconciliationError):
                    inspect_original_cohort(e)

    def test_invalid_json_or_untrusted_key_fails_closed(self):
        for details in ('{','[]','{"verified":true}',json.dumps(dict(
                key='not-a-real-entry')), 'x'*9000):
            e=cohort()
            e['progress']['details']=details
            with self.subTest(details=details[:20]):
                with self.assertRaises(HistoryReconciliationError):
                    inspect_original_cohort(e)

    def test_unverified_entry_is_visible_but_not_trainable(self):
        e=cohort()
        detail=json.loads(e['progress']['details'])
        detail['verified']=False
        e['progress']['details']=json.dumps(detail)
        result=inspect_original_cohort(e)
        self.assertFalse(result['entry_fresh'])
        self.assertFalse(result['eligible_for_learning'])

    def test_duplicates_and_missing_source_records_are_not_assumed(self):
        c=cohort()
        result=inspect_cohort_page([c])
        self.assertEqual(result['inspected_count'],1)
        self.assertFalse(result['source_exhaustion_verified'])
        with self.assertRaises(HistoryReconciliationError):
            inspect_cohort_page([c,deepcopy(c)])

    def test_other_audit_events_not_considered_fills(self):
        c=cohort()
        c['progress']['event']='SETTLED'
        result=inspect_cohort_page([c])
        self.assertEqual(result['inspected_count'],0)


if __name__=='__main__':
    unittest.main()
