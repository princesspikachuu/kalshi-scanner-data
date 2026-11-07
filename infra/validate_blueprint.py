"""Read-only validation against Render's current public JSON Schema."""
from pathlib import Path
import json
import jsonschema
import requests
import yaml

ROOT=Path(__file__).resolve().parents[1]
response=requests.get('https://render.com/schema/render.yaml.json',timeout=20)
response.raise_for_status()
schema=response.json()
blueprint=yaml.safe_load((ROOT/'infra/render.staging.yaml').read_text())
jsonschema.validate(blueprint,schema)
for project in blueprint['projects']:
    for environment in project['environments']:
        for service in environment.get('services',[]):
            assert service['autoDeployTrigger']=='off','Automatic deployments must remain disabled'
            config={v['key']:v for v in service['envVars'] if 'key' in v}
            profile='research' if service['type']=='worker' else 'api'
            assert config['DATABASE_URL']=={'key':'DATABASE_URL','sync':False},'Runtime URL must be a private independent credential'
            assert config['RUNTIME_DB_PROFILE']['value']==profile
            assert service['preDeployCommand']=='python -m services.api.manage verify-runtime --profile '+profile
            if profile=='api':assert config['REQUIRE_API_RUNTIME_DB']['value']=='true'

        workers=[s for s in environment.get('services',[]) if s['type']=='worker']
        assert len(workers)==1,'Staging requires exactly one research worker'
        worker=workers[0]
        variables={v['key']:v for v in worker['envVars'] if 'key' in v}
        assert variables['COLLECTION_ENABLED']['value']=='true','Owner-authorized collection must remain enabled'
        assert {'fromGroup':'pocket-r2-staging'} in worker['envVars'],'Worker must use the private R2 group'
        for service in environment.get('services',[]):
            if service['type']!='worker':
                assert not any('fromGroup' in v for v in service['envVars']),'R2 credentials belong only on the worker'
        for database in environment.get('databases',[]):
            assert database['ipAllowList']==[],'Database must not permit public connections'
print('Blueprint schema and staging guard checks passed; nothing was provisioned')

processor=yaml.safe_load((ROOT/'infra/render.processor.yaml').read_text())
jsonschema.validate(processor,schema)
assert len(processor['services'])==1
service=processor['services'][0]
assert service['type']=='worker' and service['name']=='pocket-processing-staging'
assert service['autoDeployTrigger']=='off' and service['plan']=='0.5c-512mb'
variables={v['key']:v for v in service['envVars'] if 'key' in v}
assert variables['WORKER_ROLE']['value']=='demo'
assert variables['DATABASE_URL']['fromService']=={'name':'pocket-research-staging','type':'worker','envVarKey':'DATABASE_URL'}
assert {'fromGroup':'pocket-r2-staging'} in service['envVars']
assert not {'KALSHI_API_KEY_ID','KALSHI_PRIVATE_KEY_PEM'} & variables.keys()
print('Additive processor worker schema and credential wiring passed; nothing was provisioned')
