import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import discord
import bot
import test_slash

FakeInteraction = test_slash.FakeInteraction


class Reaction:
    def __init__(self, normal=(), burst=()):
        self.normal = normal
        self.burst = burst
        self.normal_count = len(normal)
        self.burst_count = len(burst)

    async def users(self, *, limit=None, after=None, type=None):
        users = self.burst if type == discord.ReactionType.burst else self.normal
        users = sorted(uid for uid in users if after is None or uid > after.id)
        for uid in users[:limit]:
            yield SimpleNamespace(id=uid)


class ReaderJumpTests(unittest.IsolatedAsyncioTestCase):
    member = test_slash.SlashTests.member
    invoke = test_slash.SlashTests.invoke

    async def asyncSetUp(self):
        await test_slash.SlashTests.asyncSetUp(self)
        self.client._connection.user = SimpleNamespace(id=999)
        self.now = datetime(2026, 10, 3, 16, tzinfo=timezone.utc)
        self.client.tracker.now = lambda: self.now
        self.messages = []
        self.clock = 0.0
        self.sent = []
        self.client.dashboard.monotonic = lambda: self.clock
        self.client.delete_message = AsyncMock()
        self.client.dashboard.delete = self.client.delete_message
        self.channel.history = self.history
        self.channel.fetch_message = self.fetch
        self.channel.send = self.send

    async def history(self, *, after, before, oldest_first, limit):
        self.assertTrue(oldest_first)
        self.assertIsNone(limit, 'Must search beyond a single history page')
        for message in sorted(self.messages, key=lambda msg: msg.id):
            if after.id < message.id < before.id:
                yield message

    async def fetch(self, mid):
        return next(msg for msg in self.messages if msg.id == mid)

    async def send(self, text, **kwargs):
        self.sent.append((text, kwargs))
        return SimpleNamespace(id=9000 + len(self.sent))

    def message(self, hour, *, author=8, reactions=(), bot_author=False, webhook=None,
                kind=discord.MessageType.default, day=3, millisecond=0, content=''):
        created = datetime(2026, 10, day, hour, microsecond=millisecond * 1000, tzinfo=timezone.utc)
        mid = discord.utils.time_snowflake(created) + len(self.messages)
        message = SimpleNamespace(id=mid, created_at=created,
            author=SimpleNamespace(id=author, bot=bot_author), type=kind, webhook_id=webhook,
            reactions=list(reactions), content=content, jump_url=f'https://discord.com/channels/456/123/{mid}')
        self.messages.append(message)
        return message

    async def select_reader(self, user=None, source=8):
        if source is not None:
            await self.invoke('cap_source', FakeInteraction(self.admin), user=self.member(source))
        interaction = FakeInteraction(self.admin)
        await self.invoke('cap_reader', interaction, user=user or self.user)
        self.assertTrue(interaction.deferred)
        self.assertTrue(interaction.messages[-1]['ephemeral'])

    async def button(self):
        await self.client.dashboard.refresh()
        return self.sent[-1][1]['view'].children[0]

    async def test_summary_has_direct_link_to_oldest_without_reader_reaction(self):
        self.message(8, reactions=[Reaction(normal=[7])])
        oldest = self.message(9, reactions=[Reaction(normal=[1, 2, 8, 100])])
        self.message(10)
        await self.select_reader()
        button = await self.button()
        self.assertEqual(button.style, discord.ButtonStyle.link)
        self.assertEqual(button.url, oldest.jump_url)
        self.assertIsNone(button.custom_id)

    async def test_midnight_is_inclusive_and_reader_own_and_service_posts_are_skipped(self):
        self.message(3)  # Yesterday in Toronto.
        self.message(4, author=7)
        self.message(4, author=999, bot_author=True)
        self.message(4, author=111, bot_author=True)
        self.message(4, webhook=1234)
        self.message(4, kind=discord.MessageType.pins_add)
        target = self.message(4, author=bot.REPLY_CLEANUP_BOT_ID, bot_author=True,
                              kind=discord.MessageType.reply)
        await self.select_reader()
        await self.invoke('cap_source', FakeInteraction(self.admin), user=self.member(bot.REPLY_CLEANUP_BOT_ID))
        self.assertEqual((await self.button()).url, target.jump_url)

    async def test_burst_reaction_also_marks_seen_and_caught_up_has_no_link(self):
        self.message(8, reactions=[Reaction(burst=[7])])
        await self.select_reader()
        button = await self.button()
        self.assertTrue(button.disabled)
        self.assertIsNone(button.url)
        self.assertIn('caught up', button.label.lower())

    async def test_reaction_removal_and_addition_refresh_the_direct_target(self):
        old = self.message(8, reactions=[Reaction(normal=[7])])
        newer = self.message(9)
        await self.select_reader()
        self.assertEqual((await self.button()).url, newer.jump_url)
        old.reactions = []
        self.clock += 5
        await self.client.on_raw_reaction_remove(SimpleNamespace(channel_id=123, user_id=7))
        self.assertEqual((await self.button()).url, old.jump_url)
        old.reactions = [Reaction(normal=[7])]
        self.clock += 5
        await self.client.on_raw_reaction_add(SimpleNamespace(channel_id=123, user_id=7))
        self.assertEqual((await self.button()).url, newer.jump_url)

    async def test_midnight_rollover_never_links_yesterday(self):
        self.message(8)
        await self.select_reader()
        self.assertIsNotNone((await self.button()).url)
        self.now = datetime(2026, 10, 4, 4, tzinfo=timezone.utc)
        self.clock += 5
        self.assertTrue((await self.button()).disabled)

    async def test_history_failure_disables_stale_link_then_recovers(self):
        self.message(8)
        await self.select_reader()
        await self.button()
        async def failed(**kwargs):
            raise OSError('history unavailable')
            yield
        self.channel.history = failed
        self.clock += 5
        await self.client.on_raw_reaction_clear(SimpleNamespace(channel_id=123))
        with self.assertLogs('messagecap', level='WARNING'):
            button = await self.button()
        self.assertTrue(button.disabled)
        self.assertIsNone(button.url)
        self.assertNotIn('caught up', button.label.lower())
        self.channel.history = self.history
        self.clock += 5
        self.assertIsNotNone((await self.button()).url)

    async def test_reader_persists_through_restart_and_quota_reset(self):
        old = self.message(8)
        await self.select_reader()
        await self.client.tracker.reset()
        replacement = bot.create_client(bot.load_config(self.config), self.store, config_path=self.config)
        await replacement._async_setup_hook()
        self.addAsyncCleanup(replacement.close)
        replacement._connection.user = SimpleNamespace(id=999)
        replacement.channel = self.channel
        replacement.tracker.now = lambda: self.now
        replacement.dashboard.delete = AsyncMock()
        self.client = replacement
        self.assertEqual((await self.button()).url, old.jump_url)

    async def test_only_moderators_can_select_human_reader_in_configured_channel(self):
        for interaction, reader in [(FakeInteraction(self.user), self.user),
                                    (FakeInteraction(self.admin, channel_id=555), self.user),
                                    (FakeInteraction(self.admin, guild_id=None), self.user)]:
            await self.invoke('cap_reader', interaction, user=reader)
            self.assertFalse(interaction.deferred)
        robot = self.member(222)
        robot.bot = True
        await self.invoke('cap_reader', FakeInteraction(self.admin), user=robot)
        self.message(8)
        await self.client.dashboard.refresh()
        self.assertIsNone(self.sent[-1][1].get('view'))

    async def test_clear_reader_removes_button(self):
        await self.select_reader()
        await self.invoke('cap_reader', FakeInteraction(self.admin), user=None)
        await self.client.dashboard.refresh()
        self.assertIsNone(self.sent[-1][1].get('view'))

    async def test_deleting_a_target_outside_quota_tracking_advances_the_button(self):
        old = self.message(8)
        newer = self.message(9)
        await self.select_reader()
        self.assertEqual((await self.button()).url, old.jump_url)
        self.messages.remove(old)
        self.clock += 5
        await self.client.on_raw_message_delete(SimpleNamespace(channel_id=123, message_id=old.id))
        self.assertEqual((await self.button()).url, newer.jump_url)

    async def test_periodic_recheck_recovers_a_missed_reaction_event(self):
        old = self.message(8)
        newer = self.message(9)
        await self.select_reader()
        await self.button()
        old.reactions = [Reaction(normal=[7])]
        self.clock += 60
        self.assertEqual((await self.button()).url, newer.jump_url)

    async def test_scan_covers_more_than_one_history_page(self):
        for _ in range(110):
            self.message(8, reactions=[Reaction(normal=[7])])
        target = self.message(9)
        await self.select_reader()
        self.assertEqual((await self.button()).url, target.jump_url)

    async def test_changed_reaction_on_final_fetch_skips_stale_candidate(self):
        old = self.message(8)
        newer = self.message(9)
        async def fetch(mid):
            if mid == old.id:
                old.reactions = [Reaction(normal=[7])]
            return await self.fetch(mid)
        self.channel.fetch_message = fetch
        await self.select_reader()
        self.assertEqual((await self.button()).url, newer.jump_url)

    async def test_midnight_clears_previous_day_even_inside_scan_throttle(self):
        self.message(8)
        await self.select_reader()
        await self.button()
        self.now = datetime(2026, 10, 4, 4, tzinfo=timezone.utc)
        self.clock += 1
        await self.client.prepare_status()
        self.assertIsNone(self.client.reader_jump.view().children[0].url)

    async def test_changing_reader_during_scan_cannot_publish_previous_readers_target(self):
        old = self.message(8, author=8, reactions=[Reaction(normal=[10])])
        newer = self.message(9, author=8)
        entered, resume = asyncio.Event(), asyncio.Event()
        async def fetch(mid):
            entered.set()
            await resume.wait()
            return await self.fetch(mid)
        self.channel.fetch_message = fetch
        await self.select_reader()
        task = asyncio.create_task(self.client.dashboard.refresh())
        await entered.wait()
        await self.select_reader(user=self.member(10), source=None)
        resume.set()
        await task
        self.assertNotEqual(self.sent[-1][1]['view'].children[0].url, old.jump_url)
        self.clock += 5
        self.assertEqual((await self.button()).url, newer.jump_url)

    async def test_setup_and_sync_requests_are_not_jump_targets_but_plain_mentions_are(self):
        self.message(8, content='<@999> sync')
        self.message(8, content='<@!999> slash sync')
        self.message(8, content='<@999> channel here')
        target = self.message(9, content='<@999>')
        await self.select_reader()
        self.assertEqual((await self.button()).url, target.jump_url)


    async def test_no_source_hides_jump_even_with_reader_selected(self):
        self.message(8)
        await self.select_reader(source=None)
        await self.client.dashboard.refresh()
        self.assertIsNone(self.sent[-1][1].get('view'))

    async def test_slash_source_limits_jump_to_selected_bot(self):
        self.message(8)
        target = self.message(9, author=222, bot_author=True)
        await self.select_reader()
        interaction = FakeInteraction(self.admin)
        source = self.member(222)
        source.bot = True
        await self.invoke('cap_source', interaction, user=source)
        self.assertTrue(interaction.messages[-1]['ephemeral'])
        self.assertEqual((await self.button()).url, target.jump_url)


    async def test_clearing_source_removes_button_without_changing_reader(self):
        self.message(8)
        await self.select_reader()
        await self.button()
        await self.invoke('cap_source', FakeInteraction(self.admin), user=None)
        self.clock += 5
        await self.client.dashboard.refresh()
        self.assertIsNone(self.sent[-1][1].get('view'))
        self.assertEqual(self.client.reader_jump.reader_id, 7)
        self.assertIsNone(self.client.reader_jump.source_id)

    async def test_source_permissions_reject_nonmoderator_wrong_channel_and_self(self):
        for interaction, source in [(FakeInteraction(self.user), self.member(222)),
                                    (FakeInteraction(self.admin, channel_id=555), self.member(222)),
                                    (FakeInteraction(self.admin, guild_id=None), self.member(222)),
                                    (FakeInteraction(self.admin), self.member(999))]:
            await self.invoke('cap_source', interaction, user=source)
            self.assertFalse(interaction.deferred)
            self.assertIsNone(self.client.reader_jump.source_id)

    async def test_changing_source_during_scan_discards_previous_target(self):
        old = self.message(8)
        target = self.message(9, author=222, bot_author=True)
        entered, resume = asyncio.Event(), asyncio.Event()
        async def fetch(mid):
            entered.set()
            await resume.wait()
            return await self.fetch(mid)
        self.channel.fetch_message = fetch
        await self.select_reader()
        task = asyncio.create_task(self.client.dashboard.refresh())
        await entered.wait()
        await self.invoke('cap_source', FakeInteraction(self.admin), user=self.member(222))
        resume.set()
        await task
        self.assertNotEqual(self.sent[-1][1]['view'].children[0].url, old.jump_url)
        self.clock += 5
        self.assertEqual((await self.button()).url, target.jump_url)

    async def test_source_with_only_other_authors_is_caught_up(self):
        self.message(8)
        self.message(9, author=333, bot_author=True)
        await self.select_reader(source=222)
        button = await self.button()
        self.assertTrue(button.disabled)
        self.assertIn('caught up', button.label.lower())
        self.assertIsNone(button.url)
