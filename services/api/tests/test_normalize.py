"""Settled inventory provenance, full-source completeness and conflict tests."""
from copy import deepcopy
from dataclasses import asdict
import unittest

from services.research.archive import ArchiveInvalid, ArchiveStore
from services.research.inventory import Scope, page_key
from services.research.normalize import normalize_inventory, NormalizationLimit
from services.research.queue import EvidenceConflict

DAY, GENERATION = '2026-10-25', 'normalization-test'
RECENT = Scope('KXBTC15M','recent',DAY,GENERATION)
HISTORY = Scope('KXBTC15M','historical',None,GENERATION)
MARKET = dict(ticker='KXBTC15M-TEST', event_ticker='KXBTC15M-EVENT',
              close_time='2026-10-25T12:00:00Z', result='yes', yes_bid_dollars='0.8800')


class MemoryObjects:
    def __init__(self): self.data, self.gets = {}, 0
    def put_if_absent(self,key,body,content_type):
        if key in self.data: return False
        self.data[key] = body
        return True
    def get(self,key,max_bytes):
        self.gets += 1
        return self.data[key]


class NormalizeTests(unittest.TestCase):
    def setUp(self): self.archives = ArchiveStore(MemoryObjects())
    def attempt(self,scope,rows,*,jid=None,status='succeeded',cursor='',availability='available'):
        jid = scope.source if jid is None else jid
        cp = dict(scope=scope.key,sequence=0,cursor_in='',cursor_out=cursor,items=len(rows),availability=availability)
        envelope = dict(scope=asdict(scope),checkpoint=cp,response={'markets':rows,'cursor':cursor})
        receipt = self.archives.upload('kalshi',envelope)
        page = dict(page_key=page_key(scope,0),object_key=receipt['object_key'],checkpoint=cp,receipt=receipt)
        return dict(id=jid,parameters=scope.parameters(),status=status), [page]
    def run_batch(self,*attempts,**kwargs):
        return normalize_inventory(['KXBTC15M'],DAY,GENERATION,attempts,self.archives,**kwargs)

    def test_same_market_across_sources_deduplicates_and_retains_original_price_variants(self):
        first = self.attempt(RECENT,[MARKET])
        second = self.attempt(HISTORY,[{**MARKET,'yes_bid_dollars':'0.8700'}])
        batch = self.run_batch(first,second)
        self.assertTrue(batch.ready)
        self.assertEqual((len(batch.candidates),batch.rows_scanned),(1,2))
        candidate = batch.candidates[0]
        self.assertEqual(candidate.result,'yes')
        self.assertEqual(len(candidate.evidence),2)
        rows = [self.archives.read(ref.receipt())['response']['markets'][ref.row_index] for ref in candidate.evidence]
        self.assertEqual({r['yes_bid_dollars'] for r in rows},{'0.8800','0.8700'})
        self.assertEqual(batch.fingerprint,self.run_batch(second,first).fingerprint)

    def test_exact_half_open_utc_day_and_settled_yes_no_selection(self):
        def row(ticker,closed,result='yes'): return {**MARKET,'ticker':ticker,'close_time':closed,'result':result}
        rows = [row('start','2026-10-25T00:00:00Z'),row('offset','2026-10-24T17:00:00-07:00','no'),
                row('end','2026-10-26T00:00:00Z'),row('before','2026-10-24T23:59:59.999999Z'),
                row('last','2026-10-25T23:59:59.999999Z'),row('pending','2026-10-25T12:00:00Z','')]
        batch = self.run_batch(self.attempt(RECENT,rows),self.attempt(HISTORY,[]))
        self.assertEqual({c.ticker for c in batch.candidates},{'start','offset','last'})
        self.assertEqual(next(c for c in batch.candidates if c.ticker=='offset').close_time,'2026-10-25T00:00:00Z')
        self.assertEqual(batch.rows_scanned,6)

    def test_gap_states_never_return_a_partial_candidate_cohort(self):
        complete = self.attempt(RECENT,[MARKET])
        for attempt, expected in [(None,'fetch'),
                (self.attempt(HISTORY,[],cursor='next',status='running'),'resume'),
                (self.attempt(HISTORY,[],status='failed'),'failed'),
                (self.attempt(HISTORY,[],availability='unavailable'),'unavailable')]:
            before = self.archives.objects.gets
            batch = self.run_batch(complete,*([attempt] if attempt else []))
            self.assertFalse(batch.ready)
            self.assertEqual(batch.candidates,())
            self.assertIn(expected,{i.state for i in batch.inputs})
            self.assertEqual(self.archives.objects.gets,before)

    def test_complete_zero_settled_candidates_is_distinct_from_missing_inventory(self):
        batch = self.run_batch(self.attempt(RECENT,[{**MARKET,'result':''}]),self.attempt(HISTORY,[]))
        self.assertTrue(batch.ready)
        self.assertEqual(batch.candidates,())
        self.assertEqual(batch.rows_scanned,1)
        self.assertNotEqual(batch.fingerprint,self.run_batch().fingerprint)

    def test_conflicting_outcomes_identity_or_close_dates_block_entire_batch(self):
        first = self.attempt(RECENT,[MARKET])
        for patch in ({'result':'no'},{'event_ticker':'other'}, {'close_time':'2026-10-26T12:00:00Z'},
                      {'series_ticker':'KXETH15M'}):
            with self.assertRaises(EvidenceConflict):
                self.run_batch(first,self.attempt(HISTORY,[{**MARKET,**patch}]))

    def test_unsettled_then_settled_duplicate_keeps_only_confirming_evidence(self):
        batch = self.run_batch(self.attempt(RECENT,[{**MARKET,'result':''},MARKET]),self.attempt(HISTORY,[]))
        self.assertEqual(len(batch.candidates),1)
        self.assertEqual(len(batch.candidates[0].evidence),1)
        self.assertEqual(batch.candidates[0].evidence[0].row_index,1)

    def test_hash_mismatch_missing_objects_and_cross_wired_receipts_fail(self):
        first, second = self.attempt(RECENT,[MARKET]), self.attempt(HISTORY,[])
        key = first[1][0]['object_key']; body = self.archives.objects.data[key]
        self.archives.objects.data[key] = b'corrupt'
        with self.assertRaises(ArchiveInvalid): self.run_batch(first,second)
        del self.archives.objects.data[key]
        with self.assertRaises(KeyError): self.run_batch(first,second)
        self.archives.objects.data[key] = body
        wrong = deepcopy(first); wrong[1][0]['receipt'] = second[1][0]['receipt']
        with self.assertRaises(EvidenceConflict): self.run_batch(wrong,second)

    def test_valid_hash_with_wrong_envelope_or_checkpoint_cannot_impersonate_a_page(self):
        first, second = self.attempt(RECENT,[MARKET]), self.attempt(HISTORY,[])
        for patch in ({'scope':asdict(HISTORY)}, {'checkpoint':{}}):
            forged = deepcopy(first)
            envelope = dict(scope=asdict(RECENT),checkpoint=forged[1][0]['checkpoint'],response={'markets':[MARKET],'cursor':''})
            receipt = self.archives.upload('kalshi',{**envelope,**patch})
            forged[1][0].update(receipt=receipt,object_key=receipt['object_key'])
            with self.assertRaises(EvidenceConflict): self.run_batch(forged,second)
        # A receipt with a valid hash is insufficient when row count disagrees.
        forged = deepcopy(first)
        cp = {**forged[1][0]['checkpoint'],'items':2}
        forged[1][0]['checkpoint'] = cp
        receipt = self.archives.upload('kalshi',dict(scope=asdict(RECENT),checkpoint=cp,response={'markets':[MARKET],'cursor':''}))
        forged[1][0].update(receipt=receipt,object_key=receipt['object_key'])
        with self.assertRaises(EvidenceConflict): self.run_batch(forged,second)

    def test_ambiguous_completed_attempts_require_explicit_membership_and_other_generations_do_not_mix(self):
        first, second = self.attempt(RECENT,[MARKET]), self.attempt(HISTORY,[])
        with self.assertRaises(EvidenceConflict):
            self.run_batch(first,second,self.attempt(RECENT,[MARKET],jid='new-complete-job'))
        other = Scope('KXBTC15M','recent',DAY,'different-generation')
        self.assertFalse(self.run_batch(self.attempt(other,[MARKET]),second).ready)
        self.assertEqual(self.run_batch(first,second).fingerprint,self.run_batch(first,first,second).fingerprint)

    def test_limits_fail_without_truncating_or_returning_a_usable_subset(self):
        first, second = self.attempt(RECENT,[MARKET]),self.attempt(HISTORY,[MARKET])
        with self.assertRaises(NormalizationLimit): self.run_batch(first,second,max_rows=1)
        with self.assertRaises(NormalizationLimit): self.run_batch(first,second,max_pages=1)
        for limit in (0,True,1000001):
            with self.assertRaises(ValueError): self.run_batch(first,second,max_rows=limit)
        with self.assertRaises(ValueError): normalize_inventory([],DAY,GENERATION,[],self.archives)

    def test_multiple_series_sort_deterministically_and_never_deduplicate_different_tickers(self):
        series = ['KXETH15M','KXBTC15M']
        attempts = []
        for ticker in series:
            for source in ('recent','historical'):
                scope = Scope(ticker,source,DAY if source=='recent' else None,GENERATION)
                attempts.append(self.attempt(scope,[{**MARKET,'ticker':ticker+'-TEST','event_ticker':ticker+'-EVENT'}],jid=ticker+source))
        batch = normalize_inventory(series,DAY,GENERATION,reversed(attempts),self.archives)
        self.assertEqual([c.ticker for c in batch.candidates],['KXBTC15M-TEST','KXETH15M-TEST'])
        self.assertEqual(batch.fingerprint,normalize_inventory(list(reversed(series)),DAY,GENERATION,attempts,self.archives).fingerprint)

    def test_multi_page_evidence_and_fractional_duplicate_times_are_preserved(self):
        first = self.attempt(RECENT,[MARKET],cursor='two')
        job, pages = first
        cp = dict(scope=RECENT.key,sequence=1,cursor_in='two',cursor_out='',items=1,availability='available')
        receipt = self.archives.upload('kalshi',dict(scope=asdict(RECENT),checkpoint=cp,
            response={'markets':[{**MARKET,'close_time':'2026-10-25T05:00:00-07:00'}],'cursor':''}))
        pages.append(dict(page_key=page_key(RECENT,1),object_key=receipt['object_key'],checkpoint=cp,receipt=receipt))
        batch = self.run_batch(first,self.attempt(HISTORY,[]))
        self.assertTrue(batch.ready)
        self.assertEqual(len(batch.candidates[0].evidence),2)
        self.assertEqual({e.page_key for e in batch.candidates[0].evidence},{page_key(RECENT,0),page_key(RECENT,1)})
        missing = deepcopy(first); missing[1].pop(0)
        with self.assertRaises(EvidenceConflict): self.run_batch(missing,self.attempt(HISTORY,[]))
