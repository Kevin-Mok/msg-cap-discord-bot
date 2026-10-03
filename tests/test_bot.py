import asyncio
import importlib.util
import json
import logging
import os
from pathlib import Path
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

spec = importlib.util.find_spec('bot')
bot = __import__('bot') if spec else None


class DiscordVoiceNoticeTests(unittest.TestCase):
    def test_filter_hides_only_optional_voice_dependency_notices(self):
        notice_filter = bot.DiscordVoiceNoticeFilter()

        def record(message, name='discord.client'):
            return logging.LogRecord(name, logging.WARNING, 'client.py', 1, message, (), None)

        self.assertFalse(notice_filter.filter(record('PyNaCl is not installed, voice will NOT be supported')))
        self.assertFalse(notice_filter.filter(record('davey is not installed, voice will NOT be supported')))
        self.assertTrue(notice_filter.filter(record('Gateway disconnected')))
        self.assertTrue(notice_filter.filter(record('PyNaCl is not installed, voice will NOT be supported', 'messagecap')))


class BotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.assertIsNotNone(bot, 'Standalone bot implementation is missing')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.now = datetime(2026, 10, 2, 16, tzinfo=timezone.utc)
        self.deleted = []
        self.missing = set()
        self.forbidden = False
        self.store = bot.Store(self.path / 'data.sqlite3')
        self.addCleanup(lambda: self.store.close())
        self.engine = bot.Tracker(self.store, channel_id=123, cap=50,
                                  timezone_name='America/Toronto',
                                  now=lambda: self.now, choose=lambda ids: ids[0],
                                  delete=self.delete)

    async def delete(self, message_id):
        if self.forbidden:
            raise bot.DeleteFailed('Missing Manage Messages permission')
        if message_id in self.missing:
            raise bot.MissingMessage()
        self.deleted.append(message_id)

    async def send_messages(self, count, user=7, start=1):
        for message_id in range(start, start + count):
            await self.engine.process(message_id, user, 'Alice', self.now)

    def row(self, user=7):
        return next(row for row in self.engine.rows() if row[0] == user)

    async def test_50_allowed_51_randomly_replaces_own_message(self):
        await self.send_messages(50)
        self.assertEqual(self.deleted, [])
        await self.send_messages(1, start=51)
        self.assertEqual(self.deleted, [1])
        self.assertEqual(self.row(), (7, 'Alice', 51, 50))

    async def test_newest_is_in_random_candidate_pool(self):
        self.engine.choose = lambda ids: ids[-1]
        await self.send_messages(51)
        self.assertEqual(self.deleted, [51])

    async def test_other_users_and_previous_day_are_isolated(self):
        await self.send_messages(50)
        await self.send_messages(1, user=8, start=100)
        self.now = datetime(2026, 10, 3, 4, tzinfo=timezone.utc)
        await self.send_messages(51, user=8, start=200)
        self.assertEqual(self.deleted, [200])
        self.assertEqual(self.engine.rows(), [(8, 'Alice', 51, 50)])

    async def test_manual_deletion_does_not_refund_sent_quota(self):
        self.engine.cap = 2
        await self.send_messages(2)
        await self.engine.removed([1])
        await self.send_messages(1, start=3)
        self.assertEqual(self.row(), (7, 'Alice', 3, 1))
        self.assertEqual(self.deleted, [2])

    async def test_over_cap_message_is_kept_when_no_old_candidate_remains(self):
        self.engine.cap = 1
        await self.send_messages(1)
        await self.engine.removed([1])

        await self.send_messages(1, start=2)

        self.assertEqual(self.row(), (7, 'Alice', 2, 1))
        self.assertEqual(self.deleted, [])

    async def test_duplicate_deleted_event_is_not_counted_again(self):
        self.engine.cap = 1
        await self.send_messages(2)
        await self.engine.process(1, 7, 'Alice', self.now)
        self.assertEqual(self.row(), (7, 'Alice', 2, 1))
        self.assertEqual(self.deleted, [1])

    async def test_restart_preserves_quota_and_retained_ids(self):
        self.engine.cap = 2
        await self.send_messages(2)
        self.store.close()
        self.store = bot.Store(self.path / 'data.sqlite3')
        self.engine = bot.Tracker(self.store, 123, 2, 'America/Toronto',
                                  now=lambda: self.now, choose=lambda ids: ids[0],
                                  delete=self.delete)
        await self.send_messages(1, start=3)
        self.assertEqual(self.row(), (7, 'Alice', 3, 2))
        self.assertEqual(self.deleted, [1])

    async def test_stale_candidate_retries_without_deleting_other_users(self):
        self.engine.cap = 2
        await self.send_messages(2)
        self.missing.add(1)
        await self.send_messages(1, start=3)
        self.assertEqual(self.deleted, [2])
        self.assertEqual(self.row(), (7, 'Alice', 3, 1))

    async def test_failed_deletion_remains_retained_and_logs_error(self):
        self.engine.cap = 1
        await self.send_messages(1)
        self.forbidden = True
        with self.assertLogs('messagecap', level='ERROR'):
            await self.send_messages(1, start=2)
        self.assertEqual(self.row(), (7, 'Alice', 2, 2))
        self.assertEqual(self.deleted, [])

    async def test_concurrent_messages_cannot_bypass_cap(self):
        await asyncio.gather(*(self.engine.process(i, 7, 'Alice', self.now)
                               for i in range(1, 101)))
        self.assertEqual(self.row(), (7, 'Alice', 100, 50))
        self.assertEqual(len(self.deleted), 50)

    async def test_toronto_midnight_resets_without_human_deletion(self):
        await self.send_messages(1)
        self.now = datetime(2026, 10, 3, 3, 59, tzinfo=timezone.utc)
        await self.engine.rollover()
        self.assertEqual(self.row()[2], 1)
        self.now = datetime(2026, 10, 3, 4, tzinfo=timezone.utc)
        await self.engine.rollover()
        self.assertEqual(self.engine.rows(), [])
        self.assertEqual(self.deleted, [])
        self.assertEqual(self.store.connection.execute('SELECT count(*) FROM events').fetchone()[0], 0)

    async def test_delayed_previous_day_event_is_ignored(self):
        old = datetime(2026, 10, 2, 3, tzinfo=timezone.utc)
        self.assertFalse(await self.engine.process(1, 7, 'Alice', old))
        self.assertEqual(self.engine.rows(), [])

    async def test_raw_bulk_delete_updates_retained_once(self):
        await self.send_messages(3)
        await self.engine.removed([1, 2, 999])
        await self.engine.removed([1, 2])
        self.assertEqual(self.row(), (7, 'Alice', 3, 1))

    async def test_channel_scope_change_does_not_reuse_previous_counts(self):
        await self.send_messages(1)
        other = bot.Tracker(self.store, 999, 50, 'America/Toronto',
                            now=lambda: self.now, choose=lambda ids: ids[0], delete=self.delete)
        self.assertEqual(other.rows(), [])

    async def test_dashboard_throttles_and_replaces_persisted_batch(self):
        live = {}
        cursor = 1000
        clock = [0.0]
        async def send(text):
            nonlocal cursor
            cursor += 1
            live[cursor] = text
            return cursor
        async def remove(message_id):
            live.pop(message_id, None)
        dash = bot.Dashboard(self.store, self.engine, send, remove, monotonic=lambda: clock[0])
        await self.engine.set_user_cap(7, 50)
        await self.send_messages(1)
        await dash.refresh()
        self.assertIn('1 tweet sent', next(iter(live.values())))
        await self.send_messages(1, start=2)
        clock[0] = 4
        await dash.refresh()
        self.assertIn('1 tweet sent', next(iter(live.values())))
        clock[0] = 5
        await dash.refresh()
        self.assertEqual(len(live), 1)
        self.assertIn('2 tweets sent', next(iter(live.values())))
        restarted = bot.Dashboard(self.store, self.engine, send, remove, monotonic=lambda: clock[0])
        await restarted.refresh()
        self.assertEqual(len(live), 1)

    async def test_dashboard_failure_does_not_accumulate_new_messages(self):
        live = {}
        attempts = []
        clock = [0.0]
        async def send(text):
            attempts.append(text)
            live[1000 + len(attempts)] = text
            return 1000 + len(attempts)
        async def remove(message_id):
            raise bot.DeleteFailed('Missing permission')
        dash = bot.Dashboard(self.store, self.engine, send, remove, monotonic=lambda: clock[0])
        await dash.refresh()
        await self.send_messages(1)
        clock[0] = 5
        with self.assertLogs('messagecap', level='ERROR'):
            await dash.refresh()
        self.assertEqual(len(live), 1)
        self.assertEqual(len(attempts), 1)

    async def test_dashboard_splits_long_output_at_discord_limit(self):
        for i in range(100):
            await self.engine.process(i + 1, i + 10, 'User' + 'x' * 100, self.now)
            await self.engine.set_user_cap(i + 10, 50)
        chunks = bot.render_dashboard(self.engine)
        self.assertTrue(all(len(text) <= 2000 for text in chunks))
        self.assertEqual(sum(text.count('1 tweet sent') for text in chunks), 100)

    async def test_config_setup_preserves_token_and_state_on_rerun(self):
        config = self.path / 'config.json'
        with patch('builtins.input', side_effect=['123', '', '']), patch('getpass.getpass', return_value='secret-token'):
            bot.setup_config(config)
        initial = json.loads(config.read_text())
        with patch('builtins.input', side_effect=['', '', '']), patch('getpass.getpass', return_value=''):
            bot.setup_config(config, cap_override=3)
        current = bot.load_config(config)
        self.assertEqual(current.token, initial['token'])
        self.assertEqual(current.channel_id, 123)
        self.assertEqual(current.cap, 3)
        self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
        self.assertEqual(current.timezone_name, 'America/Toronto')

    async def test_invalid_config_errors_do_not_expose_token(self):
        config = self.path / 'config.json'
        for change in [{'cap': 0}, {'channel_id': 'abc'}, {'timezone': 'invalid'}, {'cap': True}]:
            config.write_text(json.dumps({'token': 'secret-token', 'channel_id': 123, 'cap': 50,
                                          'timezone': 'America/Toronto', **change}))
            with self.assertRaises(ValueError) as failure:
                bot.load_config(config)
            self.assertNotIn('secret-token', str(failure.exception))

    async def test_unsupported_database_schema_fails_actionably(self):
        self.store.close()
        import sqlite3
        connection = sqlite3.connect(self.path / 'data.sqlite3')
        connection.execute('PRAGMA user_version=99')
        connection.close()
        with self.assertRaisesRegex(ValueError, 'schema'):
            bot.Store(self.path / 'data.sqlite3')


@unittest.skipUnless(importlib.util.find_spec('discord'), 'Install requirements for Discord adapter checks')
class DiscordFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNotNone(bot, 'Standalone bot implementation is missing')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = bot.Store(Path(self.temp.name) / 'data.sqlite3')
        self.addCleanup(self.store.close)
        self.client = bot.create_client(bot.Settings('never-used-test-token', 123, 2), self.store)
        await self.client._async_setup_hook()
        self.addAsyncCleanup(self.client.close)


@unittest.skipUnless(importlib.util.find_spec('discord'), 'Install requirements for Discord adapter checks')
class DiscordAdapterTests(DiscordFixture):
    async def test_real_client_uses_only_guild_message_reaction_intents_no_cache(self):
        import discord
        self.assertEqual(self.client.intents.value,
                         discord.Intents.guilds.flag | discord.Intents.guild_messages.flag | discord.Intents.guild_reactions.flag)
        self.assertFalse(self.client.intents.message_content)
        self.assertEqual(len(self.client.cached_messages), 0)

    async def test_filtering_and_raw_deletes_through_real_adapter(self):
        from types import SimpleNamespace
        self.client.channel = SimpleNamespace()
        now = datetime.now(timezone.utc)
        def message(mid, *, channel=123, guild=True, is_bot=False, webhook=None):
            return SimpleNamespace(id=mid, channel=SimpleNamespace(id=channel),
                guild=SimpleNamespace() if guild else None,
                author=SimpleNamespace(id=7, display_name='Alice', bot=is_bot),
                webhook_id=webhook, created_at=now)
        for msg in [message(1, channel=999), message(2, guild=False),
                    message(4, webhook=777)]:
            await self.client.on_message(msg)
        self.assertEqual(self.client.tracker.rows(), [])
        await self.client.on_message(message(5))
        await self.client.on_message(message(6))
        await self.client.on_raw_message_delete(SimpleNamespace(channel_id=999, message_id=5))
        self.assertEqual(self.client.tracker.rows()[0][2:], (2, 2))
        await self.client.on_raw_bulk_message_delete(SimpleNamespace(channel_id=123, message_ids={5, 6}))
        self.assertEqual(self.client.tracker.rows()[0][2:], (2, 0))

    async def test_other_bot_messages_are_capped_but_own_messages_are_ignored(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        self.client._connection.user = SimpleNamespace(id=999)
        self.client.channel = SimpleNamespace()
        self.client.tracker.delete = AsyncMock()
        def message(mid, uid):
            return SimpleNamespace(id=mid, channel=SimpleNamespace(id=123), guild=SimpleNamespace(),
                author=SimpleNamespace(id=uid, display_name='Other bot', bot=True),
                webhook_id=None, created_at=datetime.now(timezone.utc), content='<@999> sync')
        for mid in range(1, 4):
            await self.client.on_message(message(mid, 7))
        self.assertEqual(self.client.tracker.rows()[0][2:], (3, 2))
        self.client.tracker.delete.assert_awaited_once()
        await self.client.on_message(message(4, 999))
        self.assertEqual(len(self.client.tracker.rows()), 1)
        self.assertEqual(self.client.tracker.rows()[0][2:], (3, 2))

    async def test_bot_reply_preserves_referenced_human_message_and_link(self):
        import discord
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        partial = SimpleNamespace(delete=AsyncMock())
        self.client.channel = SimpleNamespace(get_partial_message=lambda message_id: partial)
        source_author = SimpleNamespace(id=142822767497052161, display_name='Big B', bot=False)
        source = SimpleNamespace(id=101, author=source_author)
        channel = SimpleNamespace(id=123)
        original = SimpleNamespace(id=101, channel=channel, guild=SimpleNamespace(), author=source_author,
                                   webhook_id=None, created_at=datetime.now(timezone.utc))
        reply = SimpleNamespace(id=102, channel=channel, guild=SimpleNamespace(),
                                author=SimpleNamespace(id=647368715742216193, display_name='SaucyBot', bot=True),
                                webhook_id=None, created_at=datetime.now(timezone.utc),
                                reference=SimpleNamespace(message_id=101, channel_id=123, resolved=source),
                                type=discord.MessageType.reply)
        await self.client.process_message(original)
        await self.client.process_message(reply)
        partial.delete.assert_not_awaited()
        self.assertEqual(reply.reference.message_id, original.id)
        self.assertEqual(self.client.tracker.rows(), [(142822767497052161, 'Big B', 1, 1),
                                                       (647368715742216193, 'SaucyBot', 1, 1)])

    async def test_original_and_saucy_posts_remain_eligible_for_cap_deletion(self):
        import discord
        from types import SimpleNamespace
        messages = {}

        async def delete(mid):
            messages.pop(mid)

        channel = SimpleNamespace(id=123, get_partial_message=lambda mid: SimpleNamespace(delete=lambda: delete(mid)))
        self.client.channel = channel
        self.client.tracker.choose = lambda ids: ids[0]
        author = SimpleNamespace(id=8008, display_name='Original poster', bot=False)
        for mid in (401, 402, 403):
            original = SimpleNamespace(id=mid, channel=channel, guild=SimpleNamespace(), author=author,
                                       webhook_id=None, created_at=datetime.now(timezone.utc),
                                       content=f'https://x.com/example/status/{mid}')
            messages[mid] = original
            await self.client.process_message(original)
        self.assertEqual(set(messages), {402, 403})
        for mid in (404, 405, 406):
            reply = SimpleNamespace(id=mid, channel=channel, guild=SimpleNamespace(),
                                    author=SimpleNamespace(id=647368715742216193, display_name='SaucyBot', bot=True),
                                    webhook_id=None, created_at=datetime.now(timezone.utc),
                                    reference=SimpleNamespace(message_id=403, channel_id=123, resolved=messages[403]),
                                    type=discord.MessageType.reply)
            messages[mid] = reply
            await self.client.process_message(reply)
        self.assertEqual(set(messages), {402, 403, 405, 406})
        self.assertEqual(messages[403].content, 'https://x.com/example/status/403')
        self.assertEqual(self.client.tracker.rows(), [(8008, 'Original poster', 3, 2),
                                                     (647368715742216193, 'SaucyBot', 3, 2)])

    async def test_bot_reply_does_not_delete_another_bot_or_cross_channel_reference(self):
        import discord
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        partial = SimpleNamespace(delete=AsyncMock())
        self.client.channel = SimpleNamespace(get_partial_message=lambda message_id: partial)
        author = SimpleNamespace(id=8, display_name='Another bot', bot=True)
        channel = SimpleNamespace(id=123)
        source = SimpleNamespace(id=201, author=author)
        reply = SimpleNamespace(id=202, channel=channel, guild=SimpleNamespace(),
                                author=SimpleNamespace(id=647368715742216193, display_name='SaucyBot', bot=True),
                                webhook_id=None, created_at=datetime.now(timezone.utc),
                                reference=SimpleNamespace(message_id=201, channel_id=123, resolved=source),
                                type=discord.MessageType.reply)
        await self.client.process_message(reply)
        reply.reference.channel_id = 123
        reply.author = SimpleNamespace(id=12, display_name='Other bot', bot=True)
        reply.id = 204
        await self.client.process_message(reply)
        reply.author = SimpleNamespace(id=647368715742216193, display_name='SaucyBot', bot=True)
        reply.reference.channel_id = 999
        reply.id = 203
        await self.client.process_message(reply)
        partial.delete.assert_not_awaited()

    async def test_saucy_reply_preserves_any_users_referenced_message(self):
        import discord
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        partial = SimpleNamespace(delete=AsyncMock())
        self.client.channel = SimpleNamespace(get_partial_message=lambda message_id: partial)
        author = SimpleNamespace(id=8008, display_name='Another user', bot=False)
        channel = SimpleNamespace(id=123)
        original = SimpleNamespace(id=301, channel=channel, guild=SimpleNamespace(), author=author,
                                   webhook_id=None, created_at=datetime.now(timezone.utc))
        reply = SimpleNamespace(id=302, channel=channel, guild=SimpleNamespace(),
                                author=SimpleNamespace(id=647368715742216193, display_name='SaucyBot', bot=True),
                                webhook_id=None, created_at=datetime.now(timezone.utc),
                                reference=SimpleNamespace(message_id=301, channel_id=123,
                                                         resolved=SimpleNamespace(id=301, author=author)),
                                type=discord.MessageType.reply)
        await self.client.process_message(original)
        await self.client.process_message(reply)
        partial.delete.assert_not_awaited()
        self.assertEqual(reply.reference.message_id, original.id)
        self.assertEqual(self.client.tracker.rows()[0], (8008, 'Another user', 1, 1))

    async def test_discord_errors_are_translated_for_safe_retry(self):
        import discord
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        response = SimpleNamespace(status=404, reason='Not Found')
        partial = SimpleNamespace(delete=AsyncMock(side_effect=discord.NotFound(response, 'Unknown Message')))
        self.client.channel = SimpleNamespace(get_partial_message=lambda mid: partial)
        with self.assertRaises(bot.MissingMessage):
            await self.client.delete_message(42)
        response.status = 403
        partial.delete.side_effect = discord.Forbidden(response, 'Missing Permissions')
        with self.assertRaises(bot.DeleteFailed):
            await self.client.delete_message(42)

    async def test_ready_missing_permissions_waits_for_repair_without_creating_counter(self):
        import discord
        from types import SimpleNamespace
        from unittest.mock import Mock
        channel = Mock(spec=discord.TextChannel)
        channel.guild = SimpleNamespace(me=object())
        permissions = discord.Permissions.none()
        permissions.view_channel = True
        permissions.send_messages = True
        permissions.read_message_history = True
        channel.permissions_for.return_value = permissions
        self.client.get_channel = lambda mid: channel
        with self.assertLogs('messagecap', level='ERROR'):
            await self.client.on_ready()
        self.assertFalse(self.client.is_closed())
        self.assertIn('manage_messages', self.client.startup_error)
        self.assertIsNone(self.client.channel)

    async def test_shutdown_cancels_single_worker(self):
        await self.client.setup_hook()
        worker = self.client.worker
        await self.client.close()
        self.assertTrue(worker.done())
        self.assertTrue(self.client.is_closed())


class DatabaseValidationTests(unittest.TestCase):
    def test_malformed_version_one_schema_is_rejected(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data.sqlite3'
            connection = sqlite3.connect(path)
            connection.execute('CREATE TABLE users (wrong_column TEXT)')
            connection.execute('PRAGMA user_version=1')
            connection.close()
            with self.assertRaisesRegex(ValueError, 'schema'):
                bot.Store(path)


@unittest.skipUnless(importlib.util.find_spec('discord'), 'Install requirements for transport checks')
class TransportRecoveryTests(DiscordFixture):
    async def test_network_failure_refresh_recovers_next_interval(self):
        from types import SimpleNamespace
        live = {}
        fail = [True]
        cursor = [100]
        async def send(text, **kwargs):
            if fail[0]:
                raise OSError('test transport failure')
            cursor[0] += 1
            live[cursor[0]] = text
            return SimpleNamespace(id=cursor[0])
        self.client.channel = SimpleNamespace(send=send)
        clock = [0.0]
        self.client.dashboard.monotonic = lambda: clock[0]
        with self.assertLogs('messagecap', level='ERROR'):
            await self.client.dashboard.refresh()
        fail[0] = False
        clock[0] = 5
        await self.client.dashboard.refresh()
        self.assertEqual(len(live), 1)
        self.assertIn('No tweets from users with personal caps today', next(iter(live.values())))

    async def test_unready_adapter_rejects_operations_actionably(self):
        with self.assertRaises(bot.DeleteFailed):
            await self.client.delete_message(100)
        with self.assertRaises(bot.DeleteFailed):
            await self.client.send_status('test status')

    async def test_timeout_deletion_is_retryable_failure(self):
        from types import SimpleNamespace
        async def delete():
            raise TimeoutError('test timeout')
        self.client.channel = SimpleNamespace(get_partial_message=lambda mid: SimpleNamespace(delete=delete))
        with self.assertRaises(bot.DeleteFailed):
            await self.client.delete_message(100)

    async def test_failed_worker_does_not_prevent_client_shutdown(self):
        async def failed():
            raise RuntimeError('test worker failure')
        self.client.worker = asyncio.create_task(failed())
        await asyncio.sleep(0)
        with self.assertLogs('messagecap', level='ERROR'):
            await self.client.close()
        self.assertTrue(self.client.is_closed())
        self.client.worker = None

    async def test_raw_delete_database_failure_stops_tracking_honestly(self):
        from types import SimpleNamespace
        await self.client.tracker.process(1, 7, 'Alice', datetime.now(timezone.utc))
        self.store.connection.execute('PRAGMA query_only=ON')
        with self.assertLogs('messagecap', level='ERROR'):
            await self.client.on_raw_message_delete(SimpleNamespace(channel_id=123, message_id=1))
        self.assertTrue(self.client.is_closed())
        self.assertIsNotNone(self.client.startup_error)


if __name__ == '__main__':
    unittest.main()
