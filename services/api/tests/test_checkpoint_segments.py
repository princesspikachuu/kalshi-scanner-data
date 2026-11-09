"""Compressed-member reuse preserves the exact existing decoded MessagePack state."""
import base64,gzip,json,unittest
from decimal import Decimal as D
from unittest.mock import Mock,patch
from services.paper_demo.shadow.checkpoint_segments import CheckpointSegments
from services.paper_demo.shadow.checkpoint_codec import pack_checkpoint,unpack_checkpoint,BINARY_ENCODING,ENCODING
from services.api.tests import test_demo_postgres as fixture
from services.paper_demo.shadow.storage import HostedAudit
from services.paper_demo.shadow.core import Engine,StrategyFleet
from services.paper_demo.shadow.migrate import profiles

def dataset():
    research=dict(totals=dict(net='.0166',completed=1),cells={str(i):dict(price=.42,net=i*.001,reason='real observation '+str(i)) for i in range(250)})
    return dict(wallet=dict(cash=D('1000.016600000000001'),lots=[dict(quantity='1.25',price='.42')]),
        experiments=dict(_summary={'old':list(range(3000))},maker=dict(model={'old':list(range(3000))},
            engine=dict(wallet=dict(cash='1000.0166')),strategies=dict(MM=dict(exit_evidence={'cells':list(range(3000))},
                attempts={'live':dict(quantity='1.25',price='.42')},scalper=dict(research=research,config=dict(order_ttl=1800)))))))

class CheckpointSegmentTests(unittest.TestCase):
    def test_default_cache_covers_the_full_scalper_and_maker_profile_population(self):
        data=dict(experiments=dict(strategy=dict(strategies={str(i):dict(scalper=dict(research=dict(padding='x'*5000))) for i in range(273)})))
        cache=CheckpointSegments();pack_checkpoint(data,threshold=0,binary=True,segments=cache)
        before=cache.metrics();value=pack_checkpoint(data,threshold=0,binary=True,segments=cache)
        self.assertEqual(cache.metrics()['hits']-before['hits'],273)
        self.assertEqual(unpack_checkpoint(value),data)
    def test_section_sizes_explain_exact_raw_bytes_without_leaking_state(self):
        data=dataset();cache=CheckpointSegments()
        encoded=pack_checkpoint(data,threshold=0,binary=True,segments=cache)
        sections=cache.metrics()['last_state_sections']
        self.assertEqual(sum(s['raw_bytes'] for s in sections.values()),encoded['bytes'])
        self.assertIn('hot_and_small',sections)
        self.assertIn('shared_summary',sections)
        self.assertIn('calibration_models',sections)
        self.assertIn('verified_exit_evidence',sections)
        self.assertIn('scalper_research',sections)
        self.assertEqual(sections['hot_and_small']['compressed_bytes'],None)
        self.assertTrue(all(value['members']>=1 for value in sections.values()))
        self.assertTrue(all(value['raw_bytes']>=0 for value in sections.values()))
        self.assertNotIn('MM',str(sections))
        self.assertNotIn('reason',str(sections))
        # Collecting the metric must not alter checkpoint identity or reuse.
        before=cache.metrics();again=pack_checkpoint(data,threshold=0,binary=True,segments=cache)
        self.assertEqual(again,encoded)
        self.assertEqual(cache.metrics()['last_state_sections'],before['last_state_sections'])
        self.assertGreater(cache.metrics()['hits'],before['hits'])

    def test_decoded_bytes_hash_schema_money_and_research_are_identical(self):
        data=dataset();cache=CheckpointSegments()
        whole=pack_checkpoint(data,threshold=0,binary=True)
        segmented=pack_checkpoint(data,threshold=0,binary=True,segments=cache)
        self.assertEqual(segmented['checkpoint_encoding'],BINARY_ENCODING)
        self.assertEqual((segmented['bytes'],segmented['sha256']),(whole['bytes'],whole['sha256']))
        self.assertEqual(gzip.decompress(base64.b64decode(segmented['data'])),gzip.decompress(base64.b64decode(whole['data'])))
        self.assertEqual(unpack_checkpoint(segmented),json.loads(json.dumps(data,default=str)))
    def test_cache_compares_actual_bytes_so_direct_nested_mutations_cannot_go_stale(self):
        data=dataset();cache=CheckpointSegments();pack_checkpoint(data,threshold=0,binary=True,segments=cache)
        data['wallet']['cash']=D('999.1234567890123456789')
        data['experiments']['maker']['strategies']['MM']['scalper']['research']['cells']['1']['net']=9.123
        data['experiments']['maker']['strategies']['MM']['exit_evidence']['cells'].append(9999)
        data['experiments']['_summary']['old'].append(7777)
        encoded=pack_checkpoint(data,threshold=0,binary=True,segments=cache)
        self.assertEqual(unpack_checkpoint(encoded),json.loads(json.dumps(data,default=str)))
        self.assertGreater(cache.metrics()['hits'],0);self.assertGreater(cache.metrics()['misses'],4)
    def test_unchanged_large_blocks_are_not_recompressed(self):
        data=dataset();cache=CheckpointSegments();pack_checkpoint(data,threshold=0,binary=True,segments=cache)
        before=cache.metrics();compress=gzip.compress
        with patch('services.paper_demo.shadow.checkpoint_segments.gzip.compress',wraps=compress) as call:
            data['wallet']['cash']='900';pack_checkpoint(data,threshold=0,binary=True,segments=cache)
        self.assertGreater(cache.metrics()['hits'],before['hits']);self.assertEqual(cache.metrics()['misses'],before['misses'])
        self.assertTrue(all(len(c.args[0])<4096 for c in call.call_args_list))
    def test_cache_retention_is_bounded_and_eviction_does_not_change_state(self):
        data=dataset();cache=CheckpointSegments(max_bytes=20000,max_entries=1)
        for n in range(3):
            data['experiments']['maker']['strategies']['MM']['scalper']['research']['totals']['completed']=n
            value=pack_checkpoint(data,threshold=0,binary=True,segments=cache)
            self.assertEqual(unpack_checkpoint(value),json.loads(json.dumps(data,default=str)))
            self.assertLessEqual(cache.metrics()['retained_bytes'],20000);self.assertLessEqual(cache.metrics()['entries'],1)
        self.assertGreater(cache.metrics()['evictions'],0)
    def test_old_size_checksum_and_corruption_guards_still_apply_across_members(self):
        encoded=pack_checkpoint(dataset(),threshold=0,binary=True,segments=CheckpointSegments())
        for changed in (dict(sha256='0'*64),dict(bytes=encoded['bytes']-1),dict(data=encoded['data'][:-12]+'AAAAAAAAAAAA')):
            with self.assertRaises(ValueError):unpack_checkpoint(dict(encoded,**changed))
        with self.assertRaises(ValueError):unpack_checkpoint(encoded,max_bytes=1000)
    def test_large_integer_json_fallback_and_plain_small_state_remain_compatible(self):
        data=dataset();data['large_counter']=2**100
        value=pack_checkpoint(data,threshold=0,binary=True,segments=CheckpointSegments())
        self.assertEqual(value['checkpoint_encoding'],ENCODING);self.assertEqual(unpack_checkpoint(value),json.loads(json.dumps(data,default=str)))
        self.assertEqual(pack_checkpoint(dict(cash=D('.0166')),binary=True,segments=CheckpointSegments()),dict(cash='0.0166'))

@unittest.skipUnless(fixture.URL,'Disposable PostgreSQL is required')
class SegmentedHostedPostgresTests(unittest.TestCase):
    setUp=fixture.DemoPostgres.setUp
    tearDown=fixture.DemoPostgres.tearDown
    @classmethod
    def setUpClass(cls):fixture.DemoPostgres.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):fixture.DemoPostgres.tearDownClass.__func__(cls)
    def test_current_database_reader_recovers_segmented_checkpoint_and_all_research(self):
        import shutil
        from services.paper_demo.shadow.storage import put
        audit=HostedAudit(self.demo,lambda:None);self.addCleanup(shutil.rmtree,audit.path)
        audit.engine=Engine(Mock(),cash='1000.0166');audit.fleet=StrategyFleet(audit.engine,profiles())
        audit.experiments=Mock();audit.experiments.state.return_value=dataset()['experiments']
        first=audit.checkpoint_snapshot();second=audit.checkpoint_snapshot()
        self.assertGreater(audit.checkpoint_segments.metrics()['hits'],0)
        with self.demo.pool.connection() as c:put(c,'demo/shadow/checkpoint',{},second)
        state=self.demo.get('shadow/checkpoint')['progress']
        self.assertEqual(state['wallet']['cash'],'1000.0166')
        self.assertEqual(state['experiments'],dataset()['experiments'])
