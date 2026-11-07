import unittest
from services.demo.maintenance import storage_measurement

class StorageMeasurement(unittest.TestCase):
    def test_provisioned_capacity_replaces_the_old_monitoring_fallback(self):
        data=storage_measurement(5*1024**3,dict(storage_limit_gb=5),dict(DATABASE_CAPACITY_GB='10'),1000)
        self.assertEqual((data['provisioned_gb'],data['percent'],data['capacity_source']),(10,50,'deployment'))
        self.assertEqual(data['configured_limit_gb'],5)
        self.assertEqual(data['measurement'],'logical_database')
    def test_missing_or_invalid_capacity_retains_the_conservative_fallback(self):
        for value in (None,'0','bad','10.5','-5'):
            env={} if value is None else dict(DATABASE_CAPACITY_GB=value)
            self.assertEqual(storage_measurement(5*1024**3,dict(storage_limit_gb=5),env,1000)['percent'],100)
    def test_growth_uses_the_actual_observed_interval_and_rejects_stale_samples(self):
        previous=dict(at=700,database_bytes=1000)
        data=storage_measurement(1500,dict(storage_limit_gb=5),{},1000,previous)
        self.assertEqual((data['change_bytes'],data['change_seconds']),(500,300))
        for at in (500,701,10000):
            self.assertNotIn('change_bytes',storage_measurement(1500,dict(storage_limit_gb=5),{},at,previous))
