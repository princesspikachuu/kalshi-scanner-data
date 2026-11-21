"""Transient read-only control failure gate for the paper simulator.

The worker retains wallet, orders, market books, settlement tasks and its
advisory fencing lock. Only fresh strategy entry admission is suspended.
"""
def all_entry_bots(host):
    # Include the durable control ID so removal from the newly read catalog
    # cannot accidentally reactivate an old in-memory strategy.
    seen=set()
    legacy_ids={p['series']:p['id'] for p in host.profiles}
    for series,bot in host.strategy.bots.items():
        if id(bot) not in seen:
            seen.add(id(bot))
            yield bot,legacy_ids.get(series)
    for engine,fleet,profiles in host.experiments.portfolios.values():
        controls={p['series']:p['id'] for p in profiles}
        for series,bot in fleet.bots.items():
            if id(bot) not in seen:
                seen.add(id(bot))
                yield bot,controls.get(series)


def suspend_new_entries(host):
    """Disable entry admission without touching outstanding orders or lots.

    Preserve the ORIGINAL enabled flags across repeated read timeouts, so that
    a newly requested pause can still perform the normal maker-cancellation
    transition once the complete current catalog is available again.
    """
    if getattr(host, '_suspended_entry_bots', None) is not None:
        return 0
    saved=[(bot,bool(bot.enabled),control_id) for bot,control_id in all_entry_bots(host)]
    for bot,was_enabled,control_id in saved:
        bot.enabled=False
    host._suspended_entry_bots=saved
    return sum(was_enabled for bot,was_enabled,control_id in saved)


def restore_prior_entries(host,verified_rows):
    """Call under state_mutex immediately before applying fresh controls.

    The caller MUST have acquired the full bot catalog and trading mode before
    invoking this. Never restore stale flags in response to another timeout.
    """
    saved=getattr(host,'_suspended_entry_bots',None)
    if saved is None:
        return 0
    ids={row['parameters'].get('id') for row in verified_rows}
    for bot,was_enabled,control_id in saved:
        # A missing control has no authority to submit new entries.
        bot.enabled=was_enabled and control_id in ids
    host._suspended_entry_bots=None
    return sum(was_enabled and control_id in ids for bot,was_enabled,control_id in saved)
