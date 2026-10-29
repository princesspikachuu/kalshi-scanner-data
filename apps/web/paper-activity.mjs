export function replayState(run){
 const a=run.activity;
 if(run.status==='queued')return 'Queued · waiting for the processing worker';
 if(run.status==='running'&&!run.lease_active)return 'Interrupted · waiting for the worker to retry';
 if(run.status==='running')return a?.phase||'Starting replay';
 return ({succeeded:'Finished',failed:'Failed · choose fewer days and retry',cancelled:'Canceled'})[run.status]||run.status;
}
export function orderLine(event){
 const price=event.bid_cents??event.sale_cents;
 return `${event.order_id??'position'} · ${event.ticker} · ${event.side?.toUpperCase()??''} · ${event.kind.replaceAll('_',' ')} · ${event.contracts} contracts${price!==undefined?' @ '+price+'¢':''}${event.remaining!==undefined?' · '+event.remaining+' unfilled':''}${event.reason?' · '+event.reason.replaceAll('_',' '):''}`;
}
export function appendActivity(card,run,doc){
 const make=(tag,text)=>{const el=doc.createElement(tag);el.textContent=text;return el},a=run.activity;
 card.append(make('p',`Replay ${run.id} · ${replayState(run)}`));
 if(run.created_at)card.append(make('p',`Created ${new Date(run.created_at).toLocaleString()} · ${run.dataset_ids?.length??1} saved dataset(s)`));
 if(run.strategy_names?.length)card.append(make('p','Strategies: '+run.strategy_names.join(', ')));
 if(a?.updated_at)card.append(make('p',`Worker update: ${new Date(a.updated_at).toLocaleString()} · ${a.provider_reads??0} Kalshi reads for this replay`));
 if(a?.simulated_time)card.append(make('p',`Simulated market time: ${new Date(a.simulated_time*1000).toLocaleString()}${a.current_market?' · '+a.current_market:''}`));
 else if(a?.dataset_id)card.append(make('p',`Reading saved dataset ${a.dataset_id}${a.current_market?' · '+a.current_market:''} · ${a.records_loaded??0} records loaded`));
 if(a?.open_orders?.length){card.append(make('h3','Open simulated orders'));
  for(const order of a.open_orders){card.append(make('p',`${order.order_id} · ${order.ticker} · ${order.side.toUpperCase()} · bid ${order.bid_cents}¢ · ${order.remaining}/${order.contracts} contracts unfilled · expires ${new Date(order.expires*1000).toLocaleString()}`));}}
 const events=run.result?.recent_activity||a?.recent_activity||run.result?.order_preview||[];
 if(events.length){const details=doc.createElement('details');details.open=run.status==='running';details.append(make('summary','Recent simulated order activity'));
  for(const event of [...events].reverse())details.append(make('p',`${new Date(event.time*1000).toLocaleString()} · ${orderLine(event)}`));card.append(details);}
 else card.append(make('p',run.status==='queued'?'No order has been simulated yet.':run.status==='running'?'Worker is preparing saved evidence; no bid activity recorded yet.':'No simulated orders were recorded. Check the saved data, ask-price range, and entry window.'));
}
