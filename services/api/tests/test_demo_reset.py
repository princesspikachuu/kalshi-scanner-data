import copy,unittest,time
from unittest.mock import patch
from services.demo.reset import ResetController,ResetRequest,reset_payload
from services.demo.engine import wire_order
from services.demo.exchange import ExchangeFailure

class Store:
    def __init__(self):self.saved=[];self.events=[]
    def put(self,key,data):self.saved.append((key,copy.deepcopy(data)))
    def event(self,*args,**kw):self.events.append((args,kw))
class Exchange:
    def __init__(self):self.orders=[];self.positions=[];self.calls=[];self.submitted=[];self.remote=None;self.fail=None;self.balance=10000
    def pages(self,path,key,**params):
        self.calls.append((path,params))
        return iter(self.orders if path.endswith('/orders') else self.positions)
    def cancel(self,identifier,ticker):self.calls.append(('cancel',identifier,ticker));self.orders=[]
    def call(self,method,path,**kw):
        self.calls.append((method,path,kw))
        if path.endswith('/balance'):return dict(balance=self.balance,portfolio_value=0)
        if path.startswith('/markets/'):return {'market':{'status':'active'}}
        if method=='POST':
            self.submitted.append(kw['body'])
            if self.fail:raise self.fail
            return dict(order_id='sale')
        return {'order':self.remote}
def row():return dict(parameters=dict(request_id='00000000-0000-0000-0000-000000000001',sources=[],fresh_bots=True,target_balance_cents=100000),progress=dict(state='requested',pending=None,attempt=0,cloned=False))
class Reset(unittest.TestCase):
    def test_payload_is_reduce_only_immediate_and_normal_bots_remain_maker_only(self):
        for position,side,price in [(3,'ask','0.0100'),(-3,'bid','0.9900')]:
            body=reset_payload('T',position,'client')
            self.assertEqual((body['side'],body['price']),(side,price))
            self.assertTrue(body['reduce_only']);self.assertFalse(body['post_only'])
            self.assertEqual(body['time_in_force'],'immediate_or_cancel');self.assertNotIn('expiration_time',body)
            self.assertEqual(body['subaccount'],0)
        normal=wire_order(dict(kind='exit',side='yes',ticker='T',client_id='x',price=55,quantity=3,close=time.time()+100))
        self.assertTrue(normal['post_only']);self.assertNotIn('reduce_only',normal)
        self.assertRaises(ValueError,reset_payload,'T',0,'x')
        self.assertRaises(ValueError,reset_payload,'T','NaN','x')
    def test_all_resting_orders_canceled_before_any_sale(self):
        store=Store();ex=Exchange();ex.orders=[dict(order_id='manual',ticker='T')];ex.positions=[dict(ticker='T',position_fp='3.00')]
        c=ResetController(store,ex);r=row();c.step(r)
        self.assertEqual(r['progress']['state'],'canceling');self.assertFalse(ex.submitted)
        c.next_check=0;c.step(r)
        self.assertEqual(len(ex.submitted),1);self.assertEqual(r['progress']['pending']['exchange_id'],'sale')
        pending_saves=[d for k,d in store.saved if k=='reset' and d.get('pending')]
        self.assertNotIn('exchange_id',pending_saves[0]['pending'])
    def test_ambiguous_sale_is_never_reposted_when_history_is_missing(self):
        store=Store();ex=Exchange();ex.positions=[dict(ticker='T',position_fp='3.00')];ex.fail=ExchangeFailure('connection',True)
        c=ResetController(store,ex);r=row()
        with self.assertRaises(ExchangeFailure):c.step(r)
        self.assertIsNotNone(r['progress']['pending'])
        c.next_check=0;c.step(r)
        self.assertEqual(len(ex.submitted),1);self.assertEqual(r['progress']['state'],'attention')
    def test_confirmed_partial_sale_rechecks_real_remaining_position(self):
        store=Store();ex=Exchange();ex.positions=[dict(ticker='T',position_fp='3.00')]
        c=ResetController(store,ex);r=row();c.step(r)
        ex.remote=dict(order_id='sale',status='canceled',fill_count_fp='1.00');c.next_check=0;c.step(r)
        self.assertIsNone(r['progress']['pending'])
        ex.positions=[dict(ticker='T',position_fp='2.00')];c.next_check=0;c.step(r)
        self.assertEqual([p['count'] for p in ex.submitted],['3.00','2.00'])
        self.assertNotEqual(ex.submitted[0]['client_order_id'],ex.submitted[1]['client_order_id'])
    def test_zero_exposure_is_verified_before_archive_and_balance_is_not_invented(self):
        store=Store();ex=Exchange();c=ResetController(store,ex);r=row()
        with patch('services.demo.reset.archive_and_clone') as archive:c.step(r)
        archive.assert_called_once();self.assertEqual(r['progress']['state'],'awaiting_funds')
        self.assertEqual(r['progress']['deposit_needed_cents'],90000)
        self.assertEqual(store.saved[0][1]['cash_cents'],10000)
        ex.balance=100000;c.next_check=0;c.step(r)
        self.assertEqual(r['progress']['state'],'complete')
    def test_no_target_completes_with_verified_resulting_cash(self):
        store=Store();ex=Exchange();c=ResetController(store,ex);r=row();r['parameters']['target_balance_cents']=None
        with patch('services.demo.reset.archive_and_clone'):c.step(r)
        self.assertEqual(r['progress']['state'],'complete')
