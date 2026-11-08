"""Large dashboard views remain strict JSON with verifiable transport bytes."""
import hashlib,json,unittest
from copy import deepcopy
from services.api.shadow import workspace_response

class WorkspaceTransport(unittest.TestCase):
    def test_compaction_preserves_visible_accounts_and_research_without_mutating_snapshot(self):
        evidence=[dict(price='0.9',net='1',label='Quoted "text" · 🌱')]
        account=dict(portfolio=dict(cash='999',total_pnl='-1'),positions=[dict(ticker='held')],
            current_cycles={'old':{'details':'x'*1100000}},bots={'fav':{'cash':'999'}},at=100)
        payload=dict(contract='demo-v1',status=dict(experiments={'favorites':dict(accounting=account)},positions=[dict(ticker='held')]),
            bots=[dict(id='fav',account=dict(cash='999'),experiment=dict(entry_timing=evidence))],
            folders=[dict(id='favorites',accounting=account,bots={'fav':dict(entry_timing=evidence)})])
        original=deepcopy(payload);response=workspace_response(payload);result=json.loads(response.body)
        self.assertEqual(payload,original)
        self.assertEqual(result['bots'],payload['bots'])
        self.assertEqual(result['status']['positions'],payload['status']['positions'])
        self.assertEqual(result['folders'][0]['accounting']['portfolio'],account['portfolio'])
        self.assertEqual(result['folders'][0]['accounting']['positions'],account['positions'])
        self.assertLess(len(response.body),2000)
        self.assertEqual(response.headers['x-pocket-workspace-sha256'],hashlib.sha256(response.body).hexdigest())
        self.assertEqual(response.headers['x-pocket-workspace-bytes'],str(len(response.body)))
    def test_nonfinite_values_fail_before_response_is_sent(self):
        with self.assertRaises(ValueError):workspace_response(dict(status={},folders=[],bots=[],invalid=float('nan')))
    def test_repeated_research_above_transport_limit_is_sent_once(self):
        import base64,gzip
        research=dict(cells=[dict(net='1',dimensions=dict(underlying='BTC'),evidence='x'*1200) for _ in range(1000)])
        metric=dict(gross_profit='12',fees='2',net_realized_pnl='10',win_rate='50',cycles=20,excluded_cycles=1,
            scalper=research,entry_timing=[dict(net='10')])
        periods={p:metric for p in ('all','1H','6H','24H')}
        payload=dict(status={},folders=[],bots=[dict(id='scalper',experiment=metric,metrics=periods,financial_metrics=periods)])
        original=deepcopy(payload)
        self.assertGreater(len(json.dumps(payload)),8388608)
        response=workspace_response(payload,compressed=True)
        envelope=json.loads(response.body)
        result=json.loads(gzip.decompress(base64.b64decode(envelope['data'])))
        self.assertLess(envelope['bytes'],1500000)
        bot=result['bots'][0]
        self.assertEqual(bot['experiment'],metric)
        for field in ('metrics','financial_metrics'):
            for summary in bot[field].values():
                self.assertEqual(summary,dict(gross_profit='12',fees='2',net_realized_pnl='10',win_rate='50',cycles=20,excluded_cycles=1))
        self.assertEqual(payload,original)
    def test_negotiated_compression_preserves_large_unicode_payload_and_embedded_checksum(self):
        import base64,gzip
        payload=dict(status={},folders=[],bots=[dict(id=i,label='Quoted "price" · 🌱',pnl='-0.123') for i in range(30000)])
        plain=workspace_response(payload)
        compressed=workspace_response(payload,compressed=True)
        envelope=json.loads(compressed.body)
        raw=gzip.decompress(base64.b64decode(envelope['data']))
        self.assertEqual(raw,plain.body)
        self.assertEqual(json.loads(raw),payload)
        self.assertEqual(envelope['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(envelope['bytes'],len(raw))
        self.assertEqual(compressed.headers['x-pocket-workspace-encoding'],'gzip-base64-v1')
        self.assertLess(len(compressed.body),len(raw)//4)
        self.assertNotIn('x-pocket-workspace-encoding',plain.headers)
