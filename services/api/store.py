"""PostgreSQL auth state; no production in-memory fallback."""
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from .auth_policy import LoginRejected, require_owner


class PostgresStore:
    def __init__(self,url,*,require_runtime_db=False):
        self._url=url
        self._require_runtime_db=require_runtime_db
        self.pool=ConnectionPool(url,min_size=1,max_size=5,open=False,timeout=5,
                                 kwargs={'row_factory':dict_row,'connect_timeout':5,
                                         'options':'-c statement_timeout=5000'})

    def open(self):
        if self._require_runtime_db:
            from .db_privileges import audit_database
            try:
                ready=audit_database(self._url,'api')['privilege_boundary_ready']
            except Exception:
                raise RuntimeError('API runtime database permission check failed') from None
            if not ready:
                raise RuntimeError('API runtime database privileges are not isolated')
        self.pool.open(wait=True,timeout=5)
    def close(self): self.pool.close()

    def ready(self):
        with self.pool.connection() as c:
            return c.execute("SELECT to_regclass('owner_session') IS NOT NULL AND to_regclass('login_challenge') IS NOT NULL AS ready").fetchone()['ready']

    def allow(self,key,limit):
        with self.pool.connection() as c:
            r=c.execute("""INSERT INTO login_rate (key,window_start,hits) VALUES (%s,date_trunc('minute',now()),1)
                ON CONFLICT(key) DO UPDATE SET window_start=EXCLUDED.window_start,
                hits=CASE WHEN login_rate.window_start=EXCLUDED.window_start THEN login_rate.hits+1 ELSE 1 END
                RETURNING hits""",(key,)).fetchone()
            return r['hits']<=limit

    def challenge(self,token_hash,csrf_hash,nonce_hash):
        with self.pool.connection() as c:
            c.execute('DELETE FROM login_challenge WHERE expires_at<=now()')
            c.execute("INSERT INTO login_challenge(token_hash,csrf_hash,nonce_hash,expires_at) VALUES (%s,%s,%s,now()+interval '5 minutes')",(token_hash,csrf_hash,nonce_hash))

    def consume(self,token_hash,csrf_hash,nonce_hash):
        with self.pool.connection() as c:
            return c.execute('DELETE FROM login_challenge WHERE token_hash=%s AND csrf_hash=%s AND nonce_hash=%s AND expires_at>now() RETURNING token_hash',
                             (token_hash,csrf_hash,nonce_hash)).fetchone() is not None

    def session(self,identity,material,settings,previous_hash=None):
        with self.pool.connection() as c:
            c.execute('SELECT pg_advisory_xact_lock(723741901)')
            owner=c.execute('SELECT google_subject FROM owner_account WHERE id=1 FOR UPDATE').fetchone()
            if owner is None:
                match=(identity.subject==settings.owner_subject) if settings.owner_subject else (
                    identity.email_authoritative and identity.email.casefold()==settings.owner_email.casefold())
                if not match: raise LoginRejected('Login rejected')
                c.execute('INSERT INTO owner_account(id,google_subject,display_email) VALUES(1,%s,%s)',(identity.subject,identity.email))
            else:
                require_owner(identity,owner['google_subject'])
                c.execute('UPDATE owner_account SET display_email=%s WHERE id=1',(identity.email,))
            if previous_hash:
                c.execute('UPDATE owner_session SET revoked_at=now() WHERE token_hash=%s',(previous_hash,))
            c.execute("INSERT INTO owner_session(token_hash,csrf_hash,owner_id,expires_at) VALUES(%s,%s,1,now()+%s*interval '1 second')",
                      (material['token_hash'],material['csrf_hash'],settings.session_seconds))

    def current(self,token_hash):
        with self.pool.connection() as c:
            return c.execute('''SELECT s.csrf_hash,a.display_email FROM owner_session s JOIN owner_account a ON a.id=s.owner_id
                WHERE s.token_hash=%s AND s.revoked_at IS NULL AND s.expires_at>now()''',(token_hash,)).fetchone()

    def revoke(self,token_hash):
        with self.pool.connection() as c:
            c.execute('UPDATE owner_session SET revoked_at=now() WHERE token_hash=%s AND revoked_at IS NULL',(token_hash,))
