// Fail before invoking Wrangler if the staging destination or publication surface drifts.
import assert from 'node:assert/strict';
import fs from 'node:fs';
const config=JSON.parse(fs.readFileSync('infra/wrangler.staging.json','utf8'));
assert.equal(config.name,'pocket-analytics-staging');
assert.equal(config.main,'../apps/gateway/index.mjs');
assert.equal(config.workers_dev,true);
assert.equal(config.preview_urls,false);
assert.equal(config.keep_vars,true);
assert.deepEqual(config.assets,{directory:'../apps/web',binding:'ASSETS',run_worker_first:true});
assert.deepEqual(config.vars,{
 APP_ORIGIN:'https://pocket-analytics-staging.ezrealrose831.workers.dev',
 API_ORIGIN:'https://pocket-api-staging.onrender.com'
});
assert.deepEqual(Object.keys(config).sort(),['assets','compatibility_date','keep_vars','main','name','preview_urls','vars','workers_dev']);
const workflow=fs.readFileSync('.github/workflows/deploy-pocket-app.yml','utf8');
assert.match(workflow,/deploy:\n    if: github.ref == 'refs\/heads\/main'/);
assert.match(workflow,/staging:\n    if: github.ref == 'refs\/heads\/build\/google-auth-foundation'/);
assert.match(workflow,/wrangler@4\.153\.0 deploy --config infra\/wrangler\.staging\.json/);
assert.doesNotMatch(workflow.split('\n  staging:')[1],/secret put|GITHUB_ACTIONS_TOKEN|wrangler\.jsonc/);
console.log('Staging target, public origins, secret preservation and branch gates passed');
