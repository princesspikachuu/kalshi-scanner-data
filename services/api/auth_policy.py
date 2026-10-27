"""Google-only verification and owner authorization policy."""
from dataclasses import dataclass
import hashlib
import math
import secrets
import time
import threading


class LoginRejected(ValueError):
    """Safe to map to a generic unauthorized response; never expose credentials."""


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    email_authoritative: bool = False


def require_login_csrf(*, cookie_token, body_token, origin, app_origin):
    # Called before token verification. Tokens must be minted by our login setup.
    if not app_origin or origin != app_origin:
        raise LoginRejected('Login rejected')
    if not all(isinstance(t, str) and 32 <= len(t) <= 256 for t in (cookie_token, body_token)):
        raise LoginRejected('Login rejected')
    if not secrets.compare_digest(cookie_token.encode(), body_token.encode()):
        raise LoginRejected('Login rejected')


_transport=threading.local()


def _google_request():
    if not hasattr(_transport,'request'):
        from cachecontrol import CacheControl
        from requests import Session
        from google.auth.transport.requests import Request
        _transport.request=Request(session=CacheControl(Session()))
    def bounded(*args,**kwargs):
        kwargs['timeout']=5
        return _transport.request(*args,**kwargs)
    return bounded


def _verify_with_google(credential,client_id):
    from google.oauth2.id_token import verify_oauth2_token
    return verify_oauth2_token(credential,_google_request(),client_id)


def verify_google_login(*, credential, client_id, expected_nonce):
    if not client_id or not isinstance(credential, str) or not 1 <= len(credential) <= 16384:
        raise LoginRejected('Login rejected')
    if not isinstance(expected_nonce, str) or not 32 <= len(expected_nonce) <= 256:
        raise LoginRejected('Login rejected')
    try:
        claims = _verify_with_google(credential, client_id)
    except Exception:
        # Do not log or propagate provider errors which might contain the token.
        raise LoginRejected('Login rejected') from None
    try:
        subject, email = claims['sub'], claims['email']
        expiry = float(claims['exp'])
        valid = (claims['aud'] == client_id
                 and claims['iss'] in ('accounts.google.com', 'https://accounts.google.com')
                 and math.isfinite(expiry) and expiry > time.time()
                 and claims['email_verified'] is True
                 and isinstance(subject, str) and 1 <= len(subject) <= 255
                 and isinstance(email, str) and 3 <= len(email) <= 320 and '@' in email
                 and isinstance(claims.get('nonce'), str)
                 and secrets.compare_digest(claims['nonce'].encode(), expected_nonce.encode()))
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise LoginRejected('Login rejected')
    return GoogleIdentity(subject=subject,email=email,email_authoritative=email.casefold().endswith('@gmail.com') or (isinstance(claims.get('hd'),str) and bool(claims.get('hd'))))


def require_owner(identity, bound_google_subject):
    # Owner binding is persisted in PostgreSQL, never derived from an email on
    # each request. An uninitialized database must not turn into open signup.
    if not isinstance(bound_google_subject, str) or not bound_google_subject:
        raise LoginRejected('Login rejected')
    if not secrets.compare_digest(identity.subject.encode(), bound_google_subject.encode()):
        raise LoginRejected('Login rejected')


def new_session_material():
    """Return browser secrets and database hashes; store only hashes server-side."""
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    return {'token': token, 'csrf': csrf,
            'token_hash': hashlib.sha256(token.encode()).hexdigest(),
            'csrf_hash': hashlib.sha256(csrf.encode()).hexdigest()}
