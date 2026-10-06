import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import discord

import bot


class RestartRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('restart_recovery'),
                             'Restart recovery must reconcile persisted counters with Discord history')
        from restart_recovery import RestartRecovery
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'data.sqlite3'
        self.now = datetime(2026, 10, 3, 16, tzinfo=timezone.utc)
        self.clock = 0.0
        self.store = bot.Store(self.path)
        self.addCleanup(lambda: self.store.close())
        self.delete = AsyncMock()
        self.tracker = bot.Tracker(self.store, 123, 50, 'America/Toronto',
                                   now=lambda: self.now, delete=self.delete)
        self.recovery = RestartRecovery(self.tracker, monotonic=lambda: self.clock)
        self.messages = []
        self.channel = SimpleNamespace(id=123, history=self.history)
        self.history_calls = []

    def message(self, minute, *, user=7, author_bot=False, webhook=None, day=None):
        created = (day or self.now.replace(hour=4, minute=0)) + timedelta(minutes=minute)
        return SimpleNamespace(id=discord.utils.time_snowflake(created) + user,
                               author=SimpleNamespace(id=user, display_name=f'User {user}', bot=author_bot),
                               webhook_id=webhook, created_at=created, content='',
                               channel=SimpleNamespace(id=123), guild=SimpleNamespace(id=456))

    async def history(self, **kwargs):
        self.history_calls.append(kwargs)
        for message in self.messages:
            yield message

    async def record(self, message):
        await self.tracker.process(message.id, message.author.id,
                                   message.author.display_name, message.created_at)

    async def test_restart_recovers_offline_messages_preserves_sent_and_removes_deleted_retained(self):
        first, second, offline = [self.message(i) for i in (1, 2, 3)]
        await self.record(first)
        await self.record(second)
        self.store.close()
        self.store = bot.Store(self.path)
        self.tracker = bot.Tracker(self.store, 123, 50, 'America/Toronto',
                                   now=lambda: self.now, delete=self.delete)
        from restart_recovery import RestartRecovery
        self.recovery = RestartRecovery(self.tracker, monotonic=lambda: self.clock)
        self.messages = [second, offline]

        self.assertTrue(await self.recovery.refresh(self.channel, 999))

        self.assertEqual(self.tracker.rows(), [(7, 'User 7', 3, 2)])
        self.assertEqual(set(self.tracker.owners), {second.id, offline.id})
        self.delete.assert_not_awaited()
        self.store.close()
        self.store = bot.Store(self.path)  # Persisted counters and event invariants remain valid.
        self.assertEqual(self.store.connection.execute('SELECT sent FROM users').fetchone()[0], 3)

    async def test_recovery_never_deletes_old_messages_even_above_cap(self):
        self.tracker.cap = 1
        self.messages = [self.message(i) for i in (1, 2, 3)]
        await self.recovery.refresh(self.channel, 999)
        self.assertEqual(self.tracker.rows(), [(7, 'User 7', 3, 3)])
        self.delete.assert_not_awaited()

    async def test_repeated_recovery_deduplicates_saved_ids(self):
        self.messages = [self.message(1)]
        await self.recovery.refresh(self.channel, 999)
        self.recovery.request()
        await self.recovery.refresh(self.channel, 999)
        self.assertEqual(self.tracker.rows(), [(7, 'User 7', 1, 1)])

    async def test_local_midnight_is_inclusive_and_previous_day_is_ignored(self):
        midnight = self.message(0)
        self.messages = [self.message(-1), midnight]
        await self.recovery.refresh(self.channel, 999)
        self.assertEqual(set(self.tracker.owners), {midnight.id})
        call = self.history_calls[0]
        self.assertEqual(call['after'].id, discord.utils.time_snowflake(midnight.created_at) - 1)
        self.assertGreater(call['before'].id, discord.utils.time_snowflake(self.now))
        self.assertTrue(call['oldest_first'])
        self.assertIsNone(call['limit'])

    async def test_self_and_webhooks_excluded_other_bots_count_normally(self):
        self.messages = [self.message(1, user=999, author_bot=True),
                         self.message(2, user=8, webhook=1234),
                         self.message(3, user=9, author_bot=True)]
        await self.recovery.refresh(self.channel, 999)
        self.assertEqual(self.tracker.rows(), [(9, 'User 9', 1, 1)])

    async def test_setup_and_sync_mentions_do_not_become_tweets_after_restart(self):
        contents = ['<@999> channel here', '<@!999> channel', '<@999> sync',
                    '<@!999> slash sync', '<@999> hello', '<@111> sync', '<@999> sync extra']
        self.messages = [self.message(index + 1) for index in range(len(contents))]
        for message, content in zip(self.messages, contents):
            message.content = content
        robot = self.message(20, user=8, author_bot=True)
        robot.content = '<@999> sync'
        self.messages.append(robot)
        await self.recovery.refresh(self.channel, 999)
        self.assertEqual(self.tracker.rows(), [(7, 'User 7', 3, 3), (8, 'User 8', 1, 1)])

    async def test_saved_personal_and_global_reset_windows_are_respected(self):
        self.now = self.now.replace(hour=5)
        prior = self.message(1)
        await self.record(prior)
        await self.tracker.reset()
        self.now += timedelta(hours=1)
        global_window = self.message(90, user=8)
        personal_old = self.message(90)
        await self.record(personal_old)
        await self.tracker.reset(7)
        self.now += timedelta(hours=1)
        personal_new = self.message(150)
        self.messages = [prior, global_window, personal_old, personal_new]
        await self.recovery.refresh(self.channel, 999)
        self.assertEqual(self.tracker.rows(), [(7, 'User 7', 1, 1), (8, 'User 8', 1, 1)])
        self.assertEqual(set(self.tracker.owners), {global_window.id, personal_new.id})

    async def test_partial_history_failure_changes_nothing_and_retries_after_delay(self):
        saved, offline = self.message(1), self.message(2)
        await self.record(saved)

        async def failed_history(**kwargs):
            yield offline
            raise OSError('connection interrupted')

        self.channel.history = failed_history
        with self.assertLogs('messagecap', level='WARNING'):
            self.assertFalse(await self.recovery.refresh(self.channel, 999))
        self.assertEqual(self.tracker.rows(), [(7, 'User 7', 1, 1)])
        self.assertEqual(set(self.tracker.owners), {saved.id})
        self.channel.history = self.history
        self.messages = [offline]
        self.assertFalse(await self.recovery.refresh(self.channel, 999))
        self.assertEqual(self.history_calls, [])
        self.clock = 30
        self.assertTrue(await self.recovery.refresh(self.channel, 999))
        self.assertEqual(self.tracker.rows(), [(7, 'User 7', 2, 1)])

    async def test_network_timeout_leaves_saved_counts_untouched(self):
        saved = self.message(1)
        await self.record(saved)

        async def slow_history(**kwargs):
            await asyncio.sleep(60)
            yield saved

        self.channel.history = slow_history
        self.recovery.timeout = 0.01
        with self.assertLogs('messagecap', level='WARNING'):
            self.assertFalse(await self.recovery.refresh(self.channel, 999))
        self.assertEqual(self.tracker.rows(), [(7, 'User 7', 1, 1)])
        self.assertTrue(self.recovery.pending)

    async def test_database_failure_rolls_back_complete_snapshot(self):
        saved = self.message(1)
        await self.record(saved)
        self.messages = [self.message(2), self.message(3)]
        rejected = self.messages[-1].id
        self.store.connection.execute(f'''CREATE TRIGGER reject_recovery BEFORE INSERT ON events
            WHEN NEW.id={rejected} BEGIN SELECT RAISE(ABORT, 'test storage failure'); END''')
        with self.assertRaises(sqlite3.IntegrityError):
            await self.recovery.refresh(self.channel, 999)
        self.assertEqual(self.tracker.rows(), [(7, 'User 7', 1, 1)])
        self.assertEqual(set(self.tracker.owners), {saved.id})
        self.assertEqual(self.store.connection.execute('SELECT count(*) FROM events').fetchone()[0], 1)

    async def test_messages_after_snapshot_cutoff_are_not_marked_deleted(self):
        future = self.message(0, day=self.now + timedelta(seconds=1))
        await self.record(future)
        await self.recovery.refresh(self.channel, 999)
        self.assertEqual(self.tracker.rows(), [(7, 'User 7', 1, 1)])

    async def test_live_events_progress_during_snapshot_and_deduplicate(self):
        offline = self.message(1)
        started, proceed = asyncio.Event(), asyncio.Event()

        async def held_history(**kwargs):
            started.set()
            await proceed.wait()
            yield offline

        self.channel.history = held_history
        recovery = asyncio.create_task(self.recovery.refresh(self.channel, 999))
        await started.wait()
        event = asyncio.create_task(self.record(offline))
        try:
            await asyncio.sleep(0)
            self.assertTrue(event.done(), 'Network history must not hold the accounting lock')
        finally:
            proceed.set()
            await asyncio.gather(recovery, event)
        self.assertEqual(self.tracker.rows(), [(7, 'User 7', 1, 1)])

    async def test_live_delete_during_snapshot_does_not_resurrect_unknown_post(self):
        offline = self.message(1)
        started, proceed = asyncio.Event(), asyncio.Event()
        async def held_history(**kwargs):
            started.set()
            await proceed.wait()
            yield offline
        self.channel.history = held_history
        task = asyncio.create_task(self.recovery.refresh(self.channel, 999))
        await started.wait()
        removal = asyncio.create_task(self.tracker.removed([offline.id]))
        try:
            await asyncio.sleep(0)
            self.assertTrue(removal.done(), 'Raw deletion must not wait for history')
        finally:
            proceed.set()
            await asyncio.gather(task, removal)
        self.assertEqual(self.tracker.rows(), [])

    async def test_live_reset_during_snapshot_discards_old_window(self):
        offline = self.message(1)
        started, proceed = asyncio.Event(), asyncio.Event()
        async def held_history(**kwargs):
            started.set()
            await proceed.wait()
            yield offline
        self.channel.history = held_history
        task = asyncio.create_task(self.recovery.refresh(self.channel, 999))
        await started.wait()
        reset = asyncio.create_task(self.tracker.reset())
        try:
            await asyncio.sleep(0)
            self.assertTrue(reset.done(), 'Moderator reset must not wait for history')
        finally:
            proceed.set()
            await asyncio.gather(task, reset)
        self.assertEqual(self.tracker.rows(), [])
        self.assertTrue(self.recovery.pending)

    async def test_live_new_post_absent_from_snapshot_remains_retained(self):
        offline, live = self.message(1), self.message(2)
        started, proceed = asyncio.Event(), asyncio.Event()
        async def held_history(**kwargs):
            started.set()
            await proceed.wait()
            yield offline
        self.channel.history = held_history
        task = asyncio.create_task(self.recovery.refresh(self.channel, 999))
        await started.wait()
        event = asyncio.create_task(self.record(live))
        try:
            await asyncio.sleep(0)
            self.assertTrue(event.done(), 'Incoming post must progress during history')
        finally:
            proceed.set()
            await asyncio.gather(task, event)
        self.assertEqual(self.tracker.rows(), [(7, 'User 7', 2, 2)])

    async def test_midnight_during_scan_discards_stale_snapshot_then_recovers_new_day(self):
        previous = self.message(1)
        await self.record(previous)

        async def crossing_history(**kwargs):
            yield previous
            self.now = datetime(2026, 10, 4, 4, tzinfo=timezone.utc)

        self.channel.history = crossing_history
        self.assertFalse(await self.recovery.refresh(self.channel, 999))
        self.assertTrue(self.recovery.pending)
        self.assertEqual(self.tracker.rows(), [])
        self.channel.history = self.history
        self.messages = [self.message(0)]
        self.assertTrue(await self.recovery.refresh(self.channel, 999))
        self.assertEqual(self.tracker.rows(), [(7, 'User 7', 1, 1)])


class RestartIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_standalone_refresh_schedules_counts_before_background_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            store = bot.Store(Path(directory) / 'data.sqlite3')
            self.addCleanup(store.close)
            client = bot.create_client(bot.Settings('test-secret', 123), store)
            await client._async_setup_hook()
            self.addAsyncCleanup(client.close)
            self.assertTrue(hasattr(client, 'recovery'), 'Live controllers need restart recovery')
            client._connection.user = SimpleNamespace(id=999)
            message = SimpleNamespace(id=discord.utils.time_snowflake(datetime.now(timezone.utc) - timedelta(seconds=1)),
                author=SimpleNamespace(id=7, display_name='Alice', bot=False), webhook_id=None, content='',
                created_at=datetime.now(timezone.utc), channel=SimpleNamespace(id=123), guild=SimpleNamespace(id=456))

            async def history(**kwargs):
                yield message

            client.channel = SimpleNamespace(id=123, guild=SimpleNamespace(id=456), history=history)
            client.wait_until_ready = AsyncMock()
            client.is_ready = Mock(return_value=True)
            client.is_closed = Mock(side_effect=[False, True])
            seen = []

            async def publish():
                seen.append(client.tracker.rows())

            client.dashboard.refresh = publish
            with patch('bot.asyncio.sleep', new=AsyncMock()):
                await client.refresh_loop()
            await client.dashboard_task
            await client.recovery_task
            self.assertEqual(seen, [[]], 'Saved counts publish while history reconciles')
            self.assertEqual(client.tracker.rows(), [(7, 'Alice', 1, 1)])

    async def test_guild_refresh_schedules_only_its_monitored_channel_recovery(self):
        from guild_bot import create_guild_client
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            settings = bot.Settings('test-secret', 123)
            bot.save_config(path, settings)
            legacy = bot.Store(path.parent / 'data.sqlite3')
            self.addCleanup(legacy.close)
            gateway = create_guild_client(settings, legacy, config_path=path)
            await gateway._async_setup_hook()
            self.addAsyncCleanup(gateway.close)
            gateway._connection.user = SimpleNamespace(id=999)
            gateway.tree.sync = AsyncMock(return_value=[])
            channel = Mock(spec=discord.TextChannel, id=123)
            channel.guild = SimpleNamespace(id=456, me=object())
            channel.permissions_for.return_value = discord.Permissions.all()
            created_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            message = SimpleNamespace(id=discord.utils.time_snowflake(created_at),
                author=SimpleNamespace(id=7, display_name='Alice', bot=False), webhook_id=None, content='',
                created_at=created_at, channel=channel, guild=channel.guild)

            async def history(**kwargs):
                yield message

            channel.history = history
            await gateway.configure_guild(456, channel)
            gateway.wait_until_ready = AsyncMock()
            gateway.is_closed = Mock(side_effect=[False, True])
            seen = []

            async def publish():
                seen.append(gateway.controllers[456].tracker.rows())

            gateway.controllers[456].dashboard.refresh = publish
            with patch('guild_bot.asyncio.sleep', new=AsyncMock()):
                await gateway.refresh_loop()
            controller = gateway.controllers[456]
            await controller.dashboard_task
            await controller.recovery_task
            self.assertEqual(seen, [[]], 'Saved counts publish independently of history')
            self.assertEqual(controller.tracker.rows(), [(7, 'Alice', 1, 1)])


class RepairedChannelRestartTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from test_recovery import RecoveryTests
        await RecoveryTests.asyncSetUp(self)

    async def test_repaired_channel_recovery_uses_the_replacement_tracker(self):
        await self.client.recover_channel(456, 789)
        created_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        message = SimpleNamespace(id=discord.utils.time_snowflake(created_at),
            author=SimpleNamespace(id=7, display_name='Alice', bot=False), webhook_id=None, content='',
            created_at=created_at, channel=self.channel, guild=self.channel.guild)

        async def history(**kwargs):
            yield message

        self.channel.history = history
        await self.client.recovery.refresh(self.channel, 999)
        self.assertEqual(self.client.tracker.rows(), [(7, 'Alice', 1, 1)])


class GatewayReconnectRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from test_guilds import GuildTests
        await GuildTests.asyncSetUp(self)

    async def test_new_gateway_session_recovers_missed_posts_in_existing_controllers(self):
        channel = self.channels[123]
        await self.client.configure_guild(10, channel, self.member)
        controller = self.client.controllers[10]
        controller.recovery.pending = False
        created_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        message = SimpleNamespace(id=discord.utils.time_snowflake(created_at),
            author=self.member, webhook_id=None, content='', created_at=created_at,
            channel=channel, guild=channel.guild)

        async def history(**kwargs):
            yield message

        channel.history = history
        with patch.object(type(self.client), 'guilds', new=property(lambda _: [channel.guild])):
            await self.client.on_ready()
        await controller.recovery.refresh(channel, 999)
        self.assertEqual(controller.tracker.rows(), [(7, 'Alice', 1, 1)])
