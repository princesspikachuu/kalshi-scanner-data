"""Exercise the real GET allowlist and recover cursors after bounded reads fail."""
import json,unittest
from unittest.mock import Mock,patch
import httpx
from services.demo.exchange import ExchangeFailure
from services.paper_demo.exchange import ProductionData
from services.paper_demo.shadow.market_maker import maker_event_page

class MakerReadTransportTests(unittest.TestCase):
    def test_category_catalog_is_get_only_and_does_not_bypass_response_limit(self):
        seen=[]
        def respond(request):
            seen.append(request)
            return httpx.Response(200,json=dict(series=[]))
        data=ProductionData(client=httpx.Client(transport=httpx.MockTransport(respond)))
        with patch('services.paper_demo.exchange.PRODUCTION_READS.wait'):
            self.assertEqual(data.call('GET','/series',dict(category='Politics',include_volume='true')),dict(series=[]))
            for method in ('POST','PATCH','PUT','DELETE'):
                with self.assertRaises(ExchangeFailure):data.call(method,'/series')
            for path in ('/series/../portfolio/orders','/portfolio/orders'):
                with self.assertRaises(ExchangeFailure):data.call('GET',path)
        self.assertEqual(len(seen),1);self.assertEqual(seen[0].url.params['category'],'Politics');data.close()
        large=ProductionData(client=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=b' '* (4*1024*1024+1)))))
        with patch('services.paper_demo.exchange.PRODUCTION_READS.wait'):
            with self.assertRaises(ExchangeFailure) as caught:large.call('GET','/series')
        self.assertEqual(caught.exception.code,'paper_data_capacity');large.close()

class MakerCapacityTests(unittest.IsolatedAsyncioTestCase):
    def state(self,**kw):return dict(cursor='unchanged',reads=0,pages=1,series_at=9999,**kw)
    async def test_oversize_page_shrinks_without_advancing_or_repeating_same_size(self):
        h=Mock();s=self.state()
        def call(method,path,params):
            self.assertEqual(params['cursor'],'unchanged')
            if params['limit']>25:raise ExchangeFailure('paper_data_capacity')
            return dict(events=[],cursor='next')
        h.verified_data.call.side_effect=call
        self.assertEqual(await maker_event_page(h,s,200,86400),dict(events=[],milestones=[]))
        self.assertEqual(s['cursor'],'unchanged');self.assertEqual(s['pages'],1)
        await maker_event_page(h,s,230,86400)
        self.assertEqual(s['cursor'],'next');self.assertEqual(s['reads'],2)
        self.assertEqual([c.args[2]['limit'] for c in h.verified_data.call.call_args_list],[50,25])
    async def test_single_large_event_splits_market_pages_and_survives_restart(self):
        h=Mock();s=self.state(event_page_limit=1)
        def call(method,path,params):
            if path=='/events':
                if params['with_nested_markets']=='true':raise ExchangeFailure('paper_data_capacity')
                return dict(events=[dict(event_ticker='POL',series_ticker='ELECTION',category='Politics',title='Election')],cursor='next-event',milestones=[])
            self.assertEqual(path,'/markets');self.assertEqual(params['event_ticker'],'POL')
            return dict(markets=[dict(ticker='FIRST' if not params['cursor'] else 'SECOND')],cursor='next-market' if not params['cursor'] else '')
        h.verified_data.call.side_effect=call
        first=await maker_event_page(h,s,200,86400)
        self.assertEqual(first['events'][0]['markets'][0]['ticker'],'FIRST')
        self.assertEqual(s['cursor'],'unchanged');self.assertEqual(s['pages'],1)
        rebuilt=json.loads(json.dumps(s))
        last=await maker_event_page(h,rebuilt,230,86400)
        self.assertEqual(last['events'][0]['markets'][0]['ticker'],'SECOND')
        self.assertEqual(rebuilt['cursor'],'next-event');self.assertEqual(rebuilt['pages'],2)
        self.assertNotIn('split_event',rebuilt)
        self.assertEqual(sum(c.args[1]=='/events' for c in h.verified_data.call.call_args_list),2)
    async def test_split_market_pages_keep_the_series_cursor_independent(self):
        h=Mock();s=self.state()
        s.update(series_pool=['POL'],series_cursors={'POL':'old-series'},split_event=dict(event=dict(event_ticker='POL'),milestones=[],selected='POL',cursor='old-market',next_cursor='new-series',limit=50))
        h.verified_data.call.side_effect=ExchangeFailure('paper_data_capacity')
        await maker_event_page(h,s,200,86400)
        self.assertEqual(s['split_event']['limit'],25);self.assertEqual(s['split_event']['cursor'],'old-market')
        self.assertEqual(s['series_cursors']['POL'],'old-series')
        h.verified_data.call.side_effect=lambda *a:dict(markets=[],cursor='')
        await maker_event_page(h,s,230,86400)
        self.assertEqual(s['series_cursors']['POL'],'new-series');self.assertEqual(s['cursor'],'unchanged')
    async def test_unrelated_error_never_changes_cursor_or_page_size(self):
        h=Mock();h.verified_data.call.side_effect=ExchangeFailure('paper_data_rate_limited');s=self.state()
        with self.assertRaises(ExchangeFailure):await maker_event_page(h,s,200,86400)
        self.assertEqual(s['cursor'],'unchanged');self.assertEqual(s['pages'],1)
        self.assertNotIn('event_page_limit',s)
    async def test_catalog_failure_is_isolated_and_requests_are_bounded_per_hour(self):
        h=Mock();queries=[]
        def call(method,path,params):
            if path=='/series':
                queries.append(params['category'])
                if params['category']=='Sports':raise ExchangeFailure('paper_data_capacity')
                return dict(series=[dict(ticker='FED',category='Economics',title='Federal Reserve',volume_fp='100')])
            return dict(events=[],cursor='')
        h.verified_data.call.side_effect=call;s=dict(cursor='',reads=0,pages=1)
        for i in range(12):await maker_event_page(h,s,200+i*30,86400)
        self.assertEqual(len(queries),7);self.assertEqual(len(set(queries)),6)
        tagged=[c.args[2] for c in h.verified_data.call.call_args_list if c.args[1]=='/series' and c.args[2].get('tags')]
        self.assertEqual(tagged,[dict(category='Sports',tags='Football',include_volume='true')])
        self.assertIn('FED',s['series_pool']);self.assertLessEqual(len(s['series_pool']),48)
        self.assertEqual(s['reads'],19)
