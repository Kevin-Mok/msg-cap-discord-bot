#!/usr/bin/env python3
"""Standalone per-server daily Discord message cap. Python 3.11+, discord.py only."""

import argparse
import asyncio
from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone, timedelta
import getpass
import json
import logging
import os
from pathlib import Path
import random
import sqlite3
import sys
import tempfile
import time
from typing import Awaitable, Callable, Sequence, Self, cast
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger('messagecap')
Delete = Callable[[int], Awaitable[None]]
VOICE_DEPENDENCY_NOTICES = {
    'PyNaCl is not installed, voice will NOT be supported',
    'davey is not installed, voice will NOT be supported',
}


class DiscordVoiceNoticeFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not (record.name == 'discord.client' and record.getMessage() in VOICE_DEPENDENCY_NOTICES)


@dataclass(frozen=True)
class Settings:
    token: str = field(repr=False)
    channel_id: int
    cap: int = 50
    timezone_name: str = 'America/Toronto'


def validate_config(data: object) -> Settings:
    if not isinstance(data, dict):
        raise ValueError('Configuration must be a JSON object. Run --setup.')
    token = data.get('token')
    channel_id = data.get('channel_id')
    cap = data.get('cap', 50)
    tz = data.get('timezone', 'America/Toronto')
    if not isinstance(token, str) or not token.strip():
        raise ValueError('Missing bot token. Run --setup.')
    if type(channel_id) is not int or not 0 < channel_id < 2**64:
        raise ValueError('Channel ID must be a positive Discord snowflake. Run --setup.')
    if type(cap) is not int or cap < 1:
        raise ValueError('Daily cap must be a positive integer. Run --setup.')
    if not isinstance(tz, str):
        raise ValueError('Timezone must be an IANA timezone name. Run --setup.')
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('Unknown timezone. Use an IANA name such as America/Toronto.') from None
    return Settings(token.strip(), channel_id, cap, tz)


def load_config(path: Path) -> Settings:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ValueError('Cannot read configuration. Run python bot.py --setup (or use --config PATH).') from None
    return validate_config(data)


def setup_config(path: Path, cap_override: int | None = None) -> None:
    existing = {}
    if path.exists():
        current = load_config(path)
        existing = {'token': current.token, 'channel_id': current.channel_id,
                    'cap': current.cap, 'timezone': current.timezone_name}
    token = getpass.getpass('Bot token (hidden; blank keeps stored token): ').strip()
    channel = input(f"Channel ID [{existing.get('channel_id', '')}]: ").strip()
    cap = input(f"Daily cap [{cap_override if cap_override is not None else existing.get('cap', 50)}]: ").strip()
    tz = input(f"Timezone [{existing.get('timezone', 'America/Toronto')}]: ").strip()
    try:
        data = {'token': token or existing.get('token', ''),
                'channel_id': int(channel) if channel else existing.get('channel_id'),
                'cap': int(cap) if cap else (cap_override if cap_override is not None else existing.get('cap', 50)),
                'timezone': tz or existing.get('timezone', 'America/Toronto')}
    except ValueError:
        raise ValueError('Channel ID and daily cap must be integers; configuration was not changed.') from None
    save_config(path, validate_config(data))
    print(f'Configuration saved to {path}. Token hidden. Invite with ./scripts/run.sh --invite, then start ./scripts/run.sh')


def save_config(path: Path, settings: Settings) -> None:
    data = {'token': settings.token, 'channel_id': settings.channel_id,
            'cap': settings.cap, 'timezone': settings.timezone_name}
    validate_config(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.config-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary)


def invite_url(application_id: int) -> str:
    # View Channel + Send Messages + Manage Messages + Read Message History.
    return 'https://discord.com/oauth2/authorize?' + urlencode({
        'client_id': application_id, 'permissions': 76800,
        'scope': 'bot applications.commands', 'integration_type': 0,
    })


async def channel_input() -> str:
    """Cancellable terminal input without a thread that blocks shutdown (Linux)."""
    loop = asyncio.get_running_loop()
    result = loop.create_future()
    print('New channel ID (Enter to configure in Discord): ', end='', flush=True)
    def read_line():
        if not result.done():
            result.set_result(sys.stdin.readline().strip())
    try:
        loop.add_reader(sys.stdin.fileno(), read_line)
    except (OSError, ValueError, NotImplementedError):
        LOG.warning('Terminal input unavailable. Use @bot channel here in Discord.')
        return ''
    try:
        return await result
    finally:
        loop.remove_reader(sys.stdin.fileno())


async def print_invite(settings: Settings) -> None:
    import discord
    async with discord.Client(intents=discord.Intents.none()) as client:
        await client.login(settings.token)
        application_id = client.application_id
        if application_id is None:
            application_id = (await client.application_info()).id
        print('Open this link, choose the server containing your configured channel, and authorize the bot:')
        print(invite_url(application_id))
        print('Then run ./scripts/run.sh. If access still fails, check the channel ID and channel permission overrides.')


class MissingMessage(Exception):
    """Discord reports that a candidate message no longer exists."""


class DeleteFailed(Exception):
    """Discord could not perform the requested operation."""


class Store:
    """Small transactional SQLite store; no message bodies are stored."""
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError('Database path must not be a symlink.')
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        path.chmod(0o600)
        self.connection = sqlite3.connect(path, timeout=5)
        try:
            version = self.connection.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1, 2, 3):
                raise ValueError('Unsupported database schema; use the matching bot version or a separate config directory.')
            # Explicit BEGIN is required: sqlite3 does not start a transaction for DDL.
            self.connection.execute('BEGIN IMMEDIATE')
            for statement in (
                'CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, sent INTEGER NOT NULL)',
                'CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, retained INTEGER NOT NULL)',
                'CREATE TABLE IF NOT EXISTS status (id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL)',
            ):
                self.connection.execute(statement)
            expected = {'meta': ['key', 'value'], 'users': ['id', 'name', 'sent'],
                        'events': ['id', 'user_id', 'retained'], 'status': ['id', 'channel_id']}
            if version >= 2:
                expected['events'].append('active')
            for table, columns in expected.items():
                if [row[1] for row in self.connection.execute(f'PRAGMA table_info({table})')] != columns:
                    raise ValueError('Invalid database schema; restore a backup or use a separate config directory.')
            if version < 2:
                self.connection.execute('ALTER TABLE events ADD COLUMN active INTEGER NOT NULL DEFAULT 1')
            self.connection.execute('''CREATE TABLE IF NOT EXISTS overrides (
                channel_id INTEGER NOT NULL, user_id INTEGER NOT NULL, cap INTEGER NOT NULL,
                PRIMARY KEY (channel_id, user_id))''')
            self.connection.execute('CREATE TABLE IF NOT EXISTS resets (user_id INTEGER PRIMARY KEY, at TEXT NOT NULL)')
            self.connection.execute('''CREATE TABLE IF NOT EXISTS exemptions (
                channel_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                PRIMARY KEY (channel_id, user_id))''')
            self.connection.execute('CREATE INDEX IF NOT EXISTS events_user_active ON events(user_id, active)')
            for table, columns in {'overrides': ['channel_id', 'user_id', 'cap'], 'resets': ['user_id', 'at'],
                                   'exemptions': ['channel_id', 'user_id']}.items():
                if [row[1] for row in self.connection.execute(f'PRAGMA table_info({table})')] != columns:
                    raise ValueError('Invalid database schema; restore a backup.')
            for user_id, at in self.connection.execute('SELECT * FROM resets'):
                if type(user_id) is not int or user_id < 0 or not isinstance(at, str) or datetime.fromisoformat(at).tzinfo is None:
                    raise ValueError('Invalid persisted reset window; restore a backup.')
            if self.connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Database integrity check failed; restore a backup.')
            invalid = self.connection.execute('''SELECT 1 FROM users u WHERE
                typeof(u.sent) != 'integer' OR u.sent < 0 OR u.id <= 0 OR typeof(u.name) != 'text'
                OR u.sent != (SELECT count(*) FROM events e WHERE e.user_id=u.id AND e.active=1)
                UNION ALL SELECT 1 FROM events e LEFT JOIN users u ON u.id=e.user_id
                WHERE u.id IS NULL OR e.id <= 0 OR typeof(e.user_id) != 'integer'
                OR e.retained NOT IN (0, 1) OR e.active NOT IN (0, 1) OR e.retained > e.active
                UNION ALL SELECT 1 FROM status WHERE id <= 0 OR channel_id <= 0 OR typeof(channel_id) != 'integer'
                UNION ALL SELECT 1 FROM overrides WHERE typeof(channel_id) != 'integer'
                OR typeof(user_id) != 'integer' OR channel_id <= 0 OR user_id <= 0
                OR typeof(cap) != 'integer' OR cap < 1
                UNION ALL SELECT 1 FROM exemptions WHERE typeof(channel_id) != 'integer'
                OR typeof(user_id) != 'integer' OR channel_id <= 0 OR user_id <= 0 LIMIT 1''').fetchone()
            if invalid:
                raise ValueError('Invalid persisted counters or message IDs; restore a database backup.')
            self.connection.execute('PRAGMA user_version=3')
            self.connection.commit()
        except (sqlite3.Error, ValueError):
            self.connection.rollback()
            self.close()
            raise

    def close(self) -> None:
        self.connection.close()

    def scope(self, key: str) -> bool:
        previous = self.connection.execute("SELECT value FROM meta WHERE key='scope'").fetchone()
        if previous and previous[0] == key:
            return False
        with self.connection:
            self.connection.execute('DELETE FROM users')
            self.connection.execute('DELETE FROM events')
            self.connection.execute('DELETE FROM resets')
            self.connection.execute("INSERT OR REPLACE INTO meta VALUES ('scope', ?)", (key,))
        return True

    def record(self, message_id: int, user_id: int, name: str) -> bool:
        with self.connection:
            cursor = self.connection.execute('INSERT OR IGNORE INTO events VALUES (?, ?, 1, 1)', (message_id, user_id))
            if not cursor.rowcount:
                return False
            self.connection.execute('''INSERT INTO users VALUES (?, ?, 1)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name, sent=sent+1''', (user_id, name))
        return True

    def removed(self, message_id: int) -> None:
        with self.connection:
            self.connection.execute('UPDATE events SET retained=0 WHERE id=?', (message_id,))

    def status_ids(self) -> list[tuple[int, int]]:
        return self.connection.execute('SELECT id, channel_id FROM status ORDER BY id').fetchall()

    def remember_status(self, message_id: int, channel_id: int) -> None:
        with self.connection:
            self.connection.execute('INSERT INTO status VALUES (?, ?)', (message_id, channel_id))

    def forget_status(self, message_id: int) -> None:
        with self.connection:
            self.connection.execute('DELETE FROM status WHERE id=?', (message_id,))


class Tracker:
    def __init__(self, store: Store, channel_id: int, cap: int, timezone_name: str,
                 *, now: Callable[[], datetime] | None = None,
                 choose: Callable[[Sequence[int]], int] = random.choice,
                 delete: Delete):
        self.store = store
        self.channel_id = channel_id
        self.cap = cap
        self.tz = ZoneInfo(timezone_name)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.choose = choose
        self.delete = delete
        self.lock = asyncio.Lock()
        self.revision = 0
        self.retired = False
        self.day = self.today()
        self.store.scope(f'{channel_id}:{timezone_name}:{self.day}')
        self.users = {uid: (name, sent) for uid, name, sent in store.connection.execute('SELECT * FROM users')}
        self.seen = set()
        self.retained: dict[int, dict[int, None]] = defaultdict(dict)
        self.owners = {}
        self.overrides = dict(store.connection.execute('SELECT user_id, cap FROM overrides WHERE channel_id=?', (channel_id,)))
        self.exemptions = {uid for (uid,) in store.connection.execute(
            'SELECT user_id FROM exemptions WHERE channel_id=?', (channel_id,))}
        self.resets = dict(store.connection.execute('SELECT user_id, at FROM resets'))
        for mid, uid, retained, active in store.connection.execute('SELECT * FROM events ORDER BY id'):
            self.seen.add(mid)
            if retained:
                self.retained[uid][mid] = None
                self.owners[mid] = uid

    def today(self) -> str:
        return self.now().astimezone(self.tz).date().isoformat()

    def _rollover(self) -> None:
        if self.retired:
            raise ValueError("Channel changed. Run the command again in the new channel.")
        day = self.today()
        if day != self.day:
            self.store.scope(f'{self.channel_id}:{self.tz.key}:{day}')
            self.day = day
            self.users.clear()
            self.seen.clear()
            self.retained.clear()
            self.owners.clear()
            self.resets.clear()
            self.revision += 1

    async def rollover(self) -> None:
        async with self.lock:
            self._rollover()

    def _removed(self, message_id: int) -> None:
        owner = self.owners.get(message_id)
        if owner is not None:
            self.store.removed(message_id)
            self.owners.pop(message_id)
            self.retained[owner].pop(message_id, None)
            self.revision += 1

    async def removed(self, message_ids: Sequence[int]) -> None:
        async with self.lock:
            self._rollover()
            for message_id in message_ids:
                self._removed(message_id)

    async def process(self, message_id: int, user_id: int, name: str, created_at: datetime) -> bool:
        async with self.lock:
            self._rollover()
            if created_at.astimezone(self.tz).date().isoformat() != self.day or message_id in self.seen:
                return False
            reset_at = self.reset_at(user_id)
            if reset_at is not None and created_at <= datetime.fromisoformat(reset_at):
                return False
            if not self.store.record(message_id, user_id, name):
                return False
            self.seen.add(message_id)
            sent = self.users.get(user_id, ('', 0))[1] + 1
            self.users[user_id] = (name, sent)
            self.retained[user_id][message_id] = None
            self.owners[message_id] = user_id
            self.revision += 1
            cap = self.cap_for(user_id)
            if cap is not None and sent > cap:
                while self.retained[user_id]:
                    candidate = self.choose(list(self.retained[user_id]))
                    try:
                        await self.delete(candidate)
                    except MissingMessage:
                        self._removed(candidate)
                        continue
                    except DeleteFailed:
                        LOG.error('Could not delete message %s in channel %s; check Manage Messages and connectivity.',
                                  candidate, self.channel_id)
                        break
                    self._removed(candidate)
                    break
            return True

    def cap_for(self, user_id: int) -> int | None:
        if user_id in self.exemptions:
            return None
        return self.overrides.get(user_id, self.cap)

    def reset_at(self, user_id: int) -> str | None:
        return self.resets.get(user_id, self.resets.get(0))

    def window_token(self, user_id: int | None) -> tuple:
        if user_id is None:
            return (self.day, tuple(sorted(self.resets.items())))
        return (self.day, self.reset_at(user_id))

    async def set_user_cap(self, user_id: int, cap: int) -> int | None:
        if type(cap) is not int or cap < 1:
            raise ValueError('Choose a positive daily limit.')
        async with self.lock:
            self._rollover()
            old = self.cap_for(user_id)
            with self.store.connection:
                self.store.connection.execute('INSERT OR REPLACE INTO overrides VALUES (?, ?, ?)',
                                              (self.channel_id, user_id, cap))
                self.store.connection.execute('DELETE FROM exemptions WHERE channel_id=? AND user_id=?',
                                              (self.channel_id, user_id))
            self.overrides[user_id] = cap
            self.exemptions.discard(user_id)
            self.revision += 1
            return old

    async def clear_user_cap(self, user_id: int) -> tuple[bool, int | None]:
        async with self.lock:
            self._rollover()
            old = self.overrides.get(user_id)
            changed = user_id not in self.exemptions
            with self.store.connection:
                self.store.connection.execute('DELETE FROM overrides WHERE channel_id=? AND user_id=?',
                                              (self.channel_id, user_id))
                self.store.connection.execute('INSERT OR IGNORE INTO exemptions VALUES (?, ?)',
                                              (self.channel_id, user_id))
            self.overrides.pop(user_id, None)
            self.exemptions.add(user_id)
            self.revision += int(changed or old is not None)
            return changed, old

    async def reset(self, user_id: int | None = None, *, expected_window: tuple | None = None,
                    validate: Callable[[], Awaitable[None]] | None = None) -> None:
        async with self.lock:
            if validate is not None:
                await validate()
            self._rollover()
            if expected_window is not None and expected_window != self.window_token(user_id):
                raise ValueError('The accounting window changed. Run /cap_reset again.')
            at = self.now().isoformat()
            targets = list(self.users) if user_id is None else [user_id]
            with self.store.connection:
                if user_id is None:
                    self.store.connection.execute('UPDATE events SET retained=0, active=0')
                    self.store.connection.execute('UPDATE users SET sent=0')
                    self.store.connection.execute('DELETE FROM resets')
                else:
                    self.store.connection.execute('UPDATE events SET retained=0, active=0 WHERE user_id=?', (user_id,))
                    self.store.connection.execute('UPDATE users SET sent=0 WHERE id=?', (user_id,))
                self.store.connection.execute('INSERT OR REPLACE INTO resets VALUES (?, ?)', (user_id or 0, at))
            if user_id is None:
                self.resets.clear()
            self.resets[user_id or 0] = at
            for uid in targets:
                if uid in self.users:
                    self.users[uid] = (self.users[uid][0], 0)
                for mid in self.retained.pop(uid, {}):
                    self.owners.pop(mid, None)
            self.revision += 1

    def rows(self) -> list[tuple[int, str, int, int]]:
        return [(uid, name, sent, len(self.retained[uid]))
                for uid, (name, sent) in sorted(self.users.items())]


def render_dashboard(tracker: Tracker) -> list[str]:
    # Names are untrusted display data; neutralize Markdown/control formatting.
    def clean(name: str) -> str:
        escaped = ''.join(' ' if ord(char) < 32 else char for char in name)[:80]
        for char in ('\\', '*', '_', '~', '`', '|', '>'):
            escaped = escaped.replace(char, '\\' + char)
        return escaped
    header = f'Daily messages · {tracker.day} · {tracker.tz.key}\n'
    lines = [f'{clean(name)} ({uid}): {sent} sent · {retained} retained · cap '
             f'{tracker.overrides[uid]}'
             + (' · since reset' if tracker.reset_at(uid) else '') + '\n'
             for uid, name, sent, retained in tracker.rows() if uid in tracker.overrides]
    if not lines:
        lines = ['No messages from users with personal caps today.\n']
    chunks = []
    text = header
    for line in lines:
        if len(text) + len(line) > 2000:
            chunks.append(text)
            text = header
        text += line
    chunks.append(text)
    return chunks


class Dashboard:
    def __init__(self, store: Store, tracker: Tracker,
                 send: Callable[[str], Awaitable[int]], delete: Delete,
                 *, monotonic: Callable[[], float] = time.monotonic):
        self.store, self.tracker = store, tracker
        self.send, self.delete = send, delete
        self.monotonic = monotonic
        self.last_attempt = float('-inf')
        self.published = -1  # Force replacement of persisted batch after restart.
        self.lock = asyncio.Lock()

    async def refresh(self) -> None:
        async with self.lock:
            await self.tracker.rollover()
            if self.published == self.tracker.revision or self.monotonic() - self.last_attempt < 5:
                return
            self.last_attempt = self.monotonic()
            async with self.tracker.lock:
                revision = self.tracker.revision
                contents = render_dashboard(self.tracker)
            try:
                for message_id, channel_id in self.store.status_ids():
                    if channel_id != self.tracker.channel_id:
                        LOG.warning('Forgetting old counter %s in previous channel %s; remove it manually.', message_id, channel_id)
                        self.store.forget_status(message_id)
                        continue
                    try:
                        await self.delete(message_id)
                    except MissingMessage:
                        pass
                    self.store.forget_status(message_id)
                for text in contents:
                    message_id = await self.send(text)
                    self.store.remember_status(message_id, self.tracker.channel_id)
                self.published = revision
            except DeleteFailed:
                LOG.error('Counter refresh failed in channel %s; check channel permissions and connectivity.', self.tracker.channel_id)

    def removed(self, message_ids: Sequence[int]) -> None:
        stored = {mid for mid, _ in self.store.status_ids()}
        for message_id in message_ids:
            if message_id in stored:
                self.store.forget_status(message_id)
                self.published = -1


def create_client(settings: Settings, store: Store, *, config_path: Path | None = None, gateway=None):
    # Import only for live runtime; setup and core tests need no dependency.
    import discord
    import aiohttp

    from discord import app_commands
    from discord.state import ConnectionState

    async def reply(interaction, content: str, **kwargs):
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await send(content, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(), **kwargs)

    class SlashTree(app_commands.CommandTree):
        async def on_error(self, interaction, error):
            original = getattr(error, 'original', error)
            if isinstance(original, ValueError):
                text = str(original)
            elif isinstance(original, app_commands.CheckFailure):
                text = 'You do not have permission to use this command here.'
            else:
                LOG.error('Slash command failed (%s); check local storage and Discord connectivity.', type(original).__name__)
                text = 'Could not complete that command. Check bot logs/storage and try again; use /cap_status to verify the current state.'
            await reply(interaction, text)

    class ResetView(discord.ui.View):
        def __init__(self, client, origin, user_id: int | None, window: tuple, label: str):
            super().__init__(timeout=30)
            self.client, self.origin = client, origin
            self.user_id, self.window, self.label = user_id, window, label
            self.owner_id = origin.user.id
            self.deadline = time.monotonic() + 30
            self.used = False
            self.action_lock = asyncio.Lock()

        async def interaction_check(self, interaction):
            if interaction.user.id != self.owner_id:
                await reply(interaction, 'Only the moderator who requested this reset can use these buttons.')
                return False
            return True

        async def finish(self, interaction, confirm: bool):
            if not await self.interaction_check(interaction):
                return
            if not await self.client.authorize(interaction, moderator=confirm):
                return
            await interaction.response.defer(ephemeral=True)
            async with self.action_lock:
                if self.used or time.monotonic() >= self.deadline:
                    await reply(interaction, 'This reset confirmation has expired or already been used. Run /cap_reset again.')
                    return
                self.used = True
                self.stop()
                text = 'Reset cancelled. Nothing changed.'
                if confirm:
                    try:
                        async def validate_confirmation():
                            channel = self.client.channel
                            if channel is None:
                                raise ValueError('Channel is not ready. Nothing changed.')
                            try:
                                member = await channel.guild.fetch_member(interaction.user.id)
                            except (discord.HTTPException, OSError, aiohttp.ClientError):
                                raise ValueError('Could not verify current permissions. Nothing changed; try /cap_reset again.') from None
                            if time.monotonic() >= self.deadline:
                                raise ValueError('Reset confirmation expired while waiting. Nothing changed; run /cap_reset again.')
                            error = self.client.permission_error(interaction, moderator=True, member=member)
                            if error:
                                raise ValueError(error)
                        await self.client.tracker.reset(self.user_id, expected_window=self.window, validate=validate_confirmation)
                        text = f'Reset complete for {self.label}. Counters now show **since reset**. Existing messages and cap settings were kept.'
                    except ValueError as error:
                        text = str(error)
                    except sqlite3.Error:
                        LOG.error('Could not persist requested reset; database transaction rolled back.')
                        text = 'Reset failed. Check database access and use /cap_status before retrying.'
                await interaction.edit_original_response(content=text, view=None, allowed_mentions=discord.AllowedMentions.none())

        @discord.ui.button(label='Reset counters', style=discord.ButtonStyle.danger)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            await self.finish(interaction, True)

        @discord.ui.button(label='Cancel', style=discord.ButtonStyle.secondary)
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            await self.finish(interaction, False)

        async def on_timeout(self):
            if not self.used:
                self.used = True
                self.stop()
                with suppress(discord.HTTPException, OSError, aiohttp.ClientError):
                    await self.origin.edit_original_response(content='Reset expired. Nothing changed. Run /cap_reset again.', view=None)

        async def on_error(self, interaction, error, item):
            LOG.error('Reset interaction failed (%s).', type(error).__name__)
            await reply(interaction, 'Could not finish the reset response. Check /cap_status before trying again.')

    class CapClient(discord.Client):
        def __init__(self):
            intents = discord.Intents.none()
            intents.guilds = True
            intents.guild_messages = True
            super().__init__(intents=intents, max_messages=None, allowed_mentions=discord.AllowedMentions.none())
            self.channel: discord.TextChannel | None = None
            self.worker = None
            self.channel_prompt = None
            self.runtime_lock = asyncio.Lock()
            self.startup_error = None
            self.tree = SlashTree(self)
            self.sync_attempted = False
            self.commands_synced = False
            self.sync_lock = asyncio.Lock()
            self.last_manual_sync = float("-inf")
            self.register_commands()
            if gateway is not None:
                # Channel controllers never connect; the parent owns the shared Gateway.
                self._connection = cast('ConnectionState[Self]', gateway._connection)
                self.http = gateway.http
            self.tracker = Tracker(store, settings.channel_id, settings.cap, settings.timezone_name,
                                   delete=self.delete_message)
            self.dashboard = Dashboard(store, self.tracker, self.send_status, self.delete_message)

        def permission_error(self, interaction, *, moderator: bool = False, target=None, member=None) -> str | None:
            channel = self.channel
            if channel is None:
                return 'The bot is still connecting. Try again shortly.'
            if interaction.guild_id != channel.guild.id or interaction.channel_id != settings.channel_id:
                return f'Use this command in the monitored channel <#{settings.channel_id}>.'
            actor = member or interaction.user
            if not isinstance(actor, discord.Member):
                return 'This command is available to server members in the monitored channel.'
            if moderator:
                permissions = channel.permissions_for(actor)
                if not (permissions.manage_messages or permissions.administrator):
                    return 'You need **Manage Messages** permission in this channel to change caps or reset counters.'
            if target is not None and not isinstance(target, discord.Member):
                return 'Choose a server member, including a bot account.'
            if target is not None and self.user is not None and target.id == self.user.id:
                return 'My own messages are excluded to keep the scoreboard and command replies working. Choose another member or bot.'
            return None

        async def authorize(self, interaction, *, moderator: bool = False, target=None) -> bool:
            error = self.permission_error(interaction, moderator=moderator, target=target)
            if error:
                await reply(interaction, error)
                return False
            return True

        def register_commands(self):
            @self.tree.command(name='cap_user', description='Set a personal daily message cap for a member.')
            @app_commands.guild_only()
            @app_commands.default_permissions(manage_messages=True)
            @app_commands.describe(user='Member or bot whose daily cap you want to change', limit='Positive daily limit; takes effect on their next message')
            async def cap_user(interaction: discord.Interaction, user: discord.Member, limit: app_commands.Range[int, 1]):
                if not await self.authorize(interaction, moderator=True, target=user):
                    return
                await interaction.response.defer(ephemeral=True)
                if limit < 1:
                    await reply(interaction, 'Choose a positive daily limit.')
                    return
                old = await self.tracker.set_user_cap(user.id, limit)
                previous = f'{old}/day' if old is not None else 'unlimited'
                await reply(interaction, f'Personal cap for {discord.utils.escape_markdown(user.display_name)}: **{previous} → {limit}/day** in <#{settings.channel_id}>. Counts kept; applies to future messages. Use /cap_clear to exempt them from caps.')

            @self.tree.command(name='cap_default', description='Change the default daily cap for this channel.')
            @app_commands.guild_only()
            @app_commands.default_permissions(manage_messages=True)
            @app_commands.describe(limit='Positive daily limit for members without a personal cap')
            async def cap_default(interaction: discord.Interaction, limit: app_commands.Range[int, 1]):
                if not await self.authorize(interaction, moderator=True):
                    return
                await interaction.response.defer(ephemeral=True)
                if limit < 1:
                    await reply(interaction, 'Choose a positive daily limit.')
                    return
                async with self.tracker.lock:
                    self.tracker._rollover()
                    path = config_path or ROOT / 'config.json'
                    current = load_config(path)
                    if current.channel_id != settings.channel_id or current.timezone_name != settings.timezone_name:
                        raise ValueError('Local channel/timezone settings changed. Restart the bot before changing the default cap.')
                    old = self.tracker.cap
                    save_config(path, replace(current, cap=limit))
                    self.tracker.cap = limit
                    self.tracker.revision += 1
                await reply(interaction, f'Channel default: **{old} → {limit}/day** in <#{settings.channel_id}>. Personal caps and counts kept. Applies to future messages.')

            @self.tree.command(name='cap_clear', description='Exempt a member from all message caps.')
            @app_commands.guild_only()
            @app_commands.default_permissions(manage_messages=True)
            @app_commands.describe(user='Member or bot to exempt from message caps')
            async def cap_clear(interaction: discord.Interaction, user: discord.Member):
                if not await self.authorize(interaction, moderator=True, target=user):
                    return
                await interaction.response.defer(ephemeral=True)
                changed, old = await self.tracker.clear_user_cap(user.id)
                text = f'Cap cleared: **{old if old is not None else "channel default"} → unlimited** for this member. Counts kept.' if changed else 'This member is already exempt from caps. Nothing changed.'
                await reply(interaction, f'{discord.utils.escape_markdown(user.display_name)} in <#{settings.channel_id}>: {text}')

            @self.tree.command(name='cap_status', description='Check your message allowance or another member’s status.')
            @app_commands.guild_only()
            @app_commands.describe(user='Member to check; leave blank to check yourself')
            async def cap_status(interaction: discord.Interaction, user: discord.Member | None = None):
                target = user or interaction.user
                if not await self.authorize(interaction, target=target):
                    return
                await interaction.response.defer(ephemeral=True)
                async with self.tracker.lock:
                    self.tracker._rollover()
                    tracker = self.tracker
                    uid = target.id
                    name, sent = tracker.users.get(uid, (target.display_name, 0))
                    retained = len(tracker.retained.get(uid, {}))
                    cap = tracker.cap_for(uid)
                    source = 'cap exemption' if cap is None else ('personal override' if uid in tracker.overrides else 'channel default')
                    reset_at = tracker.reset_at(uid)
                    window = f'since reset <t:{int(datetime.fromisoformat(reset_at).timestamp())}:f>' if reset_at else f'today ({tracker.day})'
                    local = tracker.now().astimezone(tracker.tz)
                    midnight = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), tzinfo=tracker.tz)
                    display_cap = f'{cap}/day' if cap is not None else 'Unlimited'
                    remaining = str(max(0, cap - sent)) if cap is not None else 'unlimited'
                    text = (f'**{discord.utils.escape_markdown(name)} · {window}**\n'
                            f'Channel: <#{settings.channel_id}>\nCap: **{display_cap}** · {source}\n'
                            f'**{sent} sent · {retained} retained · {remaining} remaining**\n'
                            f'Next reset: <t:{int(midnight.timestamp())}:f> (<t:{int(midnight.timestamp())}:R>) · {tracker.tz.key}\n' +
                            ('You are exempt from cap deletions.' if cap is None else
                             'After the allowance is used, each new message replaces one random eligible message of yours.'))
                await reply(interaction, text)

            @self.tree.command(name='cap_reset', description='Reset one member’s counters, or everyone’s; confirmation required.')
            @app_commands.guild_only()
            @app_commands.default_permissions(manage_messages=True)
            @app_commands.describe(user='Member to reset; leave blank to reset everyone in this channel')
            async def cap_reset(interaction: discord.Interaction, user: discord.Member | None = None):
                if not await self.authorize(interaction, moderator=True, target=user):
                    return
                await interaction.response.defer(ephemeral=True)
                uid = user.id if user else None
                label = discord.utils.escape_markdown(user.display_name) if user else f'**everyone in <#{settings.channel_id}>**'
                async with self.tracker.lock:
                    self.tracker._rollover()
                    window = self.tracker.window_token(uid)
                view = ResetView(self, interaction, uid, window, label)
                await reply(interaction, f'Reset counters for {label}?\nThis starts a fresh allowance. Existing messages stay and are excluded from future random deletions. Caps stay unchanged.\nOnly you can confirm, within **30 seconds**.', view=view)

            @self.tree.command(name='cap_help', description='Learn the message-cap commands and how random replacement works.')
            @app_commands.guild_only()
            async def cap_help(interaction: discord.Interaction):
                if not await self.authorize(interaction):
                    return
                await reply(interaction,
                    '**Daily message cap · this server**\n'
                    '`/cap_channel channel:#channel` — set this server’s channel (Manage Server).\n'
                    '`/cap_status` — your allowance; choose a member to inspect theirs.\n'
                    '**Moderators · Manage Messages required**\n'
                    '`/cap_user user:@member limit:25` — persistent personal cap.\n'
                    '`/cap_default limit:50` — default for members without an override.\n'
                    '`/cap_clear user:@member` — exempt them from all caps.\n'
                    '`/cap_reset user:@member` — fresh counters for one member.\n'
                    '`/cap_reset` — fresh counters for everyone; confirmation required.\n\n'
                    f'Use commands in <#{settings.channel_id}>. Each message after your allowance replaces one random eligible message of yours, possibly the new one. '
                    f'Counters reset at midnight in {settings.timezone_name}. Manual resets keep existing messages but exclude them from the new window. Personal caps persist until changed or the member is exempted with /cap_clear.')

        async def delete_message(self, message_id: int) -> None:
            channel = self.channel
            if channel is None:
                raise DeleteFailed('Channel is not ready.')
            try:
                await channel.get_partial_message(message_id).delete()
            except discord.NotFound:
                raise MissingMessage() from None
            except (discord.HTTPException, OSError, aiohttp.ClientError):
                raise DeleteFailed() from None

        async def send_status(self, text: str) -> int:
            channel = self.channel
            if channel is None:
                raise DeleteFailed('Channel is not ready.')
            try:
                message = await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
                return message.id
            except (discord.HTTPException, OSError, aiohttp.ClientError):
                raise DeleteFailed() from None

        async def setup_hook(self):
            self.worker = asyncio.create_task(self.refresh_loop(), name='daily-counter')

        async def sync_commands(self, guild_id: int):
            async with self.sync_lock:
                guild = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)
                commands = await self.tree.sync(guild=guild)
                self.commands_synced = True
                return commands

        async def handle_sync_message(self, message) -> bool:
            if self.user is None or self.channel is None:
                return False
            words = getattr(message, 'content', '').lower().split()
            if (not words or words[0] not in (f'<@{self.user.id}>', f'<@!{self.user.id}>')
                    or words[1:] not in (['slash', 'sync'], ['sync'])):
                return False
            try:
                permissions = self.channel.permissions_for(message.author)
                if not isinstance(message.author, discord.Member) or not (permissions.manage_guild or permissions.administrator):
                    text = 'You need Manage Server or Administrator permission to sync slash commands.'
                elif self.sync_lock.locked():
                    text = 'Slash command sync is already running. Try again shortly.'
                elif time.monotonic() - self.last_manual_sync < 30:
                    text = 'Please wait 30 seconds between slash command sync requests.'
                else:
                    self.last_manual_sync = time.monotonic()
                    progress = await message.reply('Syncing slash commands…', mention_author=False,
                                                   allowed_mentions=discord.AllowedMentions.none())
                    try:
                        commands = await self.sync_commands(message.guild.id)
                        text = f'Registered {len(commands)} slash commands: ' + ', '.join(f'/{command.name}' for command in commands)
                        text += '. Type /cap_help to get started. If missing, reopen Discord’s command picker.'
                    except (discord.HTTPException, OSError, aiohttp.ClientError, app_commands.AppCommandError):
                        LOG.error('Manual slash command registration failed for guild %s.', message.guild.id)
                        text = ('Slash sync failed. Check the connection and re-authorize the bot with '
                                'the applications.commands scope, then retry after 30 seconds: '
                                + invite_url(self.application_id or self.user.id))
                    await progress.edit(content=text, allowed_mentions=discord.AllowedMentions.none())
                    return True
                await message.reply(text, mention_author=False, allowed_mentions=discord.AllowedMentions.none())
            except (discord.HTTPException, OSError, aiohttp.ClientError):
                LOG.error('Could not send slash sync feedback; check channel permissions and connection.')
            return True

        async def checked_channel(self, channel_id: int, guild_id: int | None = None):
            if not 0 < channel_id < 2**64:
                raise ValueError('Enter a valid channel ID, channel mention, or here.')
            channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                raise ValueError('Choose a server text channel, not a thread or DM.')
            if guild_id is not None and channel.guild.id != guild_id:
                raise ValueError('Choose a channel in the same server as this command.')
            permissions = channel.permissions_for(channel.guild.me)
            missing = [name for name in ('view_channel', 'send_messages', 'read_message_history', 'manage_messages')
                       if not getattr(permissions, name)]
            if missing:
                raise ValueError('Missing bot permissions: ' + ', '.join(missing))
            return channel

        async def recover_channel(self, channel_id: int, guild_id: int | None = None):
            nonlocal settings
            if self.channel is not None:
                return f'Already tracking <#{settings.channel_id}>. Use terminal setup while stopped to move an active channel.'
            channel = await self.checked_channel(channel_id, guild_id)
            path = config_path or ROOT / 'config.json'
            current = load_config(path)
            updated = replace(current, channel_id=channel.id)
            save_config(path, updated)
            tracker = Tracker(store, channel.id, updated.cap, updated.timezone_name, delete=self.delete_message)
            settings = updated
            self.tracker = tracker
            self.dashboard = Dashboard(store, tracker, self.send_status, self.delete_message)
            self.channel = channel
            self.startup_error = None
            if self.channel_prompt is not None and self.channel_prompt is not asyncio.current_task():
                self.channel_prompt.cancel()
            self.sync_attempted = True
            self.commands_synced = False
            try:
                await self.sync_commands(channel.guild.id)
                suffix = 'Slash commands registered. Try /cap_help.'
            except (discord.HTTPException, OSError, aiohttp.ClientError, app_commands.AppCommandError):
                suffix = 'Counting is active; slash registration failed. Use @bot slash sync to retry.'
                LOG.error('%s', suffix)
            LOG.info('Channel saved and tracking active: %s', channel.id)
            return f'Now tracking <#{channel.id}>. Saved for future starts. {suffix}'

        async def prompt_channel(self):
            while self.channel is None:
                answer = await channel_input()
                if not answer:
                    return
                async with self.runtime_lock:
                    try:
                        await self.recover_channel(int(answer))
                    except sqlite3.Error:
                        self.startup_error = 'Database update failed during channel setup.'
                        LOG.error('%s', self.startup_error)
                        await self.close()
                        return
                    except (ValueError, discord.HTTPException, OSError, aiohttp.ClientError):
                        LOG.warning('Channel not saved. Check the ID and bot permissions, or press Enter to configure in Discord.')

        async def handle_channel_message(self, message) -> bool:
            words = getattr(message, 'content', '').lower().split()
            if (self.user is None or len(words) < 2
                    or words[0] not in (f'<@{self.user.id}>', f'<@!{self.user.id}>') or words[1] != 'channel'):
                return False
            try:
                if not isinstance(message.author, discord.Member):
                    text = 'Use this command as a server member.'
                else:
                    permissions = message.channel.permissions_for(message.author)
                    if not (permissions.manage_guild or permissions.administrator):
                        text = 'You need Manage Server or Administrator permission to set the channel.'
                    elif len(words) != 3:
                        text = 'Use @bot channel here, or @bot channel #channel (select the channel mention).'
                    else:
                        try:
                            channel_id = message.channel.id if words[2] == 'here' else int(words[2].removeprefix('<#').removesuffix('>'))
                            text = await self.recover_channel(channel_id, message.guild.id)
                        except ValueError as error:
                            text = str(error) if words[2] == 'here' or words[2].removeprefix('<#').removesuffix('>').isdigit() else 'Enter a valid channel ID, channel mention, or here.'
                        except (discord.HTTPException, OSError, aiohttp.ClientError):
                            text = 'Channel setup failed. Check the ID, bot permissions, connection, and config file access; then retry.'
                await message.reply(text, mention_author=False, allowed_mentions=discord.AllowedMentions.none())
            except (discord.HTTPException, OSError, aiohttp.ClientError):
                LOG.error('Cannot send channel setup feedback; check Send Messages permission.')
            return True

        async def on_ready(self):
            async with self.runtime_lock:
                await self.ready_channel()

        async def ready_channel(self):
            try:
                channel = await self.checked_channel(settings.channel_id)
                self.channel = channel
                self.startup_error = None
                if self.channel_prompt is not None:
                    self.channel_prompt.cancel()
                if not self.sync_attempted:
                    self.sync_attempted = True
                    try:
                        await self.sync_commands(channel.guild.id)
                        LOG.info('Slash commands registered for guild %s.', channel.guild.id)
                    except (discord.HTTPException, OSError, aiohttp.ClientError, app_commands.AppCommandError):
                        LOG.error('Slash command registration failed; check application-command authorization and use @bot slash sync. Counting remains active.')
                LOG.info('Ready: channel=%s cap=%s timezone=%s', settings.channel_id, settings.cap, settings.timezone_name)
            except (discord.HTTPException, OSError, aiohttp.ClientError, ValueError) as error:
                self.startup_error = str(error) if isinstance(error, ValueError) else 'Cannot access configured channel; check channel ID and permissions.'
                LOG.error('%s', self.startup_error)
                application_id = self.application_id or (self.user.id if self.user is not None else None)
                if application_id is not None:
                    LOG.error('Invite/re-authorize this bot in the correct server: %s', invite_url(application_id))
                else:
                    LOG.error('Get the bot invite link with ./scripts/run.sh --invite.')
                LOG.error('For channel %s, allow View Channel, Send Messages, Read Message History and Manage Messages. Check channel overrides; rerun ./scripts/setup.sh if the channel ID is wrong.', settings.channel_id)
                self.channel = None
                LOG.warning('Bot stays online. In the desired channel send @bot channel here (Manage Server required).')
                if sys.stdin.isatty() and (self.channel_prompt is None or self.channel_prompt.done()):
                    self.channel_prompt = asyncio.create_task(self.prompt_channel(), name='channel-setup')

        async def on_message(self, message):
            async with self.runtime_lock:
                try:
                    await self.process_message(message)
                except sqlite3.Error:
                    self.startup_error = 'Database update failed during channel setup.'
                    LOG.error('%s', self.startup_error)
                    await self.close()

        async def process_message(self, message):
            if message.guild is not None and not message.author.bot and message.webhook_id is None:
                if await self.handle_channel_message(message):
                    return
            if (message.guild is None or message.channel.id != settings.channel_id
                    or (self.user is not None and message.author.id == self.user.id)
                    or message.webhook_id is not None or self.channel is None):
                return
            if not message.author.bot and await self.handle_sync_message(message):
                return
            try:
                await self.tracker.process(message.id, message.author.id, message.author.display_name, message.created_at)
            except sqlite3.Error:
                LOG.error('Database write failed; stopping to avoid incorrect quota tracking. Check disk space and database access.')
                self.startup_error = 'Database write failed.'
                await self.close()

        async def on_raw_message_delete(self, payload):
            if payload.channel_id == settings.channel_id:
                await self.handle_removed([payload.message_id])

        async def on_raw_bulk_message_delete(self, payload):
            if payload.channel_id == settings.channel_id:
                await self.handle_removed(list(payload.message_ids))

        async def handle_removed(self, ids):
            try:
                self.dashboard.removed(ids)
                await self.tracker.removed(ids)
            except sqlite3.Error:
                LOG.error('Database deletion accounting failed; stopping. Check disk space and database access.')
                self.startup_error = 'Database deletion accounting failed.'
                await self.close()

        async def refresh_loop(self):
            await self.wait_until_ready()
            while not self.is_closed():
                if self.channel is not None and self.is_ready():
                    try:
                        async with self.runtime_lock:
                            if self.channel is not None:
                                await self.dashboard.refresh()
                    except sqlite3.Error:
                        LOG.error('Database update failed; stopping. Check disk space and database access.')
                        self.startup_error = 'Database update failed.'
                        await self.close()
                        return
                await asyncio.sleep(1)

        async def close(self):
            if self.channel_prompt is not None and self.channel_prompt is not asyncio.current_task():
                self.channel_prompt.cancel()
                with suppress(asyncio.CancelledError):
                    await self.channel_prompt
            if self.worker is not None and self.worker is not asyncio.current_task():
                self.worker.cancel()
                try:
                    await self.worker
                except asyncio.CancelledError:
                    pass
                except Exception:
                    LOG.error('Counter worker failed; closing Discord connection.')
            await super().close()

    return CapClient()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config.json', help='Configuration path; database lives beside it.')
    parser.add_argument('--setup', action='store_true', help='Configure once, preserving existing values on blank input.')
    parser.add_argument('--cap', type=int, help='Default cap for --setup; requires --setup.')
    parser.add_argument('--check', action='store_true', help='Validate configuration and database offline; does not connect to Discord.')
    parser.add_argument('--invite', action='store_true', help='Print this bot’s server invite link; login only, no message tracking.')
    args = parser.parse_args()
    if args.cap is not None and not args.setup:
        parser.error('--cap requires --setup')
    if sum((args.setup, args.check, args.invite)) > 1:
        parser.error('Choose one of --setup, --check or --invite')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    # Discord logs can include application-level data; keep runtime output scoped.
    logging.getLogger('discord').setLevel(logging.WARNING)
    logging.getLogger('discord.client').addFilter(DiscordVoiceNoticeFilter())
    store = None
    try:
        if args.setup:
            setup_config(args.config, args.cap)
            return 0
        settings = load_config(args.config)
        if args.invite:
            asyncio.run(print_invite(settings))
            return 0
        store = Store(args.config.resolve().parent / 'data.sqlite3')
        if args.check:
            from guild_bot import check_guild_data
            guild_count = check_guild_data(args.config)
            print(f'OK: configuration/database valid; channel={settings.channel_id} cap={settings.cap} timezone={settings.timezone_name}; saved servers={guild_count}')
            return 0
        from guild_bot import create_guild_client
        client = create_guild_client(settings, store, config_path=args.config)
        client.run(settings.token, log_handler=None)
        return 1 if client.startup_error else 0
    except (ValueError, OSError, sqlite3.Error):
        # Validation errors contain no input/token values; generic IO/database errors
        # avoid exposing any config contents or HTTP authentication details.
        import sys
        error = sys.exc_info()[1]
        if isinstance(error, ValueError):
            LOG.error('%s', error)
        else:
            LOG.error('Cannot access local configuration/database. Check paths, permissions, disk space, and schema.')
        return 1
    except ModuleNotFoundError:
        LOG.error('discord.py is not installed. Run ./scripts/setup.sh.')
        return 1
    except KeyboardInterrupt:
        return 0
    except EOFError:
        LOG.error('Setup requires an interactive terminal. Run ./scripts/setup.sh.')
        return 1
    except Exception:
        LOG.error('Discord connection failed. Check the stored token, bot invite, network, and channel permissions; rerun --setup if needed.')
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == '__main__':
    raise SystemExit(main())
