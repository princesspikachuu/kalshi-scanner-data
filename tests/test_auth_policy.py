import hashlib
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services' / 'api'))
from auth_policy import (GoogleIdentity, LoginRejected, new_session_material,
                         require_login_csrf, require_owner, verify_google_login)

NONCE = 'n' * 43


def claims(**updates):
    result = {'sub': 'owner-subject', 'email': 'owner@example.test', 'email_verified': True,
              'iss': 'https://accounts.google.com', 'aud': 'our-client',
              'exp': time.time()+300, 'nonce': NONCE}
    result.update(updates)
    return result


class AuthPolicyTests(unittest.TestCase):
    def login(self):
        return verify_google_login(credential='opaque-google-token', client_id='our-client', expected_nonce=NONCE)

    def test_library_receives_expected_audience_before_identity_is_used(self):
        with patch('auth_policy._verify_with_google', return_value=claims()) as verifier:
            identity = self.login()
        verifier.assert_called_once_with('opaque-google-token', 'our-client')
        self.assertEqual(identity.subject, 'owner-subject')

    def test_invalid_claims_and_nonce_fail_closed_even_if_adapter_returns_them(self):
        for override in ({'aud': 'another-app'}, {'iss': 'https://attacker.test'},
                         {'exp': time.time()-1}, {'exp': float('nan')}, {'exp': None},
                         {'email_verified': False}, {'email_verified': 'true'},
                         {'sub': ''}, {'nonce': 'other-nonce'}, {'nonce': None}):
            with self.subTest(override=override), patch('auth_policy._verify_with_google', return_value=claims(**override)):
                with self.assertRaises(LoginRejected): self.login()

    def test_verifier_failure_does_not_expose_the_google_token(self):
        with patch('auth_policy._verify_with_google', side_effect=ValueError('opaque-google-token')):
            with self.assertRaises(LoginRejected) as error: self.login()
        self.assertNotIn('opaque-google-token', str(error.exception))

    def test_missing_configuration_or_nonce_does_not_call_google(self):
        with patch('auth_policy._verify_with_google') as verifier:
            for options in ({'client_id': ''}, {'expected_nonce': ''}, {'credential': ''}):
                settings = dict(credential='token', client_id='client', expected_nonce=NONCE)
                settings.update(options)
                with self.assertRaises(LoginRejected): verify_google_login(**settings)
            verifier.assert_not_called()

    def test_owner_authorization_uses_stable_subject_and_denies_open_signup(self):
        identity = GoogleIdentity('owner-subject', 'changed-email@example.test')
        require_owner(identity, 'owner-subject')
        for subject in (None, '', 'some-other-subject'):
            with self.assertRaises(LoginRejected): require_owner(identity, subject)

    def test_csrf_missing_mismatch_and_cross_origin_are_rejected(self):
        good = dict(cookie_token=NONCE, body_token=NONCE, origin='https://app.test', app_origin='https://app.test')
        require_login_csrf(**good)
        for override in ({'cookie_token': None}, {'body_token': ''}, {'body_token': 'x'*43},
                         {'origin': 'https://attacker.test'}, {'origin': None}, {'app_origin': ''}):
            with self.subTest(override=override), self.assertRaises(LoginRejected):
                require_login_csrf(**(good | override))

    def test_session_tokens_are_distinct_and_only_hashes_belong_in_database(self):
        a, b = new_session_material(), new_session_material()
        self.assertNotEqual(a['token'], b['token'])
        self.assertNotEqual(a['token'], a['csrf'])
        self.assertEqual(a['token_hash'], hashlib.sha256(a['token'].encode()).hexdigest())
        self.assertEqual(a['csrf_hash'], hashlib.sha256(a['csrf'].encode()).hexdigest())


if __name__ == '__main__': unittest.main()
