import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const workflow=fs.readFileSync(new URL('../.github/workflows/deploy-money-tree-staging.yml',import.meta.url),'utf8');
const config=JSON.parse(fs.readFileSync(new URL('../infra/wrangler.staging.json',import.meta.url),'utf8'));

test('post-deploy validation is restricted to the existing staging Worker',()=>{
 assert.equal(config.name,'pocket-analytics-staging');
 assert.equal(config.main,'../apps/gateway/index.mjs');
 assert.equal(config.assets.directory,'../apps/web');
 assert.equal(config.keep_vars,true);
 assert.equal(config.vars.APP_ORIGIN,'https://pocket-analytics-staging.ezrealrose831.workers.dev');
 assert.match(workflow,/npx --yes wrangler@4 deploy --config infra\/wrangler\.staging\.json/);
 assert.match(workflow,/Verify exact staging target/);
 assert.match(workflow,/config\.vars\?\.APP_ORIGIN/);
 assert.doesNotMatch(workflow,/wrangler\.production|--env production|deploy --config infra\/wrangler\.production/);
});
test('published frontend files are checked against the exact source revision',()=>{
 assert.match(workflow,/Verify deployed staging assets match this commit/);
 for(const path of ['shadow.html','shadow.mjs','shadow-view.mjs','money.css']){
  assert.match(workflow,new RegExp(path.replaceAll('.','\\.')));
 }
 assert.match(workflow,/cmp --silent "apps\/web\/\$file" "\$remote"/);
 assert.match(workflow,/\?commit=\$GITHUB_SHA&attempt=\$attempt/);
 assert.match(workflow,/--connect-timeout 8 --max-time 20/);
 assert.match(workflow,/Cloudflare staging asset verification failed/);
 assert.match(workflow,/exit 1/);
});
