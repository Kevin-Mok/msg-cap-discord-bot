import asyncio
from copy import copy
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import unittest

import discord
from reader_jump import ReaderJump
import test_reader_jump as fixtures


class ReaderCacheEdgeTests(unittest.IsolatedAsyncioTestCase):
    member = fixtures.ReaderJumpTests.member
    invoke = fixtures.ReaderJumpTests.invoke
    history = fixtures.ReaderJumpTests.history
    fetch = fixtures.ReaderJumpTests.fetch
    send = fixtures.ReaderJumpTests.send
    edit = fixtures.ReaderJumpTests.edit
    message = fixtures.ReaderJumpTests.message
    select_reader = fixtures.ReaderJumpTests.select_reader

    async def asyncSetUp(self):
        await fixtures.ReaderJumpTests.asyncSetUp(self)
        self.history_reads = 0
        self.fetch_reads = []
        self.membership_reads = []
        self.channel.history = self.counted_history
        self.channel.fetch_message = self.counted_fetch

    async def counted_history(self, **kwargs):
        self.history_reads += 1
        async for message in self.history(**kwargs):
            yield message

    async def counted_fetch(self, mid):
        self.fetch_reads.append(mid)
        return await self.fetch(mid)

    def reaction(self, *, normal=(), burst=()):
        reaction = fixtures.Reaction(normal=normal, burst=burst)
        users = reaction.users

        async def counted_users(**kwargs):
            self.membership_reads.append(kwargs['type'])
            async for user in users(**kwargs):
                yield user

        reaction.users = counted_users
        return reaction

    def event(self, message, *, user=7, channel=123, kind=discord.ReactionType.normal):
        return SimpleNamespace(channel_id=channel, guild_id=456, message_id=message.id,
                               user_id=user, emoji=discord.PartialEmoji(name='heart'),
                               type=kind, burst=kind == discord.ReactionType.burst)

    async def refresh(self, clock=0, *, jump=None, channel=None):
        await (jump or self.client.reader_jump).refresh(
            channel or self.channel, 999, self.client.tracker.revision, clock)

    def live_message(self, hour, **kwargs):
        message = self.message(hour, **kwargs)
        message.channel = self.channel
        message.guild = self.channel.guild
        message.author.display_name = f'User {message.author.id}'
        return message

    def reads(self):
        return self.history_reads, len(self.fetch_reads), len(self.membership_reads)

    async def test_new_source_post_after_caught_up_updates_url_and_counts_without_reads(self):
        self.message(8, reactions=[self.reaction(normal=[7])])
        await self.select_reader()
        await self.refresh()
        self.assertTrue(self.client.reader_jump.available)
        self.assertIsNone(self.client.reader_jump.url)
        previous_reads = self.reads()

        target = self.live_message(9)
        await self.client.on_message(target)
        await self.refresh(1)

        self.assertEqual(self.client.reader_jump.url, target.jump_url)
        self.assertEqual(self.client.tracker.rows(), [(8, 'User 8', 1, 1)])
        self.assertEqual(self.reads(), previous_reads)

    async def test_wrong_channel_and_other_reader_events_do_not_change_cached_target(self):
        target = self.live_message(8)
        await self.select_reader()
        await self.refresh()
        previous_reads = self.reads()
        await self.client.on_raw_reaction_add(self.event(target, channel=789))
        await self.client.on_raw_reaction_add(self.event(target, user=10))
        other_channel_post = self.live_message(9)
        other_channel_post.channel = SimpleNamespace(id=789)
        await self.client.on_message(other_channel_post)
        await self.refresh(1)
        self.assertEqual(self.client.reader_jump.url, target.jump_url)
        self.assertEqual(self.client.tracker.rows(), [])
        self.assertEqual(self.reads(), previous_reads)

    async def test_reader_and_source_changes_do_not_reuse_previous_membership(self):
        first = self.message(8, reactions=[self.reaction(normal=[7])])
        later = self.message(9)
        replacement_source = self.message(10, author=222)
        await self.select_reader()
        await self.refresh()
        self.assertEqual(self.client.reader_jump.url, later.jump_url)
        await self.select_reader(user=self.member(10), source=None)
        await self.refresh(1)
        self.assertEqual(self.client.reader_jump.url, first.jump_url)
        await self.client.on_raw_reaction_add(self.event(first, user=7))
        await self.refresh(2)
        self.assertEqual(self.client.reader_jump.url, first.jump_url)
        await self.invoke('cap_source', fixtures.FakeInteraction(self.admin), user=self.member(222))
        await self.refresh(3)
        self.assertEqual(self.client.reader_jump.url, replacement_source.jump_url)

    async def test_midnight_discards_cached_previous_day_target(self):
        previous = self.message(8)
        await self.select_reader()
        await self.refresh()
        self.assertEqual(self.client.reader_jump.url, previous.jump_url)
        self.now = datetime(2026, 10, 4, 8, tzinfo=timezone.utc)
        today = self.live_message(5, day=4)
        await self.client.on_message(today)
        self.assertNotEqual(self.client.reader_jump.url, previous.jump_url)
        await self.refresh(1)
        self.assertEqual(self.client.reader_jump.url, today.jump_url)
        self.assertEqual(self.client.tracker.rows(), [(8, 'User 8', 1, 1)])

    async def test_replacement_channel_reconciles_instead_of_reusing_saved_target(self):
        previous = self.message(8)
        await self.select_reader()
        await self.refresh()
        replacement = ReaderJump(self.store.connection, self.client.tracker.tz, lambda: self.now)
        new_post = self.message(9)
        new_post.jump_url = f'https://discord.com/channels/654/789/{new_post.id}'

        async def history(**kwargs):
            yield new_post

        async def fetch(mid):
            self.assertEqual(mid, new_post.id)
            return new_post

        new_channel = SimpleNamespace(id=789, guild=SimpleNamespace(id=654),
                                      history=history, fetch_message=fetch)
        self.assertFalse(replacement.available)
        await self.refresh(jump=replacement, channel=new_channel)
        self.assertEqual(replacement.url, new_post.jump_url)
        self.assertNotEqual(replacement.url, previous.jump_url)

    async def test_normal_removal_keeps_burst_seen_then_clear_all_needs_no_reads(self):
        first = self.message(8, reactions=[self.reaction(normal=[7], burst=[7])])
        target = self.message(9)
        await self.select_reader()
        await self.refresh()
        first.reactions = [self.reaction(burst=[7])]
        previous_history = self.history_reads
        previous_fetches = len(self.fetch_reads)
        await self.client.on_raw_reaction_remove(self.event(first))
        await self.refresh(5)
        self.assertEqual(self.client.reader_jump.url, target.jump_url)
        self.assertEqual(self.history_reads, previous_history)
        self.assertEqual(self.fetch_reads[previous_fetches:], [first.id])
        self.assertIn(discord.ReactionType.burst, self.membership_reads)

        first.reactions = []
        previous_reads = self.reads()
        await self.client.on_raw_reaction_clear(self.event(first))
        await self.refresh(6)
        self.assertEqual(self.client.reader_jump.url, first.jump_url)
        self.assertEqual(self.reads(), previous_reads)

    async def test_emoji_clear_keeps_other_reaction_seen(self):
        first = self.message(8, reactions=[self.reaction(normal=[7]), self.reaction(burst=[7])])
        target = self.message(9)
        await self.select_reader()
        await self.refresh()
        first.reactions = [self.reaction(burst=[7])]
        previous_history = self.history_reads
        previous_fetches = len(self.fetch_reads)
        await self.client.on_raw_reaction_clear_emoji(self.event(first))
        await self.refresh(5)
        self.assertEqual(self.client.reader_jump.url, target.jump_url)
        self.assertEqual(self.history_reads, previous_history)
        self.assertEqual(self.fetch_reads[previous_fetches:], [first.id])

    async def test_reader_add_before_stale_history_arrival_is_not_overwritten(self):
        first = self.message(8)
        target = self.message(9)
        snapshots = [copy(first), copy(target)]
        entered, resume = asyncio.Event(), asyncio.Event()

        async def held_history(**kwargs):
            self.history_reads += 1
            entered.set()
            await resume.wait()
            for message in snapshots:
                yield message

        self.channel.history = held_history
        await self.select_reader()
        task = asyncio.create_task(self.refresh())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await self.client.on_raw_reaction_add(self.event(first))
            resume.set()
            await asyncio.wait_for(task, 1)
            self.assertEqual(self.client.reader_jump.url, target.jump_url)
            self.assertNotIn(first.id, self.fetch_reads)
        finally:
            resume.set()
            await asyncio.gather(task, return_exceptions=True)

    async def test_deleted_message_in_stale_history_cannot_be_resurrected(self):
        first = self.message(8)
        target = self.message(9)
        snapshots = [copy(first), copy(target)]
        entered, resume = asyncio.Event(), asyncio.Event()

        async def held_history(**kwargs):
            self.history_reads += 1
            entered.set()
            await resume.wait()
            for message in snapshots:
                yield message

        self.channel.history = held_history
        await self.select_reader()
        task = asyncio.create_task(self.refresh())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await self.client.on_raw_message_delete(self.event(first))
            resume.set()
            await asyncio.wait_for(task, 1)
            self.assertEqual(self.client.reader_jump.url, target.jump_url)
            self.assertNotIn(first.id, self.fetch_reads)
        finally:
            resume.set()
            await asyncio.gather(task, return_exceptions=True)

    async def test_live_post_missing_from_held_history_is_preserved(self):
        entered, resume = asyncio.Event(), asyncio.Event()

        async def empty_held_history(**kwargs):
            self.history_reads += 1
            entered.set()
            await resume.wait()
            if False:
                yield

        self.channel.history = empty_held_history
        await self.select_reader()
        task = asyncio.create_task(self.refresh())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            target = self.live_message(8)
            await self.client.on_message(target)
            resume.set()
            await asyncio.wait_for(task, 1)
            self.assertEqual(self.client.reader_jump.url, target.jump_url)
            self.assertEqual(self.client.tracker.rows(), [(8, 'User 8', 1, 1)])
        finally:
            resume.set()
            await asyncio.gather(task, return_exceptions=True)

    async def test_concurrent_refreshes_share_one_history_and_candidate_fetch(self):
        target = self.message(8)
        entered, resume = asyncio.Event(), asyncio.Event()

        async def held_history(**kwargs):
            self.history_reads += 1
            entered.set()
            await resume.wait()
            async for message in self.history(**kwargs):
                yield message

        self.channel.history = held_history
        await self.select_reader()
        first = asyncio.create_task(self.refresh())
        second = None
        try:
            await asyncio.wait_for(entered.wait(), 1)
            second = asyncio.create_task(self.refresh(1))
            await asyncio.sleep(0)
            resume.set()
            await asyncio.wait_for(asyncio.gather(first, second), 1)
            self.assertEqual(self.client.reader_jump.url, target.jump_url)
            self.assertEqual(self.history_reads, 1)
            self.assertEqual(self.fetch_reads, [target.id])
        finally:
            resume.set()
            await asyncio.gather(first, *([second] if second else []), return_exceptions=True)

    async def test_incomplete_membership_scan_reuses_completed_checks_on_retry(self):
        first = self.message(8, reactions=[self.reaction(normal=[7])])
        second = self.message(9, reactions=[self.reaction(normal=[7])])
        target = self.message(10)
        requests = {first.id: 0, second.id: 0}
        for message in (first, second):
            original = message.reactions[0].users

            async def users(message=message, original=original, **kwargs):
                requests[message.id] += 1
                if message.id == second.id and requests[message.id] == 1:
                    raise TimeoutError('intentional interrupted membership scan')
                async for user in original(**kwargs):
                    yield user

            message.reactions[0].users = users
        await self.select_reader()
        with self.assertLogs('messagecap', level='WARNING'):
            await self.refresh()
        self.assertFalse(self.client.reader_jump.available)
        await self.refresh(5)
        self.assertEqual(self.client.reader_jump.url, target.jump_url)
        self.assertEqual(requests, {first.id: 1, second.id: 2})
        self.assertEqual(self.history_reads, 1)

    async def test_malformed_persisted_cache_refuses_load(self):
        valid = {'version': 1, 'scope': [123, '2026-10-03', 7, 8],
                 'complete': True, 'posts': [[12345, True]]}
        malformed = [
            '{',
            json.dumps({**valid, 'version': True}),
            json.dumps({**valid, 'version': 1.0}),
            json.dumps({**valid, 'scope': [123, '2026-10-03', True, 8]}),
            json.dumps({**valid, 'scope': [123, '2026-13-03', 7, 8]}),
            json.dumps({**valid, 'complete': 'yes'}),
            json.dumps({**valid, 'posts': [[12345, True], [12345, False]]}),
            json.dumps({**valid, 'posts': [['12345', True]]}),
            json.dumps({**valid, 'posts': [[12345, 1]]}),
        ]
        for value in malformed:
            with self.subTest(cache=value):
                with self.store.connection:
                    self.store.connection.execute(
                        "INSERT OR REPLACE INTO meta VALUES ('reader_cache', ?)", (value,))
                with self.assertRaisesRegex(ValueError, 'Invalid saved reader cache'):
                    ReaderJump(self.store.connection, self.client.tracker.tz, lambda: self.now)
