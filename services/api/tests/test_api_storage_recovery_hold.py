"""MT-019: API stays fully quiescent during explicit storage recovery hold."""
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from services.api.app import create_app
from services.api.config import Settings


class APIRecoveryHoldTests(unittest.TestCase):
    def settings(self, hold):
        return Settings(
            app_origin='https://example.test',
            google_client_id='test-client',
            database_url='postgresql://example.invalid/research',
            proxy_secret='a' * 40,
            owner_email='owner@example.test',
            recovery_hold=hold,
        )

    def store(self):
        stub=MagicMock()
        stub.ready.return_value=True
        stub.allow.return_value=True
        stub.pool=MagicMock()
        return stub

    def test_invalid_recovery_hold_settings_fail_closed(self):
        with self.assertRaises(ValueError):
            self.settings('true')
        env={
            'APP_ORIGIN':'https://example.test',
            'GOOGLE_CLIENT_ID':'test-client',
            'DATABASE_URL':'postgresql://example.invalid/research',
            'API_PROXY_SECRET':'a'*40,
            'OWNER_GOOGLE_EMAIL':'owner@example.test',
        }
        with patch.dict('os.environ',dict(env,MT_API_RECOVERY_HOLD='no'),clear=True):
            with self.assertRaises(ValueError):
                Settings.from_env()
        with patch.dict('os.environ',dict(env,MT_API_RECOVERY_HOLD='true'),clear=True):
            self.assertTrue(Settings.from_env().recovery_hold)
        with patch.dict('os.environ',env,clear=True):
            self.assertFalse(Settings.from_env().recovery_hold)

    def test_recovery_hold_only_exposes_health_and_never_writes(self):
        store=self.store()
        app=create_app(settings=self.settings(True),store=store)
        with TestClient(app) as client:
            self.assertEqual(client.get('/health/live').status_code,200)
            self.assertEqual(client.get('/health/ready').status_code,200)
            for method,path in (
                ('GET','/auth/challenge'),
                ('GET','/collection/campaigns'),
                ('POST','/collection/campaigns'),
                ('POST','/demo/bots'),
                ('POST','/demo/shadow/funds'),
                ('POST','/live/pause'),
                ('POST','/auth/google'),
                ('POST','/auth/logout'),
            ):
                with self.subTest(method=method,path=path):
                    response=client.request(method,path,headers={
                        'x-pocket-proxy':'a'*40,
                        'origin':'https://example.test',
                    })
                    self.assertEqual(response.status_code,503)
                    self.assertEqual(response.headers['Cache-Control'],'no-store')
        store.allow.assert_not_called()
        store.challenge.assert_not_called()
        store.session.assert_not_called()
        store.revoke.assert_not_called()

    def test_default_mode_preserves_owner_auth_challenge(self):
        store=self.store()
        app=create_app(settings=self.settings(False),store=store)
        with TestClient(app) as client:
            response=client.get('/auth/challenge',headers={
                'x-pocket-proxy':'a'*40,
                'origin':'https://example.test',
            })
        self.assertEqual(response.status_code,200)
        store.challenge.assert_called_once()
        store.allow.assert_called_once()


if __name__=='__main__':
    unittest.main()
