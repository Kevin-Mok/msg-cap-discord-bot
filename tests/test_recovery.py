from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
import discord
import bot


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'config.json'
        bot.save_config(self.path, bot.Settings('secret', 123))
        self.store = bot.Store(self.path.parent / 'data.sqlite3')
        self.addCleanup(self.store.close)
        self.client = bot.create_client(bot.load_config(self.path), self.store, config_path=self.path)
        await self.client._async_setup_hook()
        self.addAsyncCleanup(self.client.close)
        identity = Mock(spec=discord.ClientUser, id=999)
        self.client._connection.user = identity
        self.channel = Mock(spec=discord.TextChannel, id=456)
        self.channel.guild = SimpleNamespace(id=789, me=object())
        self.channel.permissions_for.return_value = discord.Permissions.all()
        self.client.get_channel = lambda cid: self.channel if cid == 456 else None
        self.client.fetch_channel = AsyncMock(side_effect=discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'Missing Access'))
        self.client.tree.sync = AsyncMock(return_value=[])
        self.member = Mock(spec=discord.Member, id=7, bot=False)
        self.message = SimpleNamespace(content='<@999> channel here', guild=self.channel.guild,
            channel=self.channel, author=self.member, webhook_id=None, reply=AsyncMock())

    async def test_bad_channel_keeps_bot_online(self):
        with patch('sys.stdin.isatty', return_value=False), self.assertLogs('messagecap'):
            await self.client.on_ready()
        self.assertFalse(self.client.is_closed())
        self.assertIsNone(self.client.channel)

    async def test_discord_repair_saves_and_activates_channel(self):
        await self.client.on_message(self.message)
        self.assertEqual(bot.load_config(self.path).channel_id, 456)
        self.assertIs(self.client.channel, self.channel)
        self.assertEqual(self.client.tracker.channel_id, 456)
        self.assertEqual(self.client.tree.sync.await_count, 1)
        self.assertIn('456', self.message.reply.call_args.args[0])

    async def test_unauthorized_setup_does_not_change_config(self):
        self.channel.permissions_for.return_value = discord.Permissions.none()
        await self.client.on_message(self.message)
        self.assertEqual(bot.load_config(self.path).channel_id, 123)
        self.assertIn('Manage Server', self.message.reply.call_args.args[0])

    async def test_missing_bot_permissions_do_not_save(self):
        self.channel.permissions_for.side_effect = lambda member: discord.Permissions(manage_guild=True) if member is self.member else discord.Permissions.none()
        await self.client.on_message(self.message)
        self.assertEqual(bot.load_config(self.path).channel_id, 123)
        self.assertIn('permissions', self.message.reply.call_args.args[0])

    async def test_terminal_blank_leaves_discord_repair_available(self):
        with patch.object(bot, 'channel_input', AsyncMock(return_value='')):
            await self.client.prompt_channel()
        self.assertIsNone(self.client.channel)
        self.assertFalse(self.client.is_closed())

    async def test_terminal_invalid_then_valid_retries(self):
        with patch.object(bot, 'channel_input', AsyncMock(side_effect=['invalid', '456'])):
            await self.client.prompt_channel()
        self.assertEqual(bot.load_config(self.path).channel_id, 456)

    async def test_other_server_target_is_rejected(self):
        self.channel.guild = SimpleNamespace(id=111, me=object())
        self.message.content = '<@999> channel 456'
        await self.client.on_message(self.message)
        self.assertEqual(bot.load_config(self.path).channel_id, 123)
        self.assertIn('same server', self.message.reply.call_args.args[0])

    async def test_failed_save_preserves_channel_and_tracker(self):
        tracker = self.client.tracker
        with patch.object(bot, 'save_config', side_effect=OSError('read only')):
            await self.client.on_message(self.message)
        self.assertIs(self.client.tracker, tracker)
        self.assertIsNone(self.client.channel)
        self.assertEqual(bot.load_config(self.path).channel_id, 123)
        self.assertIn('failed', self.message.reply.call_args.args[0])

    async def test_concurrent_requests_only_activate_once(self):
        import asyncio
        await asyncio.gather(self.client.on_message(self.message), self.client.on_message(self.message))
        self.assertEqual(self.client.tree.sync.await_count, 1)
        self.assertIn('Already tracking', self.message.reply.call_args.args[0])

    async def test_recovery_preserves_saved_cap_and_token(self):
        bot.save_config(self.path, bot.Settings('secret', 123, cap=17))
        await self.client.on_message(self.message)
        saved = bot.load_config(self.path)
        self.assertEqual((saved.cap, saved.token), (17, 'secret'))
        self.assertEqual(self.client.tracker.cap, 17)

    async def test_sync_failure_still_activates_tracking(self):
        self.client.tree.sync.side_effect = OSError('offline')
        with self.assertLogs('messagecap', level='ERROR'):
            await self.client.on_message(self.message)
        self.assertIs(self.client.channel, self.channel)
        self.assertIsNone(self.client.startup_error)
        self.assertIn('registration failed', self.message.reply.call_args.args[0])

    async def test_discord_repair_cancels_terminal_wait(self):
        import asyncio
        with patch.object(bot, 'channel_input', AsyncMock(side_effect=lambda: None)):
            self.client.channel_prompt = asyncio.create_task(asyncio.sleep(100))
            await self.client.on_message(self.message)
            await asyncio.sleep(0)
        self.assertTrue(self.client.channel_prompt.cancelled())

    async def test_terminal_reader_returns_input_and_removes_reader(self):
        import asyncio
        import os
        reader_fd, writer_fd = os.pipe()
        with os.fdopen(reader_fd) as reader, os.fdopen(writer_fd, 'w') as writer:
            with patch('sys.stdin', reader):
                task = asyncio.create_task(bot.channel_input())
                await asyncio.sleep(0)
                writer.write('456\n')
                writer.flush()
                self.assertEqual(await asyncio.wait_for(task, 1), '456')
                self.assertFalse(asyncio.get_running_loop().remove_reader(reader.fileno()))

    async def test_terminal_reader_cancel_cleans_up(self):
        import asyncio
        import os
        reader_fd, writer_fd = os.pipe()
        with os.fdopen(reader_fd) as reader, os.fdopen(writer_fd, 'w'):
            with patch('sys.stdin', reader):
                task = asyncio.create_task(bot.channel_input())
                await asyncio.sleep(0)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertFalse(asyncio.get_running_loop().remove_reader(reader.fileno()))

    async def test_recovered_channel_routes_messages_and_slash_permissions(self):
        from datetime import datetime, timezone
        await self.client.on_message(self.message)
        self.message.content = 'normal message'
        self.message.id = 100
        self.message.created_at = datetime.now(timezone.utc)
        self.member.display_name = 'Alice'
        await self.client.on_message(self.message)
        self.assertEqual(self.client.tracker.rows()[0][2:], (1, 1))
        interaction = SimpleNamespace(guild_id=789, channel_id=456, user=self.member)
        self.assertIsNone(self.client.permission_error(interaction))
        self.message.channel = SimpleNamespace(id=123)
        self.message.id = 101
        await self.client.on_message(self.message)
        self.assertEqual(self.client.tracker.rows()[0][2:], (1, 1))

    async def test_ready_reuses_one_prompt_and_close_cancels_it(self):
        import asyncio
        async def wait_input():
            await asyncio.Event().wait()
        with patch('sys.stdin.isatty', return_value=True), patch.object(bot, 'channel_input', wait_input), self.assertLogs('messagecap'):
            await self.client.on_ready()
            prompt = self.client.channel_prompt
            await asyncio.sleep(0)
            await self.client.on_ready()
            self.assertIs(self.client.channel_prompt, prompt)
            await self.client.close()
            self.assertTrue(prompt.cancelled())
