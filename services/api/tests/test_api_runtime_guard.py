"""API cutover gate checks its own direct DB identity before opening the pool."""
from dataclasses import replace
import os
import unittest
from unittest.mock import Mock,patch
from services.api.config import Settings
from services.api.store import PostgresStore


class ApiRuntimeGuardTests(unittest.TestCase):
    def test_environment_flag_is_explicit_and_boolean(self):
        env=dict(APP_ORIGIN='https://app.test',GOOGLE_CLIENT_ID='client',DATABASE_URL='postgresql://private-sentinel',
                 API_PROXY_SECRET='x'*32,OWNER_GOOGLE_SUB='owner')
        with patch.dict(os.environ,env,clear=True):
            self.assertFalse(Settings.from_env().require_runtime_db)
            with patch.dict(os.environ,{'REQUIRE_API_RUNTIME_DB':'true'}):
                self.assertTrue(Settings.from_env().require_runtime_db)
            with patch.dict(os.environ,{'REQUIRE_API_RUNTIME_DB':'yes'}):
                with self.assertRaisesRegex(ValueError,'true or false'):Settings.from_env()
        with self.assertRaises(ValueError):
            Settings('https://app.test','client','url','x'*32,owner_subject='owner',require_runtime_db='false')

    def test_strict_api_gate_rejects_before_pool_open_without_echoing_uri(self):
        with patch('services.api.store.ConnectionPool') as pool, \
             patch('services.api.db_privileges.audit_database',return_value={'privilege_boundary_ready':False}) as audit:
            store=PostgresStore('postgresql://private-sentinel',require_runtime_db=True)
            with self.assertRaisesRegex(RuntimeError,'API runtime database privileges are not isolated') as caught:
                store.open()
            audit.assert_called_once_with('postgresql://private-sentinel','api')
            pool.return_value.open.assert_not_called()
            self.assertNotIn('sentinel',str(caught.exception))

    def test_valid_api_identity_opens_pool_and_legacy_mode_does_not_audit(self):
        with patch('services.api.store.ConnectionPool') as pool, \
             patch('services.api.db_privileges.audit_database',return_value={'privilege_boundary_ready':True}) as audit:
            store=PostgresStore('postgresql://private-sentinel',require_runtime_db=True);store.open()
            pool.return_value.open.assert_called_once_with(wait=True,timeout=5)
            audit.reset_mock();store=PostgresStore('postgresql://private-sentinel');store.open()
            audit.assert_not_called()

    def test_audit_connection_errors_are_sanitized(self):
        with patch('services.api.store.ConnectionPool') as pool, \
             patch('services.api.db_privileges.audit_database',side_effect=RuntimeError('private-sentinel')):
            store=PostgresStore('postgresql://private-sentinel',require_runtime_db=True)
            with self.assertRaisesRegex(RuntimeError,'permission check failed') as caught:store.open()
            self.assertNotIn('sentinel',str(caught.exception));pool.return_value.open.assert_not_called()
