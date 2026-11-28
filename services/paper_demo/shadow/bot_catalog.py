"""Complete bounded control catalogs; never treat a truncated page as all bots."""
BOT_LIMIT = 4096


class BotCatalogCapacityError(ValueError):
    pass


def load_bots(store):
    # One SQL statement gives startup/control/API the same coherent snapshot.
    # Keep paused and retired controls too: their historical strategy state must
    # survive restore/encode. The extra row distinguishes a full catalog from
    # a silently truncated page at the supported capacity.
    rows = store.bot_catalog(BOT_LIMIT + 1)
    if len(rows) > BOT_LIMIT:
        raise BotCatalogCapacityError('paper_bot_catalog_capacity')
    # Preserve the former consumer order after the bounded index-range read.
    return sorted(rows, key=lambda row: row['id'], reverse=True)
