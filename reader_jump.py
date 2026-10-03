"""A precomputed Discord link for one reader; no message content is stored."""

import asyncio
from datetime import datetime
import logging
import sqlite3
from typing import Callable
from zoneinfo import ZoneInfo

import aiohttp
import discord

LOG = logging.getLogger('messagecap')


def saved_selection(connection: sqlite3.Connection, key: str) -> int | None:
    row = connection.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    if row is None:
        return None
    value = row[0]
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or not 0 < int(value) < 2**64:
        raise ValueError(f'Invalid saved {key}; restore a database backup.')
    return int(value)


class ReaderJump:
    def __init__(self, connection: sqlite3.Connection, tz: ZoneInfo,
                 now: Callable[[], datetime]):
        self.connection, self.tz, self.now = connection, tz, now
        self.reader_id = saved_selection(connection, 'reader_id')
        self.source_id = saved_selection(connection, 'source_id')
        self.url: str | None = None
        self.available = False
        self.dirty = True
        self.last_attempt = float('-inf')
        self.key: tuple | None = None
        self.generation = 0

    def set_reader(self, user_id: int | None) -> None:
        self.set_selection('reader_id', user_id)

    def set_source(self, user_id: int | None) -> None:
        self.set_selection('source_id', user_id)

    def set_selection(self, key: str, user_id: int | None) -> None:
        if user_id is not None and (type(user_id) is not int or not 0 < user_id < 2**64):
            raise ValueError('Choose a valid server member.')
        with self.connection:
            if user_id is None:
                self.connection.execute('DELETE FROM meta WHERE key=?', (key,))
            else:
                self.connection.execute('INSERT OR REPLACE INTO meta VALUES (?, ?)', (key, str(user_id)))
        if key == 'reader_id':
            self.reader_id = user_id
        else:
            self.source_id = user_id
        self.generation += 1
        self.url, self.available, self.dirty = None, False, True
        self.last_attempt = float('-inf')

    async def reacted(self, message: discord.Message, reader_id: int) -> bool:
        for reaction in message.reactions:
            for kind, count in ((discord.ReactionType.normal, reaction.normal_count),
                                (discord.ReactionType.burst, reaction.burst_count)):
                if not count:
                    continue
                # Reaction users are ordered by ID: this checks membership with one result.
                async for user in reaction.users(limit=1, after=discord.Object(id=reader_id - 1), type=kind):
                    if user.id == reader_id:
                        return True
        return False

    async def find_oldest(self, channel: discord.TextChannel, own_id: int, start: datetime,
                          end: datetime, reader_id: int, source_id: int) -> str | None:
        after = discord.Object(id=discord.utils.time_snowflake(start) - 1)
        before = discord.Object(id=discord.utils.time_snowflake(end, high=True))
        async for message in channel.history(after=after, before=before, oldest_first=True, limit=None):
            if (message.author.id != source_id or message.author.id in (own_id, reader_id) or message.webhook_id is not None
                    or message.type not in (discord.MessageType.default, discord.MessageType.reply)):
                continue
            words = message.content.lower().split() if not message.author.bot else []
            if (len(words) >= 2 and words[0] in (f'<@{own_id}>', f'<@!{own_id}>')
                    and (words[1] == 'channel' or words[1:] in (['sync'], ['slash', 'sync']))):
                continue
            if await self.reacted(message, reader_id):
                continue
            # The history page may have been fetched before a reaction or deletion.
            try:
                current = await channel.fetch_message(message.id)
            except discord.NotFound:
                continue
            if not await self.reacted(current, reader_id):
                return current.jump_url
        return None

    async def refresh(self, channel: discord.TextChannel, own_id: int, revision: int, clock: float) -> bool:
        reader_id, source_id = self.reader_id, self.source_id
        if reader_id is None or source_id is None:
            return False
        now = self.now()
        day = now.astimezone(self.tz).date()
        key = (revision, day, reader_id, source_id)
        interval = 5 if self.dirty or key != self.key or not self.available else 60
        day_changed = self.key is not None and self.key[1] != day
        if not day_changed and clock - self.last_attempt < interval:
            return False
        previous = (self.url, self.available)
        self.last_attempt = clock
        self.key, self.dirty = key, False
        generation = self.generation
        start = datetime.combine(day, datetime.min.time(), tzinfo=self.tz)
        try:
            async with asyncio.timeout(10):
                url = await self.find_oldest(channel, own_id, start, now, reader_id, source_id)
            available = self.now().astimezone(self.tz).date() == day
            if not available:
                url = None
                self.dirty = True
        except (discord.HTTPException, OSError, aiohttp.ClientError):
            LOG.warning('Could not refresh unreacted tweet jump in channel %s; retrying.', channel.id)
            url, available = None, False
        if generation == self.generation:
            self.url, self.available = url, available
        return previous != (self.url, self.available)

    def view(self) -> discord.ui.View | None:
        if self.reader_id is None or self.source_id is None:
            return None
        view = discord.ui.View(timeout=None)
        if self.available and self.url is not None:
            view.add_item(discord.ui.Button(label='Jump to unreacted', style=discord.ButtonStyle.link, url=self.url))
        else:
            label = 'All caught up today' if self.available else 'Jump temporarily unavailable'
            view.add_item(discord.ui.Button(label=label, disabled=True, custom_id='reader-jump-unavailable'))
        return view
