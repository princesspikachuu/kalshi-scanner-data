"""Verified original entry/fill linkage is not settled Favorites P/L."""
import json
import unittest
from copy import deepcopy
from uuid import uuid4

from services.demo.shadow_history_reconcile import HistoryReconciliationError
from services.demo.shadow_favorite_fill_linkage import inspect_supplied_favorite_fill_links


def original(progress):
    ident=str(uuid4())
    return dict(id=ident,key='demo/shadow/event/'+ident,
                parameters={},progress=progress)


def events(order=None, *, qty='2',price='0.80',fee='0.02',
           time='1794437000.123456',ticker='KXFAV'):
    order=order or str(uuid4())
    detail=dict(key='entry-v2|KXFAV|yes|80|<3m|market_close',
                at=float(time),price=price,quantity=qty,remaining=qty,
                cost=str(int(qty)*0.8+0.02) if qty=='2' and price=='0.80'
                and fee=='0.02' else str(__import__('decimal').Decimal(qty)*
                  __import__('decimal').Decimal(price)+__import__('decimal').Decimal(fee)),
                remaining_cost='1.62' if qty=='2' and price=='0.80'
                and fee=='0.02' else str(__import__('decimal').Decimal(qty)*
                  __import__('decimal').Decimal(price)+__import__('decimal').Decimal(fee)),
                verified=True,order_id=order)
    cohort=original(dict(event='FAVORITE_ENTRY_COHORT',ticker=ticker,
                         order_id=order,side='yes',action='buy',
                         quantity=qty,price=price,fee=fee,time=time,
                         details=json.dumps(detail)))
    fill=original(dict(event='FILL',ticker=ticker,order_id=order,
                       side='yes',action='buy',quantity=qty,
                       price=price,fee=fee,time=time,
                       reason='DEPTH_SWEEP'))
    return cohort,fill


def page(*items,source='hot_raw',verified=False):
    return dict(source=source,verified=verified,items=list(items))


class FavoriteOriginalFillLinkageTests(unittest.TestCase):
    def test_exact_audited_fill_links_without_pnl_or_learning(self):
        cohort,fill=events()
        result=inspect_supplied_favorite_fill_links([page(cohort,fill)])
        self.assertEqual(result['supplied_cohorts'],1)
        self.assertEqual(result['unambiguous_fill_links'],1)
        self.assertEqual(result['matched_originals'][0]['cohort_original_id'],
                         cohort['id'])
        self.assertEqual(result['matched_originals'][0]['fill_original_id'],
                         fill['id'])
        self.assertEqual(result['matched_originals'][0]['entry_fee'],'0.02')
        for flag in ('authoritative_settlement_verified','realized_pnl_reconciled',
                     'all_time_coverage_complete','safe_to_train',
                     'eligible_for_learning'):
            self.assertFalse(result[flag])
        self.assertEqual(result['authoritative_outcome_samples'],0)

    def test_same_original_repeated_from_verified_r2_is_not_second_fill(self):
        cohort,fill=events()
        result=inspect_supplied_favorite_fill_links([
            page(cohort,fill),
            page(deepcopy(fill),source='r2_reclaimed_raw',verified=True)])
        self.assertEqual(result['unique_original_events'],2)
        self.assertEqual(result['duplicate_source_copies'],1)
        self.assertEqual(result['unambiguous_fill_links'],1)

    def test_multiple_partial_fills_of_one_order_match_distinct_cohorts(self):
        order=str(uuid4())
        a,fa=events(order,qty='2',time='1794437000.123456')
        b,fb=events(order,qty='1',time='1794437000.223456')
        result=inspect_supplied_favorite_fill_links([page(a,b,fa,fb)])
        self.assertEqual(result['supplied_cohorts'],2)
        self.assertEqual(result['unambiguous_fill_links'],2)
        self.assertEqual(result['ambiguous_cohorts_in_supplied_pages'],0)

    def test_partial_source_missing_fill_is_unmatched_not_failed_trade(self):
        cohort,_=events()
        result=inspect_supplied_favorite_fill_links([page(cohort)])
        self.assertEqual(result['unmatched_cohorts_in_supplied_pages'],1)
        self.assertEqual(result['unambiguous_fill_links'],0)
        self.assertFalse(result['authoritative_settlement_verified'])

    def test_same_order_but_wrong_ticker_fee_price_side_quantity_time(self):
        cohort,fill=events()
        variants=(
            dict(ticker='OTHER'),dict(fee='0.03'),dict(price='0.81'),
            dict(side='no'),dict(quantity='3'),dict(time='1794437100.123456'),
            dict(action='sell'),
        )
        for changed in variants:
            mismatch=deepcopy(fill)
            mismatch['progress'].update(changed)
            with self.subTest(changed=changed):
                result=inspect_supplied_favorite_fill_links([page(cohort,mismatch)])
                self.assertEqual(result['unmatched_cohorts_in_supplied_pages'],1)
                self.assertEqual(result['unambiguous_fill_links'],0)

    def test_ambiguous_duplicate_fill_or_two_cohorts_never_double_count(self):
        cohort,fill=events()
        second=deepcopy(fill)
        second['id']=str(uuid4())
        second['key']='demo/shadow/event/'+second['id']
        r=inspect_supplied_favorite_fill_links([page(cohort,fill,second)])
        self.assertEqual(r['ambiguous_cohorts_in_supplied_pages'],1)
        self.assertEqual(r['unambiguous_fill_links'],0)
        second=deepcopy(cohort)
        second['id']=str(uuid4())
        second['key']='demo/shadow/event/'+second['id']
        r=inspect_supplied_favorite_fill_links([page(cohort,second,fill)])
        self.assertEqual(r['ambiguous_cohorts_in_supplied_pages'],2)
        self.assertEqual(r['unambiguous_fill_links'],0)

    def test_relevant_malformed_fill_fails_closed(self):
        cohort,fill=events()
        for field,value in (('quantity','NaN'),('price','Infinity'),
                            ('fee','-0.01'),('time','x'),('side','maybe'),
                            ('ticker',''),('action','wrong')):
            bad=deepcopy(fill)
            bad['progress'][field]=value
            with self.subTest(field=field):
                with self.assertRaises(HistoryReconciliationError):
                    inspect_supplied_favorite_fill_links([page(cohort,bad)])

    def test_invalid_cohort_is_not_promoted(self):
        cohort,fill=events()
        bad=deepcopy(cohort)
        bad['progress']['details']='{}'
        with self.assertRaises(HistoryReconciliationError):
            inspect_supplied_favorite_fill_links([page(bad,fill)])

    def test_conflicting_original_across_hot_and_r2_fails(self):
        cohort,fill=events()
        bad=deepcopy(fill)
        bad['progress']['fee']='0.99'
        with self.assertRaises(HistoryReconciliationError):
            inspect_supplied_favorite_fill_links([
                page(cohort,fill),page(bad,source='r2_reclaimed_raw',verified=True)])

    def test_unverified_cold_and_unbounded_pages_fail(self):
        cohort,fill=events()
        with self.assertRaises(HistoryReconciliationError):
            inspect_supplied_favorite_fill_links([
                page(cohort),page(fill,source='r2_reclaimed_raw')])
        many=[original(dict(event='OTHER',time='1794437000')) for _ in range(257)]
        with self.assertRaises(HistoryReconciliationError):
            inspect_supplied_favorite_fill_links([page(*many)])


if __name__=='__main__':
    unittest.main()
