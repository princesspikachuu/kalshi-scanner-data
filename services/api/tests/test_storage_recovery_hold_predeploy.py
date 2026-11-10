"""Storage emergency hold cannot bypass normal API or active worker predeploy."""
import unittest
from services.api.manage import recovery_hold_predeploy

class StorageRecoveryHoldTests(unittest.TestCase):
    def config(self,**changes):
        env=dict(MT_STORAGE_RECOVERY_HOLD='true',WORKER_ROLE='collector',
            COLLECTION_ENABLED='false',RUNTIME_DB_PROFILE='research',
            STAGING_ACCEPTANCE='off',STAGING_OPERATOR_ACTION='off')
        env.update(changes)
        return env

    def test_disabled_research_collector_may_defer_database_check(self):
        for action in ('migrate','verify-runtime'):
            self.assertTrue(recovery_hold_predeploy(self.config(),action,'research'))

    def test_every_non_idle_or_non_research_configuration_still_checks_database(self):
        violations=[
            dict(MT_STORAGE_RECOVERY_HOLD='false'),
            dict(MT_STORAGE_RECOVERY_HOLD=''),
            dict(WORKER_ROLE='demo'),
            dict(WORKER_ROLE='processor'),
            dict(WORKER_ROLE='combined'),
            dict(COLLECTION_ENABLED='true'),
            dict(RUNTIME_DB_PROFILE='api'),
            dict(STAGING_ACCEPTANCE='r2-v1'),
            dict(STAGING_OPERATOR_ACTION='prepare-roles-v1')
        ]
        for changed in violations:
            with self.subTest(changed=changed):
                self.assertFalse(recovery_hold_predeploy(self.config(**changed),
                    'migrate','research'))
        self.assertFalse(recovery_hold_predeploy(self.config(),'prepare-runtime-roles','research'))
        self.assertFalse(recovery_hold_predeploy(self.config(),'verify-runtime','api'))
        self.assertFalse(recovery_hold_predeploy(self.config(),'other','research'))
        self.assertFalse(recovery_hold_predeploy({},'migrate','research'))

if __name__=='__main__':
    unittest.main()
