"""Versioned shared configuration for multi-square Kalshi Demo bots."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from services.research.reports import SERIES

class Square(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    asset:str
    min_price:int=Field(ge=1,le=99)
    max_price:int=Field(ge=1,le=99)
    min_minutes:int=Field(ge=0,le=1439)
    max_minutes:int=Field(ge=1,le=1440)
    report_id:int|None=Field(default=None,ge=1)
    expected_roi:float|None=None
    loss_cents:int|None=Field(default=None,ge=1,le=99)
    @model_validator(mode='after')
    def ranges(self):
        if self.asset not in SERIES or self.min_price>self.max_price or self.min_minutes>=self.max_minutes:raise ValueError('Invalid square')
        return self

class BotConfig(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    version:Literal[1]=1
    name:str=Field(min_length=1,max_length=80)
    squares:list[Square]=Field(min_length=1,max_length=45)
    qualification:Literal['bid','ask']='ask'
    price_reference:Literal['bid','ask']='ask'
    adjustment_cents:int=Field(default=-1,ge=-99,le=99)
    maximum_cents:int|None=Field(default=None,ge=1,le=99)
    minimum_cents:int|None=Field(default=None,ge=1,le=99)
    bid_percent:float=Field(default=1,gt=0,le=100)
    market_percent:float=Field(default=3,gt=0,le=100)
    bot_percent:float=Field(default=10,gt=0,le=100)
    loss_mode:Literal['off','manual','research']='off'
    loss_cents:int|None=Field(default=None,ge=1,le=99)
    daily_loss_percent:float|None=Field(default=None,gt=0,le=100)
    @model_validator(mode='after')
    def limits(self):
        if self.bid_percent>self.market_percent or self.market_percent>self.bot_percent:raise ValueError('Limits must increase from bid to market to bot')
        if self.minimum_cents is not None and self.maximum_cents is not None and self.minimum_cents>self.maximum_cents:raise ValueError('Minimum bid must not exceed maximum bid')
        if self.loss_mode=='manual' and self.loss_cents is None:raise ValueError('Enter an exit threshold')
        keys=[(s.asset,s.min_price,s.max_price,s.min_minutes,s.max_minutes) for s in self.squares]
        if len(set(keys))!=len(keys):raise ValueError('Duplicate squares')
        return self

class Controls(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:Literal['pause','resume','archive','restore']
    revision:int=Field(ge=1)

class Policy(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    archive_enabled:bool=True
    archive_days:int=Field(default=30,ge=7,le=3650)
    storage_warning_percent:int=Field(default=70,ge=20,le=95)
    storage_critical_percent:int=Field(default=85,ge=30,le=99)
    storage_limit_gb:int=Field(default=5,ge=1,le=16000)
    backup_hours:int=Field(default=24,ge=1,le=168)
    critical_email:bool=True
    @model_validator(mode='after')
    def levels(self):
        if self.storage_warning_percent>=self.storage_critical_percent:raise ValueError('Storage thresholds must increase')
        return self
