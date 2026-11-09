/**
 * Offline CPU benchmark for gateway response copying. No network, credentials,
 * actual customer data, Cloudflare usage or provider APIs.
 *
 * Run: node tools/benchmark_gateway_cpu.mjs
 * Results are local Node CPU, NOT production Cloudflare CPU or saved billing.
 */
import {performance} from 'node:perf_hooks';
import {proxyAuth} from '../apps/gateway/index.mjs';

const bytes=2*1024*1024;
const data=new Uint8Array(bytes).fill(64);
const env={APP_ORIGIN:'https://app.test',API_ORIGIN:'https://api.test',API_PROXY_SECRET:'s'.repeat(32)};
const url='https://app.test/api/demo/shadow/workspace';
function localMeasure(fn,iterations){
 const start=process.cpuUsage(),wall=performance.now();
 for(let i=0;i<iterations;i++)fn();
 const usage=process.cpuUsage(start);
 return {cpu_ms:Number(((usage.user+usage.system)/1000).toFixed(3)),
         wall_ms:Number((performance.now()-wall).toFixed(3)),operations:iterations};
}
let checksum=0;
for(let i=0;i<8;i++)checksum+=data[i];
const direct=localMeasure(()=>{checksum+=data[0]+data[data.length-1]},100);
const copied=localMeasure(()=>{const copy=data.slice();checksum+=copy[0]+copy[copy.length-1]},100);

async function measureStream(iterations){
 const start=process.cpuUsage(),wall=performance.now();
 let total=0;
 for(let i=0;i<iterations;i++){
  // Force the real streaming gateway path without exposing any private data.
  const payload=new Uint8Array(65536).fill(31);
  const body=new ReadableStream({start(c){
    for(let j=0;j<32;j++)c.enqueue(payload);
    c.close();
  }});
  const response=await proxyAuth(new Request(url),env,{fetcher:async()=>new Response(body,{
    headers:{'content-type':'application/json','x-pocket-workspace-contract':'demo-v1'}
  })});
  if(response.status!==200)throw Error('unexpected benchmark response '+response.status);
  const reader=response.body.getReader();
  while(true){const {done,value}=await reader.read();if(done)break;total+=value.byteLength}
 }
 const usage=process.cpuUsage(start);
 return {cpu_ms:Number(((usage.user+usage.system)/1000).toFixed(3)),
         wall_ms:Number((performance.now()-wall).toFixed(3)),operations:iterations,
         total_bytes:total};
}
const streamed=await measureStream(10);
if(streamed.total_bytes!==bytes*10)throw Error('unexpected byte count');
if(checksum<=0)throw Error('missing checksum');
console.log(JSON.stringify({
 benchmark:'mt017-gateway-cpu-synthetic-v1',runtime:'Node.js',per_payload_bytes:bytes,
 original_copy_operations:copied,raw_reference_operations:direct,real_gateway_stream:streamed,
 note:'Synthetic Node process CPU; cannot establish Cloudflare CPU quota, per-route p95 or production savings.'
},null,2));
