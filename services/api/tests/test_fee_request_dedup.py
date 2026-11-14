"""Concurrent fee refreshes reuse identical series/event reads without weakening freshness."""
import threading,time,unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock,patch
from services.paper_demo.exchange import Fees

class FeeRequestDedup(unittest.TestCase):
    def test_cold_concurrent_markets_fetch_series_once_but_verify_every_event(self):
        calls=[];lock=threading.Lock();start=threading.Barrier(4)
        def call(method,path,params=None):
            with lock:calls.append((path,params))
            if path=='/series/S':
                time.sleep(.01)
                return dict(series=dict(fee_type='quadratic',fee_multiplier=1))
            return {'series_fee_change_arr':[]} if path=='/series/fee_changes' else {'event_fee_changes':[]}
        fees=Fees(Mock(call=call));now=time.time()
        def load(i):
            start.wait();fees.load('S-'+str(i),dict(event_ticker='EVENT-'+str(i)),now)
        with ThreadPoolExecutor(max_workers=4) as executor:list(executor.map(load,range(4)))
        self.assertEqual(sum(p=='/series/S' for p,_ in calls),1)
        self.assertEqual(sum(p=='/series/fee_changes' for p,_ in calls),1)
        self.assertEqual(sum(p=='/events/fee_changes' for p,_ in calls),4)
        for i in range(4):self.assertEqual(fees.schedule('S-'+str(i),now),('quadratic',1))
        fees.load('S-new',dict(event_ticker='NEW'),now+31)
        self.assertEqual(sum(p=='/series/S' for p,_ in calls),2)

    def test_same_event_markets_share_one_verified_event_fee_read(self):
        calls=[];lock=threading.Lock();start=threading.Barrier(4)
        def call(method,path,params=None):
            with lock:calls.append((path,params))
            if path=='/series/S':
                return dict(series=dict(fee_type='quadratic',fee_multiplier=1))
            if path=='/series/fee_changes':
                return {'series_fee_change_arr':[]}
            if path=='/events/fee_changes':
                time.sleep(.01)
                return {'event_fee_changes':[]}
            raise AssertionError(path)
        fees=Fees(Mock(call=call));now=time.time()
        def load(i):
            start.wait();fees.load('S-'+str(i),dict(event_ticker='SHARED'),now)
        with ThreadPoolExecutor(max_workers=4) as executor:list(executor.map(load,range(4)))
        self.assertEqual(sum(p=='/events/fee_changes' for p,_ in calls),1)
        self.assertEqual(sum(p=='/series/S' for p,_ in calls),1)
        for i in range(4):self.assertEqual(fees.schedule('S-'+str(i),now),('quadratic',1))
        fees.load('S-next',dict(event_ticker='SHARED'),now+31)
        self.assertEqual(sum(p=='/events/fee_changes' for p,_ in calls),2)

    def test_failed_event_refresh_does_not_publish_shared_event_cache(self):
        calls=[]
        def call(method,path,params=None):
            calls.append(path)
            if path=='/series/S':return dict(series=dict(fee_type='quadratic',fee_multiplier=1))
            if path=='/series/fee_changes':return {'series_fee_change_arr':[]}
            raise RuntimeError('unavailable')
        fees=Fees(Mock(call=call))
        with self.assertRaises(RuntimeError):
            fees.load('S-one',dict(event_ticker='E'),time.time())
        self.assertNotIn('E',fees.events)
        self.assertNotIn('S-one',fees.cache)

    def test_failed_series_refresh_does_not_publish_an_unverified_cache(self):
        data=Mock();data.call.side_effect=[dict(series=dict(fee_type='quadratic',fee_multiplier=1)),RuntimeError('unavailable')]
        fees=Fees(data)
        with self.assertRaises(RuntimeError):fees.load('S-one',dict(event_ticker='E'),time.time())
        self.assertNotIn('S',fees.series);self.assertNotIn('S-one',fees.cache)
