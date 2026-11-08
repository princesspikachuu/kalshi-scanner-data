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
