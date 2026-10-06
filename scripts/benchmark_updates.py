#!/usr/bin/env python3
"""Compare reader API work against a Git revision using synthetic Discord data."""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import types
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import discord
from reader_jump import ReaderJump


class Reaction:
    normal_count = 1
    burst_count = 0

    def __init__(self, counters, pause):
        self.counters, self.pause = counters, pause

    async def users(self, **kwargs):
        self.counters['membership'] += 1
        await asyncio.sleep(self.pause)
        yield types.SimpleNamespace(id=7)


async def measure(reader_class, pause):
    counters = dict.fromkeys(('history', 'fetch', 'membership'), 0)
    now = datetime(2026, 10, 6, 16, tzinfo=timezone.utc)
    messages = []
    for i in range(51):
        created = now.replace(hour=8, minute=i)
        mid = discord.utils.time_snowflake(created)
        messages.append(types.SimpleNamespace(
            id=mid, created_at=created, author=types.SimpleNamespace(id=8, bot=True),
            webhook_id=None, type=discord.MessageType.default, content='',
            reactions=[Reaction(counters, pause)] if i < 49 else [],
            jump_url=f'https://discord.com/channels/456/123/{mid}'))
    async def history(**kwargs):
        counters['history'] += 1
        for message in messages:
            if kwargs['after'].id < message.id < kwargs['before'].id:
                yield message
    async def fetch(mid):
        counters['fetch'] += 1
        return next(message for message in messages if message.id == mid)
    channel = types.SimpleNamespace(id=123, guild=types.SimpleNamespace(id=456),
                                    history=history, fetch_message=fetch)
    with sqlite3.connect(':memory:') as connection:
        connection.execute('CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        reader = reader_class(connection, ZoneInfo('America/Toronto'), lambda: now)
        reader.set_reader(7)
        reader.set_source(8)
        result = {}
        for name, clock in (('initial', 0), ('warm_refresh', 5), ('reader_add', 10)):
            if name == 'reader_add':
                messages[49].reactions = [Reaction(counters, pause)]
                if hasattr(reader, 'reaction'):
                    reader.reaction(messages[49].id, True)
                else:
                    reader.dirty = True
            counters.update(dict.fromkeys(counters, 0))
            started = time.perf_counter()
            await reader.refresh(channel, 999, int(clock), clock)
            elapsed = time.perf_counter() - started
            expected = messages[50 if name == 'reader_add' else 49].jump_url
            if not reader.available or reader.url != expected:
                raise RuntimeError(f'{name}: lookup did not reach the independently expected target')
            result[name] = {**counters, 'elapsed_ms': round(elapsed * 1000, 3)}
    return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='HEAD', help='Git revision for comparison; default HEAD')
    parser.add_argument('--request-wait-ms', type=float, default=4,
                        help='Simulated wait per membership request; default 4ms')
    args = parser.parse_args()
    if not 0 <= args.request_wait_ms <= 100:
        parser.error('--request-wait-ms must be between 0 and 100')
    root = Path(__file__).resolve().parent.parent
    source = subprocess.run(['git', 'show', f'{args.baseline}:reader_jump.py'], cwd=root,
                            text=True, capture_output=True, check=True).stdout
    baseline = types.ModuleType('reader_benchmark_baseline')
    sys.modules[baseline.__name__] = baseline
    exec(compile(source, 'reader_benchmark_baseline', 'exec'), baseline.__dict__)
    pause = args.request_wait_ms / 1000
    results = {'fixture': '49 reacted posts plus two unreacted posts; no live API',
               'simulated_wait_ms': args.request_wait_ms,
               'baseline_revision': args.baseline,
               'baseline': await measure(baseline.ReaderJump, pause),
               'working_tree': await measure(ReaderJump, pause)}
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
