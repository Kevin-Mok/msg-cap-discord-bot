"""Event-driven, persistent reader state with bounded Discord reconciliation."""

import asyncio
from dataclasses import dataclass
from datetime import date, datetime
import json
import logging
import sqlite3
import time
from typing import Callable
from zoneinfo import ZoneInfo

import aiohttp
import discord

LOG = logging.getLogger('messagecap')
SCAN_TIMEOUT_SECONDS = 120
RECONCILE_SECONDS = 60


def saved_selection(connection: sqlite3.Connection, key: str) -> int | None:
    row = connection.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    if row is None:
        return None
    value = row[0]
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or not 0 < int(value) < 2**64:
        raise ValueError(f'Invalid saved {key}; restore a database backup.')
    return int(value)


@dataclass(frozen=True)
class SavedCache:
    scope: tuple[int, str, int, int]
    complete: bool
    posts: dict[int, bool | None]


def saved_cache(connection: sqlite3.Connection) -> SavedCache | None:
    row = connection.execute("SELECT value FROM meta WHERE key='reader_cache'").fetchone()
    if row is None:
        return None
    try:
        value = json.loads(row[0])
        if (not isinstance(value, dict) or type(value.get('version')) is not int
                or value['version'] != 1):
            raise ValueError('version')
        scope = value['scope']
        if (not isinstance(scope, list) or len(scope) != 4
                or any(type(scope[i]) is not int or not 0 < scope[i] < 2**64 for i in (0, 2, 3))
                or not isinstance(scope[1], str) or date.fromisoformat(scope[1]).isoformat() != scope[1]
                or type(value['complete']) is not bool or not isinstance(value['posts'], list)):
            raise ValueError('scope')
        seen = set()
        for post in value['posts']:
            if (not isinstance(post, list) or len(post) != 2 or type(post[0]) is not int
                    or not 0 < post[0] < 2**64 or post[0] in seen
                    or (post[1] is not None and type(post[1]) is not bool)):
                raise ValueError('post')
            seen.add(post[0])
        return SavedCache(tuple(scope), value['complete'], dict(value['posts']))
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise ValueError('Invalid saved reader cache; remove only the reader_cache meta entry or restore a database backup.') from error


class ReaderJump:
    def __init__(self, connection: sqlite3.Connection, tz: ZoneInfo,
                 now: Callable[[], datetime], *, monotonic: Callable[[], float] = time.monotonic):
        self.monotonic = monotonic
        self.connection, self.tz, self.now = connection, tz, now
        self.reader_id = saved_selection(connection, 'reader_id')
        self.source_id = saved_selection(connection, 'source_id')
        self._saved = saved_cache(connection)
        self.url: str | None = None
        self.available = False
        self.dirty = True
        self.last_attempt = float('-inf')
        self.last_reconcile = float('-inf')
        self.key: tuple | None = None
        self.generation = 0
        self.checked: set[int] = set()
        self.posts: dict[int, bool | None] = {}
        self.versions: dict[int, int] = {}
        self.events: dict[int, bool | None] = {}
        self.deleted: set[int] = set()
        self.complete = False
        self.history_pending = True
        self.reconciling = False
        self.retired = False
        self.lock = asyncio.Lock()
        self.channel: discord.TextChannel | None = None

    def signature(self) -> tuple:
        return self.reader_id, self.source_id, self.available, self.url

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
            self.connection.execute("DELETE FROM meta WHERE key='reader_cache'")
        if key == 'reader_id':
            self.reader_id = user_id
        else:
            self.source_id = user_id
        self._saved = None
        self.key = None
        self._reset()

    def _reset(self) -> None:
        self.generation += 1
        self.checked.clear()
        self.posts.clear()
        self.events.clear()
        self.versions.clear()
        self.deleted.clear()
        self.complete, self.history_pending, self.reconciling = False, True, False
        self.url, self.available, self.dirty = None, False, True
        self.last_attempt = self.last_reconcile = float('-inf')

    def ensure_scope(self, channel: discord.TextChannel) -> None:
        scope = (channel.id, self.now().astimezone(self.tz).date().isoformat(), self.reader_id, self.source_id)
        self.channel = channel
        if self.key == scope:
            return
        self._reset()
        self.key = scope
        if self._saved is not None and self._saved.scope == scope:
            # The bot could have missed reader removals while offline. IDs/order are
            # useful, but no persisted membership is authoritative in a new session.
            self.posts = dict.fromkeys(self._saved.posts)
        self._saved = None

    def request_reconcile(self) -> None:
        self.generation += 1
        self.history_pending = True
        self.reconciling = True
        self.complete = False
        self.posts = dict.fromkeys(self.posts)
        self.checked.clear()
        self.url, self.available, self.dirty = None, False, True
        self.last_attempt = float('-inf')

    def _save(self) -> None:
        if self.retired or self.key is None or self.reader_id is None or self.source_id is None:
            return
        value = {'version': 1, 'scope': list(self.key), 'complete': self.complete,
                 'posts': sorted(self.posts.items())}
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO meta VALUES ('reader_cache', ?)",
                                    (json.dumps(value, separators=(',', ':')),))

    def _publish(self) -> None:
        self.url, self.available = None, self.complete
        if self.channel is None:
            self.available = False
            return
        for mid, state in sorted(self.posts.items()):
            if state is None:
                self.available = False
                return
            if not state:
                self.url = f'https://discord.com/channels/{self.channel.guild.id}/{self.channel.id}/{mid}'
                return

    def eligible(self, message: discord.Message, own_id: int) -> bool:
        if (message.author.id != self.source_id or message.author.id in (own_id, self.reader_id)
                or message.webhook_id is not None
                or message.type not in (discord.MessageType.default, discord.MessageType.reply)
                or message.created_at.astimezone(self.tz).date() != self.now().astimezone(self.tz).date()):
            return False
        words = message.content.lower().split() if not message.author.bot else []
        return not (len(words) >= 2 and words[0] in (f'<@{own_id}>', f'<@!{own_id}>')
                    and (words[1] == 'channel' or words[1:] in (['sync'], ['slash', 'sync'])))

    def observe(self, message: discord.Message, own_id: int) -> None:
        if self.channel is None or self.reader_id is None or self.source_id is None:
            return
        self.ensure_scope(self.channel)
        if not self.eligible(message, own_id) or message.id in self.deleted:
            return
        if message.id not in self.posts:
            self.posts[message.id] = self.events.get(message.id, None if message.reactions else False)
            self.versions[message.id] = self.versions.get(message.id, 0) + 1
            self.dirty = True
            self._publish()
            self._save()

    def reaction(self, message_id: int | None, state: bool | None) -> None:
        if message_id is None:
            # Defensive compatibility for an incomplete payload: recover by audit.
            self.request_reconcile()
            return
        if self.channel is not None:
            self.ensure_scope(self.channel)
        self.events[message_id] = state
        self.versions[message_id] = self.versions.get(message_id, 0) + 1
        if message_id in self.posts:
            self.posts[message_id] = state
            if state:
                self.checked.add(message_id)
            else:
                self.checked.discard(message_id)
            self.dirty = True
            self.last_attempt = float('-inf')
            self._publish()
            self._save()

    def removed(self, ids) -> None:
        for mid in ids:
            self.deleted.add(mid)
            self.versions[mid] = self.versions.get(mid, 0) + 1
            self.posts.pop(mid, None)
            self.events.pop(mid, None)
            self.checked.discard(mid)
        self.dirty = True
        self._publish()
        self._save()

    async def reacted(self, message: discord.Message, reader_id: int) -> bool:
        for reaction in message.reactions:
            for kind, count in ((discord.ReactionType.normal, reaction.normal_count),
                                (discord.ReactionType.burst, reaction.burst_count)):
                if not count:
                    continue
                async for user in reaction.users(limit=1, after=discord.Object(id=reader_id - 1), type=kind):
                    if user.id == reader_id:
                        return True
        return False

    async def _scan(self, channel: discord.TextChannel, own_id: int, generation: int) -> None:
        reader_id = self.reader_id
        if reader_id is None:
            return
        snapshots: dict[int, discord.Message] = {}
        snapshot_versions: dict[int, int] = {}
        validate_target = False
        if self.history_pending:
            now = self.now()
            day = now.astimezone(self.tz).date()
            start = datetime.combine(day, datetime.min.time(), tzinfo=self.tz)
            after = discord.Object(id=discord.utils.time_snowflake(start) - 1)
            before = discord.Object(id=discord.utils.time_snowflake(now, high=True))
            versions = self.versions.copy()
            snapshot_versions = versions
            surviving = set()
            async for message in channel.history(after=after, before=before, oldest_first=True, limit=None):
                if generation != self.generation or self.retired:
                    return
                if not self.eligible(message, own_id) or message.id in self.deleted:
                    continue
                mid = message.id
                surviving.add(mid)
                snapshots[mid] = message
                if mid not in self.posts:
                    self.posts[mid] = self.events.get(mid, None if message.reactions else False)
            if generation != self.generation or self.retired:
                return
            for mid in list(self.posts):
                if mid < before.id and mid not in surviving and self.versions.get(mid, 0) == versions.get(mid, 0):
                    self.posts.pop(mid)
                    self.checked.discard(mid)
            self.complete, self.history_pending = True, False
            validate_target = True
            self._save()
        for mid in sorted(self.posts):
            if generation != self.generation or self.retired:
                return
            if mid not in self.posts:
                continue
            state = self.posts[mid]
            if state is True:
                continue
            if state is False and not validate_target:
                break
            version = self.versions.get(mid, 0)
            try:
                snapshot = snapshots.get(mid)
                if snapshot_versions.get(mid, 0) != version:
                    snapshot = None  # A live event superseded the history page.
                if state is None and snapshot is not None and await self.reacted(snapshot, reader_id):
                    result = True
                else:
                    current = await channel.fetch_message(mid)
                    result = await self.reacted(current, reader_id)
            except discord.NotFound:
                if generation == self.generation and self.versions.get(mid, 0) == version:
                    self.posts.pop(mid, None)
                    self.checked.discard(mid)
                continue
            if generation != self.generation or self.retired:
                return
            if self.versions.get(mid, 0) != version or mid in self.deleted:
                continue
            self.posts[mid] = result
            if result:
                self.checked.add(mid)
            else:
                self.checked.discard(mid)
            self._save()
            if not result:
                break
        if generation == self.generation and not self.retired:
            self._publish()

    async def refresh(self, channel: discord.TextChannel, own_id: int, revision: int, clock: float) -> bool:
        async with self.lock:
            previous = self.signature()
            if self.retired or self.reader_id is None or self.source_id is None:
                return False
            self.ensure_scope(channel)
            if clock - self.last_reconcile >= RECONCILE_SECONDS and not self.reconciling:
                if self.last_reconcile != float('-inf'):
                    self.request_reconcile()
                self.reconciling = True
            if not self.dirty and not self.reconciling and not self.history_pending:
                return previous != self.signature()
            # Healthy live cache mutations have no network work or artificial wait.
            if not self.history_pending and all(state is not None for state in self.posts.values()):
                self._publish()
                self.dirty = False
                if self.reconciling:
                    self.last_reconcile, self.reconciling = clock, False
                return previous != self.signature()
            if clock - self.last_attempt < 5:
                return previous != self.signature()
            self.last_attempt = clock
            started = self.monotonic()
            generation = self.generation
            try:
                async with asyncio.timeout(SCAN_TIMEOUT_SECONDS):
                    await self._scan(channel, own_id, generation)
                if generation == self.generation and not self.retired:
                    if self.key is None or self.now().astimezone(self.tz).date().isoformat() != self.key[1]:
                        self.ensure_scope(channel)
                    else:
                        self._publish()
                        self.dirty = not self.available
                        if self.available and self.reconciling:
                            self.last_reconcile = clock + max(0, self.monotonic() - started)
                            self.reconciling = False
                        self._save()
            except (discord.HTTPException, OSError, aiohttp.ClientError) as error:
                LOG.warning('Could not refresh unreacted tweet jump in channel %s (%s, HTTP status %s); '
                            'retrying with %s reacted posts checked.', channel.id, type(error).__name__,
                            getattr(error, 'status', None), len(self.checked))
                if generation == self.generation:
                    self.url, self.available, self.dirty = None, False, True
                    self._save()
            return previous != self.signature()

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
