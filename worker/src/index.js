/**
 * Pocket Analytics backend — deploy to Cloudflare Workers with the docs/ UI.
 *
 * Protected manual GitHub Actions dispatch and read-only latest workflow status.
 * Secrets GITHUB_ACTIONS_TOKEN / APP_ADMIN_KEY are only stored on Cloudflare.
 * Never put either secret in a browser bundle or public wrangler configuration.
 */
const REPO = "princesspikachuu/kalshi-scanner-data";
const WORKFLOW = "research-backtest.yml";
const API = "https://api.github.com/repos/" + REPO;
const MAX_BATCH_MARKETS = 900;
const DEFAULT_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff"
};
function respond(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), {status, headers:{...DEFAULT_HEADERS,...extra}});
}
function exactInteger(x, low, high) {
  return typeof x === "number" && Number.isInteger(x) && x >= low && x <= high;
}
function validSettings(p) {
  if (!p || typeof p !== "object" || Array.isArray(p)) return "Invalid collection settings.";
  if (!["weather","btc","eth"].includes(p.asset)) return "Select hourly weather, Bitcoin, or Ethereum.";
  if (!exactInteger(p.max_markets,1,300)) return "Markets per day must be 1–300.";
  if (!exactInteger(p.days_ago,1,30) || !exactInteger(p.days_to_collect,1,7) ||
      p.days_ago+p.days_to_collect-1>30) return "Choose 1–7 complete UTC days within the last 30 days.";
  if (p.max_markets*p.days_to_collect > MAX_BATCH_MARKETS)
    return "One run is limited to 900 sampled markets total. Reduce the sample or number of days.";
  return "";
}
function timingEqual(value, expected) {
  if (typeof value !== "string" || typeof expected !== "string" || !expected || value.length>256) return false;
  const a = new TextEncoder().encode(value), b = new TextEncoder().encode(expected);
  let difference = a.length ^ b.length;
  for(let i=0;i<Math.max(a.length,b.length);i++) difference |= (a[i]||0) ^ (b[i]||0);
  return difference===0;
}
function authorized(request, env) {
  const header = request.headers.get("authorization") || "";
  return header.startsWith("Bearer ") && timingEqual(header.slice(7), env.APP_ADMIN_KEY);
}
function validateOrigin(request) {
  const origin = request.headers.get("origin");
  return !origin || origin === new URL(request.url).origin;
}
async function github(path, env, method="GET", body) {
  const headers = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2026-03-10",
    "User-Agent": "Kalshi-Pocket-Analytics-Backend"
  };
  if (env.GITHUB_ACTIONS_TOKEN) headers.Authorization="Bearer "+env.GITHUB_ACTIONS_TOKEN;
  if(body) headers["Content-Type"]="application/json";
  const res = await fetch(API+path,{method,headers,body:body?JSON.stringify(body):undefined,
    redirect:"follow"});
  if (!res.ok) {
    const note=res.status===401||res.status===403 ? "The GitHub token cannot access Actions. Verify fine-grained Actions: write permission." :
     res.status===404 ? "GitHub workflow was not found for this repository." :
     res.status===429 ? "GitHub API rate limit reached." : "GitHub returned HTTP "+res.status+".";
    return {ok:false,status:res.status,message:note};
  }
  if (res.status===204) return {ok:true,payload:null};
  let payload=null;
  try{payload=await res.json()}catch(_e){}
  return {ok:true,payload};
}
async function routes(request,env,url) {
  if(url.pathname==="/api/health" && request.method==="GET"){
    return respond({backend:"online",enabled:Boolean(env.GITHUB_ACTIONS_TOKEN&&env.APP_ADMIN_KEY),require_auth:true,
      max_batch_markets:MAX_BATCH_MARKETS});
  }
  if(url.pathname==="/api/runs" && request.method==="GET"){
    // The historical repository is public; run metadata contains no secrets.
    const result=await github("/actions/workflows/"+WORKFLOW+"/runs?per_page=8&event=workflow_dispatch",env);
    if(!result.ok)return respond({error:result.message},502);
    const entries=Array.isArray(result.payload?.workflow_runs)?result.payload.workflow_runs:[];
    return respond({runs:entries.map(r=>({id:r.id,created_at:r.created_at,status:r.status,
      conclusion:r.conclusion,html_url:r.html_url,run_started_at:r.run_started_at,updated_at:r.updated_at}))
    },200,{"cache-control":"public, max-age=8"});
  }
  if(url.pathname==="/api/runs" && request.method==="POST"){
    if(!env.GITHUB_ACTIONS_TOKEN || !env.APP_ADMIN_KEY) return respond({error:"Server is not configured yet. Set the Worker secrets first."},503);
    if(!validateOrigin(request))return respond({error:"Cross-origin requests are not allowed."},403);
    if(!authorized(request,env))return respond({error:"Incorrect app access key."},401);
    const contentType=request.headers.get("content-type")||"";
    if(!contentType.toLowerCase().startsWith("application/json"))return respond({error:"Expected JSON settings."},415);
    if(Number(request.headers.get("content-length")||0)>2048)return respond({error:"Request too large."},413);
    let body;
    try{const input=await request.text();if(input.length>2048)return respond({error:"Request too large."},413);body=JSON.parse(input)}
    catch(_e){return respond({error:"Invalid JSON."},400)}
    const error=validSettings(body);
    if(error)return respond({error},400);
    // Avoid accidental repeat launches while the workflow is still queued or running.
    const recent=await github("/actions/workflows/"+WORKFLOW+"/runs?per_page=8&event=workflow_dispatch",env);
    if(!recent.ok)return respond({error:recent.message},502);
    const active=(recent.payload?.workflow_runs||[]).find(r=>r.status!=="completed");
    if(active)return respond({error:"A research collection is already queued or running.",existing_run:{
      id:active.id,html_url:active.html_url,status:active.status}},409);
    const result=await github("/actions/workflows/"+WORKFLOW+"/dispatches",env,"POST",{
      ref:"main",
      inputs:{asset:body.asset,days_ago:String(body.days_ago),
        days_to_collect:String(body.days_to_collect),max_markets:String(body.max_markets)},
      return_run_details:true
    });
    if(!result.ok)return respond({error:result.message},502);
    return respond({accepted:true,run_id:result.payload?.workflow_run_id||null,
      run_url:result.payload?.html_url||null,settings:body},202);
  }
  return respond({error:"Not found"},404);
}
export default {
  async fetch(request,env) {
    const url=new URL(request.url);
    if(url.pathname.startsWith("/api/")){
      try{return await routes(request,env,url)}
      catch(e){console.error("backend_error",String(e));return respond({error:"Unexpected server error."},500)}
    }
    // Static assets are served by Workers Assets binding on the same hostname.
    return env.ASSETS.fetch(request);
  }
};
