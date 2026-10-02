import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import urlparse, parse_qs

import bot


class InviteTests(unittest.IsolatedAsyncioTestCase):
    async def test_invite_has_bot_slash_scopes_and_only_required_permissions(self):
        self.assertTrue(hasattr(bot, 'invite_url'), 'Invite URL helper missing')
        parsed = urlparse(bot.invite_url(123456789))
        self.assertEqual(parsed.scheme, 'https')
        self.assertEqual(parsed.netloc, 'discord.com')
        params = parse_qs(parsed.query)
        self.assertEqual(params['client_id'], ['123456789'])
        self.assertEqual(set(params['scope'][0].split()), {'bot', 'applications.commands'})
        self.assertEqual(params['permissions'], ['76800'])

    async def test_invite_logs_in_without_gateway_or_database(self):
        self.assertTrue(hasattr(bot, 'print_invite'), 'Invite-only command missing')
        import discord
        async def login(client, token):
            client._connection.application_id = 123456789
        output = io.StringIO()
        with patch.object(discord.Client, 'login', login), patch.object(discord.Client, 'connect', side_effect=AssertionError('Must not connect gateway')), contextlib.redirect_stdout(output):
            await bot.print_invite(bot.Settings('dummy-secret-token', 123))
        self.assertIn('client_id=123456789', output.getvalue())
        self.assertNotIn('dummy-secret-token', output.getvalue())

    async def test_channel_access_failure_includes_invite_and_repair_steps(self):
        import discord
        with tempfile.TemporaryDirectory() as directory:
            store = bot.Store(Path(directory) / 'data.sqlite3')
            self.addCleanup(store.close)
            client = bot.create_client(bot.Settings('dummy-secret-token', 123), store)
            await client._async_setup_hook()
            self.addAsyncCleanup(client.close)
            client._connection.application_id = 123456789
            client.get_channel = lambda cid: None
            client.fetch_channel = AsyncMock(side_effect=discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'Missing Access'))
            with self.assertLogs('messagecap', level='ERROR') as captured:
                await client.on_ready()
            logs = '\n'.join(captured.output)
            self.assertIn('https://discord.com/oauth2/authorize', logs)
            self.assertIn('123456789', logs)
            self.assertIn('View Channel', logs)
            self.assertNotIn('dummy-secret-token', logs)


class InviteCLITests(unittest.TestCase):
    def test_invite_cli_skips_database_initialization(self):
        self.assertTrue(hasattr(bot, 'print_invite'), 'Invite-only command missing')
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.json'
            config.write_text(json.dumps({'token': 'dummy-secret-token', 'channel_id': 123, 'cap': 50, 'timezone': 'America/Toronto'}))
            with patch('sys.argv', ['bot.py', '--config', str(config), '--invite']), patch.object(bot, 'print_invite', AsyncMock()), patch.object(bot, 'Store', side_effect=AssertionError('Invite must not touch quota DB')):
                self.assertEqual(bot.main(), 0)
            self.assertFalse((config.parent / 'data.sqlite3').exists())
