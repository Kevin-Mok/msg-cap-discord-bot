import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

import bot


class CapStateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'data.sqlite3'
        self.store = bot.Store(self.path)
        self.addCleanup(lambda: self.store.close())
        self.now = datetime(2026, 10, 2, 16, tzinfo=timezone.utc)
        self.deleted = []
        async def delete(mid):
            self.deleted.append(mid)
        self.engine = bot.Tracker(self.store, 123, 50, 'America/Toronto',
                                  now=lambda: self.now, delete=delete, choose=lambda ids: ids[0])

    async def send(self, mid, uid=7):
        await self.engine.process(mid, uid, 'Alice', self.now)

    async def test_dashboard_lists_only_personal_caps(self):
        await self.send(1, 7)
        await self.send(2, 8)
        await self.engine.set_user_cap(7, 4)
        lines = '\n'.join(bot.render_dashboard(self.engine))
        self.assertIn('7): 1 sent · 1 retained · cap 4', lines)
        self.assertNotIn('(8):', lines)

    async def test_personal_override_controls_deletion_and_survives_midnight(self):
        self.assertTrue(hasattr(self.engine, 'set_user_cap'), 'Personal cap API missing')
        await self.engine.set_user_cap(7, 1)
        await self.send(1)
        await self.send(2)
        await self.send(3, 8)
        self.assertEqual(self.deleted, [1])
        self.assertEqual(self.engine.cap_for(8), 50)
        self.now = datetime(2026, 10, 3, 16, tzinfo=timezone.utc)
        await self.engine.rollover()
        self.assertEqual(self.engine.cap_for(7), 1)
        self.assertEqual(await self.engine.clear_user_cap(7), (True, 1))
        self.assertIsNone(self.engine.cap_for(7))
        self.assertEqual(await self.engine.clear_user_cap(7), (False, None))
        await self.send(4)
        self.assertEqual(self.deleted, [1])
        self.store.close()
        self.store = bot.Store(self.path)
        self.engine = bot.Tracker(self.store, 123, 50, 'America/Toronto', now=lambda: self.now,
                                  delete=self.engine.delete)
        self.assertIsNone(self.engine.cap_for(7))
        self.assertIsNone(await self.engine.set_user_cap(7, 3))
        self.assertEqual(self.engine.cap_for(7), 3)

    async def test_reset_excludes_old_candidates_preserves_dedup_and_other_user(self):
        self.assertTrue(hasattr(self.engine, 'reset'), 'Reset API missing')
        await self.send(1)
        await self.send(2, 8)
        await self.engine.set_user_cap(7, 1)
        self.now = datetime(2026, 10, 2, 16, 1, tzinfo=timezone.utc)
        await self.engine.reset(7)
        await self.send(1)
        self.now = datetime(2026, 10, 2, 16, 2, tzinfo=timezone.utc)
        await self.send(3)
        await self.send(4)
        self.assertEqual(self.deleted, [3])
        self.assertEqual(self.engine.rows(), [(7, 'Alice', 2, 1), (8, 'Alice', 1, 1)])
        self.assertIn('since reset', '\n'.join(bot.render_dashboard(self.engine)))
        self.store.close()
        self.store = bot.Store(self.path)
        resumed = bot.Tracker(self.store, 123, 50, 'America/Toronto', now=lambda: self.now,
                              delete=self.engine.delete)
        self.assertEqual(resumed.cap_for(7), 1)
        self.assertEqual(resumed.rows(), self.engine.rows())
        self.assertFalse(await resumed.process(1, 7, 'Alice', self.now))
        self.assertIsNotNone(resumed.reset_at(7))

    async def test_channel_reset_and_stale_confirmation(self):
        self.assertTrue(hasattr(self.engine, 'reset'), 'Reset API missing')
        await self.send(1)
        await self.send(2, 8)
        self.now = datetime(2026, 10, 2, 16, 1, tzinfo=timezone.utc)
        window = self.engine.window_token(None)
        await self.engine.reset(None, expected_window=window)
        self.assertEqual([row[2:] for row in self.engine.rows()], [(0, 0), (0, 0)])
        self.assertEqual(self.deleted, [])
        with self.assertRaises(ValueError):
            await self.engine.reset(None, expected_window=window)
        self.now = datetime(2026, 10, 3, 16, tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            await self.engine.reset(7, expected_window=window)
        self.assertIsNone(self.engine.reset_at(7))

    async def test_lowering_cap_does_not_delete_until_next_send(self):
        self.assertTrue(hasattr(self.engine, 'set_user_cap'), 'Personal cap API missing')
        await self.send(1)
        await self.send(2)
        await self.engine.set_user_cap(7, 1)
        self.assertEqual(self.deleted, [])
        await self.send(3)
        self.assertEqual(len(self.deleted), 1)
        with self.assertRaises(ValueError):
            await self.engine.set_user_cap(7, 0)


class MigrationTests(unittest.TestCase):
    def test_v1_upgrade_preserves_counts_status_and_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data.sqlite3'
            connection = sqlite3.connect(path)
            connection.executescript('''
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, sent INTEGER NOT NULL);
                CREATE TABLE events (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, retained INTEGER NOT NULL);
                CREATE TABLE status (id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL);
                INSERT INTO users VALUES (7, 'Alice', 2);
                INSERT INTO events VALUES (1, 7, 0), (2, 7, 1);
                INSERT INTO status VALUES (42, 123);
                PRAGMA user_version=1;
            ''')
            connection.close()
            store = bot.Store(path)
            try:
                self.assertEqual(store.connection.execute('PRAGMA user_version').fetchone()[0], 3)
                self.assertEqual(store.connection.execute('SELECT sent FROM users').fetchone()[0], 2)
                self.assertEqual(store.status_ids(), [(42, 123)])
                self.assertEqual(store.connection.execute('SELECT count(*) FROM events WHERE active=1').fetchone()[0], 2)
            finally:
                store.close()

    def test_v2_upgrade_creates_exemptions_and_preserves_personal_caps(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data.sqlite3'
            connection = sqlite3.connect(path)
            connection.executescript('''
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, sent INTEGER NOT NULL);
                CREATE TABLE events (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, retained INTEGER NOT NULL,
                                     active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE status (id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL);
                CREATE TABLE overrides (channel_id INTEGER NOT NULL, user_id INTEGER NOT NULL, cap INTEGER NOT NULL,
                                        PRIMARY KEY (channel_id, user_id));
                CREATE TABLE resets (user_id INTEGER PRIMARY KEY, at TEXT NOT NULL);
                INSERT INTO overrides VALUES (123, 7, 3);
                PRAGMA user_version=2;
            ''')
            connection.close()
            store = bot.Store(path)
            try:
                self.assertEqual(store.connection.execute('PRAGMA user_version').fetchone()[0], 3)
                self.assertEqual(store.connection.execute('SELECT user_id, cap FROM overrides').fetchall(), [(7, 3)])
                self.assertEqual(store.connection.execute('SELECT count(*) FROM exemptions').fetchone()[0], 0)
            finally:
                store.close()


class FakeResponse:
    def __init__(self, interaction):
        self.interaction = interaction
        self.done = False

    def is_done(self):
        return self.done

    async def defer(self, **kwargs):
        self.done = True
        self.interaction.deferred = True

    async def send_message(self, content, **kwargs):
        self.done = True
        self.interaction.messages.append({'content': content, **kwargs})


class FakeInteraction:
    def __init__(self, user, *, channel_id=123, guild_id=456):
        self.user = user
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.messages = []
        self.deferred = False
        self.response = FakeResponse(self)
        self.followup = SimpleNamespace(send=self.send)
        self.edit_original_response = AsyncMock()

    async def send(self, content, **kwargs):
        self.messages.append({'content': content, **kwargs})


class SlashTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import discord
        self.discord = discord
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.config = self.path / 'config.json'
        self.config.write_text(json.dumps({'token': 'dummy-token', 'channel_id': 123, 'cap': 50, 'timezone': 'America/Toronto'}))
        self.store = bot.Store(self.path / 'data.sqlite3')
        self.addCleanup(self.store.close)
        self.assertIn('config_path', __import__('inspect').signature(bot.create_client).parameters,
                      'Slash-cap configuration interface missing')
        self.client = bot.create_client(bot.load_config(self.config), self.store, config_path=self.config)
        await self.client._async_setup_hook()
        self.addAsyncCleanup(self.client.close)
        self.channel = Mock(spec=discord.TextChannel)
        self.channel.id = 123
        self.channel.guild = SimpleNamespace(id=456, me=SimpleNamespace(is_mod=True))
        def perms(member):
            p = discord.Permissions(view_channel=True, send_messages=True, read_message_history=True)
            p.manage_messages = member.is_mod
            return p
        self.channel.permissions_for.side_effect = perms
        self.client.channel = self.channel
        self.client.get_channel = lambda mid: self.channel
        self.admin = self.member(1, True)
        self.channel.guild.fetch_member = AsyncMock(side_effect=lambda uid: self.admin)
        self.user = self.member(7)

    def member(self, uid, mod=False):
        member = Mock(spec=self.discord.Member)
        member.id = uid
        member.bot = False
        member.display_name = 'Alice'
        member.is_mod = mod
        return member

    async def invoke(self, name, interaction, **kwargs):
        command = self.client.tree.get_command(name)
        self.assertIsNotNone(command, f'/{name} must be registered')
        await command.callback(interaction, **kwargs)

    async def test_commands_have_native_options_and_permission_defaults(self):
        names = {c.name for c in self.client.tree.get_commands()}
        self.assertEqual(names, {'cap_user', 'cap_default', 'cap_clear', 'cap_status', 'cap_reset', 'cap_help'})
        command = self.client.tree.get_command('cap_user')
        self.assertEqual([(p.name, p.type) for p in command.parameters],
                         [('user', self.discord.AppCommandOptionType.user), ('limit', self.discord.AppCommandOptionType.integer)])
        self.assertTrue(command.default_permissions.manage_messages)
        self.assertIsNone(self.client.tree.get_command('cap_status').default_permissions)

    async def test_denied_user_wrong_channel_and_dm_cannot_change_cap(self):
        for interaction in [FakeInteraction(self.user), FakeInteraction(self.admin, channel_id=999),
                            FakeInteraction(self.admin, guild_id=None)]:
            await self.invoke('cap_user', interaction, user=self.user, limit=2)
            self.assertEqual(self.client.tracker.cap_for(7), 50)
            self.assertTrue(interaction.messages[-1]['ephemeral'])

    async def test_mutations_defer_persist_and_show_effective_status(self):
        inter = FakeInteraction(self.admin)
        await self.invoke('cap_user', inter, user=self.user, limit=2)
        self.assertTrue(inter.deferred)
        self.assertEqual(self.client.tracker.cap_for(7), 2)
        inter = FakeInteraction(self.admin)
        await self.invoke('cap_default', inter, limit=10)
        self.assertEqual(bot.load_config(self.config).cap, 10)
        self.assertEqual(self.client.tracker.cap_for(7), 2)
        self.assertEqual(self.client.tracker.cap_for(8), 10)
        inter = FakeInteraction(self.user)
        await self.invoke('cap_status', inter)
        self.assertIn('personal override', inter.messages[-1]['content'])
        self.assertTrue(inter.messages[-1]['ephemeral'])
        await self.invoke('cap_clear', FakeInteraction(self.admin), user=self.user)
        self.assertIsNone(self.client.tracker.cap_for(7))
        status = FakeInteraction(self.user)
        await self.invoke('cap_status', status)
        self.assertIn('Unlimited', status.messages[-1]['content'])
        await self.client.tracker.process(1, 7, 'Alice', datetime.now(timezone.utc))
        dashboard = '\n'.join(bot.render_dashboard(self.client.tracker))
        self.assertNotIn('(7):', dashboard)
        no_op = FakeInteraction(self.admin)
        await self.invoke('cap_clear', no_op, user=self.user)
        self.assertIn('already', no_op.messages[-1]['content'].lower())
        await self.invoke('cap_user', FakeInteraction(self.admin), user=self.user, limit=3)
        self.assertEqual(self.client.tracker.cap_for(7), 3)

    async def test_reset_confirm_owner_cancel_expiry_and_repeat(self):
        await self.client.tracker.process(1, 7, 'Alice', datetime.now(timezone.utc))
        original = FakeInteraction(self.admin)
        await self.invoke('cap_reset', original, user=self.user)
        view = original.messages[-1]['view']
        unauthorized = FakeInteraction(self.user)
        self.assertFalse(await view.interaction_check(unauthorized))
        await view.children[1].callback(FakeInteraction(self.admin))
        self.assertEqual(self.client.tracker.rows()[0][2], 1)
        original = FakeInteraction(self.admin)
        await self.invoke('cap_reset', original, user=self.user)
        expired = original.messages[-1]['view']
        await expired.on_timeout()
        await expired.children[0].callback(FakeInteraction(self.admin))
        self.assertEqual(self.client.tracker.rows()[0][2], 1)
        original = FakeInteraction(self.admin)
        await self.invoke('cap_reset', original, user=self.user)
        view = original.messages[-1]['view']
        await view.children[0].callback(FakeInteraction(self.admin))
        self.assertEqual(self.client.tracker.rows()[0][2], 0)
        await self.client.tracker.process(2, 7, 'Alice', datetime.now(timezone.utc))
        await view.children[0].callback(FakeInteraction(self.admin))
        self.assertEqual(self.client.tracker.rows()[0][2], 1)

    async def test_confirmation_rechecks_permissions_and_day(self):
        original = FakeInteraction(self.admin)
        await self.invoke('cap_reset', original, user=self.user)
        view = original.messages[-1]['view']
        self.admin.is_mod = False
        await view.children[0].callback(FakeInteraction(self.admin))
        self.assertIsNone(self.client.tracker.reset_at(7))
        self.admin.is_mod = True
        original = FakeInteraction(self.admin)
        await self.invoke('cap_reset', original, user=self.user)
        view = original.messages[-1]['view']
        self.client.tracker.now = lambda: datetime(2027, 10, 2, 16, tzinfo=timezone.utc)
        await view.children[0].callback(FakeInteraction(self.admin))
        self.assertIsNone(self.client.tracker.reset_at(7))

    async def test_reconnect_syncs_once_and_reports_failure(self):
        self.client.tree.sync = AsyncMock(return_value=[])
        await self.client.on_ready()
        await self.client.on_ready()
        self.assertEqual(self.client.tree.sync.await_count, 1)
        self.client.tree.sync.assert_awaited_with(guild=self.discord.Object(id=456))

    async def test_invalid_limits_rejected_and_bot_target_accepted(self):
        for limit in (0, -1):
            inter = FakeInteraction(self.admin)
            await self.invoke('cap_user', inter, user=self.user, limit=limit)
            self.assertEqual(self.client.tracker.cap_for(7), 50)
            self.assertTrue(inter.messages[-1]['ephemeral'])
        self.user.bot = True
        inter = FakeInteraction(self.admin)
        await self.invoke('cap_user', inter, user=self.user, limit=1)
        self.assertEqual(self.client.tracker.cap_for(7), 1)

    async def test_own_bot_target_is_rejected(self):
        self.client._connection.user = SimpleNamespace(id=7)
        self.user.bot = True
        inter = FakeInteraction(self.admin)
        await self.invoke('cap_user', inter, user=self.user, limit=1)
        self.assertEqual(self.client.tracker.cap_for(7), 50)
        self.assertIn('own messages are excluded', inter.messages[-1]['content'])

    async def test_mutation_acknowledges_while_waiting_for_message_lock(self):
        inter = FakeInteraction(self.admin)
        async with self.client.tracker.lock:
            task = asyncio.create_task(self.invoke('cap_user', inter, user=self.user, limit=3))
            await asyncio.sleep(0)
            self.assertTrue(inter.deferred)
            self.assertFalse(task.done())
        await task
        self.assertEqual(self.client.tracker.cap_for(7), 3)

    async def test_sync_failure_is_logged_and_not_reported_as_success(self):
        self.client.tree.sync = AsyncMock(side_effect=OSError('offline'))
        with self.assertLogs('messagecap', level='ERROR'):
            await self.client.on_ready()
        self.assertFalse(self.client.commands_synced)
        self.assertIs(self.client.channel, self.channel)
        await self.client.on_ready()
        self.assertEqual(self.client.tree.sync.await_count, 1)

    async def test_deadline_blocks_confirmation_even_without_timeout_callback(self):
        await self.client.tracker.process(1, 7, 'Alice', datetime.now(timezone.utc))
        inter = FakeInteraction(self.admin)
        await self.invoke('cap_reset', inter, user=self.user)
        view = inter.messages[-1]['view']
        view.deadline = 0
        await view.children[0].callback(FakeInteraction(self.admin))
        self.assertEqual(self.client.tracker.rows()[0][2], 1)
        view.stop()

    async def test_store_error_responds_after_defer_without_false_success(self):
        inter = FakeInteraction(self.admin)
        self.store.connection.execute('PRAGMA query_only=ON')
        with self.assertRaises(sqlite3.Error) as raised:
            await self.invoke('cap_user', inter, user=self.user, limit=3)
        self.assertTrue(inter.deferred)
        self.assertEqual(self.client.tracker.cap_for(7), 50)
        with self.assertLogs('messagecap', level='ERROR'):
            await self.client.tree.on_error(inter, raised.exception)
        self.assertTrue(inter.messages[-1]['ephemeral'])
        self.assertIn('Could not complete', inter.messages[-1]['content'])

    async def test_queued_reset_rechecks_deadline_before_mutation(self):
        await self.client.tracker.process(1, 7, 'Alice', datetime.now(timezone.utc))
        inter = FakeInteraction(self.admin)
        await self.invoke('cap_reset', inter, user=self.user)
        view = inter.messages[-1]['view']
        async with self.client.tracker.lock:
            pending = asyncio.create_task(view.children[0].callback(FakeInteraction(self.admin)))
            await asyncio.sleep(0)
            view.deadline = 0
        await pending
        self.assertEqual(self.client.tracker.rows()[0][2], 1)

    async def test_queued_reset_rechecks_permissions_before_mutation(self):
        await self.client.tracker.process(1, 7, 'Alice', datetime.now(timezone.utc))
        inter = FakeInteraction(self.admin)
        await self.invoke('cap_reset', inter, user=self.user)
        view = inter.messages[-1]['view']
        async with self.client.tracker.lock:
            pending = asyncio.create_task(view.children[0].callback(FakeInteraction(self.admin)))
            await asyncio.sleep(0)
            self.admin.is_mod = False
        await pending
        self.assertEqual(self.client.tracker.rows()[0][2], 1)


    async def test_clear_feedback_uses_cap_at_time_of_mutation(self):
        await self.client.tracker.set_user_cap(7, 2)
        inter = FakeInteraction(self.admin)
        async with self.client.tracker.lock:
            change = asyncio.create_task(self.client.tracker.set_user_cap(7, 4))
            clear = asyncio.create_task(self.invoke('cap_clear', inter, user=self.user))
            await asyncio.sleep(0)
        await asyncio.gather(change, clear)
        self.assertIn('4 → unlimited', inter.messages[-1]['content'])


class MigrationAtomicTests(unittest.TestCase):
    def test_rejected_v1_migration_leaves_schema_version_and_columns_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data.sqlite3'
            connection = sqlite3.connect(path)
            connection.executescript('''
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, sent INTEGER NOT NULL);
                CREATE TABLE events (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, retained INTEGER NOT NULL);
                CREATE TABLE status (id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL);
                INSERT INTO users VALUES (7, 'Alice', 99);
                PRAGMA user_version=1;
            ''')
            connection.close()
            with self.assertRaises(ValueError):
                bot.Store(path)
            connection = sqlite3.connect(path)
            self.addCleanup(connection.close)
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 1)
            self.assertEqual([row[1] for row in connection.execute('PRAGMA table_info(events)')], ['id', 'user_id', 'retained'])
            self.assertEqual(connection.execute('SELECT sent FROM users').fetchone()[0], 99)

    def test_persisted_override_rejects_noninteger_user_or_channel_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data.sqlite3'
            store = bot.Store(path)
            with store.connection:
                store.connection.execute("INSERT INTO overrides VALUES ('invalid-channel', 'invalid-user', 2)")
            store.close()
            with self.assertRaises(ValueError):
                bot.Store(path)
