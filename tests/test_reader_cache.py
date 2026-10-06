import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import discord
from reader_jump import ReaderJump
import test_reader_jump as fixtures

Reaction = fixtures.Reaction


class ReaderCacheTests(unittest.IsolatedAsyncioTestCase):
    member = fixtures.ReaderJumpTests.member
    invoke = fixtures.ReaderJumpTests.invoke
    asyncSetUp = fixtures.ReaderJumpTests.asyncSetUp
    history = fixtures.ReaderJumpTests.history
    fetch = fixtures.ReaderJumpTests.fetch
    send = fixtures.ReaderJumpTests.send
    message = fixtures.ReaderJumpTests.message
    select_reader = fixtures.ReaderJumpTests.select_reader

    def event(self, message, *, user=7):
        return SimpleNamespace(channel_id=123, message_id=message.id, user_id=user,
                               emoji=discord.PartialEmoji(name='heart'), type=discord.ReactionType.normal)

    async def refresh(self, clock=0):
        await self.client.reader_jump.refresh(self.channel, 999, self.client.tracker.revision, clock)

    async def test_successful_scan_retains_checks_and_warm_changes_make_no_reads(self):
        first = self.message(8, reactions=[Reaction(normal=[7])])
        target = self.message(9)
        await self.select_reader()
        await self.refresh()
        jump = self.client.reader_jump
        self.assertIn(first.id, jump.checked, 'Successful work must remain cached')
        self.channel.history = lambda **kwargs: self.fail('Warm update must not read history')
        self.channel.fetch_message = AsyncMock(side_effect=AssertionError('Warm update must not fetch'))
        for clock in (1, 5, 10):
            self.client.tracker.revision += 1
            await self.refresh(clock)
            self.assertEqual(jump.url, target.jump_url)

    async def test_reader_add_uses_event_and_advances_without_network(self):
        first = self.message(8)
        target = self.message(9)
        await self.select_reader()
        await self.refresh()
        self.channel.history = lambda **kwargs: self.fail('Add must use the cache')
        self.channel.fetch_message = AsyncMock(side_effect=AssertionError('Add must not fetch'))
        await self.client.on_raw_reaction_add(self.event(first))
        await self.refresh(5)
        self.assertEqual(self.client.reader_jump.url, target.jump_url)

    async def test_remove_rechecks_only_affected_post_and_other_reactions_keep_it_seen(self):
        first = self.message(8, reactions=[Reaction(normal=[7]), Reaction(burst=[7])])
        target = self.message(9)
        await self.select_reader()
        await self.refresh()
        first.reactions = [Reaction(burst=[7])]
        self.channel.history = lambda **kwargs: self.fail('Removal must not rescan history')
        self.channel.fetch_message = AsyncMock(side_effect=self.fetch)
        await self.client.on_raw_reaction_remove(self.event(first))
        await self.refresh(5)
        self.assertEqual(self.client.reader_jump.url, target.jump_url)
        self.channel.fetch_message.assert_awaited_once_with(first.id)
        first.reactions = []
        self.channel.fetch_message.reset_mock()
        await self.client.on_raw_reaction_remove(self.event(first))
        await self.refresh(10)
        self.assertEqual(self.client.reader_jump.url, first.jump_url)
        self.channel.fetch_message.assert_awaited_once_with(first.id)

    async def test_restart_reconciles_cached_reader_removal_even_if_counts_match(self):
        first = self.message(8, reactions=[Reaction(normal=[7])])
        target = self.message(9)
        await self.select_reader()
        await self.refresh()
        self.assertEqual(self.client.reader_jump.url, target.jump_url)
        row = self.store.connection.execute("SELECT value FROM meta WHERE key='reader_cache'").fetchone()
        self.assertIsNotNone(row, 'Cache must persist in the existing private database')
        first.reactions = [Reaction(normal=[8])]
        replacement = ReaderJump(self.store.connection, self.client.tracker.tz, lambda: self.now)
        self.assertFalse(replacement.available)
        await replacement.refresh(self.channel, 999, 0, 0)
        self.assertEqual(replacement.url, first.jump_url)

    async def test_count_publication_does_not_wait_for_held_reader_scan(self):
        self.message(8)
        await self.select_reader()
        entered, resume = asyncio.Event(), asyncio.Event()
        async def history(**kwargs):
            entered.set()
            await resume.wait()
            async for message in self.history(**kwargs):
                yield message
        self.channel.history = history
        task = asyncio.create_task(self.client.dashboard.refresh())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await asyncio.sleep(0)
            self.assertTrue(task.done(), 'Publishing counts must not await history/reactions')
            self.assertTrue(self.sent, 'Counts remain available during hydration')
        finally:
            resume.set()
            await task

    async def test_reader_removal_during_fetch_cannot_commit_stale_later_target(self):
        first = self.message(8, reactions=[Reaction(normal=[7])])
        self.message(9)
        await self.select_reader()
        entered, resume = asyncio.Event(), asyncio.Event()
        async def held_fetch(mid):
            entered.set()
            await resume.wait()
            return await self.fetch(mid)
        self.channel.fetch_message = held_fetch
        task = asyncio.create_task(self.client.reader_jump.refresh(self.channel, 999, 0, 0))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            first.reactions = []
            await self.client.on_raw_reaction_remove(self.event(first))
            resume.set()
            await task
            self.assertNotEqual(self.client.reader_jump.url,
                                self.messages[1].jump_url, 'Earlier event must invalidate stale scan publication')
            await self.refresh(5)
            self.assertEqual(self.client.reader_jump.url, first.jump_url)
        finally:
            resume.set()
            await task

    async def test_removal_or_emoji_clear_during_history_cannot_restore_stale_membership(self):
        for handler in ('on_raw_reaction_remove', 'on_raw_reaction_clear_emoji'):
            with self.subTest(handler=handler):
                self.messages = []
                first = self.message(8, reactions=[Reaction(normal=[7])])
                target = self.message(9)
                stale = SimpleNamespace(**vars(first))
                entered, resume = asyncio.Event(), asyncio.Event()
                async def held_history(**kwargs):
                    yield stale
                    entered.set()
                    await resume.wait()
                    yield target
                self.channel.history = held_history
                await self.select_reader()
                task = asyncio.create_task(self.client.reader_jump.refresh(self.channel, 999, 0, 0))
                await asyncio.wait_for(entered.wait(), 1)
                try:
                    first.reactions = []
                    await getattr(self.client, handler)(self.event(first))
                finally:
                    resume.set()
                    await task
                self.assertEqual(self.client.reader_jump.url, first.jump_url)

    async def test_long_successful_scan_starts_cooldown_at_completion(self):
        self.message(8, reactions=[Reaction(normal=[7])])
        target = self.message(9)
        await self.select_reader()
        async def slow_fetch(mid):
            self.clock += 90
            return await self.fetch(mid)
        self.channel.fetch_message = slow_fetch
        await self.refresh(0)
        self.assertEqual(self.client.reader_jump.url, target.jump_url)
        self.channel.history = lambda **kwargs: self.fail('Fresh completed scan must not restart')
        self.channel.fetch_message = AsyncMock(side_effect=AssertionError('Must reuse completed results'))
        await self.refresh(91)
        self.assertEqual(self.client.reader_jump.url, target.jump_url)

    async def test_targeted_removal_rechecks_on_next_one_second_tick(self):
        first = self.message(8, reactions=[Reaction(normal=[7])])
        self.message(9)
        await self.select_reader()
        await self.refresh()
        first.reactions = []
        await self.client.on_raw_reaction_remove(self.event(first))
        await self.refresh(1)
        self.assertEqual(self.client.reader_jump.url, first.jump_url)
