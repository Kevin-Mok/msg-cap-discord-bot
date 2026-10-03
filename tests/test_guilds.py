import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
import discord
import bot
try:
    from guild_bot import create_guild_client
except ImportError:
    create_guild_client = None


class GuildTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNotNone(create_guild_client, 'Guild router missing')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'config.json'
        self.settings = bot.Settings('test-secret', 123)
        bot.save_config(self.path, self.settings)
        self.legacy = bot.Store(self.path.parent / 'data.sqlite3')
        self.addCleanup(self.legacy.close)
        self.client = create_guild_client(self.settings, self.legacy, config_path=self.path)
        await self.client._async_setup_hook()
        self.addAsyncCleanup(self.client.close)
        self.client._connection.user = SimpleNamespace(id=999)
        self.client.tree.sync = AsyncMock(return_value=[])
        self.channels = {}
        for gid, cid in [(10, 123), (20, 456)]:
            channel = Mock(spec=discord.TextChannel, id=cid)
            channel.guild = SimpleNamespace(id=gid, me=object())
            channel.permissions_for.return_value = discord.Permissions.all()
            self.channels[cid] = channel
        self.client.get_channel = lambda cid: self.channels.get(cid)
        self.client.fetch_channel = AsyncMock(side_effect=lambda cid: self.channels[cid])
        self.member = Mock(spec=discord.Member, id=7, bot=False, display_name='Alice')

    async def configure(self, cid):
        channel = self.channels[cid]
        return await self.client.configure_guild(channel.guild.id, channel, self.member)

    def message(self, cid, mid, content='hello'):
        channel = self.channels[cid]
        return SimpleNamespace(id=mid, guild=channel.guild, channel=channel, author=self.member,
            webhook_id=None, content=content, created_at=datetime.now(timezone.utc), reply=AsyncMock())

    async def test_two_guilds_keep_same_user_counts_and_caps_separate(self):
        await self.configure(123)
        await self.configure(456)
        a, b = self.client.controllers[10], self.client.controllers[20]
        a.tracker.delete = AsyncMock()
        await a.tracker.set_user_cap(7, 1)
        await self.client.on_message(self.message(123, 1))
        await self.client.on_message(self.message(456, 2))
        await self.client.on_message(self.message(123, 3))
        self.assertEqual(a.tracker.rows()[0][2:], (2, 1))
        self.assertEqual(b.tracker.rows()[0][2:], (1, 1))
        self.assertEqual(b.tracker.cap_for(7), 50)
        a.tracker.delete.assert_awaited_once()

    async def test_channel_command_bootstraps_second_server(self):
        await self.configure(123)
        message = self.message(456, 1, '<@999> channel here')
        await self.client.on_message(message)
        self.assertEqual(self.client.controllers[20].channel.id, 456)
        self.assertEqual(self.client.controllers[10].channel.id, 123)
        self.assertIn('456', message.reply.call_args.args[0])

    async def test_slash_setup_registered_separately_per_guild(self):
        await self.configure(123)
        await self.configure(456)
        for gid in (10, 20):
            names = {command.name for command in self.client.tree.get_commands(guild=discord.Object(id=gid))}
            self.assertIn('cap_channel', names)
            self.assertIn('cap_user', names)
        self.assertIsNone(self.client.tree.get_command('cap_user'))

    async def test_cross_guild_and_unauthorized_setup_rejected(self):
        with self.assertRaisesRegex(ValueError, 'same server'):
            await self.client.configure_guild(10, self.channels[456], self.member)
        self.channels[123].permissions_for.return_value = discord.Permissions.none()
        with self.assertRaisesRegex(ValueError, 'Manage Server'):
            await self.configure(123)
        self.assertEqual(self.client.controllers, {})

    async def test_restart_loads_both_guilds(self):
        await self.configure(123)
        await self.configure(456)
        await self.client.on_message(self.message(456, 5))
        await self.client.close()
        second = create_guild_client(self.settings, self.legacy, config_path=self.path)
        await second._async_setup_hook()
        self.addAsyncCleanup(second.close)
        second._connection.user = SimpleNamespace(id=999)
        second.get_channel = self.client.get_channel
        second.tree.sync = AsyncMock(return_value=[])
        with patch.object(type(second), 'guilds', new_callable=lambda: property(lambda self: [SimpleNamespace(id=10), SimpleNamespace(id=20)])):
            await second.on_ready()
        self.assertEqual(set(second.controllers), {10, 20})
        self.assertEqual(second.controllers[20].tracker.rows()[0][2:], (1, 1))

    async def test_legacy_counts_import_only_into_matching_guild(self):
        tracker = bot.Tracker(self.legacy, 123, 50, 'America/Toronto', delete=AsyncMock())
        await tracker.process(1, 7, 'Alice', datetime.now(timezone.utc))
        await self.configure(456)
        self.assertEqual(self.client.controllers[20].tracker.rows(), [])
        await self.configure(123)
        self.assertEqual(self.client.controllers[10].tracker.rows()[0][2:], (1, 1))

    async def test_switch_channel_retires_old_tracker_without_affecting_other_guild(self):
        await self.configure(123)
        await self.configure(456)
        old = self.client.controllers[10]
        await self.client.on_message(self.message(456, 1))
        replacement = Mock(spec=discord.TextChannel, id=124)
        replacement.guild = self.channels[123].guild
        replacement.permissions_for.return_value = discord.Permissions.all()
        self.channels[124] = replacement
        await self.configure(124)
        self.assertEqual(self.client.controllers[10].channel.id, 124)
        self.assertEqual(self.client.controllers[20].tracker.rows()[0][2:], (1, 1))
        with self.assertRaisesRegex(ValueError, 'changed'):
            await old.tracker.set_user_cap(7, 3)

    async def test_default_cap_and_reset_are_guild_local(self):
        from test_slash import FakeInteraction
        await self.configure(123)
        await self.configure(456)
        a, b = self.client.controllers[10], self.client.controllers[20]
        command = self.client.tree.get_command('cap_default', guild=discord.Object(id=10))
        await command.callback(FakeInteraction(self.member, guild_id=10, channel_id=123), limit=3)
        self.assertEqual(a.tracker.cap, 3)
        self.assertEqual(b.tracker.cap, 50)
        self.assertEqual(bot.load_config(self.client.config_for(10)).cap, 3)
        self.assertEqual(bot.load_config(self.client.config_for(20)).cap, 50)
        await self.client.on_message(self.message(123, 1))
        await self.client.on_message(self.message(456, 2))
        await a.tracker.reset(None)
        self.assertEqual(a.tracker.rows()[0][2:], (0, 0))
        self.assertEqual(b.tracker.rows()[0][2:], (1, 1))

    async def test_controller_close_does_not_close_gateway_or_other_guild(self):
        await self.configure(123)
        await self.configure(456)
        with self.assertLogs('messagecap', level='ERROR'):
            await self.client.controllers[10].close()
        self.assertFalse(self.client.is_closed())
        await self.client.on_message(self.message(456, 5))
        self.assertEqual(self.client.controllers[20].tracker.rows()[0][2:], (1, 1))

    async def test_manual_sync_keeps_channel_command_and_parent_dispatcher(self):
        await self.configure(123)
        controller = self.client.controllers[10]
        await controller.sync_commands(10)
        names = {cmd.name for cmd in self.client.tree.get_commands(guild=discord.Object(id=10))}
        self.assertEqual(len(names), 9)
        self.assertIn('cap_channel', names)
        self.assertIn('cap_reader', names)
        self.assertIn('cap_source', names)
        self.assertIs(self.client._connection._command_tree, self.client.tree)
        self.assertIs(controller.http, self.client.http)

    async def test_reader_reactions_update_only_the_matching_server_jump(self):
        from test_reader_jump import Reaction
        clock = [0.0]
        messages = {}
        async def history(cid, **kwargs):
            for message in messages[cid]:
                yield message
        for cid in (123, 456):
            await self.configure(cid)
            channel = self.channels[cid]
            controller = self.client.controllers[channel.guild.id]
            controller.reader_jump.set_reader(8)
            controller.reader_jump.set_source(7)
            controller.dashboard.monotonic = lambda: clock[0]
            controller.dashboard.delete = AsyncMock()
            messages[cid] = []
            for mid in (cid * 10, cid * 10 + 1):
                message = self.message(cid, mid)
                message.type = discord.MessageType.default
                message.reactions = []
                message.jump_url = f'https://discord.com/channels/{channel.guild.id}/{cid}/{mid}'
                messages[cid].append(message)
            channel.history = lambda _cid=cid, **kwargs: history(_cid, **kwargs)
            channel.fetch_message = AsyncMock(side_effect=lambda mid, _cid=cid: next(m for m in messages[_cid] if m.id == mid))
            channel.send = AsyncMock(return_value=SimpleNamespace(id=cid * 100))
            await controller.dashboard.refresh()
        self.assertTrue(self.client.intents.guild_reactions)
        self.assertFalse(self.client.intents.message_content)
        messages[123][0].reactions = [Reaction(normal=[8])]
        clock[0] += 5
        await self.client.on_raw_reaction_add(SimpleNamespace(channel_id=123, user_id=8))
        for controller in self.client.controllers.values():
            await controller.dashboard.refresh()
        self.assertEqual(self.channels[123].send.call_args.kwargs['view'].children[0].url,
                         messages[123][1].jump_url)
        self.assertEqual(self.channels[456].send.call_args.kwargs['view'].children[0].url,
                         messages[456][0].jump_url)

    async def test_failed_save_keeps_current_controller_active(self):
        await self.configure(123)
        current = self.client.controllers[10]
        replacement = Mock(spec=discord.TextChannel, id=124)
        replacement.guild = self.channels[123].guild
        replacement.permissions_for.return_value = discord.Permissions.all()
        with patch('guild_bot.save_config', side_effect=OSError('read only')):
            with self.assertRaises(OSError):
                await self.client.configure_guild(10, replacement, self.member)
        self.assertIs(self.client.controllers[10], current)
        self.assertEqual(current.channel.id, 123)
        await self.client.on_message(self.message(123, 2))
        self.assertEqual(current.tracker.rows()[0][2:], (1, 1))

    async def test_unconfigured_guild_join_gets_setup_command(self):
        await self.client.on_guild_join(SimpleNamespace(id=20))
        names = {cmd.name for cmd in self.client.tree.get_commands(guild=discord.Object(id=20))}
        self.assertEqual(names, {'cap_channel'})

    async def test_legacy_import_never_replaces_newer_guild_state(self):
        await self.configure(123)
        await self.client.on_message(self.message(123, 9))
        await self.client.on_guild_remove(SimpleNamespace(id=10))
        await self.client.on_guild_join(SimpleNamespace(id=10))
        self.assertEqual(self.client.controllers[10].tracker.rows()[0][2:], (1, 1))

    async def test_constructor_failure_restores_database_and_previous_configuration(self):
        import guild_bot
        import sqlite3
        await self.configure(123)
        await self.client.on_message(self.message(123, 1))
        current = self.client.controllers[10]
        replacement = Mock(spec=discord.TextChannel, id=124)
        replacement.guild = self.channels[123].guild
        replacement.permissions_for.return_value = discord.Permissions.all()
        real_create = guild_bot.create_client
        def fail_after_scope(*args, **kwargs):
            real_create(*args, **kwargs)
            raise sqlite3.OperationalError('injected after scope change')
        with patch('guild_bot.create_client', side_effect=fail_after_scope):
            with self.assertRaises(sqlite3.OperationalError):
                await self.client.configure_guild(10, replacement, self.member)
        self.assertIs(self.client.controllers[10], current)
        self.assertFalse(current.tracker.retired)
        self.assertEqual(current.channel.id, 123)
        self.assertEqual(bot.load_config(self.client.config_for(10)).channel_id, 123)
        self.assertEqual(current.tracker.store.connection.execute('SELECT sent FROM users WHERE id=7').fetchone(), (1,))
        await self.client.on_message(self.message(123, 2))
        self.assertEqual(current.tracker.rows()[0][2:], (2, 2))

    async def test_raw_deletion_is_isolated_to_its_channel(self):
        await self.configure(123)
        await self.configure(456)
        await self.client.on_message(self.message(123, 1))
        await self.client.on_message(self.message(456, 2))
        await self.client.on_raw_message_delete(SimpleNamespace(channel_id=123, message_id=1))
        self.assertEqual(self.client.controllers[10].tracker.rows()[0][2:], (1, 0))
        self.assertEqual(self.client.controllers[20].tracker.rows()[0][2:], (1, 1))

    async def test_offline_check_validates_saved_guilds(self):
        from guild_bot import check_guild_data
        await self.configure(123)
        await self.configure(456)
        self.assertEqual(check_guild_data(self.path), 2)
        self.client.config_for(20).write_text('{}')
        with self.assertRaises(ValueError):
            check_guild_data(self.path)
