"""Bounded discovery transport; a large event must not stall a saved cursor."""
import asyncio,json,math

CATALOG_CATEGORIES=('Politics','Economics','Financials','Sports','Entertainment','Social')

def catalog_queries(s):
    failed='Sports' in s.get('series_query_at',{}) and 'Sports' not in s.get('series_catalogs',{})
    return (*CATALOG_CATEGORIES,*(('Sports:Football',) if failed else ()))

async def read(host,state,path,params):
    state['reads']=state.get('reads',0)+1
    return await asyncio.to_thread(host.verified_data.call,'GET',path,params)

async def catalog(host,s,now,classify,groups):
    queries=s.setdefault('series_query_at',{})
    query=next((q for q in catalog_queries(s) if now>=queries.get(q,0)),None)
    if query is None:return
    queries[query]=now+3600
    # One query per pass, at most seven catalogue reads per hour. Avoid the
    # multi-megabyte full catalogue; failures in one category cannot block others.
    try:
        params=dict(include_volume='true',category=query.split(':')[0])
        if query=='Sports:Football':params['tags']='Football'
        response=await read(host,s,'/series',params)
        rows=[]
        for row in response.get('series',[]):
            group=classify(dict(row,series_ticker=row.get('ticker') or ''))
            if not group or not row.get('ticker'):continue
            try:volume=float(row.get('volume_fp') or row.get('volume') or 0)
            except (TypeError,ValueError):continue
            if math.isfinite(volume) and volume>0:rows.append(dict(group=group,ticker=row['ticker'],volume=volume))
        s.setdefault('series_catalogs',{})[query]=sorted(rows,key=lambda r:-r['volume'])[:12]
        combined={key:{} for key in groups}
        for items in s['series_catalogs'].values():
            for r in items:combined[r['group']][r['ticker']]=r['volume']
        ranked={key:sorted(rows,key=lambda t:-rows[t])[:12] for key,rows in combined.items()}
        s['series_pool']=[ranked[key][i] for i in range(12) for key in groups if i<len(ranked[key])]
        s['series_cursors']={t:c for t,c in s.get('series_cursors',{}).items() if t in s['series_pool']}
        s['series_status']='category volume priors; current trades verified separately'
    except Exception as exc:
        s['series_status']='catalogue '+query+' unavailable: '+str(getattr(exc,'code',type(exc).__name__))
    s['series_at']=min(queries.get(q,0) for q in catalog_queries(s))

def finish(s,result,selected):
    if selected:
        s.setdefault('series_cursors',{})[selected]=result.get('cursor','')
        s['series_index']=s.get('series_index',0)+1
    else:s['cursor']=result.get('cursor','')
    s['pages']=s.get('pages',0)+1;s['discovery_source']=selected or 'broad_events'

async def split_page(host,s):
    pending=s['split_event'];params=dict(event_ticker=pending['event']['event_ticker'],status='open',limit=pending.get('limit',50),cursor=pending.get('cursor',''))
    try:result=await read(host,s,'/markets',params)
    except Exception as exc:
        if getattr(exc,'code',None)!='paper_data_capacity' or params['limit']<=1:raise
        pending['limit']=max(1,params['limit']//2)
        return dict(events=[],milestones=[])
    page=dict(events=[dict(pending['event'],markets=result.get('markets',[]))],milestones=pending['milestones'])
    pending['cursor']=result.get('cursor','')
    if not pending['cursor']:
        finish(s,dict(cursor=pending['next_cursor']),pending['selected']);s.pop('split_event')
        s['event_page_limit']=50  # A single huge event must not slow every later page.
    s['discovery_source']=(pending['selected'] or 'broad_events')+':market_page'
    return page

async def event_page(host,s,now,minimum,classify,groups):
    if s.get('split_event'):return await split_page(host,s)
    pages=s.get('pages',0)
    if s.get('series_status')=='unavailable; broad event pagination retained':
        s['series_at']=0;s['series_status']='retrying category catalogues'
    football_due='Sports:Football' in catalog_queries(s) and now>=s.get('series_query_at',{}).get('Sports:Football',0)
    if pages and (now>=s.get('series_at',0) or football_due):await catalog(host,s,now,classify,groups)
    pool=s.get('series_pool',[]);selected=None
    params=dict(status='open',limit=s.get('event_page_limit',50),with_nested_markets='true',with_milestones='true',min_close_ts=int(now+minimum))
    if pool and pages%4:
        selected=pool[s.get('series_index',0)%len(pool)]
        params.update(series_ticker=selected,cursor=s.get('series_cursors',{}).get(selected,''))
    else:params['cursor']=s['cursor']
    try:result=await read(host,s,'/events',params)
    except Exception as exc:
        if getattr(exc,'code',None)!='paper_data_capacity':raise
        if params['limit']>1:
            s['event_page_limit']=max(1,params['limit']//2)
            print(json.dumps(dict(event='market_maker_page_resize',next_limit=s['event_page_limit'],cursor_preserved=True,real_orders_enabled=False)),flush=True)
            return dict(events=[],milestones=[])
        # Even one event can contain thousands of markets. Read its header,
        # then page its markets independently without skipping the event.
        headers=await read(host,s,'/events',dict(params,with_nested_markets='false'))
        if not headers.get('events'):
            finish(s,headers,selected);return headers
        event=headers['events'][0]
        metadata={k:event[k] for k in ('event_ticker','series_ticker','category','title') if k in event}
        milestones=[{k:m[k] for k in ('start_date','related_event_tickers','primary_event_tickers') if k in m}
            for m in headers.get('milestones',[]) if event['event_ticker'] in m.get('related_event_tickers',[])+m.get('primary_event_tickers',[])][:20]
        s['split_event']=dict(event=metadata,milestones=milestones,next_cursor=headers.get('cursor',''),selected=selected,cursor='',limit=50)
        return await split_page(host,s)
    finish(s,result,selected)
    return result
