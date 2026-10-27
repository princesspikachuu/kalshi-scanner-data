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
        for database in environment.get('databases',[]):
            assert database['ipAllowList']==[],'Database must not permit public connections'
print('Blueprint schema and staging guard checks passed; nothing was provisioned')
