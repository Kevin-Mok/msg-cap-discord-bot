from datetime import datetime, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

import discord
import bot


class DiscordSyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        store = bot.Store(Path(self.tmp.name) / 'data.sqlite3')
        self.addCleanup(store.close)
        self.client = bot.create_client(bot.Settings('dummy-token', 123), store)
        await self.client._async_setup_hook()
        self.addAsyncCleanup(self.client.close)
        identity = Mock(spec=discord.ClientUser)
        identity.id = 999
        self.client._connection.user = identity
        self.channel = Mock(spec=discord.TextChannel)
        self.channel.id = 123
        self.channel.guild = SimpleNamespace(id=456)
        self.channel.permissions_for.return_value = discord.Permissions(manage_guild=True)
        self.client.channel = self.channel
        self.member = Mock(spec=discord.Member)
        self.member.id = 7
        self.member.bot = False
        self.member.display_name = 'Alice'
        self.progress = SimpleNamespace(edit=AsyncMock())
        self.message = SimpleNamespace(id=100, content='<@999> slash sync', guild=self.channel.guild,
            channel=self.channel, author=self.member, webhook_id=None, created_at=datetime.now(timezone.utc),
            reply=AsyncMock(return_value=self.progress))
        names = ['cap_user', 'cap_default', 'cap_clear', 'cap_status', 'cap_reset', 'cap_help']
        self.client.tree.sync = AsyncMock(return_value=[SimpleNamespace(name=name) for name in names])

    async def test_mention_command_syncs_guild_and_does_not_consume_allowance(self):
        await self.client.on_message(self.message)
        self.assertEqual(self.client.tree.sync.await_count, 1)
        self.client.tree.sync.assert_awaited_with(guild=discord.Object(id=456))
        self.assertEqual(self.client.tracker.rows(), [])
        result = self.progress.edit.call_args.kwargs['content']
        self.assertIn('6', result)
        self.assertIn('/cap_help', result)
        self.assertFalse(self.message.reply.call_args.kwargs['mention_author'])

    async def test_non_manager_cannot_trigger_sync(self):
        self.channel.permissions_for.return_value = discord.Permissions(manage_messages=True)
        await self.client.on_message(self.message)
        self.assertEqual(self.client.tree.sync.await_count, 0)
        self.assertIn('Manage Server', self.message.reply.call_args.args[0])
        self.assertEqual(self.client.tracker.rows(), [])

    async def test_repeat_sync_is_throttled_and_alias_accepts_nickname_mention(self):
        self.message.content = '<@!999> sync'
        await self.client.on_message(self.message)
        await self.client.on_message(self.message)
        self.assertEqual(self.client.tree.sync.await_count, 1)
        self.assertIn('30', self.message.reply.call_args.args[0])

    async def test_sync_failure_reports_reauthorization_without_false_success(self):
        self.client.tree.sync.side_effect = OSError('offline')
        with self.assertLogs('messagecap', level='ERROR'):
            await self.client.on_message(self.message)
        text = self.progress.edit.call_args.kwargs['content']
        self.assertIn('failed', text.lower())
        self.assertIn('applications.commands', text)
        self.assertFalse(self.client.commands_synced)

    async def test_wrong_channel_does_not_sync(self):
        self.message.channel = SimpleNamespace(id=321)
        await self.client.on_message(self.message)
        self.assertEqual(self.client.tree.sync.await_count, 0)

    async def test_plain_bot_mention_is_still_counted_as_a_normal_message(self):
        self.message.content = '<@999>'
        await self.client.on_message(self.message)
        self.assertEqual(self.client.tree.sync.await_count, 0)
        self.assertEqual(self.client.tracker.rows()[0][2:], (1, 1))
