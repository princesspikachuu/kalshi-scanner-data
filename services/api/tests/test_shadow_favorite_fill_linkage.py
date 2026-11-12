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
    from decimal import Decimal
    cost=str(Decimal(qty)*Decimal(price)+Decimal(fee))
    detail=dict(key='entry-v2|KXFAV|yes|80|<3m|market_close',
                at=float(time),price=price,quantity=qty,remaining=qty,
                cost=cost,remaining_cost=cost,verified=True,order_id=order)
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
                            ('ticker',''),('action','wrong'),
                            ('order_id',[]),('order_id',{})):
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


from services.api.tests import test_demo_postgres as fixture

@unittest.skipUnless(fixture.URL,'Disposable PostgreSQL is required')
class RealPostgresFavoriteFillLinkageTests(unittest.TestCase):
    setUp=fixture.DemoPostgres.setUp
    tearDown=fixture.DemoPostgres.tearDown

    @classmethod
    def setUpClass(cls):
        fixture.DemoPostgres.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        fixture.DemoPostgres.tearDownClass.__func__(cls)

    def test_original_raw_fill_and_packed_cohort_link_after_api_readback(self):
        from services.paper_demo.shadow.storage import UPSERT,entry
        from services.paper_demo.shadow.diagnostic_batches import compact_diagnostic_rows
        from services.demo.shadow_history_pages import RAW_PREFIX
        cohort,fill=events()
        fill_id=self.demo.put('shadow/event/'+str(uuid4()),fill['progress'])
        packed_original=entry(RAW_PREFIX+str(uuid4()),{},
                              cohort['progress'])
        packed=compact_diagnostic_rows([packed_original],entry)
        self.assertEqual(len(packed),1)
        with self.store.pool.connection() as connection:
            connection.execute(UPSERT,packed[0])
        # Authentication and other disposable test infrastructure may
        # record additional hot audit rows. Verify the inserted originals by
        # UUID after draining bounded keyset pages, not by assuming that a
        # database page has exactly one row.
        def drain(source):
            cursor=None;items=[];seen_keys=set()
            for _ in range(16):
                params={'cursor':cursor} if cursor is not None else None
                response=self.client.get('/demo/shadow/history/'+source,
                                         params=params)
                self.assertEqual(response.status_code,200,response.text)
                body=response.json()
                self.assertEqual(body['request_cursor'],cursor)
                self.assertTrue(set(body['source_keys']).isdisjoint(seen_keys))
                seen_keys.update(body['source_keys'])
                items.extend(body['items'])
                if not body['more']:
                    return items,seen_keys
                self.assertIsInstance(body['next_cursor'],str)
                cursor=body['next_cursor']
            self.fail('Disposable source pagination did not terminate')
        raw_items,raw_keys=drain('raw')
        packed_items,packed_keys=drain('packed')
        self.assertTrue(all(k.startswith(RAW_PREFIX) for k in raw_keys))
        self.assertTrue(all(k.startswith('demo/shadow/event-batch/')
                            for k in packed_keys))
        raw_matches=[e for e in raw_items if e['id']==fill_id]
        packed_matches=[e for e in packed_items
                        if e['id']==str(packed_original[0])]
        self.assertEqual(len(raw_matches),1)
        self.assertEqual(len(packed_matches),1)
        self.assertEqual(packed_matches[0]['progress']['event'],
                         'FAVORITE_ENTRY_COHORT')
        result=inspect_supplied_favorite_fill_links([
            page(*raw_items,source='hot_raw'),
            page(*packed_items,source='hot_packed')])
        self.assertEqual(result['unambiguous_fill_links'],1)
        self.assertEqual(result['matched_originals'][0]['fill_original_id'],
                         fill_id)
        self.assertEqual(result['matched_originals'][0]['cohort_original_id'],
                         str(packed_original[0]))
        self.assertFalse(result['safe_to_train'])


if __name__=='__main__':
    unittest.main()
