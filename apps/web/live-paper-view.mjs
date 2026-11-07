export function accountSummary(session,now=Date.now()/1000){
 const s=session.state||{},orders=s.orders||[],positions=s.positions||[];
 const reserved=orders.reduce((n,o)=>n+o.remaining*o.bid,0),cost=positions.reduce((n,p)=>n+p.cost,0);
 const heartbeat=s.worker_updated_at??s.updated_at;
 const age=heartbeat==null?null:Math.max(0,now-heartbeat);
 return {reserved,cost,stale:age==null||age>15,age,
  label:session.status==='succeeded'?'Stopped · positions settled':s.stopping?'Stopping · monitoring filled positions':session.status==='queued'?'Queued for live feed':s.feed||'Waiting for feed'};
}
