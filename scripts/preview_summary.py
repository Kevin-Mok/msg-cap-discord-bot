#!/usr/bin/env python3
"""Preview the real summary with synthetic counters; no credentials or Discord."""

import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot import Store, Tracker, render_dashboard


def count(value: str) -> int:
    number = int(value)
    if not 0 <= number <= 10000:
        raise argparse.ArgumentTypeError('Use a count from 0 to 10000.')
    return number


async def preview(pistol: int, saucy: int, plain: bool) -> None:
    now = datetime(2026, 10, 13, 16, tzinfo=timezone.utc)

    async def delete(_message_id: int) -> None:
        pass  # Synthetic messages exist only in the temporary tracker.

    with tempfile.TemporaryDirectory() as temporary:
        store = Store(Path(temporary) / 'data.sqlite3')
        try:
            tracker = Tracker(store, channel_id=123, cap=50,
                              timezone_name='America/Toronto', now=lambda: now,
                              choose=lambda ids: ids[0], delete=delete)
            await tracker.set_user_cap(647368715742216193, 50)
            for uid, name, total, start in (
                (142822767497052161, 'Pistol', pistol, 1),
                (647368715742216193, 'SaucyBot', saucy, 20000),
            ):
                for mid in range(start, start + total):
                    await tracker.process(mid, uid, name, now)
            for chunk in render_dashboard(tracker):
                if plain:
                    for glyph in ('📊 ', '🐦 ', '📥 ', '🎯 '):
                        chunk = chunk.replace(glyph, '')
                    chunk = chunk.replace(' · ', ' | ')
                print(chunk, end='')
        finally:
            store.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='🐦 Preview synthetic Pistol/Saucy summary counts offline.')
    parser.add_argument('--pistol', type=count, required=True, help='Pistol sent count (0–10000).')
    parser.add_argument('--saucy', type=count, required=True, help='SaucyBot sent count (0–10000).')
    parser.add_argument('--plain', action='store_true', help='Print the summary as ASCII.')
    args = parser.parse_args()
    asyncio.run(preview(args.pistol, args.saucy, args.plain))
