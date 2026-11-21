"""Credential-free staging smoke checks; never logs response bodies or cookie values."""
import urllib.error
import urllib.request

GATEWAY = 'https://pocket-analytics-staging.ezrealrose831.workers.dev'
API = 'https://pocket-api-staging.onrender.com'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def check(label, url, expected, *, content_type=None, security=False):
    opener = urllib.request.build_opener(NoRedirect)
    try:
        response = opener.open(urllib.request.Request(url), timeout=30)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        if response.status not in expected:
            raise SystemExit(f'{label}: unexpected HTTP status {response.status}; expected {sorted(expected)}')
        if content_type and response.headers.get_content_type() != content_type:
            raise SystemExit(f'{label}: unexpected response content type')
        if response.headers.get('Cache-Control') != 'no-store':
            raise SystemExit(f'{label}: missing no-store boundary')
        if security:
            if "frame-ancestors 'none'" not in response.headers.get('Content-Security-Policy', ''):
                raise SystemExit(f'{label}: missing frame protection')
        return response.status


if __name__ == '__main__':
    check('API readiness', API + '/health/ready', {200}, content_type='application/json')
    check('Direct API denial', API + '/auth/me', {403}, content_type='application/json')
    check('Staging sign-in assets', GATEWAY + '/', {200}, content_type='text/html', security=True)
    check('Blocked trading route', GATEWAY + '/api/orders', {404}, content_type='application/json')
    status = check('Unauthenticated staging session', GATEWAY + '/api/auth/me', {401, 503}, content_type='application/json')
    print('Readiness, direct API denial, staging assets and route boundaries passed')
    if status == 503:
        print('Login connection unavailable; check the private proxy-secret binding and backend readiness')
    else:
        print('Unauthenticated gateway request requires sign-in; real Google acceptance remains pending')
