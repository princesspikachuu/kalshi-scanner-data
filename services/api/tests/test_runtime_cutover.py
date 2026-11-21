"""Cutover rejects malformed secret material and never migrates a runtime profile."""
from io import StringIO
from threading import Event
import unittest
from unittest.mock import Mock,patch
from services.api import manage,operations
from services.research.runtime import WorkerSettings,run,ConfigurationError
from test_worker_runtime import environment


def verifiers():
    # Structurally valid NON-AUTHENTICATING test verifiers, not real passwords.
    import base64
    def value(byte):
        part=lambda size:base64.b64encode(bytes([byte])*size).decode()
        return 'SCRAM-SHA-256$4096:'+part(16)+'$'+part(32)+':'+part(32)
    return dict(zip(operations.RUNTIME_ROLES,(value(1),value(2))))


class CutoverTests(unittest.TestCase):
    def test_only_fixed_independent_well_formed_scram_verifiers_are_accepted(self):
        valid=verifiers();operations.validate_runtime_verifiers(valid)
        for invalid in (None,{}, {**valid,'operator':'private-sentinel'},
                        {**valid,'pocket_api_runtime':'private-sentinel'},
                        {**valid,'pocket_api_runtime':valid['pocket_research_runtime']},
                        {k:v.replace('4096','1') for k,v in valid.items()},
                        {k:v.replace('AQEB','!!!!') for k,v in valid.items()}):
            with self.subTest(invalid_type=type(invalid)):
                with self.assertRaises(ValueError) as caught:operations.validate_runtime_verifiers(invalid)
                self.assertNotIn('private-sentinel',str(caught.exception))
        with patch.object(operations,'audit_database') as audit:
            with self.assertRaises(ValueError):operations.activate_runtime_roles('private-sentinel',{})
            audit.assert_not_called()

    def test_profile_deploy_only_audits_and_never_calls_migrations(self):
        with patch.object(manage,'migrate') as migrate,patch('services.api.db_privileges.audit_database',return_value={'privilege_boundary_ready':True}) as audit:
            self.assertTrue(manage.deployment_check('private-sentinel','api')['privilege_boundary_ready'])
            audit.assert_called_once_with('private-sentinel','api');migrate.assert_not_called()
        with patch.object(manage,'migrate') as migrate,patch('services.api.db_privileges.audit_database',return_value={'privilege_boundary_ready':False}):
            with self.assertRaises(RuntimeError):manage.deployment_check('private-sentinel','api')
            migrate.assert_not_called()

    def test_activation_is_explicit_secret_safe_and_once_without_collection(self):
        import json
        env={**environment(),'STAGING_OPERATOR_ACTION':'activate-roles-v1','STAGING_RUNTIME_VERIFIERS':json.dumps(verifiers())}
        settings=WorkerSettings.from_env(env)
        self.assertNotIn('SCRAM',repr(settings))
        stop=Mock();stop.is_set.return_value=True
        with patch('services.api.operations.activate_runtime_roles',return_value={'activated':True}) as activate,patch('services.research.runtime.serve') as serve,patch('sys.stdout',new_callable=StringIO) as out:
            run(settings,stop);activate.assert_called_once_with(settings.database_url,settings.runtime_verifiers)
            serve.assert_not_called();self.assertNotIn('SCRAM',out.getvalue())
        with patch('services.api.operations.activate_runtime_roles',side_effect=RuntimeError('private-sentinel')) as activate,patch('sys.stderr',new_callable=StringIO) as errors:
            run(settings,stop);activate.assert_called_once();self.assertNotIn('sentinel',errors.getvalue())
        for delta in ({'COLLECTION_ENABLED':'true'},{'STAGING_ACCEPTANCE':'database-v1'},
                      {'STAGING_OPERATOR_ACTION':'off'},{'STAGING_RUNTIME_VERIFIERS':'private-sentinel'}):
            with self.assertRaises(ConfigurationError) as caught:WorkerSettings.from_env({**env,**delta})
            self.assertNotIn('sentinel',str(caught.exception))
