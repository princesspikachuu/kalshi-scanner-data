"""Lossless derived-status sections in four fixed PostgreSQL slots.

Only the derived view is split. Financial checkpoints/audit commits remain
unchanged. Fixed keys bound retained versions; readers fetch all five rows in
one SQL statement so concurrent publication cannot mix document versions.
"""
from copy import deepcopy
import hashlib
import json

from .checkpoint_codec import pack_checkpoint, unpack_checkpoint, MAX_BYTES

FORMAT = 'shadow-status-sections-v1'
ROOT = 'demo/shadow/status'
SLOTS = ('scalper', 'entry_timing', 'statistics', 'comparison')
KEYS = (ROOT,) + tuple(ROOT+'-section/'+slot for slot in SLOTS)
MIN_SECTION_BYTES = 16384


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def prepare(data):
    # Codec normalizes Decimal/tuple/legacy JSON exactly as the previous path.
    normalized = unpack_checkpoint(pack_checkpoint(data, threshold=0, binary=True))
    hot = deepcopy(normalized)
    sections = {}
    references = []
    experiments = hot.get('experiments', {})
    if not isinstance(experiments, dict):
        experiments = {}
    for slot in SLOTS:
        parts = []
        for folder, portfolio in experiments.items():
            if not isinstance(portfolio, dict):
                continue
            if slot in ('statistics', 'comparison') and slot in portfolio:
                parts.append(dict(path=['experiments', folder, slot], value=portfolio[slot]))
            bots = portfolio.get('bots', {})
            if isinstance(bots, dict) and slot != 'comparison':
                for bot, info in bots.items():
                    if isinstance(info, dict) and slot in info:
                        parts.append(dict(path=['experiments', folder, 'bots', bot, slot], value=info[slot]))
        if not parts or len(json.dumps(parts, separators=(',', ':')).encode()) < MIN_SECTION_BYTES:
            continue
        fingerprint = digest(parts)
        sections[slot] = dict(payload=pack_checkpoint(dict(parts=parts), threshold=0, binary=True),
                              sha256=fingerprint)
        references.append(dict(slot=slot, sha256=fingerprint))
        for part in parts:
            node = hot
            for key in part['path'][:-1]:
                node = node[key]
            del node[part['path'][-1]]
    if not sections:
        return pack_checkpoint(normalized, binary=True), {}
    return dict(status_encoding=FORMAT, hot=pack_checkpoint(hot, threshold=0, binary=True),
                sections=references), sections


def restore(progress, stored):
    if not isinstance(progress, dict) or 'status_encoding' not in progress:
        return unpack_checkpoint(progress)
    if progress.get('status_encoding') != FORMAT:
        raise ValueError('Unknown status encoding')
    refs = progress.get('sections')
    if not isinstance(refs, list) or not 1 <= len(refs) <= len(SLOTS):
        raise ValueError('Invalid status sections')
    hot = unpack_checkpoint(progress['hot'])
    seen = set()
    total_bytes = len(json.dumps(hot, separators=(',', ':')).encode())
    for ref in refs:
        slot = ref.get('slot')
        if slot not in SLOTS or slot in seen:
            raise ValueError('Invalid or duplicate status slot')
        seen.add(slot)
        section = unpack_checkpoint(stored[ROOT+'-section/'+slot])
        parts = section.get('parts')
        if not isinstance(parts, list) or digest(parts) != ref.get('sha256'):
            raise ValueError('Status section integrity mismatch')
        total_bytes += len(json.dumps(parts, separators=(',', ':')).encode())
        if total_bytes > MAX_BYTES:
            raise ValueError('Restored status exceeds capacity')
        for part in parts:
            path = part.get('path')
            if (not isinstance(path, list) or len(path) not in (3, 5)
                    or any(not isinstance(k, str) for k in path)
                    or path[0] != 'experiments' or path[-1] != slot
                    or (len(path) == 5 and path[2] != 'bots')
                    or (len(path) == 3 and slot not in ('statistics', 'comparison'))):
                raise ValueError('Invalid status section path')
            node = hot
            for key in path[:-1]:
                node = node[key]
                if not isinstance(node, dict):
                    raise ValueError('Invalid status section parent')
            if path[-1] in node:
                raise ValueError('Duplicate status section field')
            node[path[-1]] = part['value']
    return hot
