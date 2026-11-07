"""Explicit configuration; sensitive values stay out of repr and errors."""
from dataclasses import dataclass, field
import os
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    app_origin: str
    google_client_id: str
    database_url: str = field(repr=False)
    proxy_secret: str = field(repr=False)
    owner_email: str = ''
    owner_subject: str = ''
    session_seconds: int = 43200
    require_runtime_db: bool = False

    def __post_init__(self):
        if type(self.require_runtime_db) is not bool:
            raise ValueError('Invalid runtime database requirement')
        u=urlsplit(self.app_origin)
        if u.scheme!='https' or not u.netloc or u.username or u.password or u.path or u.query or u.fragment:
            raise ValueError('APP_ORIGIN must be an HTTPS origin without a path')
        if not self.google_client_id or not self.database_url or len(self.proxy_secret)<32:
            raise ValueError('API configuration is incomplete')
        if not (self.owner_email or self.owner_subject):
            raise ValueError('Configure an explicit owner identity')
        if not 300<=self.session_seconds<=43200:
            raise ValueError('Session lifetime must be between 5 minutes and 12 hours')

    @classmethod
    def from_env(cls):
        require=os.environ.get('REQUIRE_API_RUNTIME_DB','false')
        if require not in ('true','false'):
            raise ValueError('REQUIRE_API_RUNTIME_DB must be true or false')
        return cls(app_origin=os.environ.get('APP_ORIGIN',''), google_client_id=os.environ.get('GOOGLE_CLIENT_ID',''),
                   database_url=os.environ.get('DATABASE_URL',''), proxy_secret=os.environ.get('API_PROXY_SECRET',''),
                   owner_email=os.environ.get('OWNER_GOOGLE_EMAIL','').strip().casefold(),
                   owner_subject=os.environ.get('OWNER_GOOGLE_SUB','').strip(),require_runtime_db=require=='true')
