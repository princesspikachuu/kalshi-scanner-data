"""Checkpoint encoding preserves accounting and shrinks hot database writes."""
import base64,gzip,json,unittest
from decimal import Decimal as D
from unittest.mock import Mock
from services.paper_demo.shadow.checkpoint_codec import pack_checkpoint,unpack_checkpoint
from services.paper_demo.shadow.core import Engine,StrategyFleet,FeePolicy
from services.paper_demo.shadow.state import restore
from services.paper_demo.shadow.storage import HostedAudit
from services.paper_demo.shadow.migrate import profiles
from services.api.tests import test_demo_postgres as fixture

class CheckpointCodecTests(unittest.TestCase):
    def test_legacy_checkpoint_is_unchanged(self):
        value=dict(schema=1,wallet=dict(cash='12.3456'))
        self.assertIs(unpack_checkpoint(value),value)
        self.assertEqual(pack_checkpoint(value),value)
    def test_large_nested_research_and_decimal_wallet_round_trip_losslessly(self):
        value=dict(schema=1,wallet=dict(cash=D('123.456789'),lots=[dict(quantity=D('2.25'),price=D('.4211'),entry_fee=D('.0032'))]),
            experiments={str(i):dict(cells=[dict(reason='shared causal observation',net='.0012')]*100) for i in range(20)})
        packed=pack_checkpoint(value)
        self.assertEqual(unpack_checkpoint(packed),json.loads(json.dumps(value,default=str)))
        self.assertLess(len(json.dumps(packed)),packed['bytes']/5)
    def test_integrity_mismatch_fails_closed(self):
        packed=pack_checkpoint(dict(schema=1,padding='a'*100000))
        with self.assertRaises(ValueError):unpack_checkpoint(dict(packed,sha256='0'*64))
        with self.assertRaises(ValueError):unpack_checkpoint(dict(packed,bytes=packed['bytes']-1))
    def test_malformed_and_unsupported_payloads_fail_closed(self):
        packed=pack_checkpoint(dict(schema=1,padding='a'*100000))
        for changed in (dict(data='bad base64!'),dict(data=base64.b64encode(b'bad gzip').decode()),dict(checkpoint_encoding='unknown'),dict(bytes=True)):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):unpack_checkpoint(dict(packed,**changed))
    def test_decoding_is_bounded_by_declared_size_and_capacity(self):
        packed=pack_checkpoint(dict(schema=1,padding='a'*100000))
        with self.assertRaises(ValueError):unpack_checkpoint(packed,max_bytes=1000)
        with self.assertRaises(ValueError):unpack_checkpoint(dict(packed,bytes=100))
    def test_direct_restore_accepts_encoded_state_without_resetting_wallet(self):
        e=Engine(Mock(),cash='123.4567');f=StrategyFleet(e,profiles())
        from services.paper_demo.shadow.state import encode
        packed=pack_checkpoint(encode(e,f),threshold=0)
        new=Engine(Mock());nf=StrategyFleet(new,profiles());restore(new,nf,packed)
        self.assertEqual(new.wallet.cash,D('123.4567'));self.assertEqual(new.wallet.deposits,D('123.4567'))

    def test_shared_fleet_halts_are_written_once_and_restore_for_every_owner(self):
        from services.paper_demo.shadow.state import encode
        e=Engine(Mock());f=StrategyFleet(e,profiles());f.halted.update('historical-'+str(i) for i in range(1000))
        data=encode(e,f)
        self.assertEqual(sum(len(b['halted']) for b in data['fleet'].values()),1000)
        new=Engine(Mock());nf=StrategyFleet(new,profiles());restore(new,nf,data)
        self.assertEqual(nf.halted,f.halted)
        for bot in nf.bots.values():self.assertIs(bot.halted,nf.halted)

    def test_scalar_execution_records_match_recursive_encoding_and_detach_targets(self):
        from dataclasses import asdict
        from services.paper_demo.shadow.state import encode
        e=Engine(Mock());f=StrategyFleet(e,profiles());e.advance(1000)
        e.add_market(dict(ticker='KXBTC15M-test',close=2000),FeePolicy())
        e.wallet.fill('KXBTC15M-test','yes','buy',D('2.25'),D('.4211'),D('.0032'),1,'held')
        ident=e.place('KXBTC15M-test','yes','sell',D(1),D('.5'),maker=False,targets=['held'])
        data=encode(e,f)
        self.assertEqual(data['orders'][ident],asdict(e.orders[ident]))
        self.assertEqual(data['wallet']['lots'],[asdict(l) for l in e.wallet.lots])
        self.assertEqual(data['wallet']['stats'],{k:asdict(v) for k,v in e.wallet.stats.items()})
        e.orders[ident].targets.append('later')
        self.assertEqual(data['orders'][ident]['targets'],['held'])

@unittest.skipUnless(fixture.URL,'Disposable PostgreSQL is required')
class CheckpointPostgresTests(unittest.TestCase):
    setUp=fixture.DemoPostgres.setUp
    tearDown=fixture.DemoPostgres.tearDown
    @classmethod
    def setUpClass(cls):fixture.DemoPostgres.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):fixture.DemoPostgres.tearDownClass.__func__(cls)
    def test_compressed_checkpoint_preserves_wallet_lots_events_and_restart(self):
        audit=HostedAudit(self.demo,lambda:None);e=Engine(audit,cash='1000');f=StrategyFleet(e,profiles())
        e.advance(1000);e.add_market(dict(ticker='KXBTC15M-test',open=900,close=2000,metadata='x'*100000),FeePolicy())
        e.wallet.fill('KXBTC15M-test','yes','buy',D('2.25'),D('.4211'),D('.0032'),1,'existing_lot')
        audit.engine,audit.fleet=e,f
        before=e.wallet.cash
        audit.begin();e.refill(D('5.1234'));audit.flush()
        with self.demo.pool.connection() as c:
            raw=c.execute("SELECT progress FROM research_job WHERE idempotency_key='demo/shadow/checkpoint'").fetchone()['progress']
            count=c.execute("SELECT count(*) AS n FROM research_job WHERE starts_with(idempotency_key,'demo/shadow/event/')").fetchone()['n']
        self.assertEqual(raw['checkpoint_encoding'],'shadow-checkpoint-gzip-v1');self.assertEqual(count,1)
        decoded=self.demo.get('shadow/checkpoint')['progress']
        self.assertEqual(D(decoded['wallet']['cash']),before+D('5.1234'))
        self.assertEqual(decoded['markets']['KXBTC15M-test']['metadata'],'x'*100000)
        new=Engine(Mock());nf=StrategyFleet(new,profiles());restore(new,nf,decoded)
        self.assertEqual(new.wallet.cash,e.wallet.cash);self.assertEqual(new.wallet.lots[0].quantity,D('2.25'))
        self.assertEqual(new.wallet.lots[0].price,D('.4211'));self.assertEqual(new.wallet.lots[0].entry_fee,D('.0032'))
