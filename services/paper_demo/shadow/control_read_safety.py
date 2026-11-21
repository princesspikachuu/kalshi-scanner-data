"""Transient read-only control failure gate for the paper simulator.

The worker retains wallet, orders, market books, settlement tasks and its
advisory fencing lock. Only fresh strategy entry admission is suspended.
"""
def all_entry_bots(host):
    seen=set()
    for bot in host.strategy.bots.values():
        if id(bot) not in seen:
            seen.add(id(bot))
            yield bot
    for engine, fleet, profiles in host.experiments.portfolios.values():
        for bot in fleet.bots.values():
            if id(bot) not in seen:
                seen.add(id(bot))
                yield bot


def suspend_new_entries(host):
    """Disable entry admission without touching outstanding orders or lots.

    Preserve the ORIGINAL enabled flags across repeated read timeouts, so that
    a newly requested pause can still perform the normal maker-cancellation
    transition once the complete current catalog is available again.
    """
    if getattr(host, '_suspended_entry_bots', None) is not None:
        return 0
    saved=[(bot,bool(bot.enabled)) for bot in all_entry_bots(host)]
    for bot,was_enabled in saved:
        bot.enabled=False
    host._suspended_entry_bots=saved
    return sum(was_enabled for bot,was_enabled in saved)


def restore_prior_entries(host):
    """Call under state_mutex immediately before applying fresh controls.

    The caller MUST have acquired the full bot catalog and trading mode before
    invoking this. Never restore stale flags in response to another timeout.
    """
    saved=getattr(host,'_suspended_entry_bots',None)
    if saved is None:
        return 0
    for bot,was_enabled in saved:
        bot.enabled=was_enabled
    host._suspended_entry_bots=None
    return sum(was_enabled for bot,was_enabled in saved)
