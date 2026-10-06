import asyncio
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import bot
from dashboard import Dashboard


class DashboardFastTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = bot.Store(Path(self.temp.name) / 'state.sqlite3')
        self.addCleanup(self.store.close)
        self.now = datetime(2026, 10, 6, 16, tzinfo=timezone.utc)
        self.clock = 0.0
        self.live = {}
        self.operations = []
        self.next_id = 1000
        self.fail_edit = set()
        self.fail_send_at = None
        self.send_count = 0
        self.signature_value = 0
        self.signature_calls = 0
        self.tracker = bot.Tracker(self.store, 123, 50, 'America/Toronto',
                                   now=lambda: self.now, delete=self.delete)
        self.dashboard = Dashboard(self.store, self.tracker, self.send, self.delete,
                                   monotonic=lambda: self.clock, edit=self.edit, signature=self.signature)

    def signature(self):
        self.signature_calls += 1
        return self.signature_value

    async def send(self, text):
        self.assertFalse(self.tracker.lock.locked(), 'Tracker lock held across network send')
        self.send_count += 1
        if self.send_count == self.fail_send_at:
            raise bot.DeleteFailed('temporary send failure')
        self.next_id += 1
        self.live[self.next_id] = text
        self.operations.append(('send', self.next_id, self.clock))
        return self.next_id

    async def delete(self, message_id):
        self.assertFalse(self.tracker.lock.locked(), 'Tracker lock held across network delete')
        self.live.pop(message_id, None)
        self.operations.append(('delete', message_id, self.clock))

    async def edit(self, message_id, text):
        self.assertFalse(self.tracker.lock.locked(), 'Tracker lock held across network edit')
        if message_id not in self.live:
            raise bot.MissingMessage()
        if message_id in self.fail_edit:
            raise bot.DeleteFailed('temporary edit failure')
        self.live[message_id] = text
        self.operations.append(('edit', message_id, self.clock))

    async def counted(self, message_id=1):
        await self.tracker.set_user_cap(7, 50)
        await self.tracker.process(message_id, 7, 'Alice', self.now)

    async def test_count_changes_edit_existing_batch_within_one_second(self):
        await self.counted()
        await self.dashboard.refresh()
        original = list(self.live)
        await self.tracker.process(2, 7, 'Alice', self.now)
        self.clock = 0.99
        await self.dashboard.refresh()
        self.assertIn('1 tweet sent', self.live[original[0]])
        self.clock = 1.0
        await self.dashboard.refresh()
        self.assertIn('2 tweets sent', self.live[original[0]])
        self.assertEqual(list(self.live), original)
        self.assertEqual([row[0] for row in self.operations], ['send', 'edit'])

    async def test_reader_signature_change_refreshes_without_counter_revision(self):
        await self.dashboard.refresh()
        self.operations.clear()
        self.signature_value = 1
        self.clock = 1
        await self.dashboard.refresh()
        self.assertEqual([row[0] for row in self.operations], ['edit'])
        self.assertEqual(self.signature_calls, 2)

    async def test_unchanged_content_and_signature_make_no_network_writes(self):
        await self.dashboard.refresh()
        self.operations.clear()
        self.tracker.revision += 1
        self.clock = 5
        await self.dashboard.refresh()
        self.assertEqual(self.operations, [])
        self.assertEqual(self.dashboard.published, self.tracker.revision)

    async def test_only_post_activity_relocates_and_at_most_every_five_seconds(self):
        await self.counted()
        await self.dashboard.refresh()
        first = list(self.live)
        self.dashboard.note_activity()
        await self.tracker.process(2, 7, 'Alice', self.now)
        self.clock = 1
        await self.dashboard.refresh()
        self.assertEqual(list(self.live), first)
        self.clock = 5
        await self.dashboard.refresh()
        second = list(self.live)
        self.assertNotEqual(second, first)
        await self.tracker.set_user_cap(7, 10)
        self.clock = 6
        await self.dashboard.refresh()
        self.assertEqual(list(self.live), second)
        self.dashboard.note_activity()
        self.clock = 9
        await self.dashboard.refresh()
        self.assertEqual(list(self.live), second)
        self.clock = 10
        await self.dashboard.refresh()
        self.assertNotEqual(list(self.live), second)
        sends = [row[2] for row in self.operations if row[0] == 'send']
        self.assertEqual(sends, [0, 5, 10])

    async def test_missing_edited_message_replaces_entire_batch(self):
        await self.counted()
        await self.dashboard.refresh()
        original = next(iter(self.live))
        self.live.pop(original)
        await self.tracker.process(2, 7, 'Alice', self.now)
        self.clock = 1
        await self.dashboard.refresh()
        self.assertNotIn(original, dict(self.store.status_ids()))
        self.assertEqual(len(self.live), 1)
        self.assertIn('2 tweets sent', next(iter(self.live.values())))

    async def test_deleted_status_is_replaced_even_when_summary_unchanged(self):
        await self.dashboard.refresh()
        original = next(iter(self.live))
        self.live.pop(original)
        self.dashboard.removed([original])
        self.clock = 1
        await self.dashboard.refresh()
        self.assertEqual(len(self.live), 1)
        self.assertNotIn(original, self.live)

    async def test_partial_chunk_send_is_retried_without_accumulating_messages(self):
        with patch.object(bot, 'render_dashboard', return_value=['first', 'second']):
            self.fail_send_at = 2
            with self.assertLogs('messagecap', level='ERROR'):
                await self.dashboard.refresh()
            self.assertEqual(len(self.live), 1)
            self.assertEqual(self.dashboard.published, -1)
            self.clock = 1
            await self.dashboard.refresh()
            self.assertEqual(sorted(self.live.values()), ['first', 'second'])
            self.assertEqual(len(self.store.status_ids()), 2)
            self.assertEqual(self.dashboard.published, self.tracker.revision)

    async def test_partial_chunk_edit_keeps_published_revision_until_retry(self):
        with patch.object(bot, 'render_dashboard', return_value=['first', 'second']):
            await self.dashboard.refresh()
        original = list(self.live)
        self.fail_edit.add(original[1])
        self.tracker.revision += 1
        self.clock = 1
        with patch.object(bot, 'render_dashboard', return_value=['new first', 'new second']):
            with self.assertLogs('messagecap', level='ERROR'):
                await self.dashboard.refresh()
            self.assertEqual(self.dashboard.published, 0)
            self.assertEqual(list(self.live), original)
            self.fail_edit.clear()
            self.clock = 2
            await self.dashboard.refresh()
        self.assertEqual(list(self.live.values()), ['new first', 'new second'])
        self.assertEqual(self.dashboard.published, 1)

    async def test_retirement_during_send_never_updates_shared_status_store(self):
        async def retire_during_send(text):
            message_id = await self.send(text)
            self.tracker.retired = True
            return message_id
        self.dashboard.send = retire_during_send
        await self.dashboard.refresh()
        self.assertEqual(self.store.status_ids(), [])
        self.assertEqual(self.dashboard.published, -1)

    async def test_chunk_count_change_replaces_batch_instead_of_editing_wrong_shape(self):
        with patch.object(bot, 'render_dashboard', return_value=['first']):
            await self.dashboard.refresh()
        original = next(iter(self.live))
        self.clock = 1
        with patch.object(bot, 'render_dashboard', return_value=['first', 'second']):
            await self.dashboard.refresh()
        self.assertNotIn(original, self.live)
        self.assertEqual(list(self.live.values()), ['first', 'second'])
        self.assertEqual([row[0] for row in self.operations], ['send', 'delete', 'send', 'send'])

    async def test_revision_changed_during_publish_remains_pending_for_next_edit(self):
        await self.tracker.set_user_cap(7, 50)
        revision = self.tracker.revision

        async def count_during_send(text):
            message_id = await self.send(text)
            await self.tracker.process(1, 7, 'Alice', self.now)
            return message_id

        self.dashboard.send = count_during_send
        await self.dashboard.refresh()
        self.assertEqual(self.dashboard.published, revision)
        self.assertGreater(self.tracker.revision, revision)
        self.clock = 1
        await self.dashboard.refresh()
        self.assertEqual(self.dashboard.published, self.tracker.revision)
        self.assertIn('1 tweet sent', next(iter(self.live.values())))
        self.assertEqual([row[0] for row in self.operations], ['send', 'edit'])

    async def test_signature_changed_during_publish_remains_pending_for_next_edit(self):
        async def change_signature_during_send(text):
            message_id = await self.send(text)
            self.signature_value = 1
            return message_id

        self.dashboard.send = change_signature_during_send
        await self.dashboard.refresh()
        self.clock = 1
        await self.dashboard.refresh()
        self.assertEqual(self.signature_calls, 2)
        self.assertEqual([row[0] for row in self.operations], ['send', 'edit'])

    async def test_concurrent_refreshes_do_not_send_duplicate_batches(self):
        await asyncio.gather(*(self.dashboard.refresh() for _ in range(5)))
        self.assertEqual(len(self.live), 1)
        self.assertEqual([row[0] for row in self.operations], ['send'])

    async def test_retirement_during_delete_preserves_new_controllers_store(self):
        await self.dashboard.refresh()
        message_id = next(iter(self.live))

        async def switch_scope_during_delete(deleted_id):
            await self.delete(deleted_id)
            self.tracker.retired = True
            self.store.forget_status(message_id)
            self.store.remember_status(message_id, 456)

        self.dashboard.delete = switch_scope_during_delete
        self.dashboard.note_activity()
        self.clock = 5
        await self.dashboard.refresh()
        self.assertEqual(self.store.status_ids(), [(message_id, 456)])
        self.assertEqual([row[0] for row in self.operations], ['send', 'delete'])
