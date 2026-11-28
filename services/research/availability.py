"""Conservative not-before bounds from reviewed official initial-listing filings.

These are exclusion proofs, not promises of data availability after the bound.
Unknown series ALWAYS retain their original inventory requests. No network on import.
"""
from dataclasses import dataclass,asdict
from datetime import datetime,timezone

@dataclass(frozen=True)
class StartBound:
    series:str
    not_before:str
    certification_url:str
    certification_sha256:str
    version:str='certified-not-before-v1'

_BASE='https://assets.kalshi.com/regulatory/product-certifications/'
_FILINGS={
 'LOCALTEMPERATURE':('2026-03-05','ace91260ee4cb1952df495e79f64ce7f8262d556edef5e508175802fad480117'),
 'NYCWINDEX':('2026-09-09','ce86fe7a3e3c8f1d1363e5e99238772bd1d4ead726e57fb4097441dc2cf64eb1'),
 'CHIMETROWINDEX':('2026-09-09','d64de13586308c90bed771ec1ddf494c13f51972fda5b92d83d9031a561d4afb'),
 'LAWINDEX':('2026-09-09','b160d8e38e6dc4ce15c837d990b69b96ca0f40ee0dd010b0f2b78c642038583d'),
 'MIAWINDEX':('2026-08-12','f9239740141bf38c95708fc7b954a1b44ecb40a517fe12ebe975597540eeb4b1')}
_SERIES={'KXTEMPNYCH':'LOCALTEMPERATURE','KXTEMPCHIH':'LOCALTEMPERATURE','KXTEMPDCH':'LOCALTEMPERATURE',
 'KXTEMPNYCHS':'NYCWINDEX','KXTEMPCHIHS':'CHIMETROWINDEX','KXTEMPLAXHS':'LAWINDEX','KXTEMPMIAH':'MIAWINDEX'}


def eligible_series(series,end):
    included=[];excluded=[]
    if end.tzinfo is None:raise ValueError('Timezone-aware coverage end required')
    for ticker in sorted(set(series)):
        filing=_SERIES.get(ticker)
        if filing:
            day,checksum=_FILINGS[filing];boundary=datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
            # Initial listing is AFTER close of business; midnight UTC is safely
            # earlier. Never infer the first actually available market or quote.
            if end<=boundary:
                excluded.append(StartBound(ticker,day+'T00:00:00Z',_BASE+filing+'.pdf',checksum));continue
        included.append(ticker)
    return included,tuple(excluded)
