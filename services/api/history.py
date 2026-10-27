"""Owner-only, versioned read contract for immutable precomputed research."""
import base64
from datetime import date,datetime
import hmac
import json
import re
from typing import Annotated,Literal

from fastapi import HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field,ValidationError,model_validator
from services.research.history import HistoryStore

ID=Annotated[str,Field(pattern=r'^[1-9][0-9]{0,18}$')]
Hash=Annotated[str,Field(pattern=r'^[a-f0-9]{64}$')]
Day=Annotated[str,Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
Count=Annotated[int,Field(strict=True,ge=0)]
Number=Annotated[float,Field(strict=True,allow_inf_nan=False)]
Asset=Literal['btc','eth','crypto','weather','sports','weather_daily']
View=Literal['historical','latest']
CONTRACT='research-history-v1'


class Closed(BaseModel):
    model_config=ConfigDict(extra='forbid')


class Totals(Closed):
    candidate_count:Count|None
    observation_count:Count
    first_date:Day|None
    last_date:Day|None
    @model_validator(mode='after')
    def dates(self):
        for day in (self.first_date,self.last_date):
            if day is not None:date.fromisoformat(day)
        if (self.first_date is None)!=(self.last_date is None) or (self.first_date and self.first_date>self.last_date):
            raise ValueError('Invalid dates')
        return self


class Metadata(Closed):
    id:ID
    fingerprint:Hash
    published_at:datetime


class Result(Metadata):
    model_version:Literal['research-return-conditional-v1']
    asset:Asset
    latest_membership_known:bool=Field(strict=True)
    dataset_count:Annotated[int,Field(strict=True,ge=1,le=3661)]
    historical:Totals
    latest:Totals
    @model_validator(mode='after')
    def unknown_latest(self):
        if not self.latest_membership_known and (self.latest.candidate_count is not None or self.latest.observation_count or self.latest.first_date is not None):
            raise ValueError('Unknown latest contains invented cohort')
        return self


class ScopeStates(Closed):
    complete:Count
    empty:Count
    unavailable:Count


class Coverage(Closed):
    version:Literal['evidence-coverage-v1']
    candidate_count:Count
    candle_records:Count
    trade_records:Count
    candidates_with_candles:Count
    candidates_without_candles:Count
    candidates_with_trades:Count
    candidates_without_trades:Count
    scope_states:ScopeStates
    resources:list[Literal['candles','trades']]=Field(max_length=2)
    raw_rows_scanned:Count


class Dataset(Metadata):
    day:Day
    version:Literal['evidence-coverage-v1']
    summary:Coverage


class Member(Closed):
    id:ID
    fingerprint:Hash
    day:Day
    is_latest:bool=Field(strict=True)
    summary:Coverage|None=None


class SourceWindow(Closed):
    id:ID
    dataset_id:ID
    start_at:datetime
    end_at:datetime
    @model_validator(mode='after')
    def valid_range(self):
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None or self.start_at>=self.end_at:raise ValueError('Invalid coverage interval')
        return self


class Hold(Closed):
    asset:Asset
    minutes_before_close:Annotated[int,Field(strict=True,ge=1,le=1440)]
    price_band_cents:Literal['50-60','60-70','70-80','80-90','90-100']
    sampled_markets:Annotated[int,Field(strict=True,ge=1)]
    wins:Count
    win_rate_percent:Number
    average_purchase_price_cents:Number
    average_profit_loss_cents_per_contract:Number
    hypothetical_roi_percent:Number
    sampled_days:Count


class Loss(Hold):
    threshold_cents:Annotated[int,Field(strict=True,ge=0,le=100)]|None
    trade_not_recommended:bool=Field(strict=True)
    exit_coverage:Count
    early_exits:Count
    improvement_cents:Number
    hold_net_cents:Number
    sell_label:str=Field(max_length=40)


class Cell(Closed):
    hold:Hold
    loss_prevention:Loss
    @model_validator(mode='after')
    def full_cohort(self):
        h,p=self.hold,self.loss_prevention
        for key in ('asset','minutes_before_close','price_band_cents','sampled_markets','sampled_days','average_purchase_price_cents'):
            if getattr(h,key)!=getattr(p,key):raise ValueError('Cohort mismatch')
        if h.wins>h.sampled_markets or p.wins>h.wins or p.exit_coverage>h.sampled_markets or p.early_exits>p.exit_coverage:
            raise ValueError('Invalid counts')
        rejected=2*h.wins<h.sampled_markets
        label='Trade not recommended' if rejected else 'Sell: —' if p.threshold_cents is None else f'Sell ≤ {p.threshold_cents}¢'
        if p.trade_not_recommended!=rejected or p.sell_label!=label:raise ValueError('Invalid loss label')
        return self


class Detail(Metadata):
    model_version:Literal['research-return-conditional-v1']
    asset:Asset
    latest_membership_known:bool=Field(strict=True)
    source_commit:Annotated[str,Field(pattern=r'^[a-f0-9]{40}$')]
    entry_minutes:list[Annotated[int,Field(strict=True,ge=1,le=1440)]]=Field(max_length=9)
    price_bands:list[Literal['50-60','60-70','70-80','80-90','90-100']]=Field(max_length=5)
    execution_included:Literal[False]
    baseline_fees_cents:Literal[0]
    exit_cost_stress_cents:Literal[2]
    selection_version:Literal['category-window-selection-v1']|None=None
    selection_revision:ID|None=None
    dataset_count:Annotated[int,Field(strict=True,ge=1,le=3661)]|None=None
    summary:Totals
    cells:list[Cell]=Field(max_length=45)
    @model_validator(mode='after')
    def dimensions(self):
        keys=[(c.hold.minutes_before_close,c.hold.price_band_cents) for c in self.cells]
        if len(set(keys))!=len(keys) or any(c.hold.asset!=self.asset or c.hold.minutes_before_close not in self.entry_minutes or c.hold.price_band_cents not in self.price_bands for c in self.cells):
            raise ValueError('Invalid table dimensions')
        if sum(c.hold.sampled_markets for c in self.cells)!=self.summary.observation_count:
            raise ValueError('Invalid observation denominator')
        return self


class Cursors:
    """Opaque, query-bound keysets; reuse existing server-only proxy key, domain separated."""
    def __init__(self,key):self.key=key.encode()
    def encode(self,scope,before):
        payload=json.dumps([1,scope,before],separators=(',',':')).encode()
        tag=hmac.digest(self.key,b'pocket-history\0'+payload,'sha256')
        return base64.urlsafe_b64encode(payload+tag).rstrip(b'=').decode()
    def decode(self,token,scope):
        try:
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,1024}',token):raise ValueError()
            raw=base64.b64decode(token+'='*(-len(token)%4),altchars=b'-_',validate=True)
            payload,tag=raw[:-32],raw[-32:]
            if not hmac.compare_digest(tag,hmac.digest(self.key,b'pocket-history\0'+payload,'sha256')):raise ValueError()
            version,bound,before=json.loads(payload)
            if version!=1 or bound!=scope or type(before) is not int or not 1<=before<=9223372036854775807:raise ValueError()
            return before
        except (ValueError,TypeError,UnicodeError):raise HTTPException(422,'Invalid cursor') from None


def install_history(app,auth,settings,store):
    cursors=Cursors(settings.proxy_secret)
    def query(request,kind,identifier=None):
        auth(request)
        pairs=list(request.query_params.multi_items())
        allowed={'stream','cursor','limit'} if kind!='detail' else {'stream','view'}
        if any(k not in allowed for k,v in pairs) or len(dict(pairs))!=len(pairs):raise HTTPException(422,'Invalid request')
        q=dict(pairs);stream=q.get('stream','')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',stream):raise HTTPException(422,'Invalid stream')
        if identifier is not None and (not re.fullmatch(r'[1-9][0-9]{0,18}',identifier) or int(identifier)>9223372036854775807):raise HTTPException(422,'Invalid result')
        if kind=='detail':
            if q.get('view') not in ('historical','latest'):raise HTTPException(422,'Explicit view required')
            return stream,q['view']
        scope=[kind,stream,identifier]
        limit=q.get('limit','25')
        if not re.fullmatch(r'[1-9][0-9]?',limit) or int(limit)>50:raise HTTPException(422,'Invalid limit')
        before=cursors.decode(q['cursor'],scope) if 'cursor' in q else None
        return stream,scope,before,int(limit)

    def validated(model,row):
        try:return model.model_validate(row).model_dump(mode='json')
        except ValidationError:raise HTTPException(503,'Stored research version unavailable') from None

    def page(rows,model,scope,limit):
        items=[validated(model,r) for r in rows[:limit]]
        cursor=cursors.encode(scope,int(items[-1]['id'])) if len(rows)>limit else None
        return dict(contract=CONTRACT,items=items,next_cursor=cursor)

    @app.get('/research/datasets')
    def datasets(request:Request):
        stream,scope,before,limit=query(request,'datasets')
        return page(store.datasets(stream,before=before,limit=limit+1),Dataset,scope,limit)

    @app.get('/research/results')
    def results(request:Request):
        stream,scope,before,limit=query(request,'results')
        return page(store.results(stream,before=before,limit=limit+1),Result,scope,limit)

    @app.get('/research/results/{identifier}')
    def result(identifier:str,request:Request):
        stream,view=query(request,'detail',identifier)
        row=store.result(stream,int(identifier),view=view)
        if row is None:raise HTTPException(404,'Research result not found')
        item=validated(Detail,row)
        if view=='latest' and not item['latest_membership_known'] and (item['cells'] or item['summary']['candidate_count'] is not None):
            raise HTTPException(503,'Stored research version unavailable')
        return dict(contract=CONTRACT,view=view,result=item)

    @app.get('/research/results/{identifier}/datasets')
    def members(identifier:str,request:Request):
        stream,scope,before,limit=query(request,'members',identifier)
        rows=store.members(stream,int(identifier),before=before,limit=limit+1)
        if rows is None:raise HTTPException(404,'Research result not found')
        return page(rows,Member,scope,limit)


    @app.get('/research/results/{identifier}/coverage')
    def windows(identifier:str,request:Request):
        stream,scope,before,limit=query(request,'windows',identifier)
        rows=store.windows(stream,int(identifier),before=before,limit=limit+1)
        if rows is None:raise HTTPException(404,'Research result not found')
        return page(rows,SourceWindow,scope,limit)
