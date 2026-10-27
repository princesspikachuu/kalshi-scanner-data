"""Runtime configuration is secret-safe, gated and cleaned up without hosted I/O."""
from contextlib import contextmanager
from io import StringIO
from threading import Event
import signal
import unittest
from unittest.mock import Mock,patch
from services.research import runtime


def environment():
    return dict(DATABASE_URL='postgresql://private-sentinel@db/pocket_test',R2_ACCOUNT_ID='a'*32,
        R2_BUCKET='pocket-test',R2_ACCESS_KEY_ID='access-sentinel',R2_SECRET_ACCESS_KEY='secret-sentinel',
        KALSHI_READ_RATE='1',KALSHI_READ_CAPACITY='1',KALSHI_ENDPOINT_COST='1',COLLECTION_ENABLED='false')


class RuntimeTests(unittest.TestCase):
    def test_env_names_are_parsed_without_secret_repr(self):
        settings=runtime.WorkerSettings.from_env(environment())
        self.assertFalse(settings.enabled);self.assertEqual(settings.read_rate,1)
        self.assertEqual(settings.bucket,'pocket-test')
        for value in ('sentinel','postgresql','pocket-test','a'*32):self.assertNotIn(value,repr(settings))

    def test_missing_malformed_credentials_and_budgets_fail_without_echo(self):
        original=environment()
        for key,value in (('R2_ACCOUNT_ID','https://private-sentinel.r2.cloudflarestorage.com'),
                ('R2_BUCKET','private-sentinel/invalid'),('KALSHI_READ_RATE','nan'),('KALSHI_READ_CAPACITY','0'),
                ('KALSHI_ENDPOINT_COST','2'),('COLLECTION_ENABLED','yes'),('R2_SECRET_ACCESS_KEY','')):
            with self.subTest(key=key):
                with self.assertRaises(runtime.ConfigurationError) as caught:runtime.WorkerSettings.from_env({**original,key:value})
                self.assertNotIn('sentinel',str(caught.exception))
        for key in original.keys()-{'COLLECTION_ENABLED'}:
            without={k:v for k,v in original.items() if k!=key}
            with self.assertRaises(runtime.ConfigurationError):runtime.WorkerSettings.from_env(without)

    def test_check_config_never_builds_clients_or_runs_workers(self):
        with patch.dict(runtime.os.environ,environment(),clear=True),patch.object(runtime,'run') as run,patch('sys.stdout',new_callable=StringIO) as output:
            self.assertEqual(runtime.main(['--check-config']),0);run.assert_not_called()
            self.assertNotIn('sentinel',output.getvalue())

    def test_disabled_worker_opens_no_connections(self):
        stop=Mock();stop.is_set.side_effect=[False,True]
        with patch.object(runtime,'ConnectionPool') as pool,patch.object(runtime.R2Objects,'connect') as r2:
            runtime.run(runtime.WorkerSettings.from_env(environment()),stop)
            pool.assert_not_called();r2.assert_not_called();stop.wait.assert_called_once_with(30)

    def test_enabled_wiring_uses_group_values_and_closes_resources_after_error(self):
        settings=runtime.WorkerSettings.from_env({**environment(),'COLLECTION_ENABLED':'true'})
        pool=Mock();objects=Mock();inventory=Mock();evidence=Mock()
        connection=Mock();connection.execute.return_value.fetchone.return_value={'ready':True}
        pool.connection.return_value.__enter__=Mock(return_value=connection)
        pool.connection.return_value.__exit__=Mock(return_value=False)
        inventory.__enter__=Mock(return_value=inventory);inventory.__exit__=Mock(return_value=False)
        evidence.__enter__=Mock(return_value=evidence);evidence.__exit__=Mock(return_value=False)
        with patch('services.research.acceptance.audit_database',return_value={'privilege_boundary_ready':True}), \
                patch.object(runtime,'ConnectionPool',return_value=pool),patch.object(runtime.R2Objects,'connect',return_value=objects) as r2,\
                patch.object(runtime,'KalshiInventory',return_value=inventory),patch.object(runtime,'KalshiEvidence',return_value=evidence),\
                patch.object(runtime,'ReadBudget') as budget,patch.object(runtime,'CampaignWorker') as worker,\
                patch.object(runtime,'serve',side_effect=RuntimeError('secret-sentinel')):
            with self.assertRaises(RuntimeError):runtime.run(settings,Event())
            self.assertEqual(r2.call_args.kwargs['access_key_id'],settings.access_key_id)
            self.assertEqual(r2.call_args.kwargs['secret_access_key'],settings.secret_access_key)
            budget.return_value.configure.assert_called_once_with(1,1)
            worker.assert_called_once();objects.client.close.assert_called_once();pool.close.assert_called_once()
            inventory.__exit__.assert_called_once();evidence.__exit__.assert_called_once()

    def test_startup_errors_are_sanitized_and_signal_handlers_restore(self):
        with patch.dict(runtime.os.environ,environment(),clear=True),patch.object(runtime,'run',side_effect=RuntimeError('secret-sentinel')),patch('sys.stderr',new_callable=StringIO) as output:
            self.assertEqual(runtime.main([]),1);self.assertNotIn('sentinel',output.getvalue())
        stop=Event();handlers={}
        def install(name,fn):
            previous=handlers.get(name,'previous');handlers[name]=fn;return previous
        with patch.object(runtime.signal,'signal',side_effect=install):
            with runtime.termination(stop):handlers[signal.SIGTERM](None,None);self.assertTrue(stop.is_set())
        self.assertEqual(set(handlers.values()),{'previous'})


    def test_explicit_acceptance_is_once_then_idle_and_never_starts_collection(self):
        from services.research import acceptance
        for action in ('r2-v1','database-v1'):
            settings=runtime.WorkerSettings.from_env({**environment(),'STAGING_ACCEPTANCE':action})
            stop=Mock();stop.is_set.side_effect=[False,True]
            with patch.object(acceptance,'run_check',return_value={'verified':True}) as check, \
                 patch.object(runtime,'serve') as serve,patch('sys.stdout',new_callable=StringIO):
                runtime.run(settings,stop)
                check.assert_called_once_with(settings,action);serve.assert_not_called()
        for values in ({'STAGING_ACCEPTANCE':'typo'},{'STAGING_ACCEPTANCE':'r2-v1','COLLECTION_ENABLED':'true'}):
            with self.assertRaises(runtime.ConfigurationError):
                runtime.WorkerSettings.from_env({**environment(),**values})

    def test_acceptance_failure_is_sanitized_then_idles_without_retries(self):
        from services.research import acceptance
        settings=runtime.WorkerSettings.from_env({**environment(),'STAGING_ACCEPTANCE':'r2-v1'})
        stop=Mock();stop.is_set.return_value=True
        with patch.object(acceptance,'run_check',side_effect=RuntimeError('private-sentinel')) as check, \
             patch('sys.stderr',new_callable=StringIO) as errors:
            runtime.run(settings,stop);check.assert_called_once()
            self.assertNotIn('sentinel',errors.getvalue())


    def test_collection_refuses_operator_credentials_before_constructing_clients(self):
        settings=runtime.WorkerSettings.from_env({**environment(),'COLLECTION_ENABLED':'true'})
        with patch('services.research.acceptance.audit_database',return_value={'privilege_boundary_ready':False}), \
             patch.object(runtime,'ConnectionPool') as pool,patch.object(runtime.R2Objects,'connect') as r2:
            with self.assertRaisesRegex(runtime.ConfigurationError,'privileges are not isolated'):
                runtime.run(settings,Event())
            pool.assert_not_called();r2.assert_not_called()

    def test_operator_role_preparation_is_exclusive_once_and_stays_disabled(self):
        settings=runtime.WorkerSettings.from_env({**environment(),'STAGING_OPERATOR_ACTION':'prepare-roles-v1'})
        stop=Mock();stop.is_set.side_effect=[False,True]
        with patch('services.api.operations.prepare_runtime_roles',return_value={'prepared':True}) as prepare, \
             patch.object(runtime,'ConnectionPool') as pool,patch.object(runtime.R2Objects,'connect') as r2, \
             patch('sys.stdout',new_callable=StringIO):
            runtime.run(settings,stop);prepare.assert_called_once_with(settings.database_url)
            pool.assert_not_called();r2.assert_not_called()
        for values in ({'STAGING_OPERATOR_ACTION':'typo'},
                       {'STAGING_OPERATOR_ACTION':'prepare-roles-v1','COLLECTION_ENABLED':'true'},
                       {'STAGING_OPERATOR_ACTION':'prepare-roles-v1','STAGING_ACCEPTANCE':'database-v1'}):
            with self.assertRaises(runtime.ConfigurationError):
                runtime.WorkerSettings.from_env({**environment(),**values})

    def test_operator_action_failure_is_sanitized_without_retry(self):
        settings=runtime.WorkerSettings.from_env({**environment(),'STAGING_OPERATOR_ACTION':'prepare-roles-v1'})
        stop=Mock();stop.is_set.return_value=True
        with patch('services.api.operations.prepare_runtime_roles',side_effect=RuntimeError('private-sentinel')) as prepare, \
             patch('sys.stderr',new_callable=StringIO) as errors:
            runtime.run(settings,stop);prepare.assert_called_once()
            self.assertNotIn('sentinel',errors.getvalue())
