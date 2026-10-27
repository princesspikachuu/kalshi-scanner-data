"""Owner-session + CSRF controls for undeployed long-running collection."""
from datetime import date,datetime
from typing import Literal
from uuid import UUID
from fastapi import HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field,StrictStr
from .history import Asset
from services.research.campaigns import CampaignStore
from services.research.queue import EvidenceConflict


class Closed(BaseModel):
    model_config=ConfigDict(extra='forbid')


class RangeBody(Closed):
    asset:Asset
    start_date:StrictStr=Field(min_length=10,max_length=10)
    end_date:StrictStr=Field(min_length=10,max_length=10)
    request_key:UUID
    refresh_existing:bool=Field(default=False,strict=True)


class RefreshBody(Closed):
    enabled:bool=Field(strict=True)


class Campaign(Closed):
    id:str
    asset:Asset
    mode:Literal['backfill','rolling']
    start_at:datetime
    end_at:datetime
    created_at:datetime
    status:Literal['queued','running','succeeded','cancelled','failed']
    result_id:str|None
    error_code:str|None=Field(max_length=64)
    total_sections:int=Field(ge=1,le=3661)
    completed_sections:int=Field(ge=0,le=3661)


class Section(Closed):
    day:date
    start_at:datetime
    end_at:datetime
    dataset_id:str|None
    stage:Literal['pending','inventory','evidence','collected']


class Refresh(Closed):
    asset:Asset
    enabled:bool
    next_due:datetime|None
    interval_seconds:Literal[3600]
    latest_campaign_id:str|None


def install_collection(app,auth,mutate,store):
    def summary(identifier):
        row=store.get(identifier)
        if row is None:raise HTTPException(404,'Collection not found')
        return Campaign.model_validate(row).model_dump(mode='json')
    def no_query(request):
        if request.query_params:raise HTTPException(422,'Invalid request')

    @app.post('/collection/campaigns')
    def create(body:RangeBody,request:Request):
        mutate(request);no_query(request)
        try:identifier=store.create(body.asset,body.start_date,body.end_date,str(body.request_key),refresh_existing=body.refresh_existing)
        except EvidenceConflict:raise HTTPException(409,'Request already belongs to another range') from None
        except ValueError:raise HTTPException(422,'Select a valid range of up to 3660 UTC days') from None
        return dict(contract='collection-v1',campaign=summary(identifier))

    @app.get('/collection/campaigns')
    def campaigns(request:Request):
        auth(request)
        pairs=list(request.query_params.multi_items());q=dict(pairs)
        if len(q)!=len(pairs) or set(q)-{'asset','before','limit'}:
            raise HTTPException(422,'Invalid collection page')
        try:
            asset=q.get('asset','')
            if asset not in ('btc','eth','crypto','weather','weather_daily','sports'):raise ValueError()
            before=str(UUID(q['before'])) if 'before' in q else None
            raw=q.get('limit','25')
            if not raw.isascii() or not raw.isdecimal() or not 1<=int(raw)<=50 or str(int(raw))!=raw:raise ValueError()
            limit=int(raw)
            rows=store.list(asset,before=before,limit=limit+1)
        except ValueError:raise HTTPException(422,'Invalid collection page') from None
        items=[Campaign.model_validate(row).model_dump(mode='json') for row in rows[:limit]]
        return dict(contract='collection-v1',items=items,
                    next_before=items[-1]['id'] if len(rows)>limit else None)

    @app.get('/collection/campaigns/{identifier}')
    def get(identifier:UUID,request:Request):
        auth(request)
        pairs=list(request.query_params.multi_items())
        if any(k!='after' for k,v in pairs) or len(pairs)>1:raise HTTPException(422,'Invalid request')
        after=request.query_params.get('after')
        try:
            if after is not None and date.fromisoformat(after).isoformat()!=after:raise ValueError()
            campaign=summary(identifier);rows=store.days(identifier,after=after,limit=51)
        except ValueError:raise HTTPException(422,'Invalid section page') from None
        return dict(contract='collection-v1',campaign=campaign,
            sections=[Section.model_validate(r).model_dump(mode='json') for r in rows[:50]],
            next_after=str(rows[49]['day']) if len(rows)>50 else None)

    @app.post('/collection/campaigns/{identifier}/{action}')
    def control(identifier:UUID,action:Literal['pause','resume'],request:Request):
        mutate(request);no_query(request)
        if not store.control(identifier,action):raise HTTPException(404,'Collection not found')
        return dict(contract='collection-v1',campaign=summary(identifier))

    @app.get('/collection/refresh/{asset}')
    def refresh(asset:Asset,request:Request):
        auth(request);no_query(request)
        return dict(contract='collection-v1',refresh=Refresh.model_validate(store.refresh(asset)).model_dump(mode='json'))

    @app.post('/collection/refresh/{asset}')
    def set_refresh(asset:Asset,body:RefreshBody,request:Request):
        mutate(request);no_query(request)
        return dict(contract='collection-v1',refresh=Refresh.model_validate(store.set_refresh(asset,body.enabled)).model_dump(mode='json'))
