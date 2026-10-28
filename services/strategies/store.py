"""Transactional draft-version storage; no activation or execution methods."""
from uuid import UUID,uuid4

from psycopg.types.json import Jsonb

from .definitions import validate,fingerprint


class VersionConflict(ValueError):pass


class DraftStore:
    def __init__(self,pool):self.pool=pool

    @staticmethod
    def _name(value):
        if type(value) is not str or not 1<=len(value)<=80 or value!=value.strip() or any(ord(c)<32 for c in value):
            raise ValueError('Invalid strategy name')
        return value

    def create(self,name,rules):
        name=self._name(name);canonical=validate(rules);identifier=uuid4();sha=fingerprint(canonical)
        with self.pool.connection() as c:
            c.execute('INSERT INTO strategy_draft(id,name,asset) VALUES(%s,%s,%s)',(identifier,name,canonical['asset']))
            c.execute('INSERT INTO strategy_version(strategy_id,revision,definition,fingerprint) VALUES(%s,1,%s,%s)',
                      (identifier,Jsonb(canonical),sha))
            c.execute('UPDATE strategy_draft SET current_revision=1 WHERE id=%s',(identifier,))
        return str(identifier)

    def revise(self,identifier,expected_revision,rules):
        identifier=UUID(str(identifier));canonical=validate(rules);sha=fingerprint(canonical)
        if type(expected_revision) is not int or expected_revision<1:raise ValueError('Invalid expected revision')
        with self.pool.connection() as c:
            row=c.execute('SELECT asset,current_revision FROM strategy_draft WHERE id=%s FOR UPDATE',(identifier,)).fetchone()
            if row is None:raise KeyError('Strategy draft not found')
            if row['current_revision']!=expected_revision:raise VersionConflict('Strategy changed; load its latest version')
            if row['asset']!=canonical['asset']:raise ValueError('Strategy category cannot change')
            next_revision=expected_revision+1
            c.execute('INSERT INTO strategy_version(strategy_id,revision,definition,fingerprint) VALUES(%s,%s,%s,%s)',
                      (identifier,next_revision,Jsonb(canonical),sha))
            c.execute('UPDATE strategy_draft SET current_revision=%s WHERE id=%s',(next_revision,identifier))
        return next_revision

    def get(self,identifier,revision=None):
        identifier=UUID(str(identifier))
        with self.pool.connection() as c:
            draft=c.execute('SELECT id,name,asset,state,current_revision,created_at FROM strategy_draft WHERE id=%s',(identifier,)).fetchone()
            if draft is None:raise KeyError('Strategy draft not found')
            selected=draft['current_revision'] if revision is None else revision
            if type(selected) is not int or selected<1:raise ValueError('Invalid revision')
            row=c.execute('SELECT revision,definition,fingerprint,created_at FROM strategy_version WHERE strategy_id=%s AND revision=%s',
                          (identifier,selected)).fetchone()
            if row is None:raise KeyError('Strategy version not found')
        if row['definition']['asset']!=draft['asset'] or fingerprint(row['definition'])!=row['fingerprint']:
            raise ValueError('Stored strategy version failed integrity check')
        return {**draft,**{key:value for key,value in row.items() if key!='created_at'},
                'version_created_at':row['created_at'],'id':str(draft['id'])}
