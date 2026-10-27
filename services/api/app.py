"""Google-only, owner-only API. Precomputed research reads; no trading actions."""
from contextlib import asynccontextmanager
import hashlib
import secrets
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictStr
from psycopg import Error as DatabaseError
from psycopg_pool import PoolTimeout
from .auth_policy import LoginRejected,new_session_material,require_login_csrf,verify_google_login
from .config import Settings
from .store import PostgresStore
from .history import install_history,HistoryStore

SESSION='__Host-pocket_session'
CSRF='__Host-pocket_csrf'
CHALLENGE='__Host-pocket_login'
LOGIN_CSRF='__Host-pocket_login_csrf'

def digest(value): return hashlib.sha256(value.encode()).hexdigest()


class BodyLimit:
    def __init__(self,app): self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']=='http' and scope['method'] in ('POST','PUT','PATCH'):
            parts=[];size=0
            while True:
                message=await receive()
                if message['type']=='http.disconnect':return
                size+=len(message.get('body',b''))
                if size>20480:
                    await JSONResponse({'detail':'Request too large'},status_code=413)(scope,receive,send)
                    return
                parts.append(message)
                if not message.get('more_body'):break
            async def buffered(): return parts.pop(0) if parts else {'type':'http.request','body':b'','more_body':False}
            await self.app(scope,buffered,send)
        else: await self.app(scope,receive,send)


class LoginBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    credential:StrictStr=Field(min_length=1,max_length=16384)
    nonce:StrictStr=Field(min_length=32,max_length=256)
    csrf_token:StrictStr=Field(min_length=32,max_length=256)


def create_app(settings=None,store=None,verifier=verify_google_login,history_store=None):
    settings=settings or Settings.from_env()
    owned=store is None
    store=store or PostgresStore(settings.database_url)
    @asynccontextmanager
    async def lifespan(app):
        if owned: store.open()
        try: yield
        finally:
            if owned:store.close()
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.add_middleware(BodyLimit)

    @app.middleware('http')
    async def boundary(request,call_next):
        if request.url.path not in ('/health/live','/health/ready'):
            supplied=request.headers.get('x-pocket-proxy','')
            if not secrets.compare_digest(supplied.encode(),settings.proxy_secret.encode()):
                return JSONResponse({'detail':'Request rejected'},status_code=403,headers={'Cache-Control':'no-store'})
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request,error):return JSONResponse({'detail':'Invalid request'},status_code=422)
    @app.exception_handler(LoginRejected)
    async def rejected(request,error):return JSONResponse({'detail':'Login rejected'},status_code=401)
    async def db_error(request,error):return JSONResponse({'detail':'Service temporarily unavailable'},status_code=503)
    app.add_exception_handler(DatabaseError,db_error)
    app.add_exception_handler(PoolTimeout,db_error)

    def limit(key,n):
        if not store.allow(key,n):raise HTTPException(429,'Try again later',headers={'Retry-After':'60'})
    def cookie(response,name,value,seconds,http_only=True):
        response.set_cookie(name,value,max_age=seconds,secure=True,httponly=http_only,samesite='strict',path='/')
    def csrf_check(request,body,cookie_name):
        try:require_login_csrf(cookie_token=request.cookies.get(cookie_name),body_token=body,
                               origin=request.headers.get('origin'),app_origin=settings.app_origin)
        except LoginRejected:raise HTTPException(403,'Request rejected') from None
    def current(request):
        token=request.cookies.get(SESSION,'')
        if not 32<=len(token)<=256:raise HTTPException(401,'Sign in required')
        row=store.current(digest(token))
        if row is None:raise HTTPException(401,'Sign in required')
        return token,row

    @app.get('/health/live')
    def live():return {'status':'ok'}
    @app.get('/health/ready')
    def ready():
        if not store.ready():raise HTTPException(503,'Not ready')
        return {'status':'ready'}

    @app.get('/auth/challenge')
    def challenge(request:Request):
        if request.headers.get('origin') not in (None,settings.app_origin) or request.headers.get('sec-fetch-site')=='cross-site':
            raise HTTPException(403,'Request rejected')
        limit('challenge',30)
        material=new_session_material();nonce=secrets.token_urlsafe(32)
        store.challenge(material['token_hash'],material['csrf_hash'],digest(nonce))
        response=JSONResponse({'client_id':settings.google_client_id,'nonce':nonce,'csrf_token':material['csrf'],'expires_in':300})
        cookie(response,CHALLENGE,material['token'],300)
        cookie(response,LOGIN_CSRF,material['csrf'],300)
        return response

    @app.post('/auth/google')
    def google(request:Request,body:LoginBody):
        csrf_check(request,body.csrf_token,LOGIN_CSRF)
        limit('login',10)
        token=request.cookies.get(CHALLENGE,'')
        if not 32<=len(token)<=256 or not store.consume(digest(token),digest(body.csrf_token),digest(body.nonce)):
            raise HTTPException(401,'Login challenge expired or already used')
        identity=verifier(credential=body.credential,client_id=settings.google_client_id,expected_nonce=body.nonce)
        material=new_session_material()
        previous=request.cookies.get(SESSION,'')
        store.session(identity,material,settings,digest(previous) if previous else None)
        response=JSONResponse({'authenticated':True,'email':identity.email})
        cookie(response,SESSION,material['token'],settings.session_seconds)
        cookie(response,CSRF,material['csrf'],settings.session_seconds,http_only=False)
        for name in (CHALLENGE,LOGIN_CSRF):response.delete_cookie(name,path='/',secure=True,httponly=True,samesite='strict')
        return response

    @app.get('/auth/me')
    def me(request:Request):
        token,row=current(request)
        return {'authenticated':True,'email':row['display_email']}

    @app.post('/auth/logout',status_code=204)
    def logout(request:Request):
        token,row=current(request)
        csrf=request.headers.get('x-csrf-token','')
        csrf_check(request,csrf,CSRF)
        if not secrets.compare_digest(digest(csrf),row['csrf_hash']):raise HTTPException(403,'Request rejected')
        store.revoke(digest(token))
        response=Response(status_code=204)
        response.delete_cookie(SESSION,path='/',secure=True,httponly=True,samesite='strict')
        response.delete_cookie(CSRF,path='/',secure=True,samesite='strict')
        return response
    install_history(app,current,settings,history_store or HistoryStore(getattr(store,'pool',None)))
    return app
