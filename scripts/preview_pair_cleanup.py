#!/usr/bin/env python3
"""Show cap cleanup against isolated SQLite data; never connects to Discord."""
import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot import Store, Tracker
from tweet_pairs import PISTOL_ID, SAUCY_ID


async def preview(scenario: str, plain: bool) -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / 'preview.sqlite3')
        try:
            deleted = []
            async def delete(mid: int) -> None:
                deleted.append(mid)
            now = datetime(2026, 10, 13, 16, tzinfo=timezone.utc)
            tracker = Tracker(store, 123, 2, 'America/Toronto', now=lambda: now,
                              choose=lambda ids: ids[0], delete=delete)
            await tracker.process(1, PISTOL_ID, 'Pistol', now)
            await tracker.process(10, SAUCY_ID, 'Saucy', now, reply_to=1)
            await tracker.process(2, PISTOL_ID, 'Pistol', now)
            await tracker.process(11, SAUCY_ID, 'Saucy', now, reply_to=2)
            if scenario == 'unmatched':
                await tracker.process(3, PISTOL_ID, 'Pistol', now)
            else:
                if scenario == 'exempt':
                    await tracker.clear_user_cap(PISTOL_ID)
                await tracker.process(12, SAUCY_ID, 'Saucy', now, reply_to=1)
            print(f'{"" if plain else "🐦 "}Scenario: {scenario}')
            print(f'{"" if plain else "🗑️ "}Deleted message IDs: {deleted}')
            print(f'{"" if plain else "📥 "}Retained message IDs: {sorted(tracker.owners)}')
        finally:
            store.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', choices=('unmatched', 'paired', 'exempt'), default='unmatched',
                        help='Choose unmatched-first cleanup, pair fallback or exempt counterpart.')
    parser.add_argument('--plain', action='store_true', help='Use ASCII output without emoji.')
    args = parser.parse_args()
    asyncio.run(preview(args.scenario, args.plain))
