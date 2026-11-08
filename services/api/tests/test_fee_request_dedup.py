"""Concurrent fee refreshes share series reads without caching event overrides."""
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

    def test_failed_series_refresh_does_not_publish_an_unverified_cache(self):
        data=Mock();data.call.side_effect=[dict(series=dict(fee_type='quadratic',fee_multiplier=1)),RuntimeError('unavailable')]
        fees=Fees(data)
        with self.assertRaises(RuntimeError):fees.load('S-one',dict(event_ticker='E'),time.time())
        self.assertNotIn('S',fees.series);self.assertNotIn('S-one',fees.cache)
