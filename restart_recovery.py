"""Recover surviving messages missed while offline without enforcing caps retroactively."""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import time
from typing import TYPE_CHECKING, Callable

import aiohttp
import discord

if TYPE_CHECKING:
    from bot import Tracker

LOG = logging.getLogger('messagecap')


class RestartRecovery:
    def __init__(self, tracker: Tracker, *, monotonic: Callable[[], float] = time.monotonic):
        self.tracker = tracker
        self.monotonic = monotonic
        self.pending = True
        self.next_attempt = float('-inf')
        self.timeout = 10.0

    def request(self) -> None:
        self.pending = True
        self.next_attempt = float('-inf')

    async def refresh(self, channel: discord.TextChannel, bot_id: int) -> bool:
        if not self.pending or self.monotonic() < self.next_attempt:
            return False
        tracker = self.tracker
        self.next_attempt = self.monotonic() + 30
        # Hold the existing accounting lock so messages, deletes and moderator resets
        # cannot race a fetched snapshot. The REST work has a strict time budget.
        async with tracker.lock:
            tracker._rollover()
            day = tracker.day
            midnight = datetime.fromisoformat(day).replace(tzinfo=tracker.tz)
            after = discord.Object(discord.utils.time_snowflake(midnight) - 1)
            before = discord.Object(discord.utils.time_snowflake(tracker.now(), high=True) + 1)
            messages: list[tuple[int, int, str, datetime]] = []
            try:
                async with asyncio.timeout(self.timeout):
                    async for message in channel.history(limit=None, after=after, before=before, oldest_first=True):
                        if (message.author.id == bot_id or message.webhook_id is not None
                                or message.guild is None or message.channel.id != tracker.channel_id):
                            continue
                        words = message.content.lower().split() if not message.author.bot else []
                        if (len(words) >= 2 and words[0] in (f'<@{bot_id}>', f'<@!{bot_id}>')
                                and (words[1] == 'channel' or words[1:] in (['sync'], ['slash', 'sync']))):
                            continue
                        messages.append((message.id, message.author.id, message.author.display_name, message.created_at))
            except (discord.HTTPException, OSError, aiohttp.ClientError):
                LOG.warning('Today’s history recovery failed in channel %s; saved counters kept; retrying in 30 seconds.',
                            tracker.channel_id)
                return False
            if tracker.today() != day:
                # A snapshot spanning local midnight must not update the new day.
                tracker._rollover()
                self.next_attempt = float('-inf')
                return False
            tracker._reconcile_history(messages, before.id)
            self.pending = False
            LOG.info('Recovered today’s surviving messages in channel %s; saved sent counts preserved.', tracker.channel_id)
            return True
