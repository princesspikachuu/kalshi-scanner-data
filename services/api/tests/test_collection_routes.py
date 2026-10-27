from datetime import datetime,timezone
import unittest
from uuid import uuid4
from fastapi.testclient import TestClient
from services.api.app import create_app,SESSION,CSRF,digest
from services.api.config import Settings
from test_routes import MemoryStore

ID=str(uuid4());NOW=datetime(2026,10,27,tzinfo=timezone.utc)


class FakeCampaigns:
    def __init__(self):self.calls=[]
    def get(self,identifier):
        if str(identifier)!=ID:return None
        return dict(id=ID,asset='btc',mode='backfill',start_at=NOW,end_at=NOW,created_at=NOW,status='queued',error_code=None,result_id=None,total_sections=60,completed_sections=0)
    def create(self,*args,**kwargs):self.calls.append(('create',args));return ID
    def control(self,*args):self.calls.append(('control',args));return str(args[0])==ID
    def days(self,identifier,after=None,limit=51):
        self.calls.append(('days',after))
        return [dict(day='2026-10-25',start_at=NOW,end_at=NOW,dataset_id=None,stage='pending')]*limit if after is None else []
    def refresh(self,asset):return dict(asset=asset,enabled=False,next_due=None,interval_seconds=3600,latest_campaign_id=None)
    def set_refresh(self,asset,enabled):self.calls.append(('refresh',enabled));return {**self.refresh(asset),'enabled':enabled}


class CollectionRoutes(unittest.TestCase):
    def setUp(self):
        self.store=FakeCampaigns();self.auth=MemoryStore();self.token='t'*43;self.csrf='c'*43
        self.auth.sessions[digest(self.token)]={'csrf_hash':digest(self.csrf),'display_email':'owner@example.test'}
        settings=Settings('https://app.test','client','postgresql://unused','x'*32,owner_subject='owner')
        self.client=TestClient(create_app(settings,self.auth,campaign_store=self.store),base_url='https://app.test',headers={'x-pocket-proxy':'x'*32,'origin':'https://app.test','x-csrf-token':self.csrf})
        self.client.cookies.set(SESSION,self.token);self.client.cookies.set(CSRF,self.csrf)
    def tearDown(self):self.client.close()
    def body(self):return dict(asset='btc',start_date='2026-01-01',end_date='2026-10-26',request_key=str(uuid4()))

    def test_create_controls_and_refresh_require_session_proxy_origin_and_csrf(self):
        for headers,status in (({'x-pocket-proxy':'bad'},403),({'origin':'https://evil.test'},403),({'x-csrf-token':'bad'},403)):
            self.assertEqual(self.client.post('/collection/campaigns',json=self.body(),headers=headers).status_code,status)
        self.client.cookies.clear()
        self.assertEqual(self.client.post('/collection/campaigns',json=self.body()).status_code,401)
        self.assertEqual(self.client.get('/collection/refresh/btc').status_code,401)
        self.assertFalse(self.store.calls)

    def test_create_pause_resume_and_explicit_refresh_toggle(self):
        self.assertEqual(self.client.post('/collection/campaigns',json=self.body()).status_code,200)
        for action in ('pause','resume'):
            self.assertEqual(self.client.post(f'/collection/campaigns/{ID}/{action}',json={}).status_code,200)
        self.assertFalse(self.client.get('/collection/refresh/btc').json()['refresh']['enabled'])
        r=self.client.post('/collection/refresh/btc',json={'enabled':True})
        self.assertEqual(r.status_code,200);self.assertTrue(r.json()['refresh']['enabled'])
        self.assertEqual(r.headers['cache-control'],'no-store');self.assertNotIn('email',r.text)

    def test_invalid_body_unknown_asset_or_query_cannot_mutate(self):
        for body in ({**self.body(),'private-sentinel':'secret'},{**self.body(),'asset':'financial_daily'},{**self.body(),'request_key':'private-sentinel'}):
            r=self.client.post('/collection/campaigns',json=body);self.assertEqual(r.status_code,422);self.assertNotIn('private-sentinel',r.text)
        self.assertEqual(self.client.post('/collection/refresh/btc',json={'enabled':'yes'}).status_code,422)
        self.assertEqual(self.client.post('/collection/campaigns?other=1',json=self.body()).status_code,422)
        self.assertFalse(self.store.calls)

    def test_progress_pagination_unknown_ids_and_gets_are_read_only(self):
        r=self.client.get(f'/collection/campaigns/{ID}');self.assertEqual(r.status_code,200)
        self.assertEqual(len(r.json()['sections']),50);self.assertEqual(r.json()['next_after'],'2026-10-25')
        self.assertEqual(self.client.get(f'/collection/campaigns/{ID}?after=2026-10-25').json()['sections'],[])
        for query in ('after=bad','after=2026-10-25&after=2026-10-26','other=1'):
            self.assertEqual(self.client.get(f'/collection/campaigns/{ID}?'+query).status_code,422)
        self.assertEqual(self.client.get('/collection/campaigns/'+str(uuid4())).status_code,404)
        self.assertTrue(all(call[0]=='days' for call in self.store.calls))
